"""Service-only quiz reuse and release calls; no AI or storage mutations."""
from fastapi import HTTPException
from app.lib.config import get_settings
from app.services.tenant_features import profile_feature_enabled

MESSAGES = {
    "quiz_locked": "This paper has been released. Duplicate it to edit a new draft.",
    "quiz_changed": "The quiz changed since you loaded it. Refresh and review it before publishing.",
    "quiz_restore_first": "Restore this archived quiz before publishing it.",
    "quiz_review_required": "Review all questions before publishing. Some items are unavailable or still pending.",
    "quiz_empty": "Each variant needs an approved question with valid positive marks.",
    "quiz_no_access": "Quiz or subject access is unavailable.",
    "quiz_request_conflict": "This copy request belongs to different settings. Start a new copy.",
    "quiz_invalid_title": "Enter a quiz title between 1 and 200 characters.",
    "quiz_copy_size": "Duplicate a quiz containing between 1 and 500 questions.",
    "quiz_invalid_batches": "Select active batches from this quiz's course and level.",
    "quiz_batch_access": "You can publish only to batches you manage.",
}


def enabled(profile=None) -> bool:
    if profile is not None:
        return profile_feature_enabled(profile, "quiz_reuse")
    return getattr(get_settings(), "quiz_reuse_enabled", False)


def rpc(service, name, profile, quiz_id, **extra):
    try:
        return service.rpc(name, {"p_id": quiz_id, "p_tenant": profile.tenant_id,
                                  "p_actor": profile.user_id, **extra}).execute().data
    except Exception as exc:
        message = MESSAGES.get(getattr(exc, "message", ""))
        if message:
            code = {"PT404": 404, "PT403": 403, "PT400": 400}.get(getattr(exc, "code", ""), 409)
            raise HTTPException(code, message) from exc
        raise HTTPException(503, "Quiz saving is temporarily unavailable. Check the quiz before retrying.") from exc


def assert_editable(row):
    if row.get("release_locked"):
        raise HTTPException(409, MESSAGES["quiz_locked"])
