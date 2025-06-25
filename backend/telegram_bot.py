import asyncio
import logging
import os
from typing import Dict, Optional
import aiohttp
from datetime import datetime

logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            logger.warning("Telegram бот не настроен. Проверьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID в .env")
        else:
            logger.info("Telegram бот инициализирован")

    async def send_alert(self, alert_data: Dict) -> bool:
        """Отправка алерта в Telegram канал"""
        if not self.enabled:
            return False

        try:
            # Формируем сообщение
            message = self._format_alert_message(alert_data)
            
            # Отправляем сообщение
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    if response.status == 200:
                        logger.info(f"Алерт отправлен в Telegram для {alert_data['symbol']}")
                        return True
                    else:
                        logger.error(f"Ошибка отправки в Telegram: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Ошибка отправки алерта в Telegram: {e}")
            return False

    def _format_alert_message(self, alert_data: Dict) -> str:
        """Форматирование сообщения алерта для Telegram"""
        symbol = alert_data['symbol']
        price = alert_data['price']
        volume_ratio = alert_data['volume_ratio']
        current_volume = alert_data['current_volume_usdt']
        average_volume = alert_data['average_volume_usdt']
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Эмодзи для визуального выделения
        emoji = "🚀" if volume_ratio >= 5 else "📈" if volume_ratio >= 3 else "⚡"
        
        message = f"""
{emoji} <b>АЛЕРТ ПО ОБЪЕМУ</b>

💰 <b>Пара:</b> {symbol}
💵 <b>Цена:</b> ${price:,.8f}
📊 <b>Превышение объема:</b> {volume_ratio}x

📈 <b>Текущий объем:</b> ${current_volume:,.0f}
📉 <b>Средний объем:</b> ${average_volume:,.0f}

🕐 <b>Время:</b> {timestamp}

#VolumeAlert #{symbol.replace('USDT', '')}
        """.strip()
        
        return message

    async def send_system_message(self, message: str) -> bool:
        """Отправка системного сообщения"""
        if not self.enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                'chat_id': self.chat_id,
                'text': f"🤖 <b>Система:</b> {message}",
                'parse_mode': 'HTML'
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, data=data) as response:
                    return response.status == 200

        except Exception as e:
            logger.error(f"Ошибка отправки системного сообщения: {e}")
            return False