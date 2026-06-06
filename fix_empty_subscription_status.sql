-- Fix users with empty string subscription_status
-- Run this script manually in your PostgreSQL database

UPDATE users SET subscription_status = NULL WHERE subscription_status = '';

-- To verify the fix, run:
-- SELECT user_id, subscription_status FROM users WHERE subscription_status IS NULL OR subscription_status = '';
