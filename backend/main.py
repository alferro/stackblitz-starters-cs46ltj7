import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from database import DatabaseManager
from bybit_client import BybitWebSocketClient
from volume_analyzer import VolumeAnalyzer
from price_filter import PriceFilter

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Trading Volume Analyzer", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные переменные
db_manager = None
bybit_client = None
volume_analyzer = None
price_filter = None

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        try:
            await websocket.send_text(message)
        except:
            self.disconnect(websocket)

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                disconnected.append(connection)
        
        # Удаляем отключенные соединения
        for conn in disconnected:
            self.disconnect(conn)

manager = ConnectionManager()

@app.on_event("startup")
async def startup_event():
    global db_manager, bybit_client, volume_analyzer, price_filter
    
    try:
        # Инициализация базы данных
        db_manager = DatabaseManager()
        await db_manager.initialize()
        
        # Инициализация анализатора объемов
        volume_analyzer = VolumeAnalyzer(db_manager)
        
        # Инициализация фильтра цен
        price_filter = PriceFilter(db_manager)
        
        # Запуск фильтра цен в фоновом режиме
        asyncio.create_task(price_filter.start())
        
        # Ждем первоначального обновления watchlist
        await asyncio.sleep(5)
        
        # Получение списка торговых пар
        trading_pairs = await db_manager.get_watchlist()
        logger.info(f"Загружено {len(trading_pairs)} торговых пар")
        
        if trading_pairs:
            # Инициализация Bybit WebSocket клиента
            bybit_client = BybitWebSocketClient(trading_pairs, volume_analyzer, manager)
            
            # Запуск WebSocket соединения в фоновом режиме
            asyncio.create_task(bybit_client.start())
        else:
            logger.warning("Нет торговых пар в watchlist. Ожидание обновления...")
        
        # Периодическое обновление списка торговых пар
        asyncio.create_task(periodic_watchlist_update())
        
        logger.info("Приложение успешно запущено")
        
    except Exception as e:
        logger.error(f"Ошибка при запуске приложения: {e}")
        raise

async def periodic_watchlist_update():
    """Периодическое обновление списка торговых пар"""
    global bybit_client
    
    while True:
        try:
            await asyncio.sleep(300)  # Проверяем каждые 5 минут
            
            new_pairs = await db_manager.get_watchlist()
            
            if bybit_client:
                current_pairs = bybit_client.trading_pairs
                if set(new_pairs) != set(current_pairs):
                    logger.info(f"Обновление списка торговых пар: {len(new_pairs)} пар")
                    
                    # Останавливаем текущий клиент
                    await bybit_client.stop()
                    
                    # Создаем новый клиент с обновленным списком
                    bybit_client = BybitWebSocketClient(new_pairs, volume_analyzer, manager)
                    asyncio.create_task(bybit_client.start())
            elif new_pairs:
                # Если клиента не было, но появились пары
                logger.info(f"Создание WebSocket клиента для {len(new_pairs)} пар")
                bybit_client = BybitWebSocketClient(new_pairs, volume_analyzer, manager)
                asyncio.create_task(bybit_client.start())
                
        except Exception as e:
            logger.error(f"Ошибка обновления watchlist: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    global bybit_client, price_filter
    if bybit_client:
        await bybit_client.stop()
    if price_filter:
        await price_filter.stop()

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try:
        with open("src/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="""
        <!DOCTYPE html>
        <html>
        <head><title>Trading Volume Analyzer</title></head>
        <body>
            <h1>Trading Volume Analyzer</h1>
            <p>Система анализа объемов торговых пар запущена</p>
            <p>WebSocket подключение: ws://localhost:8000/ws</p>
        </body>
        </html>
        """)

@app.get("/api/watchlist")
async def get_watchlist():
    """Получить список торговых пар из watchlist"""
    try:
        pairs = await db_manager.get_watchlist_details()
        return {"pairs": pairs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/alerts")
async def get_alerts(limit: int = 100):
    """Получить список алертов"""
    try:
        alerts = await db_manager.get_alerts(limit)
        return {"alerts": alerts}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/settings")
async def get_settings():
    """Получить текущие настройки анализатора"""
    if volume_analyzer and price_filter:
        return {
            "volume_analyzer": volume_analyzer.get_settings(),
            "price_filter": price_filter.settings
        }
    return {"error": "Анализатор не инициализирован"}

@app.post("/api/settings")
async def update_settings(settings: dict):
    """Обновить настройки анализатора"""
    try:
        if volume_analyzer and 'volume_analyzer' in settings:
            volume_analyzer.update_settings(settings['volume_analyzer'])
        
        if price_filter and 'price_filter' in settings:
            price_filter.update_settings(settings['price_filter'])
            
        await manager.broadcast(json.dumps({
            "type": "settings_updated",
            "data": settings
        }))
        return {"status": "success", "settings": settings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats")
async def get_stats():
    """Получить статистику работы"""
    try:
        if volume_analyzer:
            stats = await volume_analyzer.get_stats()
            watchlist_count = len(await db_manager.get_watchlist())
            stats['pairs_count'] = watchlist_count
            return stats
        return {"error": "Анализатор не инициализирован"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Ожидаем сообщения от клиента
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket ошибка: {e}")
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app", 
        host=os.getenv('SERVER_HOST', '0.0.0.0'), 
        port=int(os.getenv('SERVER_PORT', 8000)), 
        reload=True,
        log_level="info"
    )