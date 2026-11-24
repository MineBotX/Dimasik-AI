"""Unit tests for API key storage and admission control.

Run with: python -m unittest discover -s tests
"""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from assistant import api_server


class ApiKeyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "api_keys.sqlite3"
        self.db_patch = patch.object(api_server, "DB_PATH", self.db_path)
        self.db_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_key_is_only_stored_as_hash_and_can_be_revoked(self):
        token = api_server.create_key("unit-test", rpm=7)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT prefix, secret_hash, rpm FROM api_keys"
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], digest)
        self.assertNotEqual(rows[0][1], token)
        self.assertEqual(rows[0][2], 7)
        self.assertTrue(api_server.revoke_key(rows[0][0]))
        self.assertFalse(api_server.revoke_key(rows[0][0]))

    def test_invalid_key_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            api_server.create_key(" ", rpm=10)
        with self.assertRaises(ValueError):
            api_server.create_key("valid", rpm=0)


class AdmissionControlTests(unittest.TestCase):
    def setUp(self):
        with api_server._rate_lock:
            api_server._rate_events.clear()

    def test_per_key_rate_limit(self):
        key = {"id": "test-key", "rpm": 2}
        self.assertTrue(api_server._allow_request(key))
        self.assertTrue(api_server._allow_request(key))
        self.assertFalse(api_server._allow_request(key))

    def test_model_slot_is_exclusive(self):
        self.assertTrue(api_server._inference_slot.acquire(blocking=False))
        try:
            self.assertFalse(api_server._inference_slot.acquire(blocking=False))
        finally:
            api_server._inference_slot.release()


if __name__ == "__main__":
    unittest.main()
