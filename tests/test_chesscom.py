import io
import json
import unittest
from unittest.mock import patch

from vereinswertung import chesscom_import as cc


def exported(gid="12345", stamp=1758101000, speed="blitz"):
    return dict(
        url="https://www.chess.com/game/live/" + gid,
        rules="chess",
        time_class=speed,
        end_time=stamp,
        white=dict(username="Anna", result="win", rating=2500),
        black=dict(username="Ben", result="resigned", rating=800),
    )


class ChesscomTests(unittest.TestCase):
    def test_results_and_ids(self):
        game = cc.parse_game(exported(speed="bullet"))
        self.assertEqual(game["external_id"], "chesscom:live:12345")
        self.assertEqual(game["category"], "bullet")
        for mutation in [
            dict(rules="chess960"),
            dict(time_class="daily"),
            dict(end_time=0),
            dict(url="http://localhost/12345"),
            dict(black=dict(username="Ben", result="win")),
        ]:
            with self.assertRaises(ValueError):
                cc.parse_game({**exported(), **mutation})

    def test_archive_filters_names_dates_and_namespaces(self):
        with patch(
            "urllib.request.urlopen",
            return_value=io.BytesIO(
                json.dumps(dict(games=[exported(), exported("99", 1)])).encode()
            ),
        ) as request:
            items = cc.fetch_match("Anna", "Ben", "2025-09-17")
            self.assertEqual(len(items), 1)
            self.assertTrue(
                request.call_args.args[0].full_url.startswith(
                    "https://api.chess.com/pub/player/anna/games/2025/09"
                )
            )
        with patch.object(cc, "archive", return_value=[exported()]):
            with self.assertRaises(ValueError):
                cc.fetch_match("Anna", "Other", "2025-09-17")
            with self.assertRaises(ValueError):
                cc.fetch_match(
                    "Anna",
                    "Ben",
                    "2025-09-17",
                    "https://www.chess.com/game/live/999",
                )

    def test_utc_month_boundary(self):
        with patch.object(cc, "archive", return_value=[]) as fetch:
            with self.assertRaises(ValueError):
                cc.fetch_match("Anna", "Ben", "2025-10-01")
            self.assertEqual(
                {args.args[1:] for args in fetch.call_args_list},
                {(2025, 9), (2025, 10)},
            )

    def test_pgn_export(self):
        pgn = "\n".join(
            [
                '[Event "Live Chess"]',
                '[Site "Chess.com"]',
                '[White "Anna"]',
                '[Black "Ben"]',
                '[Result "1-0"]',
                '[UTCDate "2025.09.17"]',
                '[EndTime "12:00:00"]',
                '[TimeControl "60"]',
                '[Link "https://www.chess.com/game/live/12345"]',
                "",
                "1. e4 e5 1-0",
            ]
        )
        self.assertEqual(cc.parse_pgn(pgn)[0]["category"], "bullet")
        with self.assertRaises(ValueError):
            cc.parse_pgn(pgn.replace('[Result "1-0"]', '[Result "*"]'))
