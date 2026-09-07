from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.api.admin import _email_by_auth_user_id, _list_all_auth_users


class _PagedAuthAdmin:
    def __init__(self, users: list, *, wrapped_response: bool = False) -> None:
        self.users = users
        self.wrapped_response = wrapped_response
        self.calls: list[tuple[int, int]] = []

    def list_users(self, *, page: int, per_page: int):
        self.calls.append((page, per_page))
        start = (page - 1) * per_page
        batch = self.users[start : start + per_page]
        if self.wrapped_response:
            return SimpleNamespace(users=batch)
        return batch


def _service(users: list, *, wrapped_response: bool = False):
    admin = _PagedAuthAdmin(users, wrapped_response=wrapped_response)
    return SimpleNamespace(auth=SimpleNamespace(admin=admin)), admin


class AdminAuthPaginationTests(unittest.TestCase):
    def test_fetches_and_maps_more_than_200_users_across_all_pages(self) -> None:
        expected = [
            SimpleNamespace(id=f"user-{number}", email=f"user{number}@example.com")
            for number in range(225)
        ]
        service, admin = _service(expected)

        users = _list_all_auth_users(service, per_page=100)

        self.assertEqual(users, expected)
        self.assertEqual(admin.calls, [(1, 100), (2, 100), (3, 100)])

        service, _ = _service(expected)
        emails = _email_by_auth_user_id(service)
        self.assertEqual(len(emails), 225)
        self.assertEqual(emails["user-224"], "user224@example.com")

    def test_exact_full_page_fetches_empty_final_page(self) -> None:
        expected = [
            SimpleNamespace(id=f"user-{number}", email=None)
            for number in range(200)
        ]
        service, admin = _service(expected, wrapped_response=True)

        users = _list_all_auth_users(service, per_page=100)

        self.assertEqual(users, expected)
        self.assertEqual(admin.calls, [(1, 100), (2, 100), (3, 100)])

    def test_empty_directory_stops_after_first_request(self) -> None:
        service, admin = _service([])

        self.assertEqual(_list_all_auth_users(service, per_page=100), [])
        self.assertEqual(admin.calls, [(1, 100)])


if __name__ == "__main__":
    unittest.main()
