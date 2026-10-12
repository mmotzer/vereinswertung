import hashlib
import hmac
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from club_platform import create_platform
from platform_manage import (
    backup_platform,
    diagnose_platform,
    file_digest,
    import_club,
    restore_backup,
    verify_backup,
)
from vereinswertung import billing, storage


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        legal = self.root / "legal"
        legal.mkdir()
        for name in ("terms", "privacy", "imprint"):
            (legal / (name + ".html")).write_text("<p>Test</p>")
        self.app = create_platform(
            dict(
                DATA_ROOT=str(self.root),
                TESTING=True,
                SECURE_COOKIE=False,
                PUBLIC_ORIGIN="https://platform.example",
                LEGAL_READY=True,
                LEGAL_DIR=str(legal),
                STRIPE_SECRET_KEY="test",
                STRIPE_WEBHOOK_SECRET="secret",
                STRIPE_PRICE_MONTH="price_month",
                STRIPE_PRICE_YEAR="price_year",
            )
        )
        self.client = self.app.test_client()
        self.origin = {"Origin": "https://platform.example"}
        self.registry = self.app.extensions["registry"]

    def tearDown(self):
        self.temp.cleanup()

    def seed(self, slug, cid, status="active"):
        with self.registry() as db:
            db.execute(
                "INSERT INTO clubs(id,slug,name,email,username,password,status,plan,created) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    slug,
                    "Club " + slug,
                    "admin@example.org",
                    "admin",
                    generate_password_hash("test-password-123"),
                    status,
                    "month",
                    time.time(),
                ),
            )

    def stripe(self, config, path, fields=None, idempotency=None):
        if path.startswith("prices/"):
            return dict(
                active=True,
                unit_amount=500,
                currency="eur",
                recurring=dict(interval=path.split("_")[-1], interval_count=1),
            )
        if path == "checkout/sessions":
            return dict(id="cs_test", url="https://checkout.stripe.com/test")
        if path.startswith("subscriptions/"):
            with self.registry() as db:
                row = db.execute(
                    'SELECT id FROM clubs WHERE slug="club-new"'
                ).fetchone()
            return dict(
                status="active",
                customer="cus_test",
                metadata=dict(club_id=row["id"]),
            )
        raise AssertionError(path)

    def event(self, event):
        raw = json.dumps(event).encode()
        stamp = str(int(time.time()))
        signature = hmac.new(
            b"secret", stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        return self.client.post(
            "/api/platform/webhook",
            data=raw,
            content_type="application/json",
            headers={"Stripe-Signature": "t=" + stamp + ",v1=" + signature},
        )

    def test_isolation_and_mount(self):
        self.seed("club-one", "a" * 32)
        self.seed("club-two", "b" * 32)
        login = self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("Path=/v/club-one/", login.headers["Set-Cookie"])
        token = self.client.get_cookie(
            "club_session", path="/v/club-one/"
        ).value
        self.client.set_cookie("club_session", token, path="/v/club-two/")
        self.assertEqual(
            self.client.get("/v/club-two/api/rankings").status_code, 401
        )
        with storage.open_db(
            self.root / "tenants" / ("a" * 32) / "club.sqlite"
        ) as db:
            db.execute(
                "INSERT INTO players(name,created) VALUES(?,?)",
                ("Only One", time.time()),
            )
        self.client.post(
            "/v/club-two/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        with storage.open_db(
            self.root / "tenants" / ("b" * 32) / "club.sqlite"
        ) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM players").fetchone()[0], 0
            )
        body = self.client.get("/v/club-one/").get_data(as_text=True)
        self.assertIn("/v/club-one/static/app.js", body)
        self.assertNotIn("SK1912 Ludwigshafen", body)
        manifest = self.client.get(
            "/v/club-one/static/manifest.webmanifest"
        ).json
        self.assertEqual(manifest["scope"], "/v/club-one/")

    def test_parallel_club_sessions_and_logout_are_independent(self):
        self.seed("club-one", "a" * 32)
        self.seed("club-two", "b" * 32)
        sessions = {}
        for slug in ("club-one", "club-two"):
            response = self.client.post(
                f"/v/{slug}/api/login",
                json=dict(username="admin", password="test-password-123"),
                headers=self.origin,
            )
            self.assertEqual(response.status_code, 200, response.json)
            sessions[slug] = response.json["csrf"]
        self.assertNotEqual(sessions["club-one"], sessions["club-two"])
        # A valid CSRF token from another club must not end this session.
        denied = self.client.post(
            "/v/club-one/api/logout",
            headers={**self.origin, "X-CSRF-Token": sessions["club-two"]},
        )
        self.assertEqual(denied.status_code, 403)
        for slug in sessions:
            self.assertEqual(
                self.client.get(f"/v/{slug}/api/rankings").status_code, 200
            )
        response = self.client.post(
            "/v/club-one/api/logout",
            headers={**self.origin, "X-CSRF-Token": sessions["club-one"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.get("/v/club-one/api/rankings").status_code, 401
        )
        self.assertEqual(
            self.client.get("/v/club-two/api/rankings").status_code, 200
        )

    def test_healthcheck_detects_unreadable_register(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        file = self.root / "platform.sqlite"
        file.write_bytes(b"broken-register")
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json["ok"])
        self.assertNotIn(str(self.root), json.dumps(response.json))
        self.assertEqual(file.read_bytes(), b"broken-register")

    def test_doctor_does_not_create_missing_database(self):
        target = self.root / "missing"
        report = diagnose_platform(target, self.app.config)
        self.assertFalse(report["ok"])
        self.assertFalse(target.exists())
        self.assertNotIn("secret", json.dumps(report))

    def test_doctor_detects_missing_provisioned_club_and_bad_backup(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        snapshot = backup_platform(self.app)
        report = diagnose_platform(self.root, self.app.config)
        self.assertTrue(report["ok"], report)
        with storage.open_db(
            self.root / "tenants" / ("a" * 32) / "club.sqlite"
        ) as db:
            db.execute("UPDATE users SET active=0")
        (snapshot / "platform.sqlite").write_bytes(b"broken")
        report = diagnose_platform(self.root, self.app.config)
        statuses = {item["check"]: item["status"] for item in report["checks"]}
        self.assertFalse(report["ok"])
        self.assertEqual(statuses["club_databases"], "error")
        self.assertEqual(statuses["backup"], "error")

    def test_doctor_requires_valid_administrator_management_rights(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        file = self.root / "tenants" / ("a" * 32) / "club.sqlite"
        for overrides in (
            '{"manage_users": false}',
            "[]",
            "null",
            "broken",
            '{"manage_users": "yes"}',
        ):
            with self.subTest(overrides=overrides):
                with storage.open_db(file) as db:
                    db.execute(
                        "UPDATE users SET permissions=? WHERE role='admin'",
                        (overrides,),
                    )
                report = diagnose_platform(self.root, self.app.config)
                self.assertFalse(report["ok"])
                status = {
                    item["check"]: item["status"] for item in report["checks"]
                }
                self.assertEqual(status["club_databases"], "error")
        with storage.open_db(file) as db:
            db.execute("UPDATE users SET permissions='{}' WHERE role='admin'")
        self.assertTrue(diagnose_platform(self.root, self.app.config)["ok"])

    def test_doctor_rejects_incomplete_paid_launch_config(self):
        config = dict(self.app.config)
        config["PUBLIC_ORIGIN"] = "http://platform.example"
        config["STRIPE_SECRET_KEY"] = ""
        config["LEGAL_READY"] = False
        report = diagnose_platform(self.root, config)
        statuses = {item["check"]: item["status"] for item in report["checks"]}
        self.assertFalse(report["ok"])
        for check in ("public_origin", "billing_config", "legal_files"):
            self.assertEqual(statuses[check], "error")

    def test_separate_club_origins(self):
        config = dict(self.app.config)
        config["TENANT_DOMAIN"] = "clubs.example"
        app = create_platform(config)
        client = app.test_client()
        self.seed("club-one", "a" * 32)
        self.seed("club-two", "b" * 32)
        one = "https://club-one.clubs.example"
        two = "https://club-two.clubs.example"
        denied = client.post(
            "/api/login",
            base_url=one,
            json=dict(username="admin", password="test-password-123"),
            headers={"Origin": two},
        )
        self.assertEqual(denied.status_code, 403)
        login = client.post(
            "/api/login",
            base_url=one,
            json=dict(username="admin", password="test-password-123"),
            headers={"Origin": one},
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("Path=/", login.headers["Set-Cookie"])
        self.assertNotIn("Domain=", login.headers["Set-Cookie"])
        self.assertEqual(
            client.get("/api/rankings", base_url=two).status_code, 401
        )
        page = client.get("/", base_url=one).get_data(as_text=True)
        self.assertIn('name="club-platform"', page)
        self.assertIn("/static/app.js", page)
        self.assertEqual(
            client.get("/static/manifest.webmanifest", base_url=one).json[
                "scope"
            ],
            "/",
        )
        redirect = client.get(
            "/v/club-one/?test=1", base_url="https://platform.example"
        )
        self.assertEqual(redirect.headers["Location"], one + "/?test=1")
        self.assertEqual(
            client.post(
                "/v/club-one/api/login", headers=self.origin
            ).status_code,
            409,
        )
        self.assertEqual(
            client.get(
                "/", base_url="https://missing.clubs.example"
            ).status_code,
            404,
        )

    def test_suspended_readonly(self):
        self.seed("club-one", "a" * 32, "suspended")
        login = self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(
            self.client.get("/v/club-one/api/rankings").status_code, 200
        )
        self.assertEqual(
            self.client.post(
                "/v/club-one/api/users", json={}, headers=self.origin
            ).status_code,
            402,
        )

    def test_origin_and_disabled_checkout(self):
        self.assertEqual(
            self.client.post("/api/platform/checkout", json={}).status_code, 403
        )
        self.app.config["LEGAL_READY"] = False
        self.assertEqual(
            self.client.post(
                "/api/platform/checkout", json={}, headers=self.origin
            ).status_code,
            503,
        )
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 0
            )

    @patch("vereinswertung.billing.request")
    def test_checkout_paid_and_duplicate_event(self, mock):
        mock.side_effect = self.stripe
        data = dict(
            name="New Club",
            slug="club-new",
            email="a@example.org",
            username="admin",
            password="test-password-123",
            plan="month",
            terms=True,
        )
        response = self.client.post(
            "/api/platform/checkout", json=data, headers=self.origin
        )
        self.assertEqual(response.status_code, 200, response.json)
        with self.registry() as db:
            row = db.execute("SELECT * FROM clubs").fetchone()
        self.assertEqual(row["status"], "pending")
        event = dict(
            id="evt_one",
            created=int(time.time()),
            type="checkout.session.completed",
            data=dict(
                object=dict(
                    client_reference_id=row["id"],
                    id="cs_test",
                    subscription="sub_test",
                    customer="cus_test",
                    payment_status="unpaid",
                )
            ),
        )
        self.assertEqual(self.event(event).status_code, 200)
        self.assertFalse(
            self.client.get("/api/platform/status?slug=club-new").json["ready"]
        )
        event["id"] = "evt_two"
        event["data"]["object"]["payment_status"] = "paid"
        self.assertEqual(self.event(event).status_code, 200)
        self.assertTrue(
            self.client.get("/api/platform/status?slug=club-new").json["ready"]
        )
        count = mock.call_count
        self.assertEqual(self.event(event).status_code, 200)
        self.assertEqual(mock.call_count, count)

    @patch("vereinswertung.billing.request")
    def test_signed_malformed_webhooks_do_not_change_state(self, mock):
        self.seed("club-one", "a" * 32)
        base = dict(
            id="evt_malformed",
            created=10,
            type="customer.subscription.updated",
            data=dict(object=dict(id="sub_test")),
        )
        for changes in (
            {"data": []},
            {"data": None},
            {"data": {"object": []}},
            {"created": True},
            {"created": -1},
            {"id": ""},
            {"type": []},
        ):
            with self.subTest(changes=changes):
                result = self.event({**base, **changes})
                self.assertEqual(result.status_code, 400)
                with self.registry() as db:
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        db.execute("SELECT status FROM clubs").fetchone()[0],
                        "active",
                    )
        mock.assert_not_called()

    @patch("vereinswertung.billing.request")
    def test_malformed_payment_references_are_rejected_before_processing(
        self, mock
    ):
        self.seed("club-new", "a" * 32, "pending")
        with self.registry() as db:
            db.execute("UPDATE clubs SET checkout='cs_test'")
        base = dict(
            id="cs_test",
            client_reference_id="a" * 32,
            subscription="sub_test",
            customer="cus_test",
            payment_status="paid",
        )
        for changes in (
            {"id": []},
            {"id": ""},
            {"client_reference_id": {}},
            {"subscription": []},
            {"customer": True},
            {"subscription": None},
            {"customer": None},
        ):
            with self.subTest(changes=changes):
                result = self.event(
                    dict(
                        id="evt_refs",
                        created=10,
                        type="checkout.session.completed",
                        data=dict(object={**base, **changes}),
                    )
                )
                self.assertEqual(result.status_code, 400)
                with self.registry() as db:
                    self.assertEqual(
                        db.execute("SELECT status FROM clubs").fetchone()[0],
                        "pending",
                    )
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                        0,
                    )
        result = self.event(
            dict(
                id="evt_sub_refs",
                created=10,
                type="customer.subscription.updated",
                data=dict(object=dict(id={})),
            )
        )
        self.assertEqual(result.status_code, 400)
        mock.assert_not_called()

    def test_non_ascii_webhook_signature_is_cleanly_rejected(self):
        with self.assertRaisesRegex(ValueError, "Signatur"):
            billing.verify(b"{}", "t=1000,v1=ä", "secret", now=1000)

    def test_webhook_signature(self):
        raw = b'{"id":"test"}'
        signature = hmac.new(
            b"secret", b"1000." + raw, hashlib.sha256
        ).hexdigest()
        self.assertEqual(
            billing.verify(raw, "t=1000,v1=" + signature, "secret", now=1000)[
                "id"
            ],
            "test",
        )
        for data, now in ((raw + b" ", 1000), (raw, 1400)):
            with self.assertRaises(ValueError):
                billing.verify(
                    data, "t=1000,v1=" + signature, "secret", now=now
                )

    def test_roster_and_backup_isolation(self):
        self.seed("club-one", "a" * 32)
        self.seed("club-two", "b" * 32)
        login = self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        headers = {**self.origin, "X-CSRF-Token": login.json["csrf"]}
        response = self.client.post(
            "/v/club-one/api/club-members",
            json=dict(members=[dict(name="Player One", club_number="0001")]),
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(
            len(
                self.client.get("/v/club-one/api/club-members").json["members"]
            ),
            1,
        )
        self.client.post(
            "/v/club-two/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        self.assertEqual(
            self.client.get("/v/club-two/api/club-members").json["members"], []
        )
        backup = backup_platform(self.app)
        self.assertTrue((backup / "platform.sqlite").is_file())
        for cid, count in [("a" * 32, 1), ("b" * 32, 0)]:
            with storage.open_db(
                backup / "tenants" / cid / "club.sqlite"
            ) as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM players").fetchone()[0],
                    count,
                )

    def test_migration_rejects_invalid_references_before_copying(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        source = self.root / "tenants" / ("a" * 32) / "club.sqlite"
        with storage.open_db(source) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute(
                "INSERT INTO previews VALUES('orphan',999999,0,'{}',9999999999)"
            )
        before = {file.name for file in (self.root / "tenants").iterdir()}
        with self.assertRaisesRegex(ValueError, "ungültigen Verweisen"):
            import_club(
                self.app,
                source,
                "invalid-club",
                "Invalid",
                "a@example.org",
                "admin",
            )
        self.assertEqual(
            {file.name for file in (self.root / "tenants").iterdir()}, before
        )
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 1
            )

    def test_migration_preserves_players_and_invalidates_sessions(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        source = self.root / "tenants" / ("a" * 32) / "club.sqlite"
        with storage.open_db(source) as db:
            db.execute(
                "INSERT INTO players(name,created) VALUES(?,?)",
                ("Original Player", time.time()),
            )
            uid = db.execute(
                "SELECT id FROM users WHERE username='admin'"
            ).fetchone()[0]
            db.execute(
                "INSERT INTO previews VALUES('old-preview',?,0,'{}',9999999999)",
                (uid,),
            )
        import_club(
            self.app,
            source,
            "migrated-club",
            "Migrated",
            "a@example.org",
            "admin",
        )
        with self.registry() as db:
            row = db.execute(
                'SELECT * FROM clubs WHERE slug="migrated-club"'
            ).fetchone()
        with storage.open_db(
            self.root / "tenants" / row["id"] / "club.sqlite"
        ) as db:
            self.assertEqual(
                db.execute("SELECT name FROM players").fetchone()[0],
                "Original Player",
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM previews").fetchone()[0], 0
            )
        with storage.open_db(source) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM previews").fetchone()[0], 1
            )

    @patch("vereinswertung.billing.request")
    def test_invalid_checkout_response_keeps_reservation_retryable(self, mock):
        replies = [
            [],
            {"url": "https://checkout.stripe.com/test"},
            {"id": [], "url": "https://checkout.stripe.com/test"},
            {
                "id": "cs_test",
                "url": "https://checkout.stripe.com:invalid/test",
            },
        ]
        keys = []

        def call(config, path, fields=None, idempotency=None):
            if path == "checkout/sessions":
                keys.append(idempotency)
                if replies:
                    return replies.pop(0)
            return self.stripe(config, path, fields, idempotency)

        mock.side_effect = call
        data = dict(
            name="New Club",
            slug="club-new",
            email="a@example.org",
            username="admin",
            password="test-password-123",
            plan="month",
            terms=True,
        )
        for _ in range(4):
            result = self.client.post(
                "/api/platform/checkout", json=data, headers=self.origin
            )
            self.assertEqual(result.status_code, 502, result.json)
            with self.registry() as db:
                row = db.execute("SELECT status,checkout FROM clubs").fetchone()
                self.assertEqual(row["status"], "pending")
                self.assertIsNone(row["checkout"])
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 1
                )
        result = self.client.post(
            "/api/platform/checkout", json=data, headers=self.origin
        )
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(len(set(keys)), 1)
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT checkout FROM clubs").fetchone()[0],
                "cs_test",
            )

    @patch("vereinswertung.billing.request")
    def test_retry_after_checkout_timeout_keeps_idempotency(self, mock):
        keys = []
        fail = [True]

        def call(config, path, fields=None, idempotency=None):
            if path == "checkout/sessions":
                keys.append(idempotency)
                if fail and fail.pop():
                    raise TimeoutError()
            return self.stripe(config, path, fields, idempotency)

        mock.side_effect = call
        data = dict(
            name="New Club",
            slug="club-new",
            email="a@example.org",
            username="admin",
            password="test-password-123",
            plan="month",
            terms=True,
        )
        self.assertEqual(
            self.client.post(
                "/api/platform/checkout", json=data, headers=self.origin
            ).status_code,
            502,
        )
        self.assertEqual(
            self.client.post(
                "/api/platform/checkout", json=data, headers=self.origin
            ).status_code,
            200,
        )
        self.assertEqual(keys[0], keys[1])

    @patch("vereinswertung.billing.request")
    def test_out_of_order_subscription_reads_current_state(self, mock):
        self.seed("club-one", "a" * 32)
        with self.registry() as db:
            db.execute(
                'UPDATE clubs SET subscription="sub_test",customer="cus_test" WHERE slug="club-one"'
            )
        mock.return_value = dict(
            status="canceled",
            customer="cus_test",
            metadata=dict(club_id="a" * 32),
        )
        event = dict(
            id="evt_old",
            created=10,
            type="customer.subscription.updated",
            data=dict(object=dict(id="sub_test", status="active")),
        )
        self.assertEqual(self.event(event).status_code, 200)
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT status FROM clubs").fetchone()[0],
                "suspended",
            )

    @patch("vereinswertung.billing.request")
    def test_webhook_before_checkout_storage_is_retried(self, mock):
        self.seed("club-new", "a" * 32, "pending")
        mock.side_effect = self.stripe
        event = dict(
            id="evt_race",
            created=int(time.time()),
            type="checkout.session.completed",
            data=dict(
                object=dict(
                    client_reference_id="a" * 32,
                    id="cs_test",
                    subscription="sub_test",
                    customer="cus_test",
                    payment_status="paid",
                )
            ),
        )
        self.assertEqual(self.event(event).status_code, 409)
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0
            )
            db.execute('UPDATE clubs SET checkout="cs_test"')
        self.assertEqual(self.event(event).status_code, 200)
        self.assertTrue(
            self.client.get("/api/platform/status?slug=club-new").json["ready"]
        )

    def test_backup_does_not_create_missing_source_register(self):
        self.app.config["DATA_ROOT"] = str(self.root / "missing-source")
        with self.assertRaises(sqlite3.OperationalError):
            backup_platform(self.app)
        self.assertFalse(
            (self.root / "missing-source" / "platform.sqlite").exists()
        )
        self.assertEqual(
            list(
                (self.root / "missing-source").glob("backups/*/complete.json")
            ),
            [],
        )

    def test_invalid_backup_has_no_completion_marker(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        file = self.root / "tenants" / ("a" * 32) / "club.sqlite"
        with storage.open_db(file) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute(
                "INSERT INTO previews VALUES('invalid',999999,0,'{}',9999999999)"
            )
        with self.assertRaisesRegex(ValueError, "Datenbank beschädigt"):
            backup_platform(self.app)
        self.assertEqual(
            list((self.root / "backups").glob("*/complete.json")), []
        )
        self.assertTrue(file.is_file())

    def test_invalid_backup_manifest_is_rejected_before_restore(self):
        snapshot = backup_platform(self.app)
        original = json.loads((snapshot / "complete.json").read_text())
        destination = create_platform(
            dict(DATA_ROOT=str(self.root / "restore-invalid"), TESTING=True)
        )
        target = self.root / "restore-invalid" / "platform.sqlite"
        before = target.read_bytes()
        for manifest in (
            [],
            {**original, "files": []},
            {**original, "files": {"platform.sqlite": 123}},
            {**original, "clubs": ["a" * 32, "a" * 32]},
        ):
            with self.subTest(manifest=manifest):
                (snapshot / "complete.json").write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    restore_backup(destination, snapshot)
                self.assertEqual(target.read_bytes(), before)
                self.assertFalse((target.parent / "tenants").exists())

    def test_missing_restore_tables_rejected_before_destination_changes(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        snapshot = backup_platform(self.app)
        name = "tenants/" + "a" * 32 + "/club.sqlite"
        with storage.open_db(snapshot / name) as db:
            db.execute("DROP TABLE previews")
        manifest = json.loads((snapshot / "complete.json").read_text())
        manifest["files"][name] = file_digest(snapshot / name)
        (snapshot / "complete.json").write_text(json.dumps(manifest))
        destination = create_platform(
            dict(DATA_ROOT=str(self.root / "restore-schema"), TESTING=True)
        )
        with self.assertRaisesRegex(ValueError, "Tabellen fehlen"):
            restore_backup(destination, snapshot)
        self.assertFalse((self.root / "restore-schema" / "tenants").exists())
        with destination.extensions["registry"]() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM clubs").fetchone()[0], 0
            )

    def test_missing_billing_column_rejected_before_registry_replacement(self):
        snapshot = backup_platform(self.app)
        file = snapshot / "platform.sqlite"
        with storage.open_db(file) as db:
            db.execute("ALTER TABLE clubs DROP COLUMN subscription")
        manifest = json.loads((snapshot / "complete.json").read_text())
        manifest["files"]["platform.sqlite"] = file_digest(file)
        (snapshot / "complete.json").write_text(json.dumps(manifest))
        destination = create_platform(
            dict(DATA_ROOT=str(self.root / "restore-columns"), TESTING=True)
        )
        target = self.root / "restore-columns" / "platform.sqlite"
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "Spalten fehlen"):
            restore_backup(destination, snapshot)
        self.assertEqual(target.read_bytes(), before)
        with destination.extensions["registry"]() as db:
            self.assertIn(
                "subscription",
                {row[1] for row in db.execute("PRAGMA table_info(clubs)")},
            )

    def test_verified_restore_and_corruption_detection(self):
        self.seed("club-one", "a" * 32)
        self.client.post(
            "/v/club-one/api/login",
            json=dict(username="admin", password="test-password-123"),
            headers=self.origin,
        )
        with storage.open_db(
            self.root / "tenants" / ("a" * 32) / "club.sqlite"
        ) as db:
            db.execute(
                "INSERT INTO players(name,created) VALUES(?,?)",
                ("Restored Player", time.time()),
            )
        snapshot = backup_platform(self.app)
        self.assertEqual(verify_backup(snapshot), ["a" * 32])
        restored = create_platform(
            dict(DATA_ROOT=str(self.root / "restored"), TESTING=True)
        )
        restore_backup(restored, snapshot)
        with storage.open_db(
            self.root / "restored" / "tenants" / ("a" * 32) / "club.sqlite"
        ) as db:
            self.assertEqual(
                db.execute("SELECT name FROM players").fetchone()[0],
                "Restored Player",
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 0
            )
        with self.assertRaises(ValueError):
            restore_backup(restored, snapshot)
        with open(snapshot / "platform.sqlite", "ab") as file:
            file.write(b"corrupted")
        with self.assertRaises(ValueError):
            verify_backup(snapshot)

    @patch("vereinswertung.billing.request")
    def test_subscription_update_and_sync_reject_wrong_club_response(
        self, mock
    ):
        self.seed("club-one", "a" * 32, "suspended")
        with self.registry() as db:
            db.execute(
                "UPDATE clubs SET subscription='sub_test',customer='cus_test'"
            )
        valid = dict(
            status="active",
            customer="cus_test",
            metadata=dict(club_id="a" * 32),
        )
        for response in (
            [],
            {**valid, "metadata": []},
            {**valid, "customer": "cus_other"},
            {**valid, "metadata": dict(club_id="b" * 32)},
            {**valid, "status": None},
        ):
            with self.subTest(response=response):
                mock.return_value = response
                with self.assertRaises(ValueError):
                    self.app.extensions["sync_billing"]()
                result = self.event(
                    dict(
                        id="evt_invalid_response",
                        created=10,
                        type="customer.subscription.updated",
                        data=dict(object=dict(id="sub_test")),
                    )
                )
                self.assertEqual(result.status_code, 400)
                with self.registry() as db:
                    self.assertEqual(
                        db.execute("SELECT status FROM clubs").fetchone()[0],
                        "suspended",
                    )
                    self.assertEqual(
                        db.execute("SELECT COUNT(*) FROM events").fetchone()[0],
                        0,
                    )
        mock.return_value = valid
        result = self.event(
            dict(
                id="evt_valid_response",
                created=11,
                type="customer.subscription.updated",
                data=dict(object=dict(id="sub_test")),
            )
        )
        self.assertEqual(result.status_code, 200)
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT status FROM clubs").fetchone()[0], "active"
            )

    @patch("vereinswertung.billing.request")
    def test_reconcile_missed_cancellation(self, mock):
        self.seed("club-one", "a" * 32)
        with self.registry() as db:
            db.execute(
                'UPDATE clubs SET subscription="sub_test",customer="cus_test"'
            )
        mock.return_value = dict(
            status="canceled",
            customer="cus_test",
            metadata={"club_id": "a" * 32},
        )
        self.assertEqual(self.app.extensions["sync_billing"](), 1)
        with self.registry() as db:
            self.assertEqual(
                db.execute("SELECT status FROM clubs").fetchone()[0],
                "suspended",
            )

    @patch("vereinswertung.billing.request")
    def test_unrelated_subscription_is_not_retrieved(self, mock):
        event = dict(
            id="evt_other",
            created=10,
            type="customer.subscription.updated",
            data=dict(object=dict(id="sub_other")),
        )
        self.assertEqual(self.event(event).status_code, 200)
        mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
