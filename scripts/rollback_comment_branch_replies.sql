BEGIN;

ALTER TABLE comments
    DROP COLUMN IF EXISTS parent_youtube_comment_id,
    DROP COLUMN IF EXISTS thread_youtube_comment_id,
    DROP COLUMN IF EXISTS author_name,
    DROP COLUMN IF EXISTS published_at;

COMMIT;

-- comments_pre_branch_reply_backup is intentionally retained. Drop it only
-- after verifying the restored application/database no longer needs it.
