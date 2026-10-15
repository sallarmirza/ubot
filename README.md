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

At startup, the application creates missing tables from the SQLAlchemy models.
`create_all` does not change existing tables, and the existing SQLite
`ubot.db` file is not migrated or copied to PostgreSQL. Back up and migrate
existing data separately before switching databases. Use Alembic for future
schema changes.

## AI comment reply drafts

Set `AI_API_KEY` in the local environment to enable AI-generated drafts. The
optional `AI_BASE_URL` defaults to `https://api.openai.com/v1`, and `AI_MODEL`
defaults to `gpt-4o-mini`; any provider exposing the OpenAI-compatible
`/chat/completions` endpoint can be used.

Save a business profile and select videos to enable contextual AI replies.
Comments are loaded without generating or posting replies. Use the explicit
“Generate & Post Replies” action to generate contextual replies for eligible
comments and post them to YouTube. This requires the account's Google
authorization to include YouTube posting access.

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

AI reply code is separated into `router/ai_router.py`, `services/ai_service.py`,
and `repositories/ai_repo.py`. Comment loading remains under the comments
router and service.

The comments page refreshes saved comments without posting replies. The
explicit “Generate & Post Replies” action processes eligible viewer comments
and replies, skips channel-authored and already-replied comments, and posts
responses to YouTube. Because YouTube does not support nested replies, a
response to a viewer reply is posted as a sibling under the same thread. Threads
YouTube marks `canReply: false` are skipped and shown as unavailable in the
comments UI. Saving a selected video or loading comments never triggers AI
generation or reply posting.

## Selected-video analytics

The authenticated `GET /analytics/selected-videos` endpoint returns current
stored video statistics, channel/video metadata, prompt context, saved comments
and reply status counts, individual saved comments/replies, and any stored
analytics snapshots for all of the signed-in user's selected videos. Use
`GET /analytics/selected-videos/{channel_id}/{video_id}` for one selected video.
These endpoints report locally stored data; refresh video statistics or fetch
comments through their existing endpoints to update that data.

Video-selection responses include the YouTube channel name for each video.
Selected-video analytics also returns the stored channel name and each saved
comment's video name.