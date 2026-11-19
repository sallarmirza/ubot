ALTER TABLE youtube_channel
    ADD COLUMN IF NOT EXISTS channel_thumbnail_url VARCHAR(2048);
