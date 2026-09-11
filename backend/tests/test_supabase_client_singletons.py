from __future__ import annotations

import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import app.lib.supabase as supabase_lib


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

        def factory(_url: str, key: str):
            client = SimpleNamespace(key=key)
            created.append(client)
            return client

        with patch.object(supabase_lib, "create_client", side_effect=factory):
            service_first = supabase_lib.get_service_client()
            service_second = supabase_lib.get_service_client()
            anon_first = supabase_lib.get_anon_client()
            anon_second = supabase_lib.get_anon_client()

        self.assertIs(service_first, service_second)
        self.assertIs(anon_first, anon_second)
        self.assertIsNot(service_first, anon_first)
        self.assertEqual(len(created), 2)

    def test_concurrent_first_access_creates_one_service_client(self) -> None:
        constructions = 0

        def factory(_url: str, _key: str):
            nonlocal constructions
            constructions += 1
            time.sleep(0.01)
            return object()

        with (
            patch.object(supabase_lib, "create_client", side_effect=factory),
            ThreadPoolExecutor(max_workers=20) as pool,
        ):
            clients = list(
                pool.map(lambda _index: supabase_lib.get_service_client(), range(40))
            )

        self.assertEqual(constructions, 1)
        self.assertTrue(all(client is clients[0] for client in clients))

    def test_auth_state_operations_receive_isolated_clients(self) -> None:
        with patch.object(
            supabase_lib, "create_client", side_effect=lambda *_args: object()
        ) as factory:
            first = supabase_lib.create_anon_auth_client()
            second = supabase_lib.create_anon_auth_client()

        self.assertIsNot(first, second)
        self.assertEqual(factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
