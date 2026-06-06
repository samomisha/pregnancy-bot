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
            # New subscription-related columns
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS zenedu_subscriber_id INTEGER")
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_status VARCHAR(20)")
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_end_date TIMESTAMP")
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_start DATE")
            # Analytics columns
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS term_entered_at TIMESTAMP")
            conn.run("ALTER TABLE users ADD COLUMN IF NOT EXISTS first_paid_at TIMESTAMP")
        except:
            pass
        
        # Create subscription_events table
        conn.run("""
            CREATE TABLE IF NOT EXISTS subscription_events (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                event_type VARCHAR(20) NOT NULL,
                event_date TIMESTAMP NOT NULL DEFAULT NOW(),
                amount NUMERIC(10,2),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        
        # Create indexes
        try:
            conn.run("CREATE INDEX IF NOT EXISTS idx_subscription_events_user_id ON subscription_events(user_id)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_subscription_events_event_type ON subscription_events(event_type)")
            conn.run("CREATE INDEX IF NOT EXISTS idx_subscription_events_event_date ON subscription_events(event_date)")
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
        import logging
        logger = logging.getLogger(__name__)
        
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
        now_utc = datetime.utcnow()
        
        # Calculate time difference
        time_diff = now_utc - registered_at
        seconds_since_registration = time_diff.total_seconds()
        hours_since_registration = seconds_since_registration / 3600
        
        # Every 2 hours = +1 day (test mode)
        days_since_registration = int(hours_since_registration / 2)
        
        current_day = user["start_day"] + days_since_registration
        
        # Detailed logging
        logger.info(
            f"get_current_day for user {user_id}:\n"
            f"  registered_at (from DB): {registered_at}\n"
            f"  now_utc: {now_utc}\n"
            f"  time_diff: {time_diff}\n"
            f"  seconds_since_registration: {seconds_since_registration}\n"
            f"  hours_since_registration: {hours_since_registration}\n"
            f"  days_since_registration (hours/2): {days_since_registration}\n"
            f"  start_day: {user['start_day']}\n"
            f"  current_day (start_day + days_since_reg): {current_day}"
        )
        
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
    
    # Subscription management methods
    
    def set_trial_start(self, user_id: int, trial_date: date = None):
        """Set trial_start date for user."""
        if trial_date is None:
            trial_date = date.today()
        conn = self._get_conn()
        conn.run(
            "UPDATE users SET trial_start = :trial_start WHERE user_id = :user_id",
            trial_start=trial_date, user_id=user_id
        )
        conn.close()
    
    def update_subscription(self, user_id: int, zenedu_subscriber_id: int = None, 
                          subscription_status: str = None, subscription_end_date: datetime = None):
        """Update subscription information for user."""
        conn = self._get_conn()
        
        updates = []
        params = {"user_id": user_id}
        
        if zenedu_subscriber_id is not None:
            updates.append("zenedu_subscriber_id = :zenedu_subscriber_id")
            params["zenedu_subscriber_id"] = zenedu_subscriber_id
        
        if subscription_status is not None:
            updates.append("subscription_status = :subscription_status")
            params["subscription_status"] = subscription_status
        
        if subscription_end_date is not None:
            updates.append("subscription_end_date = :subscription_end_date")
            params["subscription_end_date"] = subscription_end_date
        
        if updates:
            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = :user_id"
            conn.run(query, **params)
        
        conn.close()
    
    def get_user_subscription(self, user_id: int):
        """Get user subscription details."""
        conn = self._get_conn()
        rows = conn.run(
            """SELECT zenedu_subscriber_id, subscription_status, subscription_end_date, trial_start 
               FROM users WHERE user_id = :user_id""",
            user_id=user_id
        )
        conn.close()
        
        if rows:
            row = rows[0]
            return {
                "zenedu_subscriber_id": row[0],
                "subscription_status": row[1],
                "subscription_end_date": row[2],
                "trial_start": row[3]
            }
        return None
    
    def find_user_by_zenedu_id(self, zenedu_subscriber_id: int):
        """Find user by Zenedu subscriber ID."""
        conn = self._get_conn()
        rows = conn.run(
            "SELECT user_id FROM users WHERE zenedu_subscriber_id = :zenedu_subscriber_id",
            zenedu_subscriber_id=zenedu_subscriber_id
        )
        conn.close()
        
        if rows:
            return rows[0][0]
        return None
    
    # Analytics methods
    
    def set_term_entered(self, user_id: int):
        """Set term_entered_at timestamp when user enters pregnancy term."""
        now = datetime.utcnow()
        conn = self._get_conn()
        conn.run(
            "UPDATE users SET term_entered_at = :term_entered_at WHERE user_id = :user_id AND term_entered_at IS NULL",
            term_entered_at=now, user_id=user_id
        )
        conn.close()
    
    def set_first_paid(self, user_id: int):
        """Set first_paid_at timestamp when user makes first payment."""
        now = datetime.utcnow()
        conn = self._get_conn()
        conn.run(
            "UPDATE users SET first_paid_at = :first_paid_at WHERE user_id = :user_id AND first_paid_at IS NULL",
            first_paid_at=now, user_id=user_id
        )
        conn.close()
    
    def add_subscription_event(self, user_id: int, event_type: str, amount: float = None):
        """Add subscription event to subscription_events table."""
        conn = self._get_conn()
        conn.run(
            """INSERT INTO subscription_events (user_id, event_type, amount)
               VALUES (:user_id, :event_type, :amount)""",
            user_id=user_id, event_type=event_type, amount=amount
        )
        conn.close()
    
    def get_analytics_stats(self):
        """Get analytics statistics for admin dashboard."""
        conn = self._get_conn()
        
        # Funnel metrics
        total_registered = conn.run("SELECT COUNT(*) FROM users")[0][0]
        entered_term = conn.run("SELECT COUNT(*) FROM users WHERE term_entered_at IS NOT NULL")[0][0]
        started_trial = conn.run("SELECT COUNT(*) FROM users WHERE trial_start IS NOT NULL")[0][0]
        first_paid = conn.run("SELECT COUNT(*) FROM users WHERE first_paid_at IS NOT NULL")[0][0]
        
        # Subscription metrics
        active_subscriptions = conn.run("SELECT COUNT(*) FROM users WHERE subscription_status = 'active'")[0][0]
        mrr = active_subscriptions * 99  # 99 грн per subscription
        
        # Activity metrics
        seven_days_ago = datetime.utcnow() - timedelta(days=7)
        wau = conn.run(
            "SELECT COUNT(*) FROM users WHERE last_active >= :date",
            date=seven_days_ago
        )[0][0]
        
        # Retention metrics - calculate how many users are still paying after N months
        retention = {}
        for month in [1, 2, 3, 4]:
            # Users who made first payment at least N months ago
            months_ago = datetime.utcnow() - timedelta(days=30 * month)
            users_eligible = conn.run(
                "SELECT COUNT(*) FROM users WHERE first_paid_at <= :date",
                date=months_ago
            )[0][0]
            
            # Of those, how many have renewed in the last 30 days
            if users_eligible > 0:
                still_paying = conn.run(
                    """SELECT COUNT(DISTINCT user_id) FROM subscription_events 
                       WHERE event_type = 'renewed' 
                       AND event_date >= :recent_date
                       AND user_id IN (
                           SELECT user_id FROM users WHERE first_paid_at <= :months_ago
                       )""",
                    recent_date=datetime.utcnow() - timedelta(days=30),
                    months_ago=months_ago
                )[0][0]
                retention[f"month_{month}"] = {
                    "eligible": users_eligible,
                    "still_paying": still_paying,
                    "percentage": round((still_paying / users_eligible) * 100, 1) if users_eligible > 0 else 0
                }
            else:
                retention[f"month_{month}"] = {"eligible": 0, "still_paying": 0, "percentage": 0}
        
        conn.close()
        
        # Calculate conversion percentages
        conv_term = round((entered_term / total_registered) * 100, 1) if total_registered > 0 else 0
        conv_trial = round((started_trial / entered_term) * 100, 1) if entered_term > 0 else 0
        conv_paid = round((first_paid / started_trial) * 100, 1) if started_trial > 0 else 0
        
        return {
            "funnel": {
                "total_registered": total_registered,
                "entered_term": entered_term,
                "started_trial": started_trial,
                "first_paid": first_paid,
                "conv_term": conv_term,
                "conv_trial": conv_trial,
                "conv_paid": conv_paid
            },
            "subscriptions": {
                "active": active_subscriptions,
                "mrr": mrr,
                "total_ever_paid": first_paid
            },
            "activity": {
                "wau": wau
            },
            "retention": retention
        }
