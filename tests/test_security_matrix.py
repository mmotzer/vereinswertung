"""Isolated two-club adversarial API exercise with synthetic accounts."""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from club_platform import create_platform
from vereinswertung import permissions, storage


class TwoClubSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="security-two-clubs-")
        self.root = Path(self.temp.name)
        self.app = create_platform(
            dict(
                DATA_ROOT=str(self.root),
                TESTING=True,
                SECURE_COOKIE=False,
                PUBLIC_ORIGIN="https://platform.example",
                TENANT_DOMAIN="clubs.example",
            )
        )
        self.clients = {}
        self.csrf = {}
        self.files = {}
        hashed = generate_password_hash("synthetic-test-password-123")
        for slug, cid in (("alpha", "a" * 32), ("beta", "b" * 32)):
            with self.app.extensions["registry"]() as db:
                db.execute(
                    "INSERT INTO clubs(id,slug,name,email,username,password,status,plan,created) VALUES(?,?,?,?,?,?,'active','legacy',?)",
                    (
                        cid,
                        slug,
                        slug,
                        "test@example.org",
                        "admin",
                        hashed,
                        time.time(),
                    ),
                )
                row = db.execute(
                    "SELECT * FROM clubs WHERE id=?", (cid,)
                ).fetchone()
            child = self.app.extensions["tenant_app"](row)
            self.files[slug] = Path(child.config["DATABASE"])
            with storage.open_db(self.files[slug]) as db:
                for role in ("director", "member"):
                    db.execute(
                        "INSERT INTO users(username,password,role,created) VALUES(?,?,?,?)",
                        (role, hashed, role, time.time()),
                    )
                db.execute(
                    "INSERT INTO players(id,name,created) VALUES(1,?,?)",
                    (slug + " Private Player", time.time()),
                )
            for role in ("admin", "director", "member"):
                client = self.app.test_client()
                response = client.post(
                    "/api/login",
                    base_url=self.origin(slug),
                    headers={"Origin": self.origin(slug)},
                    json=dict(
                        username=role, password="synthetic-test-password-123"
                    ),
                )
                self.assertEqual(response.status_code, 200, response.json)
                self.clients[slug, role] = client
                self.csrf[slug, role] = response.json["csrf"]

    def tearDown(self):
        self.temp.cleanup()

    def origin(self, slug):
        return "https://" + slug + ".clubs.example"

    def test_read_matrix_and_identical_player_ids_do_not_cross_clubs(self):
        for (slug, role), client in self.clients.items():
            for route in (
                "/api/users",
                "/api/audit",
                "/api/settings",
                "/api/club-members",
                "/api/backup",
            ):
                with self.subTest(slug=slug, role=role, route=route):
                    with client.get(
                        route, base_url=self.origin(slug)
                    ) as response:
                        self.assertEqual(
                            response.status_code,
                            200 if role == "admin" else 403,
                        )
            response = client.get("/api/players/1", base_url=self.origin(slug))
            self.assertEqual(response.status_code, 200)
            body = response.get_data(as_text=True)
            self.assertIn(slug + " Private Player", body)
            self.assertNotIn(
                ("beta" if slug == "alpha" else "alpha") + " Private Player",
                body,
            )

    def test_foreign_session_and_csrf_are_not_accepted(self):
        alpha = self.clients["alpha", "admin"]
        token = alpha.get_cookie(
            "club_session", domain="alpha.clubs.example"
        ).value
        intruder = self.app.test_client()
        intruder.set_cookie("club_session", token, domain="beta.clubs.example")
        self.assertEqual(
            intruder.get(
                "/api/users", base_url=self.origin("beta")
            ).status_code,
            401,
        )
        beta = self.clients["beta", "admin"]
        before = self.files["beta"].read_bytes()
        for origin, csrf in (
            (self.origin("alpha"), self.csrf["beta", "admin"]),
            (self.origin("beta"), self.csrf["alpha", "admin"]),
        ):
            response = beta.post(
                "/api/users/1",
                base_url=self.origin("beta"),
                headers={"Origin": origin, "X-CSRF-Token": csrf},
                json={"active": False},
            )
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.files["beta"].read_bytes(), before)

    def test_denied_accounts_cannot_use_unlisted_submission_helpers(self):
        for slug in ("alpha", "beta"):
            with storage.open_db(self.files[slug]) as db:
                db.execute(
                    "UPDATE users SET permissions=? WHERE role='member'",
                    (json.dumps({key: False for key in permissions.LABELS}),),
                )
            client = self.clients[slug, "member"]
            for route in ("/api/submission-players", "/api/submissions"):
                with self.subTest(slug=slug, route=route):
                    self.assertEqual(
                        client.get(
                            route, base_url=self.origin(slug)
                        ).status_code,
                        403,
                    )

    def test_files_and_role_escalation_are_denied(self):
        for slug in ("alpha", "beta"):
            client = self.clients[slug, "member"]
            for route in (
                "/.env",
                "/platform.sqlite",
                "/data/club.sqlite",
                "/static/../app.py",
                "/static/../../data/club.sqlite",
            ):
                with self.subTest(slug=slug, route=route):
                    self.assertIn(
                        client.get(
                            route, base_url=self.origin(slug)
                        ).status_code,
                        (400, 404),
                    )
            response = client.post(
                "/api/users/3",
                base_url=self.origin(slug),
                headers={
                    "Origin": self.origin(slug),
                    "X-CSRF-Token": self.csrf[slug, "member"],
                },
                json={"role": "admin", "permissions": {"manage_users": True}},
            )
            self.assertEqual(response.status_code, 403)

    @patch("vereinswertung.billing.request")
    def test_billing_portal_cannot_be_opened_for_another_club(self, mock):
        mock.return_value = {"url": "https://billing.stripe.com/test"}
        with self.app.extensions["registry"]() as db:
            for slug in ("alpha", "beta"):
                db.execute(
                    "UPDATE clubs SET customer=? WHERE slug=?",
                    ("cus_" + slug, slug),
                )
        for (slug, role), client in self.clients.items():
            response = client.post(
                "/api/billing/portal",
                base_url=self.origin(slug),
                headers={
                    "Origin": self.origin(slug),
                    "X-CSRF-Token": self.csrf[slug, role],
                },
            )
            self.assertEqual(
                response.status_code, 200 if role == "admin" else 403
            )
            if role == "admin":
                self.assertEqual(
                    mock.call_args.args[2]["customer"], "cus_" + slug
                )
        before = mock.call_count
        client = self.clients["beta", "admin"]
        response = client.post(
            "/api/billing/portal",
            base_url=self.origin("beta"),
            headers={
                "Origin": self.origin("beta"),
                "X-CSRF-Token": self.csrf["alpha", "admin"],
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(mock.call_count, before)
