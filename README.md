# Ubot
Dedicated backend that will use AI to manage youtube channel

## AI comment reply drafts

Set `AI_API_KEY` in the local environment to enable AI-generated drafts. The
optional `AI_BASE_URL` defaults to `https://api.openai.com/v1`, and `AI_MODEL`
defaults to `gpt-4o-mini`; any provider exposing the OpenAI-compatible
`/chat/completions` endpoint can be used.

Save a business profile and select videos to enable automatic comment replies.
The background worker checks every 10 seconds, fetches all pages of comments
and replies, generates a contextual response for each unprocessed viewer
comment/reply, and posts it to YouTube without a separate approval step. It
requires the account's Google authorization to include YouTube posting access,
and skips comments authored by the channel and comments already handled by this
app. The comments page also supports manually generating and reviewing drafts.

Google login requests `openid`, `email`, `profile`,
`youtube.force-ssl`, and `youtube.readonly`, with offline access and consent
prompting so the app can refresh access tokens. After these scopes change,
sign in again and approve the updated permissions. Returning sign-ins retain a
previous refresh token if Google omits a replacement.

Startup creates missing tables from the SQLAlchemy models and applies additive
migrations for comment author and replyability fields. Reply posting uses an
atomic database claim, so
concurrent requests across server workers cannot post the same draft twice. If
the connection fails after sending a post request, the state is kept as
uncertain; check YouTube manually before retrying to avoid duplicates.
Deselecting a video also deletes its related comments, replies, and analytics.

AI reply code is separated into `router/ai_router.py`, `services/ai_service.py`,
and `repositories/ai_repo.py`. Comment loading remains under the comments
router and service.

The application polls all selected videos every 10 seconds. Each poll fetches
all pages of top-level comments and their replies, then processes each
unanswered viewer comment and reply, including top-level comments that already
have replies. Because YouTube does not support nested replies, a response to a
viewer reply is posted as a sibling reply in that thread. Threads YouTube marks
`canReply: false` are skipped and shown as unavailable in the comments UI. The
worker skips the channel's own comments and uses the saved per-comment posting
state to avoid duplicate replies. Frequent full scans and automatic posting can
consume YouTube API quota quickly. Run one application worker to avoid starting
duplicate pollers.

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