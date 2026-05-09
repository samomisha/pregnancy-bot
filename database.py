import sqlite3
from datetime import datetime, date
import os

DB_PATH = os.environ.get("DB_PATH", "pregnancy_bot.db")


class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self._init_db()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    start_day   INTEGER NOT NULL,
                    registered_at TEXT NOT NULL,
                    registered_date TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_user(self, user_id: int, start_day: int):
        """Save or update user with their starting pregnancy day."""
        now = datetime.utcnow().isoformat()
        today = date.today().isoformat()
        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO users (user_id, start_day, registered_at, registered_date)
                VALUES (?, ?, ?, ?)
            """, (user_id, start_day, now, today))
            conn.commit()

    def get_user(self, user_id: int):
        """Get user record."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT user_id, start_day, registered_date FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
        if row:
            return {"user_id": row[0], "start_day": row[1], "registered_date": row[2]}
        return None

    def delete_user(self, user_id: int):
        """Delete user (for /restart)."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_all_users(self):
        """Get all registered users."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT user_id, start_day, registered_date FROM users"
            ).fetchall()
        return [{"user_id": r[0], "start_day": r[1], "registered_date": r[2]} for r in rows]

    def get_current_day(self, user_id: int) -> int:
        """Calculate current pregnancy day for user."""
        user = self.get_user(user_id)
        if not user:
            return 0

        registered_date = date.fromisoformat(user["registered_date"])
        days_since_registration = (date.today() - registered_date).days
        current_day = user["start_day"] + days_since_registration
        return current_day
