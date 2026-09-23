import pytest
from fastapi import HTTPException

from app.lib.auth import CurrentProfile
from app.lib.role_checks import (
    require_institution_admin,
    require_super_admin,
    require_teacher,
)


def profile(role: str) -> CurrentProfile:
    return CurrentProfile(user_id="user-1", tenant_id="tenant-1", role=role)


@pytest.mark.parametrize(
    ("guard", "role"),
    [
        (require_teacher, "teacher"),
        (require_institution_admin, "institution_admin"),
        (require_super_admin, "super_admin"),
    ],
)
def test_role_guard_accepts_its_role(guard, role: str) -> None:
    guard(profile(role))


@pytest.mark.parametrize(
    ("guard", "expected_detail"),
    [
        (require_teacher, "Teachers only."),
        (require_institution_admin, "Institution admins only."),
        (require_super_admin, "Super admins only."),
    ],
)
def test_role_guard_rejects_other_roles(guard, expected_detail: str) -> None:
    with pytest.raises(HTTPException) as error:
        guard(profile("student"))

    assert error.value.status_code == 403
    assert error.value.detail == expected_detail


def test_role_guard_preserves_action_specific_message() -> None:
    with pytest.raises(HTTPException) as error:
        require_teacher(profile("student"), action="review questions")

    assert error.value.detail == "Only teachers can review questions."
