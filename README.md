# Ubot
Dedicated backend that will use AI to manage youtube channel

## AI comment reply drafts

Set `AI_API_KEY` in the local environment to enable AI-generated drafts. The
optional `AI_BASE_URL` defaults to `https://api.openai.com/v1`, and `AI_MODEL`
defaults to `gpt-4o-mini`; any provider exposing the OpenAI-compatible
`/chat/completions` endpoint can be used.

Save a business profile, select a video, and load its comments. **Generate
reply drafts** creates contextual drafts in batches of up to 20 top-level
comments, using the business profile and selected video's description. Use
**Generate next batch** to continue through larger videos. A draft can be
regenerated individually. Review each draft, then use **Post reply** to publish
it as a reply to that specific YouTube comment. Generation does not publish
replies automatically.

Google login requests `openid`, `email`, `profile`,
`youtube.force-ssl`, and `youtube.readonly`, with offline access and consent
prompting so the app can refresh access tokens. After these scopes change,
sign in again and approve the updated permissions. Returning sign-ins retain a
previous refresh token if Google omits a replacement.

Startup creates missing tables from the SQLAlchemy models. It does not migrate
existing tables; update an existing database schema separately when its columns
do not match the models. Reply posting uses an atomic database claim, so
concurrent requests across server workers cannot post the same draft twice. If
the connection fails after sending a post request, the state is kept as
uncertain; check YouTube manually before retrying to avoid duplicates.
Deselecting a video also deletes its related comments, replies, and analytics.

AI reply code is separated into `router/ai_router.py`, `services/ai_service.py`,
and `repositories/ai_repo.py`. Comment loading remains under the comments
router and service.

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