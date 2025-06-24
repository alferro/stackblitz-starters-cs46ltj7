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

            # Создаем таблицу для хранения алертов с группировкой
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(20) NOT NULL,
                    alert_type VARCHAR(50) NOT NULL,
                    price DECIMAL(20, 8) NOT NULL,
                    volume_ratio DECIMAL(10, 2) NOT NULL,
                    current_volume_usdt DECIMAL(20, 8) NOT NULL,
                    average_volume_usdt DECIMAL(20, 8) NOT NULL,
                    message TEXT,
                    alert_count INTEGER DEFAULT 1,
                    first_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                CREATE INDEX IF NOT EXISTS idx_alerts_symbol_time 
                ON alerts(symbol, created_at)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_symbol_last_time 
                ON alerts(symbol, last_alert_time)
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

            # Проверяем и добавляем новые колонки в таблицу watchlist
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'watchlist' AND column_name = 'price_drop_percentage'
            """)

            if not cursor.fetchone():
                logger.info("Добавление новых колонок в таблицу watchlist...")

                cursor.execute("""
                    ALTER TABLE watchlist 
                    ADD COLUMN IF NOT EXISTS price_drop_percentage DECIMAL(5, 2),
                    ADD COLUMN IF NOT EXISTS current_price DECIMAL(20, 8),
                    ADD COLUMN IF NOT EXISTS historical_price DECIMAL(20, 8),
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                """)

                logger.info("Новые колонки добавлены в таблицу watchlist")

            # Проверяем и добавляем новые колонки в таблицу alerts для группировки
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'alerts' AND column_name = 'alert_count'
            """)

            if not cursor.fetchone():
                logger.info("Добавление колонок для группировки алертов...")

                cursor.execute("""
                    ALTER TABLE alerts 
                    ADD COLUMN IF NOT EXISTS alert_count INTEGER DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS first_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS last_alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                """)

                # Обновляем существующие записи
                cursor.execute("""
                    UPDATE alerts 
                    SET first_alert_time = created_at, 
                        last_alert_time = created_at,
                        updated_at = created_at
                    WHERE first_alert_time IS NULL
                """)

                logger.info("Колонки для группировки алертов добавлены")

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка обновления таблиц: {e}")

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
                SELECT symbol, is_active, price_drop_percentage, 
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

    async def remove_from_watchlist(self, symbol: str):
        """Удалить торговую пару из watchlist"""
        try:
            cursor = self.connection.cursor()
            cursor.execute("""
                UPDATE watchlist SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE symbol = %s
            """, (symbol,))

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

    async def get_recent_alert(self, symbol: str, minutes: int) -> Optional[Dict]:
        """Получить недавний алерт для символа в указанном временном окне"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            
            time_threshold = datetime.now() - timedelta(minutes=minutes)
            
            cursor.execute("""
                SELECT * FROM alerts 
                WHERE symbol = %s 
                AND last_alert_time >= %s
                ORDER BY last_alert_time DESC 
                LIMIT 1
            """, (symbol, time_threshold))

            result = cursor.fetchone()
            cursor.close()

            return dict(result) if result else None

        except Exception as e:
            logger.error(f"Ошибка получения недавнего алерта: {e}")
            return None

    async def save_alert(self, alert_data: Dict):
        """Сохранение нового алерта в базу данных"""
        try:
            cursor = self.connection.cursor()
            
            now = datetime.now()
            
            cursor.execute("""
                INSERT INTO alerts 
                (symbol, alert_type, price, volume_ratio, current_volume_usdt, 
                 average_volume_usdt, message, alert_count, first_alert_time, last_alert_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                alert_data['symbol'],
                alert_data.get('alert_type', 'volume_spike'),
                alert_data['price'],
                alert_data['volume_ratio'],
                alert_data['current_volume_usdt'],
                alert_data['average_volume_usdt'],
                alert_data.get('message', ''),
                1,
                now,
                now
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка сохранения алерта: {e}")

    async def update_grouped_alert(self, alert_id: int, alert_data: Dict):
        """Обновление группированного алерта"""
        try:
            cursor = self.connection.cursor()
            
            now = datetime.now()
            
            cursor.execute("""
                UPDATE alerts 
                SET alert_count = alert_count + 1,
                    last_alert_time = %s,
                    updated_at = %s,
                    price = %s,
                    volume_ratio = GREATEST(volume_ratio, %s),
                    current_volume_usdt = GREATEST(current_volume_usdt, %s),
                    message = %s
                WHERE id = %s
            """, (
                now,
                now,
                alert_data['price'],
                alert_data['volume_ratio'],
                alert_data['current_volume_usdt'],
                f"{alert_data.get('message', '')} (обновлен)",
                alert_id
            ))

            cursor.close()

        except Exception as e:
            logger.error(f"Ошибка обновления группированного алерта: {e}")

    async def get_alerts(self, limit: int = 100) -> List[Dict]:
        """Получить список алертов с информацией о группировке"""
        try:
            cursor = self.connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute("""
                SELECT id, symbol, alert_type, price, volume_ratio, 
                       current_volume_usdt, average_volume_usdt, message,
                       alert_count, first_alert_time, last_alert_time,
                       created_at, updated_at
                FROM alerts 
                ORDER BY last_alert_time DESC 
                LIMIT %s
            """, (limit,))

            result = cursor.fetchall()
            cursor.close()

            return [dict(row) for row in result]

        except Exception as e:
            logger.error(f"Ошибка получения алертов: {e}")
            return []

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