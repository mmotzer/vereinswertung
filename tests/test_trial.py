import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import ROOT
from club_platform import create_platform
from vereinswertung import trial


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_platform(
            dict(
                DATA_ROOT=self.temp.name,
                TESTING=True,
                SECURE_COOKIE=False,
                PUBLIC_ORIGIN="http://localhost",
            )
        )
        self.client = self.app.test_client()
        self.headers = {"Origin": "http://localhost"}

    def tearDown(self):
        self.temp.cleanup()

    def test_sample_has_no_account_or_persistent_club(self):
        response = self.client.post(
            "/api/platform/try",
            json=dict(sample=True, day="2025-09-16"),
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.assertFalse(response.json["persisted"])
        self.assertEqual(response.json["initial_rating"], 1500)
        self.assertEqual(response.json["games"], 6)
        self.assertEqual(len(response.json["players"]), 4)
        with self.app.extensions["registry"]() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 0
            )
        self.assertFalse((Path(self.temp.name) / "tenants").exists())

    def test_own_file_matches_sample_and_temp_is_removed(self):
        folders = []
        real = tempfile.TemporaryDirectory

        def track(*args, **kwargs):
            directory = real(*args, **kwargs)
            folders.append(Path(directory.name))
            return directory

        data = dict(
            content=base64.b64encode(
                (ROOT / "static" / "demo.trf").read_bytes()
            ).decode(),
            category="rapid",
            day="2025-09-16",
        )
        with patch(
            "vereinswertung.trial.tempfile.TemporaryDirectory",
            side_effect=track,
        ):
            result = trial.calculate(data, ROOT / "static" / "demo.trf")
        self.assertEqual(result["category"], "rapid")
        self.assertTrue(folders)
        self.assertTrue(all(not path.exists() for path in folders))

    def test_invalid_and_oversized_files(self):
        for content in ("not base64!", "a" * 1400000):
            response = self.client.post(
                "/api/platform/try",
                json=dict(content=content),
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 400)

    def test_rate_and_origin(self):
        self.assertEqual(
            self.client.post("/api/platform/try", json={}).status_code, 403
        )
        for _ in range(10):
            self.client.post("/api/platform/try", json={}, headers=self.headers)
        self.assertEqual(
            self.client.post(
                "/api/platform/try", json={}, headers=self.headers
            ).status_code,
            429,
        )

    def test_multi_day_requires_explicit_round_dates(self):
        text = (
            (ROOT / "static" / "demo.trf")
            .read_text(encoding="utf-8")
            .replace("052 2026-10-06", "052 2026-10-07")
        )
        data = dict(
            content=base64.b64encode(text.encode()).decode(), day="2025-09-16"
        )
        with self.assertRaises(ValueError):
            trial.calculate(data, ROOT / "static" / "demo.trf")
        data["round_dates"] = ["2025-09-16", "2025-09-17", "2025-09-18"]
        self.assertEqual(
            trial.calculate(data, ROOT / "static" / "demo.trf")["rounds"], 3
        )


if __name__ == "__main__":
    unittest.main()
