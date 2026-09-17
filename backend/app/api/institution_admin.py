"""Explicit route inventory for institution-administrator APIs.

Handlers remain in ``admin.py`` while the large module is decomposed, but the
application registers them only through this role-specific router.
"""

from fastapi import APIRouter

from app.api.admin import router as handler_router

_PATHS = {
    "/api/v1/users",
    "/api/v1/users/{user_id}",
    "/api/v1/users/{user_id}/temporary-password",
    "/api/v1/teachers/{teacher_id}/courses",
    "/api/v1/courses/{course_id}/students",
    "/api/v1/admin/courses/{course_id}/impact",
    "/api/v1/admin/stats",
    "/api/v1/admin/overview",
    "/api/v1/admin/analytics",
    "/api/v1/admin/teachers/analytics",
    "/api/v1/admin/quiz-sets",
    "/api/v1/admin/quiz-sets/{quiz_set_id}",
}

router = APIRouter()
router.routes.extend(route for route in handler_router.routes if route.path in _PATHS)

if {route.path for route in router.routes} != _PATHS:
    raise RuntimeError("Institution-admin route inventory is incomplete.")
