ALTER TABLE user_oauth
    ADD COLUMN IF NOT EXISTS comment_fetch_interval_minutes INTEGER NOT NULL DEFAULT 5;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_user_oauth_comment_fetch_interval_minutes'
          AND conrelid = 'user_oauth'::regclass
    ) THEN
        ALTER TABLE user_oauth
            ADD CONSTRAINT ck_user_oauth_comment_fetch_interval_minutes
            CHECK (comment_fetch_interval_minutes BETWEEN 1 AND 1440);
    END IF;
END $$;
