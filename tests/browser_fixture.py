"""Disposable local browser QA server. Never uses the production data folder."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".runtime"))

from app import create_app
from waitress import serve

app = create_app({"DATABASE": str(ROOT / ".runtime" / "browser-qa.sqlite"),
                  "BOOTSTRAP_TOKEN": "disposable-browser-qa-bootstrap-only", "SECURE_COOKIE": False,
                  "PUBLIC_ORIGIN": "http://127.0.0.1:8081"})
client = app.test_client()
if client.get("/api/me").json["needs_setup"]:
    response = client.post("/api/setup", json={"token": "disposable-browser-qa-bootstrap-only",
                            "username": "testleitung", "password": "Browser-Test-Only-2026!"},
                           headers={"Origin": "http://127.0.0.1:8081"})
    assert response.status_code == 200, response.json
print("Lokale Browser-Testinstanz: http://127.0.0.1:8081 (separate Testdatenbank)", flush=True)
serve(app, host="127.0.0.1", port=8081, threads=4)
