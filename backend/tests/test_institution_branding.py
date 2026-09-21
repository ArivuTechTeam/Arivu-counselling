from __future__ import annotations

import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.api.admin import INSTITUTION_LOGO_MAX_BYTES, _decode_institution_logo
from app.api.branding import institution_branding


class _BrandingQuery:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []

    def select(self, _columns: str):
        return self

    def eq(self, column: str, value: object):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        return self

    def execute(self):
        rows = [
            row
            for row in self.rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        return SimpleNamespace(data=dict(rows[0]) if rows else None)


class _BrandingService:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def table(self, name: str):
        assert name == "tenants"
        return _BrandingQuery(self.rows)


class InstitutionBrandingTests(unittest.TestCase):
    def test_logo_validation_accepts_png_and_rejects_mismatched_content(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"safe-image"
        decoded = _decode_institution_logo(
            logo_data=base64.b64encode(png).decode(),
            content_type="image/png",
            filename="academy.png",
        )
        self.assertEqual(decoded, (png, "image/png", "png"))

        with self.assertRaises(HTTPException) as raised:
            _decode_institution_logo(
                logo_data=base64.b64encode(b"not-a-png").decode(),
                content_type="image/png",
                filename="academy.png",
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_logo_validation_rejects_oversized_files(self) -> None:
        oversized = b"\x89PNG\r\n\x1a\n" + b"x" * INSTITUTION_LOGO_MAX_BYTES
        with self.assertRaises(HTTPException) as raised:
            _decode_institution_logo(
                logo_data=base64.b64encode(oversized).decode(),
                content_type="image/png",
                filename="large.png",
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_public_branding_returns_active_tenant_with_signed_logo(self) -> None:
        service = _BrandingService(
            [
                {
                    "id": "00000000-0000-0000-0000-000000000010",
                    "name": "Bright Future Academy",
                    "subdomain": "bright-future",
                    "logo_url": "tenant-logos/tenant-a/logo.png",
                    "is_active": True,
                }
            ]
        )
        with (
            patch("app.api.branding.get_service_client", return_value=service),
            patch("app.api.branding.signed_url", return_value="https://signed.example/logo") as signer,
        ):
            result = institution_branding("bright-future")

        self.assertEqual(result["name"], "Bright Future Academy")
        self.assertEqual(
            result["tenant_id"], "00000000-0000-0000-0000-000000000010"
        )
        self.assertEqual(result["logo_url"], "https://signed.example/logo")
        signer.assert_called_once_with("tenant-logos/tenant-a/logo.png", expires_in=3600)

    def test_public_branding_hides_inactive_or_invalid_tenants(self) -> None:
        service = _BrandingService(
            [
                {
                    "id": "00000000-0000-0000-0000-000000000011",
                    "name": "Paused Academy",
                    "subdomain": "paused",
                    "logo_url": None,
                    "is_active": False,
                }
            ]
        )
        with patch("app.api.branding.get_service_client", return_value=service):
            with self.assertRaises(HTTPException) as inactive:
                institution_branding("paused")
            with self.assertRaises(HTTPException) as invalid:
                institution_branding("NOT VALID!")
        self.assertEqual(inactive.exception.status_code, 404)
        self.assertEqual(invalid.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
