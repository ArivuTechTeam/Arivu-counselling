from __future__ import annotations

import asyncio
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import httpx

import app.lib.supabase as supabase_lib
from app.main import temporary_supabase_failure


class SupabaseClientSingletonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = SimpleNamespace(
            supabase_url="https://example.test",
            supabase_service_role_key="service-key",
            supabase_anon_key="anon-key",
        )
        self.service_patch = patch.object(supabase_lib, "_service_client", None)
        self.anon_patch = patch.object(supabase_lib, "_anon_client", None)
        self.settings_patch = patch.object(
            supabase_lib, "get_settings", return_value=self.settings
        )
        self.service_patch.start()
        self.anon_patch.start()
        self.settings_patch.start()

    def tearDown(self) -> None:
        self.settings_patch.stop()
        self.anon_patch.stop()
        self.service_patch.stop()

    def test_stateless_clients_are_constructed_once(self) -> None:
        created = []

        http_clients = []

        def factory(_url: str, key: str, *, options):
            client = SimpleNamespace(key=key)
            created.append(client)
            http_clients.append(options.httpx_client)
            return client

        try:
            with patch.object(supabase_lib, "create_client", side_effect=factory):
                service_first = supabase_lib.get_service_client()
                service_second = supabase_lib.get_service_client()
                anon_first = supabase_lib.get_anon_client()
                anon_second = supabase_lib.get_anon_client()
        finally:
            for http_client in http_clients:
                http_client.close()

        self.assertIs(service_first, service_second)
        self.assertIs(anon_first, anon_second)
        self.assertIsNot(service_first, anon_first)
        self.assertEqual(len(created), 2)

    def test_concurrent_first_access_creates_one_service_client(self) -> None:
        constructions = 0

        http_clients = []

        def factory(_url: str, _key: str, *, options):
            nonlocal constructions
            constructions += 1
            time.sleep(0.01)
            http_clients.append(options.httpx_client)
            return object()

        try:
            with (
                patch.object(supabase_lib, "create_client", side_effect=factory),
                ThreadPoolExecutor(max_workers=20) as pool,
            ):
                clients = list(
                    pool.map(
                        lambda _index: supabase_lib.get_service_client(), range(40)
                    )
                )
        finally:
            for http_client in http_clients:
                http_client.close()

        self.assertEqual(constructions, 1)
        self.assertTrue(all(client is clients[0] for client in clients))

    def test_auth_state_operations_receive_isolated_clients(self) -> None:
        with patch.object(
            supabase_lib,
            "create_client",
            side_effect=lambda *_args, **_kwargs: object(),
        ) as factory:
            first = supabase_lib.create_anon_auth_client()
            second = supabase_lib.create_anon_auth_client()

        self.assertIsNot(first, second)
        self.assertEqual(factory.call_count, 2)


class SupabaseReadRetryTransportTests(unittest.TestCase):
    def test_retries_get_after_remote_protocol_error(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise httpx.RemoteProtocolError(
                    "connection terminated", request=request
                )
            return httpx.Response(200, json={"ok": True})

        transport = supabase_lib._ReadRetryTransport(
            httpx.MockTransport(handler), base_delay_seconds=0
        )
        with httpx.Client(transport=transport) as client:
            response = client.get("https://example.test/profiles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, 2)

    def test_retries_transient_gateway_response_for_get(self) -> None:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(502 if calls == 1 else 200)

        transport = supabase_lib._ReadRetryTransport(
            httpx.MockTransport(handler), base_delay_seconds=0
        )
        with httpx.Client(transport=transport) as client:
            response = client.get("https://example.test/quizzes")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, 2)

    def test_does_not_retry_post_after_transport_error(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.RemoteProtocolError("connection lost", request=request)

        transport = supabase_lib._ReadRetryTransport(
            httpx.MockTransport(handler), base_delay_seconds=0
        )
        with httpx.Client(transport=transport) as client:
            with self.assertRaises(httpx.RemoteProtocolError):
                client.post("https://example.test/attempts", json={"answer": "a"})

        self.assertEqual(calls, 1)

    def test_raises_controlled_error_after_read_retries_are_exhausted(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            raise httpx.RemoteProtocolError("connection lost", request=request)

        transport = supabase_lib._ReadRetryTransport(
            httpx.MockTransport(handler), base_delay_seconds=0
        )
        with httpx.Client(transport=transport) as client:
            with self.assertRaises(supabase_lib.SupabaseUnavailableError):
                client.get("https://example.test/profiles")

        self.assertEqual(calls, 3)

    def test_exhausted_read_returns_retryable_service_unavailable(self) -> None:
        response = asyncio.run(
            temporary_supabase_failure(
                None,  # type: ignore[arg-type] -- handler does not inspect Request
                supabase_lib.SupabaseUnavailableError("temporary failure"),
            )
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["retry-after"], "2")
        self.assertEqual(
            json.loads(response.body),
            {
                "detail": (
                    "The data service is temporarily unavailable. Please try again."
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
