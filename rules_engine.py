import sqlite3
import os
import logging
from typing import Tuple, List, Dict
from config import settings

logger = logging.getLogger("rules_engine")

DB_PATH = os.path.join(os.path.dirname(__file__), "jarvis_rules.db")

# -----------------------------------------------------------------------
# FAMILY / VIP CONTACTS
# Calls from these numbers are answered by Jarvis with a short polite
# "unavailable" message ONLY — NO screening, NO interrogation.
# To add more, use the /api/family/add endpoint or edit below.
# -----------------------------------------------------------------------
DEFAULT_FAMILY_CONTACTS = [
    ("+918081214917", "Mummy"),
    ("+919889748839", "Papa"),
    ("+919795668394", "Durgesh Chacha"),
    ("+919473644895", "Rubi Chachi"),
    ("+917309450228", "Aniket Chacha"),
    ("+918604748839", "Abhishek Bhaiya"),
]


class RulesEngine:
    def __init__(self):
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS whitelist (
                    phone_number TEXT PRIMARY KEY,
                    contact_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    phone_number TEXT PRIMARY KEY,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Family / VIP-decline: Jarvis answers but gives a short
            # "Mr. Stark is unavailable" message only, then sends Telegram ping.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS family (
                    phone_number TEXT PRIMARY KEY,
                    contact_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            cursor.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES ('mode', ?)",
                (settings.SCREENING_MODE,)
            )
            conn.commit()

        self._seed_family_contacts()

    def _seed_family_contacts(self):
        """Pre-populate the family table with default contacts on first run."""
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            for phone, name in DEFAULT_FAMILY_CONTACTS:
                clean = self._normalize_number(phone)
                cursor.execute(
                    "INSERT OR IGNORE INTO family (phone_number, contact_name) VALUES (?, ?)",
                    (clean, name)
                )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  FAMILY / VIP METHODS                                               #
    # ------------------------------------------------------------------ #
    def is_family(self, phone_number: str) -> Tuple[bool, str]:
        """Returns (True, name) if the caller is a family/VIP contact."""
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT contact_name FROM family WHERE phone_number = ?",
                (clean_num,)
            )
            row = cursor.fetchone()
            if row:
                return True, row[0] or "Family Contact"
        return False, ""

    def add_family(self, phone_number: str, contact_name: str = ""):
        """Add a contact to the family/VIP-decline list."""
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO family (phone_number, contact_name) VALUES (?, ?)",
                (clean_num, contact_name)
            )
            conn.commit()
            logger.info(f"Added {clean_num} ({contact_name}) to family list.")

    def remove_family(self, phone_number: str):
        """Remove a contact from the family/VIP-decline list."""
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM family WHERE phone_number = ?", (clean_num,))
            conn.commit()

    def get_family(self) -> List[Dict[str, str]]:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT phone_number, contact_name FROM family ORDER BY contact_name ASC"
            )
            return [{"phone_number": row[0], "contact_name": row[1]} for row in cursor.fetchall()]

    # ------------------------------------------------------------------ #
    #  MODE METHODS                                                        #
    # ------------------------------------------------------------------ #
    def get_mode(self) -> str:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'mode'")
            row = cursor.fetchone()
            return row[0] if row else "screen_unknown"

    def set_mode(self, mode: str):
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('mode', ?)",
                (mode,)
            )
            conn.commit()

    # ------------------------------------------------------------------ #
    #  WHITELIST METHODS                                                   #
    # ------------------------------------------------------------------ #
    def add_whitelist(self, phone_number: str, contact_name: str = ""):
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO whitelist (phone_number, contact_name) VALUES (?, ?)",
                (clean_num, contact_name)
            )
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
            cursor.execute(
                "SELECT phone_number, contact_name FROM whitelist ORDER BY contact_name ASC"
            )
            return [{"phone_number": row[0], "contact_name": row[1]} for row in cursor.fetchall()]

    def is_whitelisted(self, phone_number: str) -> Tuple[bool, str]:
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT contact_name FROM whitelist WHERE phone_number = ?",
                (clean_num,)
            )
            row = cursor.fetchone()
            if row:
                return True, row[0] or "Whitelisted Contact"
        return False, ""

    # ------------------------------------------------------------------ #
    #  BLACKLIST METHODS                                                   #
    # ------------------------------------------------------------------ #
    def is_blacklisted(self, phone_number: str) -> bool:
        clean_num = self._normalize_number(phone_number)
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM blacklist WHERE phone_number = ?",
                (clean_num,)
            )
            return cursor.fetchone() is not None

    # ------------------------------------------------------------------ #
    #  MAIN DECISION METHOD                                                #
    # ------------------------------------------------------------------ #
    def should_answer(self, caller_number: str) -> Tuple[bool, str]:
        """
        Returns (should_answer: bool, reason: str)

        reason codes:
          "family:<name>"      → Quick polite decline + Telegram ping only
          "blacklisted"        → Hang up immediately, no response
          "whitelisted:<name>" → Full Jarvis screening
          "screen_unknown"     → Full Jarvis screening (unknown caller)
          "rejected_mode"      → whitelist_only mode, not in list
        """
        if not caller_number:
            caller_number = "Unknown"

        # 1. Family / VIP → short polite message, no full screening
        is_fam, fam_name = self.is_family(caller_number)
        if is_fam:
            return False, f"family:{fam_name}"

        # 2. Blacklist → reject silently
        if self.is_blacklisted(caller_number):
            return False, "blacklisted"

        mode = self.get_mode()
        whitelisted, contact_name = self.is_whitelisted(caller_number)

        if whitelisted:
            return True, f"whitelisted:{contact_name}"

        if mode == "whitelist_only":
            return False, "rejected_mode"

        # screen_unknown / all → full Jarvis AI screening
        return True, "screen_unknown"

    def _normalize_number(self, num: str) -> str:
        """Strip spaces, dashes, parentheses."""
        return "".join(c for c in num if c.isdigit() or c == "+")


rules_engine = RulesEngine()
