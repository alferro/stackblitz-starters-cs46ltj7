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
            'alert_grouping_minutes': int(os.getenv('ALERT_GROUPING_MINUTES', 5))
        }
        self.stats = {
            'total_candles': 0,
            'long_candles': 0,
            'alerts_count': 0,
            'last_update': None
        }

    async def analyze_volume(self, symbol: str, kline_data: Dict) -> Optional[Dict]:
        """Анализ объема для определения алертов"""
        try:
            # Проверяем, является ли свеча LONG
            is_long = float(kline_data['close']) > float(kline_data['open'])
            if not is_long:
                return None

            # Рассчитываем объем в USDT
            current_volume_usdt = float(kline_data['volume']) * float(kline_data['close'])
            
            # Проверяем минимальный объем
            if current_volume_usdt < self.settings['min_volume_usdt']:
                return None

            # Получаем исторические объемы LONG свечей
            historical_volumes = await self.db_manager.get_historical_long_volumes(
                symbol, 
                self.settings['analysis_hours'], 
                self.settings['offset_minutes']
            )

            if len(historical_volumes) < 10:  # Недостаточно данных для анализа
                return None

            # Рассчитываем средний объем
            average_volume = statistics.mean(historical_volumes)
            
            # Проверяем превышение объема
            volume_ratio = current_volume_usdt / average_volume if average_volume > 0 else 0
            
            if volume_ratio >= self.settings['volume_multiplier']:
                # Создаем данные алерта
                alert_data = {
                    'symbol': symbol,
                    'alert_type': 'volume_spike',
                    'price': float(kline_data['close']),
                    'volume_ratio': round(volume_ratio, 2),
                    'current_volume_usdt': int(current_volume_usdt),
                    'average_volume_usdt': int(average_volume),
                    'timestamp': datetime.now(),
                    'message': f"Объем превышен в {volume_ratio:.2f}x раз"
                }
                
                # Проверяем, есть ли недавняя группа алертов для этого символа
                recent_group = await self.db_manager.get_recent_alert_group(
                    symbol, 
                    self.settings['alert_grouping_minutes']
                )
                
                if recent_group:
                    # Обновляем существующую группу
                    await self.db_manager.update_alert_group(recent_group['id'], alert_data)
                    await self.db_manager.save_alert(recent_group['id'], alert_data)
                    
                    alert_data['is_grouped'] = True
                    alert_data['group_id'] = recent_group['id']
                    alert_data['group_count'] = recent_group['alert_count'] + 1
                else:
                    # Создаем новую группу
                    group_id = await self.db_manager.create_alert_group(alert_data)
                    await self.db_manager.save_alert(group_id, alert_data)
                    
                    alert_data['is_grouped'] = False
                    alert_data['group_id'] = group_id
                    alert_data['group_count'] = 1
                    
                    # Отправляем в Telegram только новые группы алертов
                    if self.telegram_bot:
                        await self.telegram_bot.send_alert(alert_data)
                
                # Обновляем статистику
                self.stats['alerts_count'] += 1
                
                # Преобразуем timestamp в ISO строку для JSON
                alert_data['timestamp'] = alert_data['timestamp'].isoformat()
                
                return alert_data

            return None

        except Exception as e:
            logger.error(f"Ошибка анализа объема для {symbol}: {e}")
            return None

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

    def update_stats(self, is_long: bool = False):
        """Обновление статистики"""
        self.stats['total_candles'] += 1
        if is_long:
            self.stats['long_candles'] += 1