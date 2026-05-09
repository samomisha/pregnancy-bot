import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import os

DATABASE_URL = os.environ.get("DATABASE_URL")


class Database:
    def __init__(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set!")
        self.database_url = DATABASE_URL
        self._init_db()

    def _get_conn(self):
        return psycopg2.connect(self.database_url)

    def _init_db(self):
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id         BIGINT PRIMARY KEY,
                        start_day       INTEGER NOT NULL,
                        registered_at   TIMESTAMP NOT NULL,
                        registered_date DATE NOT NULL
                    )
                """)
                conn.commit()

    def save_user(self, user_id: int, start_day: int):
        """Save or update user with their starting pregnancy day."""
        now = datetime.utcnow()
        today = date.today()
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (user_id, start_day, registered_at, registered_date)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET 
                        start_day = EXCLUDED.start_day,
                        registered_at = EXCLUDED.registered_at,
                        registered_date = EXCLUDED.registered_date
                """, (user_id, start_day, now, today))
                conn.commit()

    def get_user(self, user_id: int):
        """Get user record."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT user_id, start_day, registered_date FROM users WHERE user_id = %s",
                    (user_id,)
                )
                row = cur.fetchone()
        if row:
            return {
                "user_id": row["user_id"],
                "start_day": row["start_day"],
                "registered_date": row["registered_date"].isoformat()
            }
        return None

    def delete_user(self, user_id: int):
        """Delete user (for /restart)."""
        with self._get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
                conn.commit()

    def get_all_users(self):
        """Get all registered users."""
        with self._get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT user_id, start_day, registered_date FROM users"
                )
                rows = cur.fetchall()
        return [
            {
                "user_id": r["user_id"],
                "start_day": r["start_day"],
                "registered_date": r["registered_date"].isoformat()
            }
            for r in rows
        ]

    def get_current_day(self, user_id: int) -> int:
        """Calculate current pregnancy day for user."""
        user = self.get_user(user_id)
        if not user:
            return 0

        registered_date = date.fromisoformat(user["registered_date"])
        days_since_registration = (date.today() - registered_date).days
        current_day = user["start_day"] + days_since_registration
        return current_day
