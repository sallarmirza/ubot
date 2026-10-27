BEGIN;

-- Preserve the pre-migration comment data so it can be restored if needed.
CREATE TABLE IF NOT EXISTS comments_pre_branch_reply_backup AS
SELECT * FROM comments;

ALTER TABLE comments
    ADD COLUMN IF NOT EXISTS parent_youtube_comment_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS thread_youtube_comment_id VARCHAR(100),
    ADD COLUMN IF NOT EXISTS author_name VARCHAR(255),
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMP;

UPDATE comments AS child
SET parent_youtube_comment_id = parent.youtube_comment_id
FROM comments AS parent
WHERE child.parent_comment_id = parent.comment_id
  AND child.parent_youtube_comment_id IS NULL;

WITH RECURSIVE comment_threads AS (
    SELECT
        comment_id,
        youtube_comment_id AS root_youtube_comment_id
    FROM comments
    WHERE parent_comment_id IS NULL

    UNION ALL

    SELECT
        child.comment_id,
        comment_threads.root_youtube_comment_id
    FROM comments AS child
    JOIN comment_threads
      ON child.parent_comment_id = comment_threads.comment_id
)
UPDATE comments AS comment
SET thread_youtube_comment_id = comment_threads.root_youtube_comment_id
FROM comment_threads
WHERE comment.comment_id = comment_threads.comment_id
  AND comment.thread_youtube_comment_id IS NULL;

COMMIT;
