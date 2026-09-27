import asyncio
import time
import httpx
import logging
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional, Dict
from config import settings

logger = logging.getLogger("telegram_service")

DB_PATH = os.path.join(os.path.dirname(__file__), "jarvis_logs.db")

class TelegramService:
    def __init__(self):
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.auto_flush = settings.TELEGRAM_AUTO_FLUSH_24H
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS call_logs (
                    call_id TEXT PRIMARY KEY,
                    message_id INTEGER,
                    caller_number TEXT,
                    transcript TEXT,
                    summary TEXT,
                    created_at TIMESTAMP,
                    expires_at TIMESTAMP
                )
            """)
            conn.commit()

    async def send_call_started(self, call_id: str, caller_info: str) -> Optional[int]:
        """Sends initial alert to Harsh's phone when Jarvis answers."""
        if not self._is_configured():
            logger.info(f"[Mock Telegram] Call started: {caller_info}")
            return None

        text = (
            f"🔴 *J.A.R.V.I.S. Call Active*\n"
            f"👤 *Caller:* `{caller_info}`\n"
            f"🕒 *Time:* {datetime.now().strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🎙️ _Jarvis is now greeting the caller..._"
        )

        msg_id = await self._send_message(text)
        if msg_id:
            # Save into DB with 24h expiration
            now = datetime.utcnow()
            expires = now + timedelta(hours=24)
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO call_logs 
                    (call_id, message_id, caller_number, transcript, summary, created_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (call_id, msg_id, caller_info, "", "", now, expires))
                conn.commit()
        return msg_id

    async def update_live_transcript(self, message_id: int, caller_info: str, transcript_lines: list):
        """Updates the active Telegram message in real-time as the conversation progresses."""
        if not self._is_configured() or not message_id:
            return

        dialogue = "\n".join(transcript_lines[-6:])  # Show latest 6 exchanges to stay within limit
        text = (
            f"🔴 *J.A.R.V.I.S. Live Call In Progress*\n"
            f"👤 *Caller:* `{caller_info}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{dialogue}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ _Listening..._"
        )

        await self._edit_message(message_id, text)

    async def send_call_summary(self, call_id: str, message_id: Optional[int], caller_info: str, summary: str, full_transcript: str):
        """Finalizes the call: posts the structured AI summary and full conversation."""
        if not self._is_configured():
            logger.info(f"\n--- CALL SUMMARY ---\n{summary}\n--- TRANSCRIPT ---\n{full_transcript}")
            return

        final_text = (
            f"🟢 *J.A.R.V.I.S. Call Completed*\n"
            f"👤 *Caller:* `{caller_info}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"*Summary & Action Items:*\n"
            f"{summary}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📜 *Full Transcript:*\n"
            f"_{full_transcript}_\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⏳ _Self-destruct timer: This message will be flushed in 24 hours._"
        )

        if message_id:
            # Edit the existing message to avoid chat spam
            success = await self._edit_message(message_id, final_text)
            if not success:
                # If editing failed (e.g. text too long), send as new message
                new_id = await self._send_message(final_text)
                if new_id:
                    self._update_log_msg_id(call_id, new_id)
        else:
            new_id = await self._send_message(final_text)
            if new_id:
                now = datetime.utcnow()
                expires = now + timedelta(hours=24)
                with sqlite3.connect(DB_PATH) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT OR REPLACE INTO call_logs 
                        (call_id, message_id, caller_number, transcript, summary, created_at, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (call_id, new_id, caller_info, full_transcript, summary, now, expires))
                    conn.commit()

    async def flush_expired_logs(self):
        """24-Hour Auto-Flush Worker: permanently purges call logs and deletes messages."""
        now = datetime.utcnow()
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT call_id, message_id FROM call_logs WHERE expires_at < ?", (now,))
            expired_rows = cursor.fetchall()

            for call_id, msg_id in expired_rows:
                if self.auto_flush and self._is_configured() and msg_id:
                    try:
                        await self._delete_message(msg_id)
                        logger.info(f"Deleted expired Telegram message {msg_id} for call {call_id}.")
                    except Exception as e:
                        logger.error(f"Failed to delete Telegram message {msg_id}: {e}")

                # Purge from DB
                cursor.execute("DELETE FROM call_logs WHERE call_id = ?", (call_id,))
            conn.commit()
            if expired_rows:
                logger.info(f"Flushed {len(expired_rows)} call logs older than 24 hours.")

    def _update_log_msg_id(self, call_id: str, new_msg_id: int):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE call_logs SET message_id = ? WHERE call_id = ?", (new_msg_id, call_id))
            conn.commit()

    def _is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id and self.bot_token != "your_telegram_bot_token_here")

    async def _send_message(self, text: str) -> Optional[int]:
        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    return res.json().get("result", {}).get("message_id")
                else:
                    logger.error(f"Telegram error {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
        return None

    async def _edit_message(self, message_id: int, text: str) -> bool:
        url = f"{self.api_url}/editMessageText"
        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.post(url, json=payload)
                return res.status_code == 200
        except Exception as e:
            logger.error(f"Failed to edit Telegram message: {e}")
            return False

    async def _delete_message(self, message_id: int):
        url = f"{self.api_url}/deleteMessage"
        payload = {
            "chat_id": self.chat_id,
            "message_id": message_id
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)

telegram_service = TelegramService()
