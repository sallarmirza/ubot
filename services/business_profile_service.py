from fastapi import HTTPException
from sqlalchemy.orm import Session

from db_model import BusinessSetup, TargetChannel, YoutubeChannel
from schema.business_profile_schema import BusinessProfileRequest

# Data model reminder (how the tables connect):
#   User (users)
#     -> YoutubeChannel   (every channel the user owns on YouTube)
#     -> TargetChannel    (the channel the user selected to manage with the bot)
#          -> BusinessSetup (business name, services, tone, AI rules for that channel)
#
# A BusinessSetup never points to a YoutubeChannel directly.
# It always goes through TargetChannel.


def _find_user_channel(db: Session, user_id: int, channel_id: str) -> YoutubeChannel:
    """Find a YouTube channel only when it belongs to the signed-in user.

    `channel_id` here is the YouTube channel ID string (e.g. "UCNN..."),
    NOT our internal integer primary key.

    Filtering by BOTH user_id and youtube_channel_id is a security check:
    it stops a user from reading or editing another user's channel by
    guessing its ID. Raises 404 (instead of 403) so we don't reveal
    whether the channel exists for someone else.
    """
    channel = (
        db.query(YoutubeChannel)
        .filter_by(user_id=user_id, youtube_channel_id=channel_id)
        .first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


def _find_or_create_target(
    db: Session, user_id: int, channel: YoutubeChannel
) -> TargetChannel:
    """Get the user's selected-channel row, creating it on the first save.

    TargetChannel marks "this user chose this channel to be managed".
    It is created lazily: the first time a profile is saved for a channel,
    the row is made here. The (user_id, channel_id) pair is unique in the DB,
    so we look it up first to avoid creating duplicates.
    """
    target = (
        db.query(TargetChannel)
        .filter_by(user_id=user_id, channel_id=channel.channel_id)
        .first()
    )
    if target is None:
        target = TargetChannel(user_id=user_id, channel_id=channel.channel_id)
        db.add(target)
        # flush() sends the INSERT to the DB (without committing) so that
        # `target.target_channel_id` gets generated and can be used right away
        # by the caller. The final commit happens later in save_business_profile.
        db.flush()
    return target


def _profile_data(channel: YoutubeChannel, profile: BusinessSetup | None) -> dict:
    """Build a consistent response for saved and not-yet-saved profiles.

    The API always returns the same JSON shape. If the profile has not been
    saved yet (`profile is None`), the form fields come back as empty strings,
    so the frontend can render a blank form without special-casing.

    DB column names are mapped to the API field names here:
        business_name     -> business_name
        business_services -> services
        tone              -> brand_tone
        business_rules    -> ai_rules
    """
    return {
        "channel_id": channel.youtube_channel_id,
        "channel_title": channel.channel_name,
        "business_name": profile.business_name if profile else "",
        "services": profile.business_services if profile else "",
        "brand_tone": profile.tone if profile else "",
        "ai_rules": profile.business_rules if profile else "",
        # Placeholder: videos are not loaded by this function yet.
        "videos": [],
    }


def save_business_profile(
    db: Session, user_id: int, payload: BusinessProfileRequest
) -> dict:
    """Create or update a profile for one of the user's YouTube channels.

    Flow:
        1. Verify the channel belongs to this user (404 if not).
        2. Make sure a TargetChannel row exists for it.
        3. Look for an existing BusinessSetup for that target.
        4. Insert a new profile, or update the existing one (upsert).
        5. Commit once and return the saved data.
    """
    # Step 1: ownership check.
    channel = _find_user_channel(db, user_id, payload.channel_id)

    # Step 2: get or create the "selected channel" row.
    target = _find_or_create_target(db, user_id, channel)

    # Step 3: check whether this channel already has a saved profile.
    profile = (
        db.query(BusinessSetup)
        .filter_by(user_id=user_id, target_channel_id=target.target_channel_id)
        .first()
    )

    # Step 4: upsert. Map the request names to the existing database column names.
    if profile is None:
        # First save: create a new row.
        profile = BusinessSetup(
            user_id=user_id,
            target_channel_id=target.target_channel_id,
            business_name=payload.business_name,
            business_services=payload.services,
            business_rules=payload.ai_rules,
            tone=payload.brand_tone,
        )
        db.add(profile)
    else:
        # Profile already exists: overwrite its fields.
        # (SQLAlchemy tracks these changes and issues an UPDATE on commit.)
        profile.business_name = payload.business_name
        profile.business_services = payload.services
        profile.business_rules = payload.ai_rules
        profile.tone = payload.brand_tone

    # Step 5: a single commit saves the target row (if new) and the profile
    # together, so we never end up with a half-saved state.
    db.commit()
    return _profile_data(channel, profile)


def get_business_profile(db: Session, user_id: int, channel_id: str) -> dict:
    """Load a saved profile, or return empty fields for an owned channel.

    This is read-only: it never creates a TargetChannel or BusinessSetup.
    If the user owns the channel but has not saved a profile yet, the
    response simply contains empty strings (see _profile_data).
    """
    # Ownership check first (404 if the channel is not this user's).
    channel = _find_user_channel(db, user_id, channel_id)

    # Look up the selected-channel row; it may not exist yet.
    target = (
        db.query(TargetChannel)
        .filter_by(user_id=user_id, channel_id=channel.channel_id)
        .first()
    )

    # Only query for a profile if a target exists, since a profile
    # can only be attached to a target.
    profile = None
    if target is not None:
        profile = (
            db.query(BusinessSetup)
            .filter_by(user_id=user_id, target_channel_id=target.target_channel_id)
            .first()
        )
    return _profile_data(channel, profile)  