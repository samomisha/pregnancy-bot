-- Add analytics fields to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS term_entered_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_paid_at TIMESTAMP;

-- Create subscription_events table
CREATE TABLE IF NOT EXISTS subscription_events (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    event_type VARCHAR(20) NOT NULL, -- 'activated', 'renewed', 'cancelled'
    event_date TIMESTAMP NOT NULL DEFAULT NOW(),
    amount NUMERIC(10,2),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

-- Create index for faster queries
CREATE INDEX IF NOT EXISTS idx_subscription_events_user_id ON subscription_events(user_id);
CREATE INDEX IF NOT EXISTS idx_subscription_events_event_type ON subscription_events(event_type);
CREATE INDEX IF NOT EXISTS idx_subscription_events_event_date ON subscription_events(event_date);
