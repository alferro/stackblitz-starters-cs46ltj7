import asyncio
import logging
from typing import List, Dict, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import os

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self):
        self.connection = None
        self.db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'tradingbase'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'password')
        }

    async def initialize(self):
        """Инициализация подключения к базе данных"""
        try:
            self.connection = psycopg2.connect(**self.db_config)
            self.connection.autocommit = True

            # Создаем необходимые таблицы
            await self.create_tables()

            # Обновляем существующие таблицы
            await self.update_tables()

            logger.info("База данных успешно инициализирована")

        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise

    async def create_tables(self):
        """Создание необходимых таблиц"""
        try:
            cursor = self.connection.cursor()

            # Создаем таблицу watchlist
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT TRUE,
                    price_drop_percentage DECIMAL(5, 2),
                    current_price DECIMAL(20, 8),
                    historical_price DECIMAL(20, 8),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Создаем таблицу для хранения исторических данных
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS kline_data (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    open_time BIGINT NOT NULL,
                    close_time BIGINT NOT NULL,
                    open_price DECIMAL(20, 8) NOT NULL,
                    high_price DECIMAL(20, 8) NOT NULL,
                    low_price DECIMAL(20, 8) NOT NULL,
                    close_price DECIMAL(20, 8) NOT NULL,
                    volume DECIMAL(20, 8) NOT NULL,
                    volume_usdt DECIMAL(20, 8) NOT NULL,
                    is_long BOOLEAN NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(symbol, open_time)
                )
            """)

            # Создаем таблицу для групп алертов по объему
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_groups (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    first_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    alert_count INTEGER DEFAULT 1,
                    max_volume_ratio DECIMAL(10, 2) NOT NULL,
                    max_price DECIMAL(20, 8) NOT NULL,
                    max_volume_usdt DECIMAL(20, 8) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Создаем таблицу для отдельных алертов в группах
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    group_id INTEGER REFERENCES alert_groups(id) ON DELETE CASCADE,
                    symbol VARCHAR(20) NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    alert_stage VARCHAR(20) DEFAULT 'initial',
                    is_true_signal BOOLEAN,
                    price DECIMAL(20, 8) NOT NULL,
                    volume_ratio DECIMAL(10, 2) NOT NULL,
                    current_volume_usdt DECIMAL(20, 8) NOT NULL,
                    average_volume_usdt DECIMAL(20, 8) NOT NULL,
                    candle_start_time BIGINT,
                    message TEXT,
                    telegram_sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Создаем таблицу для алертов по подряд идущим LONG свечам
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS consecutive_alerts (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    consecutive_count INTEGER NOT NULL,
                    message TEXT,
                    telegram_sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Создаем таблицу для приоритетных алертов
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS priority_alerts (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    alert_stage VARCHAR(20) DEFAULT 'initial',
                    is_true_signal BOOLEAN,
                    price DECIMAL(20, 8) NOT NULL,
                    volume_ratio DECIMAL(10, 2) NOT NULL,
                    current_volume_usdt DECIMAL(20, 8) NOT NULL,
                    average_volume_usdt DECIMAL(20, 8) NOT NULL,
                    consecutive_count INTEGER,
                    candle_start_time BIGINT,
                    message TEXT,
                    telegram_sent BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Создаем индексы для оптимизации запросов
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_kline_symbol_time 
                ON kline_data(symbol, open_time)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_kline_symbol_long_time 
                ON kline_data(symbol, is_long, open_time)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alert_groups_symbol_time 
                ON alert_groups(symbol, last_alert_time)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_group_time 
                ON alerts(group_id, created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_consecutive_alerts_symbol_time 
                ON consecutive_alerts(symbol, created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_priority_alerts_symbol_time 
                ON priority_alerts(symbol, created_at)
            """)

            cursor.close()
            logger.info("Таблицы успешно созданы")

        except Exception as e:
            logger.error(f"Ошибка создания таблиц: {e}")
            raise

    async def update_tables(self):
        """Обновление существующих таблиц для добавления новых колонок"""
        try:
            cursor = self.connection.cursor()

            # Проверяем и добавляем новые колонки в таблицу alerts
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'alerts' AND column_name = 'alert_stage'
            """)

            if not cursor.fetchone():
                logger.info("Добавление новых колонок в таблицу alerts...")

                cursor.execute("""
                    ALTER TABLE alerts 
                    ADD COLUMN IF NOT EXISTS alert_stage VARCHAR(20) DEFAULT 'initial',
                    ADD COLUMN IF NOT EXISTS is_true_signal BOOLEAN,
                    ADD COLUMN IF NOT EXISTS candle_start_time BIGINT
                """)

                logger.info("Новые колонки добавлены в таблицу alerts")

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка обновления таблиц: {e}")

    async def save_consecutive_alert(self, alert_data: Dict):
        """Сохранение алерта по подряд идущим LONG свечам"""
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                INSERT INTO consecutive_alerts 
                (symbol, consecutive_count, message)
                VALUES (%s, %s, %s)
            """, (
                alert_data['symbol'],
                alert_data['consecutive_count'],
                alert_data.get('message', '')
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения consecutive алерта: {e}")

    async def save_priority_alert(self, alert_data: Dict):
        """Сохранение приоритетного алерта"""
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                INSERT INTO priority_alerts 
                (symbol, alert_type, alert_stage, is_true_signal, price, volume_ratio,
                 current_volume_usdt, average_volume_usdt, consecutive_count, 
                 candle_start_time, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                alert_data['symbol'],
                alert_data.get('alert_type', 'volume_spike'),
                alert_data.get('alert_stage', 'initial'),
                alert_data.get('is_true_signal'),
                alert_data['price'],
                alert_data['volume_ratio'],
                alert_data['current_volume_usdt'],
                alert_data['average_volume_usdt'],
                alert_data.get('consecutive_count'),
                alert_data.get('candle_start_time'),
                alert_data.get('message', '')
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения приоритетного алерта: {e}")

    async def get_consecutive_alerts(self, limit: int = 100) -> List[Dict]:
        """Получить список алертов по подряд идущим LONG свечам"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, symbol, consecutive_count, message, telegram_sent, created_at
                FROM consecutive_alerts 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения consecutive алертов: {e}")
            return []

    async def get_priority_alerts(self, limit: int = 100) -> List[Dict]:
        """Получить список приоритетных алертов"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, symbol, alert_type, alert_stage, is_true_signal, price,
                       volume_ratio, current_volume_usdt, average_volume_usdt,
                       consecutive_count, candle_start_time, message, telegram_sent, created_at
                FROM priority_alerts 
                ORDER BY created_at DESC 
                LIMIT %s
            """, (limit,))

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения приоритетных алертов: {e}")
            return []

    async def clear_consecutive_alerts(self):
        """Очистить все consecutive алерты"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM consecutive_alerts")
            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка очистки consecutive алертов: {e}")

    async def clear_priority_alerts(self):
        """Очистить все приоритетные алерты"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM priority_alerts")
            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка очистки приоритетных алертов: {e}")

    # Остальные методы остаются без изменений...
    async def get_watchlist(self) -> List[str]:
        """Получить список активных торговых пар"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                SELECT symbol FROM watchlist 
                WHERE is_active = TRUE 
                ORDER BY symbol
            """)

            pairs = [row[0] for row in cursor.fetchall()]
            cursor.close()

            return pairs

        except Exception as e:
            logger.error(f"Ошибка получения watchlist: {e}")
            return []

    async def get_watchlist_details(self) -> List[Dict]:
        """Получить детальную информацию о торговых парах в watchlist"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, symbol, is_active, price_drop_percentage, 
                       current_price, historical_price, created_at, updated_at
                FROM watchlist 
                ORDER BY updated_at DESC
            """)

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения детальной информации watchlist: {e}")
            return []

    async def add_to_watchlist(self, symbol: str, price_drop: float = None,
                               current_price: float = None, historical_price: float = None):
        """Добавить торговую пару в watchlist"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                INSERT INTO watchlist (symbol, price_drop_percentage, current_price, historical_price) 
                VALUES (%s, %s, %s, %s) 
                ON CONFLICT (symbol) DO UPDATE SET
                    is_active = TRUE,
                    price_drop_percentage = EXCLUDED.price_drop_percentage,
                    current_price = EXCLUDED.current_price,
                    historical_price = EXCLUDED.historical_price,
                    updated_at = CURRENT_TIMESTAMP
            """, (symbol, price_drop, current_price, historical_price))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка добавления в watchlist: {e}")

    async def update_watchlist_item(self, item_id: int, symbol: str, is_active: bool):
        """Обновить элемент watchlist"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE watchlist 
                SET symbol = %s, is_active = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            """, (symbol, is_active, item_id))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка обновления watchlist: {e}")

    async def remove_from_watchlist(self, symbol: str = None, item_id: int = None):
        """Удалить торговую пару из watchlist"""
        try:
            cursor = self.connection.cursor()
            
            if item_id:
                cursor.execute("DELETE FROM watchlist WHERE id = %s", (item_id,))
            elif symbol:
                cursor.execute("DELETE FROM watchlist WHERE symbol = %s", (symbol,))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка удаления из watchlist: {e}")

    async def save_kline_data(self, symbol: str, kline_data: Dict):
        """Сохранение данных свечи в базу данных"""
        try:
            cursor = self.connection.cursor()

            # Определяем, является ли свеча LONG (зеленой)
            is_long = float(kline_data['close']) > float(kline_data['open'])

            # Рассчитываем объем в USDT
            volume_usdt = float(kline_data['volume']) * float(kline_data['close'])

            cursor.execute("""
                INSERT INTO kline_data 
                (symbol, open_time, close_time, open_price, high_price, 
                 low_price, close_price, volume, volume_usdt, is_long)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, open_time) DO UPDATE SET
                    close_time = EXCLUDED.close_time,
                    open_price = EXCLUDED.open_price,
                    high_price = EXCLUDED.high_price,
                    low_price = EXCLUDED.low_price,
                    close_price = EXCLUDED.close_price,
                    volume = EXCLUDED.volume,
                    volume_usdt = EXCLUDED.volume_usdt,
                    is_long = EXCLUDED.is_long
            """, (
                symbol,
                int(kline_data['start']),
                int(kline_data['end']),
                float(kline_data['open']),
                float(kline_data['high']),
                float(kline_data['low']),
                float(kline_data['close']),
                float(kline_data['volume']),
                volume_usdt,
                is_long
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения данных свечи: {e}")

    async def get_recent_alert_group(self, symbol: str, minutes: int) -> Optional[Dict]:
        """Получить недавнюю группу алертов для символа"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            cursor.execute("""
                SELECT * FROM alert_groups 
                WHERE symbol = %s 
                AND is_active = TRUE
                AND last_alert_time >= %s
                ORDER BY last_alert_time DESC 
                LIMIT 1
            """, (symbol, time_threshold))

            result = cursor.fetchone()
            cursor.close()

            return dict(result) if result else None

        except Exception as e:
            logger.error(f"Ошибка получения недавней группы алертов: {e}")
            return None

    async def create_alert_group(self, alert_data: Dict) -> int:
        """Создание новой группы алертов"""
        try:
            cursor = self.connection.cursor()
            
            now = datetime.now()
            
            cursor.execute("""
                INSERT INTO alert_groups 
                (symbol, alert_type, first_alert_time, last_alert_time, 
                 alert_count, max_volume_ratio, max_price, max_volume_usdt)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                alert_data['symbol'],
                alert_data.get('alert_type', 'volume_spike'),
                now,
                now,
                1,
                alert_data['volume_ratio'],
                alert_data['price'],
                alert_data['current_volume_usdt']
            ))

            group_id = cursor.fetchone()[0]
            cursor.close()
            
            return group_id

        except Exception as e:
            logger.error(f"Ошибка создания группы алертов: {e}")
            return None

    async def update_alert_group(self, group_id: int, alert_data: Dict):
        """Обновление группы алертов"""
        try:
            cursor = self.connection.cursor()
            
            now = datetime.now()
            
            cursor.execute("""
                UPDATE alert_groups 
                SET alert_count = alert_count + 1,
                    last_alert_time = %s,
                    updated_at = %s,
                    max_volume_ratio = GREATEST(max_volume_ratio, %s),
                    max_price = %s,
                    max_volume_usdt = GREATEST(max_volume_usdt, %s)
                WHERE id = %s
            """, (
                now,
                now,
                alert_data['volume_ratio'],
                alert_data['price'],
                alert_data['current_volume_usdt'],
                group_id
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка обновления группы алертов: {e}")

    async def save_alert(self, group_id: int, alert_data: Dict):
        """Сохранение алерта в группе"""
        try:
            cursor = self.connection.cursor()
            
            cursor.execute("""
                INSERT INTO alerts 
                (group_id, symbol, alert_type, alert_stage, is_true_signal, price, volume_ratio, 
                 current_volume_usdt, average_volume_usdt, candle_start_time, message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                group_id,
                alert_data['symbol'],
                alert_data.get('alert_type', 'volume_spike'),
                alert_data.get('alert_stage', 'initial'),
                alert_data.get('is_true_signal'),
                alert_data['price'],
                alert_data['volume_ratio'],
                alert_data['current_volume_usdt'],
                alert_data['average_volume_usdt'],
                alert_data.get('candle_start_time'),
                alert_data.get('message', '')
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения алерта: {e}")

    async def get_alert_groups(self, limit: int = 100) -> List[Dict]:
        """Получить список групп алертов"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, symbol, alert_type, first_alert_time, last_alert_time,
                       alert_count, max_volume_ratio, max_price, max_volume_usdt,
                       is_active, created_at, updated_at
                FROM alert_groups 
                WHERE is_active = TRUE
                ORDER BY last_alert_time DESC 
                LIMIT %s
            """, (limit,))

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения групп алертов: {e}")
            return []

    async def get_alerts_in_group(self, group_id: int) -> List[Dict]:
        """Получить алерты в группе"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, alert_stage, is_true_signal, price, volume_ratio, 
                       current_volume_usdt, average_volume_usdt, candle_start_time,
                       message, telegram_sent, created_at
                FROM alerts 
                WHERE group_id = %s
                ORDER BY created_at DESC
            """, (group_id,))

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения алертов в группе: {e}")
            return []

    async def delete_alert_group(self, group_id: int):
        """Удалить группу алертов"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE alert_groups SET is_active = FALSE WHERE id = %s", (group_id,))
            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка удаления группы алертов: {e}")

    async def clear_all_alerts(self):
        """Очистить все алерты"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE alert_groups SET is_active = FALSE")
            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка очистки алертов: {e}")

    async def mark_telegram_sent(self, alert_id: int):
        """Отметить алерт как отправленный в Telegram"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE alerts SET telegram_sent = TRUE WHERE id = %s
            """, (alert_id,))
            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка отметки Telegram: {e}")

    async def get_historical_long_volumes(self, symbol: str, hours: int, offset_minutes: int = 0) -> List[float]:
        """Получить объемы LONG свечей за указанный период"""
        try:
            cursor = self.connection.cursor()

            # Рассчитываем временные границы
            current_time = int(datetime.now().timestamp() * 1000)
            end_time = current_time - (offset_minutes * 60 * 1000)
            start_time = end_time - (hours * 60 * 60 * 1000)

            cursor.execute("""
                SELECT volume_usdt FROM kline_data 
                WHERE symbol = %s 
                AND is_long = TRUE 
                AND open_time >= %s 
                AND open_time < %s
                ORDER BY open_time
            """, (symbol, start_time, end_time))

            volumes = [float(row[0]) for row in cursor.fetchall()]
            cursor.close()

            return volumes

        except Exception as e:
            logger.error(f"Ошибка получения исторических объемов: {e}")
            return []

    def close(self):
        """Закрытие соединения с базой данных"""
        if self.connection:
            self.connection.close()