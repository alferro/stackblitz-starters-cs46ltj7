import asyncio
import logging
import os
from typing import List, Dict
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

class PriceFilter:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.rest_url = "https://api.bybit.com"
        self.settings = {
            'price_check_interval_minutes': int(os.getenv('PRICE_CHECK_INTERVAL_MINUTES', 5)),
            'price_history_days': int(os.getenv('PRICE_HISTORY_DAYS', 30)),
            'price_drop_percentage': float(os.getenv('PRICE_DROP_PERCENTAGE', 10.0))
        }
        self.is_running = False

    async def start(self):
        """Запуск периодической проверки торговых пар"""
        self.is_running = True
        logger.info("Запуск фильтрации по цене")
        
        # Первоначальное обновление
        await self.update_watchlist()
        
        # Периодическое обновление
        while self.is_running:
            try:
                await asyncio.sleep(self.settings['price_check_interval_minutes'] * 60)
                if self.is_running:
                    await self.update_watchlist()
            except Exception as e:
                logger.error(f"Ошибка при обновлении watchlist: {e}")
                await asyncio.sleep(60)  # Ждем минуту перед повторной попыткой

    async def stop(self):
        """Остановка фильтрации"""
        self.is_running = False

    async def get_perpetual_pairs(self) -> List[str]:
        """Получение списка бессрочных фьючерсных контрактов"""
        try:
            url = f"{self.rest_url}/v5/market/instruments-info"
            params = {'category': 'linear'}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('retCode') == 0:
                pairs = []
                for instrument in data['result']['list']:
                    if (instrument['contractType'] == 'LinearPerpetual' and 
                        instrument['status'] == 'Trading' and
                        instrument['symbol'].endswith('USDT')):
                        pairs.append(instrument['symbol'])
                return pairs
            else:
                logger.error(f"Ошибка получения пар: {data.get('retMsg')}")
                return []
        except Exception as e:
            logger.error(f"Ошибка запроса пар: {e}")
            return []

    async def get_historical_price(self, symbol: str, days_ago: int) -> float:
        """Получение цены актива за указанный период назад"""
        try:
            url = f"{self.rest_url}/v5/market/kline"
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = end_time - (days_ago * 24 * 60 * 60 * 1000)
            params = {
                'category': 'linear',
                'symbol': symbol,
                'interval': 'D',
                'start': start_time,
                'limit': 1
            }
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('retCode') == 0 and data['result']['list']:
                return float(data['result']['list'][0][4])  # Закрытие свечи
            return 0.0
        except Exception as e:
            logger.error(f"Ошибка получения исторической цены для {symbol}: {e}")
            return 0.0

    async def get_current_price(self, symbol: str) -> float:
        """Получение текущей цены актива"""
        try:
            url = f"{self.rest_url}/v5/market/tickers"
            params = {'category': 'linear', 'symbol': symbol}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()

            if data.get('retCode') == 0 and data['result']['list']:
                return float(data['result']['list'][0]['lastPrice'])
            return 0.0
        except Exception as e:
            logger.error(f"Ошибка получения текущей цены для {symbol}: {e}")
            return 0.0

    async def update_watchlist(self):
        """Обновление watchlist на основе критериев цены"""
        try:
            logger.info("Начало обновления watchlist...")
            pairs = await self.get_perpetual_pairs()
            current_watchlist = await self.db_manager.get_watchlist()
            new_watchlist = []
            
            logger.info(f"Проверка {len(pairs)} торговых пар...")

            for i, symbol in enumerate(pairs):
                try:
                    current_price = await self.get_current_price(symbol)
                    historical_price = await self.get_historical_price(symbol, self.settings['price_history_days'])

                    if current_price > 0 and historical_price > 0:
                        price_drop = ((historical_price - current_price) / historical_price) * 100
                        
                        if price_drop >= self.settings['price_drop_percentage']:
                            new_watchlist.append(symbol)
                            if symbol not in current_watchlist:
                                await self.db_manager.add_to_watchlist(
                                    symbol, price_drop, current_price, historical_price
                                )
                                logger.info(f"Добавлена пара {symbol} в watchlist (падение цены: {price_drop:.2f}%)")
                        else:
                            if symbol in current_watchlist:
                                await self.db_manager.remove_from_watchlist(symbol)
                                logger.info(f"Удалена пара {symbol} из watchlist (падение цены: {price_drop:.2f}%)")

                    # Задержка для избежания ограничений API
                    if i % 10 == 0:  # Каждые 10 запросов
                        await asyncio.sleep(1)
                    else:
                        await asyncio.sleep(0.1)
                        
                except Exception as e:
                    logger.error(f"Ошибка обработки пары {symbol}: {e}")
                    continue

            logger.info(f"Watchlist обновлен: {len(new_watchlist)} активных пар")
            return new_watchlist
            
        except Exception as e:
            logger.error(f"Ошибка обновления watchlist: {e}")
            return []

    def update_settings(self, new_settings: Dict):
        """Обновление настроек фильтра"""
        self.settings.update(new_settings)
        logger.info(f"Настройки фильтра обновлены: {self.settings}")