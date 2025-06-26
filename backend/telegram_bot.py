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
        """Отправка алерта по объему в Telegram канал"""
        if not self.enabled:
            return False

        try:
            # Формируем сообщение
            message = self._format_volume_alert_message(alert_data)
            
            # Отправляем сообщение
            return await self._send_message(message)

        except Exception as e:
            logger.error(f"Ошибка отправки алерта в Telegram: {e}")
            return False

    async def send_consecutive_alert(self, alert_data: Dict) -> bool:
        """Отправка алерта по подряд идущим LONG свечам в Telegram"""
        if not self.enabled:
            return False

        try:
            # Формируем сообщение
            message = self._format_consecutive_alert_message(alert_data)
            
            # Отправляем сообщение
            return await self._send_message(message)

        except Exception as e:
            logger.error(f"Ошибка отправки consecutive алерта в Telegram: {e}")
            return False

    def _format_volume_alert_message(self, alert_data: Dict) -> str:
        """Форматирование сообщения алерта по объему для Telegram"""
        symbol = alert_data['symbol']
        price = alert_data['price']
        volume_ratio = alert_data['volume_ratio']
        current_volume = alert_data['current_volume_usdt']
        average_volume = alert_data['average_volume_usdt']
        alert_stage = alert_data.get('alert_stage', 'initial')
        is_true_signal = alert_data.get('is_true_signal')
        is_priority = alert_data.get('is_priority', False)
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Эмодзи для визуального выделения
        if is_priority:
            emoji = "🔥"
            priority_text = " (ПРИОРИТЕТНЫЙ)"
        elif volume_ratio >= 5:
            emoji = "🚀"
            priority_text = ""
        elif volume_ratio >= 3:
            emoji = "📈"
            priority_text = ""
        else:
            emoji = "⚡"
            priority_text = ""

        # Статус сигнала
        if alert_stage == 'final':
            if is_true_signal:
                status_emoji = "✅"
                status_text = "ИСТИННЫЙ"
            else:
                status_emoji = "❌"
                status_text = "ЛОЖНЫЙ"
        else:
            status_emoji = "⏳"
            status_text = "НАЧАЛЬНЫЙ"
        
        message = f"""
{emoji} <b>АЛЕРТ ПО ОБЪЕМУ{priority_text}</b>

💰 <b>Пара:</b> {symbol}
💵 <b>Цена:</b> ${price:,.8f}
📊 <b>Превышение объема:</b> {volume_ratio}x

📈 <b>Текущий объем:</b> ${current_volume:,.0f}
📉 <b>Средний объем:</b> ${average_volume:,.0f}

{status_emoji} <b>Статус:</b> {status_text}

🕐 <b>Время:</b> {timestamp}

#VolumeAlert #{symbol.replace('USDT', '')}
        """.strip()
        
        return message

    def _format_consecutive_alert_message(self, alert_data: Dict) -> str:
        """Форматирование сообщения алерта по подряд идущим LONG свечам"""
        symbol = alert_data['symbol']
        consecutive_count = alert_data['consecutive_count']
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Эмодзи в зависимости от количества свечей
        if consecutive_count >= 5:
            emoji = "🔥"
        elif consecutive_count >= 4:
            emoji = "🚀"
        else:
            emoji = "📈"
        
        message = f"""
{emoji} <b>ПОДРЯД ИДУЩИЕ LONG СВЕЧИ</b>

💰 <b>Пара:</b> {symbol}
🕯️ <b>Количество подряд:</b> {consecutive_count} свечей

🕐 <b>Время:</b> {timestamp}

#ConsecutiveLong #{symbol.replace('USDT', '')}
        """.strip()
        
        return message

    async def _send_message(self, message: str) -> bool:
        """Отправка сообщения в Telegram"""
        try:
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
                        logger.info(f"Сообщение отправлено в Telegram")
                        return True
                    else:
                        logger.error(f"Ошибка отправки в Telegram: {response.status}")
                        return False

        except Exception as e:
            logger.error(f"Ошибка отправки сообщения в Telegram: {e}")
            return False

    async def send_system_message(self, message: str) -> bool:
        """Отправка системного сообщения"""
        if not self.enabled:
            return False

        try:
            formatted_message = f"🤖 <b>Система:</b> {message}"
            return await self._send_message(formatted_message)

        except Exception as e:
            logger.error(f"Ошибка отправки системного сообщения: {e}")
            return False