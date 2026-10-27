# Ubot
Dedicated backend that will use AI to manage youtube channel

## Database

The application requires PostgreSQL. Set `DATABASE_URL` in the local `.env`
file or deployment environment to a PostgreSQL connection URL, for example:

```text
DATABASE_URL=postgresql://<user>:<password>@<host>:5432/<database>
```

Credentials containing special characters must be URL-encoded. Legacy
`postgres://` URLs are also accepted and use the Psycopg 3 driver.

For the LeadHive Vercel frontend, set `FRONTEND_URL` to
`https://leadhiveee.vercel.app/flow`, `GOOGLE_REDIRECT_URI` to
`https://leadhiveee.vercel.app/auth/google/callback`, and `COOKIE_SECURE=true`.
Register the callback URI with the Google OAuth client. Vercel proxies these
requests to this backend so authentication cookies remain first-party. The
frontend Vercel project's `BACKEND_URL` currently uses the user's ngrok URL;
update that environment variable if the tunnel URL changes.

At startup, the application creates missing tables from the SQLAlchemy models.
`create_all` does not change existing tables, and the existing SQLite
`ubot.db` file is not migrated or copied to PostgreSQL. Back up and migrate
existing data separately before switching databases. Use Alembic for future
schema changes.

Google sign-ins are associated with the stable Google OpenID subject, rather
than a YouTube channel ID. Before deploying this change to an existing
PostgreSQL database, apply `scripts/migrate_google_oauth_subject.sql`. Existing
OAuth records have no Google subject to backfill automatically, so users may
receive new account records after signing in; existing channel/video data is
not deleted, but may need a deliberate account-specific data migration.

## OAuth security and account lifecycle

Set `TOKEN_ENCRYPTION_KEY` in each backend environment before starting the
application. Generate a Fernet key with:

```powershell
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use the same secret on every backend instance, keep it outside source control,
and back it up securely. Losing or changing the key without re-encrypting the
database makes stored Google tokens unreadable. On startup, existing plaintext
OAuth tokens are encrypted once; a failed migration stops application startup.

`POST /auth/logout` pauses background comment monitoring and clears the login
cookie without deleting saved data. Signing in with Google again resumes
monitoring. A rejected Google token also pauses monitoring until the next sign
in, preventing repeated unauthorized requests. Before deploying this behavior
to an existing PostgreSQL database, apply
`scripts/migrate_comment_monitoring.sql`.

`POST /auth/google/disconnect` revokes the Google grant and removes that user's
channel-linked application data while retaining the stable account identity
for a later reconnect. `DELETE /auth/account` attempts Google revocation,
permanently deletes the authenticated user's local data, and clears the login
cookie. Its response reports whether Google revocation was confirmed.

The application runs data-retention cleanup at startup and once every 24 hours.
Comment text and generated replies older than 30 days are redacted, while
comment IDs and reply statuses remain as minimal tombstones to avoid reposting
replies when YouTube returns those comments again. Analytics snapshots older
than 30 days are deleted. OAuth credentials, account records, channel setup,
and comments with an uncertain in-progress posting outcome are not removed by
the retention task.

Automatic comment fetching and replies are controlled per signed-in user with
`GET /auth/comment-monitoring` and `PUT /auth/comment-monitoring` using
`{"enabled": true}` or `{"enabled": false}`. When disabled, `GET /comments/...`
returns saved comments without contacting YouTube, so the frontend can continue
showing its awaiting-reply count. Reply-generation and posting endpoints are
available only while monitoring is enabled.

## AI comment reply drafts

Set `AI_API_KEY` in the local environment to enable AI-generated drafts. The
optional `AI_BASE_URL` defaults to `https://api.openai.com/v1`, and `AI_MODEL`
defaults to `gpt-4o-mini`; any provider exposing the OpenAI-compatible
`/chat/completions` endpoint can be used.

The public contact form endpoint is `POST /api/contact.php`. Configure
`RESEND_API_KEY`, `RESEND_FROM_EMAIL` (a sender verified by Resend),
`CONTACT_EMAIL_TO`, and `RECAPTCHA_SECRET_KEY` on the backend. The request JSON
must include `name`, `email`, `message`, and `recaptcha_token`; the CAPTCHA is
verified server-side before the message is sent.

Save a business profile and select videos to enable contextual AI replies.
The background monitor automatically fetches comments and generates/posts
replies for eligible comments on selected videos while the account is signed
in. On startup, it processes the currently visible unreplied backlog and fetches
every page of comments and replies on each scan. It polls every 10 seconds.
This requires the account's Google authorization to include YouTube posting
access. The explicit “Generate & Post Replies” action remains available too.

Google login requests `openid`, `email`, `profile`,
`youtube.force-ssl`, and `youtube.readonly`, with offline access and consent
prompting so the app can refresh access tokens. After these scopes change,
sign in again and approve the updated permissions. Returning sign-ins retain a
previous refresh token if Google omits a replacement.

Reply posting uses an atomic database claim, so
concurrent requests across server workers cannot post the same draft twice. If
the connection fails after sending a post request, the state is kept as
uncertain; check YouTube manually before retrying to avoid duplicates.
Deselecting a video also deletes its related comments, replies, and analytics.

Branch-aware reply tracking stores YouTube parent/thread IDs, author names, and
comment timestamps alongside the existing unique per-video comment ID. Before
LLM generation, the worker atomically claims each eligible viewer comment;
failed attempts are retryable, stale claims are checked against YouTube, and
each thread is limited by `COMMENT_MAX_REPLIES_PER_THREAD` (default 20).
`COMMENT_REPLY_DELAY_SECONDS` controls the short pre-post delay (default 1).
Run `scripts/migrate_comment_branch_replies.sql` after taking a database backup;
`scripts/rollback_comment_branch_replies.sql` removes the added columns, while
the migration's `comments_pre_branch_reply_backup` table is retained for manual
recovery.

AI reply code is separated into `router/ai_router.py`, `services/ai_service.py`,
and `repositories/ai_repo.py`. Comment loading remains under the comments
router and service.

Manual comment refresh only fetches and saves comments. The background monitor
and explicit “Generate & Post Replies” action process eligible viewer comments
and replies, skip channel-authored and already-replied comments, and post
responses to YouTube. Genuine comments are answered even when brief or vague;
the AI asks a concise follow-up rather than skipping them. The manual action
also retries comments previously marked skipped. Obvious spam, abuse, comments
that cannot be replied to, and uncertain posting outcomes remain excluded.
YouTube's API requires replies to use the thread's top-level comment ID as
`parentId`; it does not accept reply IDs for nested replies. Each reply still
starts with the answered viewer's `@mention`, and the answered comment ID is
tracked in the database for branch context and duplicate reconciliation.
YouTube may flatten the display, so the live UI layout still needs verification.
Threads YouTube marks `canReply: false` are skipped and shown as unavailable in
the comments UI.

## Selected-video analytics

The authenticated `GET /analytics/selected-videos` endpoint fetches and stores
fresh channel subscriber/view counts and video views, likes, and comment counts
from YouTube when called, then returns the analytics and saved comment activity
for all of the signed-in user's selected videos. Use
`GET /analytics/selected-videos/{channel_id}/{video_id}` to refresh and return
one selected video and its channel statistics. A history snapshot is added only
if a selected video has no analytics row yet; subsequent refreshes update that
same row. Before deploying to an existing PostgreSQL database, apply
`scripts/migrate_analytics_current_row.sql` to retain the latest row per video
and enforce one analytics row per selected video.

Video-selection responses include the YouTube channel name for each video.
Selected-video analytics also returns the stored channel name and each saved
comment's video name.