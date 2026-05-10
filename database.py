import pg8000.native
from datetime import datetime, date, timedelta
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
                registered_date DATE NOT NULL,
                status          VARCHAR(20) DEFAULT 'active',
                last_active     TIMESTAMP
            )
        """)
        # Add columns if they don't exist (for existing databases)
        try:
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS status VARCHAR(20) DEFAULT 'active'")
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active TIMESTAMP")
        except:
            pass
        conn.close()

    def save_user(self, user_id: int, start_day: int):
        """Save or update user with their starting pregnancy day."""
        now = datetime.utcnow()
        today = date.today()
        conn = self._get_conn()
        conn.run("""
            INSERT INTO users (user_id, start_day, registered_at, registered_date, status, last_active)
            VALUES (:user_id, :start_day, :registered_at, :registered_date, 'active', :last_active)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                start_day = EXCLUDED.start_day,
                registered_at = EXCLUDED.registered_at,
                registered_date = EXCLUDED.registered_date,
                status = 'active',
                last_active = EXCLUDED.last_active
        """, user_id=user_id, start_day=start_day, registered_at=now, registered_date=today, last_active=now)
        conn.close()

    def get_user(self, user_id: int):
        """Get user record."""
        conn = self._get_conn()
        rows = conn.run(
            "SELECT user_id, start_day, registered_date, status, last_active FROM users WHERE user_id = :user_id",
            user_id=user_id
        )
        conn.close()
        if rows:
            row = rows[0]
            return {
                "user_id": row[0],
                "start_day": row[1],
                "registered_date": row[2].isoformat(),
                "status": row[3] if row[3] else "active",
                "last_active": row[4].isoformat() if row[4] else None
            }
        return None

    def delete_user(self, user_id: int):
        """Delete user (for /restart)."""
        conn = self._get_conn()
        conn.run("DELETE FROM users WHERE user_id = :user_id", user_id=user_id)
        conn.close()

    def get_all_users(self):
        """Get all active registered users."""
        conn = self._get_conn()
        rows = conn.run("SELECT user_id, start_day, registered_date, status, last_active FROM users WHERE status = 'active'")
        conn.close()
        return [
            {
                "user_id": r[0],
                "start_day": r[1],
                "registered_date": r[2].isoformat(),
                "status": r[3] if r[3] else "active",
                "last_active": r[4].isoformat() if r[4] else None
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
    
    def update_last_active(self, user_id: int):
        """Update last_active timestamp for user."""
        now = datetime.utcnow()
        conn = self._get_conn()
        conn.run(
            "UPDATE users SET last_active = :last_active WHERE user_id = :user_id",
            last_active=now, user_id=user_id
        )
        conn.close()
    
    def set_user_status(self, user_id: int, status: str):
        """Set user status (active/inactive)."""
        conn = self._get_conn()
        conn.run(
            "UPDATE users SET status = :status WHERE user_id = :user_id",
            status=status, user_id=user_id
        )
        conn.close()
    
    def get_stats(self):
        """Get statistics for admin."""
        conn = self._get_conn()
        
        # Total users and active users
        total_users = conn.run("SELECT COUNT(*) FROM users")[0][0]
        active_users = conn.run("SELECT COUNT(*) FROM users WHERE status = 'active'")[0][0]
        
        # New users in last 7 and 30 days
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        
        new_7_days = conn.run(
            "SELECT COUNT(*) FROM users WHERE registered_at >= :date",
            date=seven_days_ago
        )[0][0]
        
        new_30_days = conn.run(
            "SELECT COUNT(*) FROM users WHERE registered_at >= :date",
            date=thirty_days_ago
        )[0][0]
        
        # Unsubscribed in last 7 and 30 days (users who became inactive)
        # We'll track this by checking status changes, but for now we'll count inactive users
        unsub_7_days = conn.run(
            "SELECT COUNT(*) FROM users WHERE status = 'inactive' AND last_active >= :date",
            date=seven_days_ago
        )[0][0]
        
        unsub_30_days = conn.run(
            "SELECT COUNT(*) FROM users WHERE status = 'inactive' AND last_active >= :date",
            date=thirty_days_ago
        )[0][0]
        
        conn.close()
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "new_7_days": new_7_days,
            "new_30_days": new_30_days,
            "unsub_7_days": unsub_7_days,
            "unsub_30_days": unsub_30_days
        }
    
    def get_trimester_distribution(self):
        """Get distribution of users by trimester."""
        conn = self._get_conn()
        rows = conn.run(
            "SELECT user_id, start_day, registered_at FROM users WHERE status = 'active'"
        )
        conn.close()
        
        trimester_counts = {1: 0, 2: 0, 3: 0}
        
        for row in rows:
            user_id = row[0]
            start_day = row[1]
            registered_at = row[2]
            
            # Calculate current day
            hours_since_registration = (datetime.utcnow() - registered_at).total_seconds() / 3600
            days_since_registration = int(hours_since_registration / 2)
            current_day = start_day + days_since_registration
            
            # Determine trimester
            if current_day <= 84:  # First 12 weeks (84 days)
                trimester_counts[1] += 1
            elif current_day <= 196:  # Weeks 13-28 (196 days)
                trimester_counts[2] += 1
            elif current_day <= 280:  # Weeks 29-40 (280 days)
                trimester_counts[3] += 1
        
        return trimester_counts
    
    def get_all_users_with_details(self):
        """Get all users with full details for admin."""
        conn = self._get_conn()
        rows = conn.run(
            "SELECT user_id, start_day, registered_at, last_active, status FROM users ORDER BY last_active DESC"
        )
        conn.close()
        
        users = []
        for row in rows:
            user_id = row[0]
            start_day = row[1]
            registered_at = row[2]
            last_active = row[3]
            status = row[4] if row[4] else "active"
            
            # Calculate current day
            hours_since_registration = (datetime.utcnow() - registered_at).total_seconds() / 3600
            days_since_registration = int(hours_since_registration / 2)
            current_day = start_day + days_since_registration
            current_week = (current_day - 1) // 7 + 1
            
            users.append({
                "user_id": user_id,
                "current_day": current_day,
                "current_week": current_week,
                "last_active": last_active.isoformat() if last_active else None,
                "status": status
            })
        
        return users
