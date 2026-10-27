ALTER TABLE user_oauth
    ADD COLUMN IF NOT EXISTS comment_monitoring_enabled BOOLEAN NOT NULL DEFAULT FALSE;
