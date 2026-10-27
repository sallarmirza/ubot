ALTER TABLE user_oauth
    ADD COLUMN IF NOT EXISTS google_subject VARCHAR(255);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_oauth_google_subject
    ON user_oauth (google_subject);
