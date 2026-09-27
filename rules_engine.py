import sqlite3
import os
import logging
from typing import Tuple, List, Dict
from config import settings

logger = logging.getLogger("rules_engine")

DB_PATH = os.path.join(os.path.dirname(__file__), "jarvis_rules.db")

class RulesEngine:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            # Whitelist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    phone_number TEXT PRIMARY KEY,
                    contact_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Blacklist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    phone_number TEXT PRIMARY KEY,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Key-value settings table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            # Set default mode if not present
            cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('mode', ?)", (settings.SCREENING_MODE,))
            conn.commit()

    def get_mode(self) -> str:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'mode'")
            row = cursor.fetchone()
            return row[0] if row else "screen_unknown"

    def set_mode(self, mode: str):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('mode', ?)", (mode,))
            conn.commit()

    def add_whitelist(self, phone_number: str, contact_name: str = ""):
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO whitelist (phone_number, contact_name) VALUES (?, ?)", (clean_num, contact_name))
            conn.commit()
            logger.info(f"Added {clean_num} ({contact_name}) to whitelist.")

    def remove_whitelist(self, phone_number: str):
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM whitelist WHERE phone_number = ?", (clean_num,))
            conn.commit()

    def get_whitelist(self) -> List[Dict[str, str]]:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT phone_number, contact_name FROM whitelist ORDER BY contact_name ASC")
            return [{"phone_number": row[0], "contact_name": row[1]} for row in cursor.fetchall()]

    def is_whitelisted(self, phone_number: str) -> Tuple[bool, str]:
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT contact_name FROM whitelist WHERE phone_number = ?", (clean_num,))
            row = cursor.fetchone()
            if row:
                return True, row[0] or "Whitelisted Contact"
        return False, ""

    def is_blacklisted(self, phone_number: str) -> bool:
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM blacklist WHERE phone_number = ?", (clean_num,))
            return cursor.fetchone() is not None

    def should_answer(self, caller_number: str) -> Tuple[bool, str]:
        """
        Determines whether Jarvis should answer the call based on user rules.
        Returns: (should_answer: bool, reason: str)
        """
        if not caller_number:
            caller_number = "Unknown"

        # Check blacklist first
        if self.is_blacklisted(caller_number):
            return False, "Caller is blacklisted"

        mode = self.get_mode()
        whitelisted, contact_name = self.is_whitelisted(caller_number)

        if whitelisted:
            return True, f"Whitelisted: {contact_name}"

        if mode == "whitelist_only":
            return False, "Mode is whitelist_only, caller not in list"

        if mode == "screen_unknown":
            # Screen all incoming unknown or declined calls
            return True, "Unknown Caller Screening Active"

        if mode == "all":
            return True, "All calls handled by Jarvis"

        return True, "Default Accept"

    def _normalize_number(self, num: str) -> str:
        """Strip spaces, dashes, parentheses."""
        return "".join(c for c in num if c.isdigit() or c == "+")

rules_engine = RulesEngine()
