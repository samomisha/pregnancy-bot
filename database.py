import pg8000.native
from datetime import datetime, date
import os
from urllib.parse import urlparse

DATABASE_URL = os.environ.get("DATABASE_URL")


class Database:
    def __init__(self):
        if not DATABASE_URL:
            raise ValueError("DATABASE_URL environment variable is not set!")
        self.database_url = DATABASE_URL
        self._parse_database_url()
        self._init_db()

    def _parse_database_url(self):
        """Parse DATABASE_URL into connection parameters."""
        url = urlparse(self.database_url)
        self.db_params = {
            "user": url.username,
            "password": url.password,
            "host": url.hostname,
            "port": url.port or 5432,
            "database": url.path[1:] if url.path else None
        }

    def _get_conn(self):
        return pg8000.native.Connection(**self.db_params)

    def _init_db(self):
        conn = self._get_conn()
        conn.run("""
            CREATE TABLE IF NOT EXISTS users (
                user_id         BIGINT PRIMARY KEY,
                start_day       INTEGER NOT NULL,
                registered_at   TIMESTAMP NOT NULL,
                registered_date DATE NOT NULL
            )
        """)
        conn.close()

    def save_user(self, user_id: int, start_day: int):
        """Save or update user with their starting pregnancy day."""
        now = datetime.utcnow()
        today = date.today()
        conn = self._get_conn()
        conn.run("""
            INSERT INTO users (user_id, start_day, registered_at, registered_date)
            VALUES (:user_id, :start_day, :registered_at, :registered_date)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                start_day = EXCLUDED.start_day,
                registered_at = EXCLUDED.registered_at,
                registered_date = EXCLUDED.registered_date
        """, user_id=user_id, start_day=start_day, registered_at=now, registered_date=today)
        conn.close()

    def get_user(self, user_id: int):
        """Get user record."""
        conn = self._get_conn()
        rows = conn.run(
            "SELECT user_id, start_day, registered_date FROM users WHERE user_id = :user_id",
            user_id=user_id
        )
        conn.close()
        if rows:
            row = rows[0]
            return {
                "user_id": row[0],
                "start_day": row[1],
                "registered_date": row[2].isoformat()
            }
        return None

    def delete_user(self, user_id: int):
        """Delete user (for /restart)."""
        conn = self._get_conn()
        conn.run("DELETE FROM users WHERE user_id = :user_id", user_id=user_id)
        conn.close()

    def get_all_users(self):
        """Get all registered users."""
        conn = self._get_conn()
        rows = conn.run("SELECT user_id, start_day, registered_date FROM users")
        conn.close()
        return [
            {
                "user_id": r[0],
                "start_day": r[1],
                "registered_date": r[2].isoformat()
            }
            for r in rows
        ]

    def get_current_day(self, user_id: int) -> int:
        """Calculate current pregnancy day for user (TEST MODE: every 2 hours = +1 day)."""
        user = self.get_user(user_id)
        if not user:
            return 0

        # Get registered_at timestamp from database
        conn = self._get_conn()
        rows = conn.run(
            "SELECT registered_at FROM users WHERE user_id = :user_id",
            user_id=user_id
        )
        conn.close()
        
        if not rows:
            return 0
            
        registered_at = rows[0][0]
        
        # Calculate hours since registration
        hours_since_registration = (datetime.utcnow() - registered_at).total_seconds() / 3600
        
        # Every 2 hours = +1 day (test mode)
        days_since_registration = int(hours_since_registration / 2)
        
        current_day = user["start_day"] + days_since_registration
        return current_day
