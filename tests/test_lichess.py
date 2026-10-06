import io
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from vereinswertung import lichess_import


def exported(gid="abcdefgh", speed="blitz"):
    return {
        "id": gid,
        "variant": "standard",
        "speed": speed,
        "status": "mate",
        "winner": "white",
        "createdAt": 1758100000000,
        "lastMoveAt": 1758101000000,
        "players": {
            "white": {"user": {"name": "Anna"}},
            "black": {"user": {"name": "Ben"}},
        },
    }


class LichessTests(unittest.TestCase):
    def test_bullet_is_supported(self):
        self.assertEqual(
            lichess_import.parse_game(exported(speed="bullet"))["category"],
            "bullet",
        )

    def test_url_host_and_duplicate_normalization(self):
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(exported()).encode()),
        ) as request:
            games = lichess_import.fetch_games(
                "https://lichess.org/abcdefgh1234/black#10 https://lichess.org/abcdefgh"
            )
            self.assertEqual(len(games), 1)
            self.assertEqual(request.call_args.args[0].data, b"abcdefgh")
        for url in [
            "http://localhost/abcdefgh",
            "https://lichess.org.evil/abcdefgh",
            "https://lichess.org/@/Anna",
        ]:
            with self.assertRaises(ValueError):
                lichess_import.fetch_games(url)

    def test_invalid_game_types(self):
        for change in [
            {"variant": "chess960"},
            {"speed": "ultraBullet"},
            {"status": "started"},
            {
                "players": {
                    "white": {"user": {"name": "Anna", "title": "BOT"}},
                    "black": {"user": {"name": "Ben"}},
                }
            },
        ]:
            with self.assertRaises(ValueError):
                lichess_import.parse_game({**exported(), **change})

    def test_match_uses_german_day_and_verifies_opponents(self):
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(exported()).encode()),
        ) as request:
            self.assertEqual(
                len(lichess_import.fetch_match("Anna", "Ben", "2025-03-30")), 1
            )
            params = parse_qs(
                urlparse(request.call_args.args[0].full_url).query
            )
            self.assertEqual(
                int(params["until"][0]) - int(params["since"][0]) + 1,
                23 * 3600 * 1000,
            )
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(json.dumps(exported()).encode()),
        ):
            with self.assertRaises(ValueError):
                lichess_import.fetch_match("Anna", "Other", "2025-09-17")
