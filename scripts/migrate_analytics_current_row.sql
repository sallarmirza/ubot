-- Retain the latest analytics values before enforcing one row per selected video.
DELETE FROM analytics older
USING analytics newer
WHERE older.selected_video_id = newer.selected_video_id
  AND older.analytics_id < newer.analytics_id;

CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_selected_video
    ON analytics (selected_video_id);
