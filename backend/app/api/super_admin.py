"""Explicit route inventory for super-administrator platform APIs.

Handlers remain in ``admin.py`` while the large module is decomposed, but the
application registers them only through this role-specific router.
"""

from fastapi import APIRouter

from app.api.admin import router as handler_router

_PATHS = {
    "/api/v1/tenants",
    "/api/v1/admins",
    "/api/v1/platform/admins/{user_id}",
    "/api/v1/platform/admins/{user_id}/temporary-password",
    "/api/v1/platform/stats",
    "/api/v1/platform/overview",
    "/api/v1/platform/tenants",
    "/api/v1/platform/tenants/{tenant_id}",
    "/api/v1/platform/question-bank",
    "/api/v1/platform/ai-monitoring",
}

router = APIRouter()
router.routes.extend(route for route in handler_router.routes if route.path in _PATHS)

if {route.path for route in router.routes} != _PATHS:
    raise RuntimeError("Super-admin route inventory is incomplete.")
