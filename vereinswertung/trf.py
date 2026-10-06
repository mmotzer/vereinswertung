"""Strict TRF06/16 player-section reader, including SWISS-CHESS 9.64."""

import unicodedata
from datetime import datetime


def normalize(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def decode(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1252")
        except UnicodeDecodeError:
            raise ValueError(
                "Dateikodierung ungültig. Bitte als UTF-8 oder Windows-1252 exportieren."
            )


def parse_date(value):
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return ""


def parse(text):
    players = {}
    metadata = {}
    warnings = []
    played_codes = {"1": 1.0, "0": 0.0, "=": 0.5, "W": 1.0, "L": 0.0, "D": 0.5}
    unplayed_codes = set("+-HUZFAPX")
    for line_no, line in enumerate(text.splitlines(), 1):
        if line.startswith(("012 ", "042 ", "052 ")):
            metadata[line[:3]] = line[4:].strip()
        if not line.startswith("001 "):
            continue
        try:
            number = int(line[4:8])
        except ValueError:
            raise ValueError(f"Zeile {line_no}: ungültige Spielernummer")
        name = line[14:47].strip()
        if not name or number <= 0 or number in players:
            raise ValueError(
                f"Zeile {line_no}: Name oder Spielernummer ungültig/doppelt"
            )
        rounds = []
        tail = line[91:]
        for pos in range(0, len(tail), 10):
            block = tail[pos : pos + 10].ljust(8)
            if not block.strip():
                rounds.append(None)
                continue
            try:
                opponent = int(block[:4].strip() or "0")
            except ValueError:
                raise ValueError(
                    f"{name}, Runde {pos // 10 + 1}: ungültiger Gegner"
                )
            color, result = block[5].lower(), block[7].upper()
            if result not in played_codes and result not in unplayed_codes:
                raise ValueError(
                    f"{name}, Runde {pos // 10 + 1}: fehlender oder unbekannter Ergebniskode {result!r}"
                )
            if opponent and result in played_codes and color not in ("w", "b"):
                raise ValueError(f"{name}, Runde {pos // 10 + 1}: Farbe fehlt")
            if not opponent and result in played_codes and result != "0":
                warnings.append(
                    f"{name}, Runde {pos // 10 + 1}: Ergebnis ohne Gegner, nicht gewertet"
                )
            rounds.append(
                {"opponent": opponent, "color": color, "result": result}
            )
        players[number] = {"number": number, "name": name, "rounds": rounds}
    if not players:
        raise ValueError("Keine TRF-Spielereinträge (001) gefunden")
    if (
        len(players) > 500
        or max(len(p["rounds"]) for p in players.values()) > 100
    ):
        raise ValueError("Maximal 500 Spieler und 100 Runden pro Import")
    keys = [normalize(p["name"]) for p in players.values()]
    if len(keys) != len(set(keys)):
        raise ValueError(
            "Doppelte Spielernamen: Bitte in SWISS-CHESS eindeutig benennen"
        )
    games, skipped, seen = [], [], set()
    for number, player in players.items():
        for index, entry in enumerate(player["rounds"]):
            if entry is None:
                continue
            rnd = index + 1
            opponent = entry["opponent"]
            result = entry["result"]
            if opponent == number:
                raise ValueError(
                    f"{player['name']}, Runde {rnd}: Spieler gegen sich selbst"
                )
            if opponent == 0:
                skipped.append(
                    {
                        "round": rnd,
                        "name": player["name"],
                        "reason": "Freilos / nicht gespielt",
                    }
                )
                continue
            if opponent not in players:
                raise ValueError(f"Runde {rnd}: Gegner {opponent} fehlt")
            opp_rounds = players[opponent]["rounds"]
            reverse = opp_rounds[index] if index < len(opp_rounds) else None
            if reverse is None or reverse["opponent"] != number:
                raise ValueError(
                    f"Runde {rnd}: Gegnereinträge für {player['name']} stimmen nicht überein"
                )
            pair_key = (rnd, min(number, opponent), max(number, opponent))
            if pair_key in seen:
                continue
            seen.add(pair_key)
            if result in unplayed_codes or reverse["result"] in unplayed_codes:
                if (
                    result not in unplayed_codes
                    or reverse["result"] not in unplayed_codes
                ):
                    raise ValueError(
                        f"Runde {rnd}: gespielt/kampflos widersprüchlich"
                    )
                if (result, reverse["result"]) not in (
                    ("+", "-"),
                    ("-", "+"),
                    ("-", "-"),
                    ("P", "A"),
                    ("A", "P"),
                    ("A", "A"),
                    ("X", "X"),
                ):
                    raise ValueError(
                        f"Runde {rnd}: widersprüchliche kampflose Ergebnisse"
                    )
                skipped.append(
                    {
                        "round": rnd,
                        "name": player["name"]
                        + " / "
                        + players[opponent]["name"],
                        "reason": "Kampflos",
                    }
                )
                continue
            if entry["color"] == reverse["color"] or reverse["color"] not in (
                "w",
                "b",
            ):
                raise ValueError(f"Runde {rnd}: Farben widersprechen sich")
            if played_codes[result] + played_codes[reverse["result"]] != 1:
                raise ValueError(f"Runde {rnd}: Ergebnisse widersprechen sich")
            white = number if entry["color"] == "w" else opponent
            black = opponent if entry["color"] == "w" else number
            score = (
                played_codes[result]
                if entry["color"] == "w"
                else 1 - played_codes[result]
            )
            games.append(
                {"round": rnd, "white": white, "black": black, "score": score}
            )
    if not games:
        raise ValueError(
            "Die Datei enthält keine vollständig gespielten Partien"
        )
    return {
        "name": metadata.get("012") or "Vereinsturnier",
        "date": parse_date(metadata.get("042", "")),
        "end_date": parse_date(metadata.get("052", "")),
        "players": list(players.values()),
        "games": sorted(
            games, key=lambda g: (g["round"], g["white"], g["black"])
        ),
        "rounds": max(g["round"] for g in games),
        "skipped": skipped,
        "warnings": warnings,
    }
