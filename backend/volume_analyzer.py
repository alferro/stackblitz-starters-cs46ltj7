import logging
import os
from typing import Dict, Optional, List
from datetime import datetime, timedelta
import statistics

logger = logging.getLogger(__name__)

class VolumeAnalyzer:
    def __init__(self, db_manager, telegram_bot=None):
        self.db_manager = db_manager
        self.telegram_bot = telegram_bot
        self.settings = {
            'analysis_hours': int(os.getenv('ANALYSIS_HOURS', 1)),
            'offset_minutes': int(os.getenv('OFFSET_MINUTES', 0)),
            'volume_multiplier': float(os.getenv('VOLUME_MULTIPLIER', 2.0)),
            'min_volume_usdt': int(os.getenv('MIN_VOLUME_USDT', 1000)),
            'alert_grouping_minutes': int(os.getenv('ALERT_GROUPING_MINUTES', 5)),
            'consecutive_long_count': int(os.getenv('CONSECUTIVE_LONG_COUNT', 3)),
            'volume_alerts_enabled': True,
            'consecutive_alerts_enabled': True
        }
        self.stats = {
            'total_candles': 0,
            'long_candles': 0,
            'alerts_count': 0,
            'consecutive_alerts_count': 0,
            'priority_alerts_count': 0,
            'last_update': None
        }
        # Кэш для отслеживания состояния свечей
        self.candle_cache = {}
        # Кэш для отслеживания подряд идущих LONG свечей
        self.consecutive_long_cache = {}

    async def analyze_volume(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Анализ объема для определения алертов"""
        try:
            current_time = int(kline_data['start'])
            is_long = float(kline_data['close']) > float(kline_data['open'])
            current_volume_usdt = float(kline_data['volume']) * float(kline_data['close'])
            
            # Проверяем, является ли это новой свечой или обновлением текущей
            is_new_candle = self._is_new_candle(symbol, current_time)
            is_candle_closed = self._is_candle_closed(kline_data)
            
            alerts = []
            
            # Обрабатываем алерты по объему
            if self.settings['volume_alerts_enabled']:
                volume_alert = await self._process_volume_alert(
                    symbol, kline_data, is_long, current_volume_usdt, is_new_candle, is_candle_closed
                )
                if volume_alert:
                    alerts.append(volume_alert)
            
            # Обрабатываем алерты по подряд идущим LONG свечам
            if self.settings['consecutive_alerts_enabled'] and is_candle_closed:
                consecutive_alert = await self._process_consecutive_long_alert(symbol, is_long)
                if consecutive_alert:
                    alerts.append(consecutive_alert)
            
            # Обновляем кэш
            self._update_candle_cache(symbol, current_time, is_long, is_candle_closed)
            
            # Проверяем приоритетные сигналы
            for alert in alerts:
                if alert['alert_type'] == 'volume_spike' and self._check_priority_signal(symbol):
                    alert['is_priority'] = True
                    self.stats['priority_alerts_count'] += 1
                    await self._save_priority_alert(alert)
            
            return alerts[0] if alerts else None
            
        except Exception as e:
            logger.error(f"Ошибка анализа объема для {symbol}: {e}")
            return None

    def _is_new_candle(self, symbol: str, current_time: int) -> bool:
        """Проверяет, является ли это новой свечой"""
        if symbol not in self.candle_cache:
            return True
        return self.candle_cache[symbol]['start_time'] != current_time

    def _is_candle_closed(self, kline_data: Dict) -> bool:
        """Проверяет, закрыта ли свеча (примерно через 58-59 секунд после начала)"""
        current_time = datetime.now().timestamp() * 1000
        candle_start = int(kline_data['start'])
        elapsed = current_time - candle_start
        return elapsed >= 58000  # 58 секунд

    async def _process_volume_alert(self, symbol: str, kline_data: Dict, is_long: bool, 
                                  current_volume_usdt: float, is_new_candle: bool, 
                                  is_candle_closed: bool) -> Optional[Dict]:
        """Обработка алертов по объему"""
        if current_volume_usdt < self.settings['min_volume_usdt']:
            return None

        # Получаем исторические объемы
        historical_volumes = await self.db_manager.get_historical_long_volumes(
            symbol, self.settings['analysis_hours'], self.settings['offset_minutes']
        )

        if len(historical_volumes) < 10:
            return None

        average_volume = statistics.mean(historical_volumes)
        volume_ratio = current_volume_usdt / average_volume if average_volume > 0 else 0

        if volume_ratio < self.settings['volume_multiplier']:
            return None

        # Проверяем, нужно ли создать алерт
        cache_key = f"{symbol}_{int(kline_data['start'])}"
        
        # Первый алерт - в момент превышения объема (если свеча LONG)
        if is_long and is_new_candle and cache_key not in self.candle_cache:
            alert_data = self._create_volume_alert_data(
                symbol, kline_data, volume_ratio, current_volume_usdt, 
                average_volume, 'initial', False
            )
            await self._save_alert(alert_data)
            return alert_data

        # Второй алерт - после закрытия свечи
        if is_candle_closed and cache_key in self.candle_cache:
            cached_data = self.candle_cache[cache_key]
            if not cached_data.get('final_alert_sent', False):
                is_true_signal = is_long
                alert_data = self._create_volume_alert_data(
                    symbol, kline_data, volume_ratio, current_volume_usdt,
                    average_volume, 'final', is_true_signal
                )
                await self._save_alert(alert_data)
                self.candle_cache[cache_key]['final_alert_sent'] = True
                return alert_data

        return None

    async def _process_consecutive_long_alert(self, symbol: str, is_long: bool) -> Optional[Dict]:
        """Обработка алертов по подряд идущим LONG свечам"""
        if symbol not in self.consecutive_long_cache:
            self.consecutive_long_cache[symbol] = {'count': 0, 'last_alert_count': 0}

        cache = self.consecutive_long_cache[symbol]

        if is_long:
            cache['count'] += 1
        else:
            cache['count'] = 0

        # Проверяем, достигли ли нужного количества подряд идущих LONG свечей
        if (cache['count'] >= self.settings['consecutive_long_count'] and 
            cache['count'] > cache['last_alert_count']):
            
            alert_data = {
                'symbol': symbol,
                'alert_type': 'consecutive_long',
                'consecutive_count': cache['count'],
                'timestamp': datetime.now(),
                'message': f"Подряд {cache['count']} LONG свечей"
            }
            
            cache['last_alert_count'] = cache['count']
            await self._save_consecutive_alert(alert_data)
            self.stats['consecutive_alerts_count'] += 1
            
            # Отправляем в Telegram
            if self.telegram_bot:
                await self.telegram_bot.send_consecutive_alert(alert_data)
            
            return alert_data

        return None

    def _create_volume_alert_data(self, symbol: str, kline_data: Dict, volume_ratio: float,
                                current_volume_usdt: float, average_volume: float,
                                alert_stage: str, is_true_signal: Optional[bool]) -> Dict:
        """Создание данных алерта по объему"""
        return {
            'symbol': symbol,
            'alert_type': 'volume_spike',
            'alert_stage': alert_stage,  # 'initial' или 'final'
            'is_true_signal': is_true_signal,
            'price': float(kline_data['close']),
            'volume_ratio': round(volume_ratio, 2),
            'current_volume_usdt': int(current_volume_usdt),
            'average_volume_usdt': int(average_volume),
            'timestamp': datetime.now(),
            'candle_start_time': int(kline_data['start']),
            'message': f"Объем превышен в {volume_ratio:.2f}x раз ({alert_stage})"
        }

    def _check_priority_signal(self, symbol: str) -> bool:
        """Проверяет, является ли сигнал приоритетным"""
        if symbol not in self.consecutive_long_cache:
            return False
        
        # Проверяем, были ли недавно подряд идущие LONG свечи
        cache = self.consecutive_long_cache[symbol]
        return cache['count'] >= self.settings['consecutive_long_count']

    async def _save_alert(self, alert_data: Dict):
        """Сохранение обычного алерта"""
        # Проверяем недавние группы алертов
        recent_group = await self.db_manager.get_recent_alert_group(
            alert_data['symbol'], self.settings['alert_grouping_minutes']
        )
        
        if recent_group:
            await self.db_manager.update_alert_group(recent_group['id'], alert_data)
            await self.db_manager.save_alert(recent_group['id'], alert_data)
        else:
            group_id = await self.db_manager.create_alert_group(alert_data)
            await self.db_manager.save_alert(group_id, alert_data)
            
            # Отправляем в Telegram только новые группы
            if self.telegram_bot and alert_data['alert_stage'] == 'initial':
                await self.telegram_bot.send_alert(alert_data)
        
        self.stats['alerts_count'] += 1

    async def _save_consecutive_alert(self, alert_data: Dict):
        """Сохранение алерта по подряд идущим свечам"""
        await self.db_manager.save_consecutive_alert(alert_data)

    async def _save_priority_alert(self, alert_data: Dict):
        """Сохранение приоритетного алерта"""
        await self.db_manager.save_priority_alert(alert_data)

    def _update_candle_cache(self, symbol: str, current_time: int, is_long: bool, is_closed: bool):
        """Обновление кэша свечей"""
        cache_key = f"{symbol}_{current_time}"
        if cache_key not in self.candle_cache:
            self.candle_cache[cache_key] = {
                'start_time': current_time,
                'is_long': is_long,
                'is_closed': is_closed,
                'final_alert_sent': False
            }
        else:
            self.candle_cache[cache_key].update({
                'is_long': is_long,
                'is_closed': is_closed
            })

    def update_settings(self, new_settings: Dict):
        """Обновление настроек анализатора"""
        self.settings.update(new_settings)
        logger.info(f"Настройки анализатора обновлены: {self.settings}")

    def get_settings(self) -> Dict:
        """Получение текущих настроек"""
        return self.settings.copy()

    async def get_stats(self) -> Dict:
        """Получение статистики работы"""
        self.stats['last_update'] = datetime.now().isoformat()
        return self.stats.copy()