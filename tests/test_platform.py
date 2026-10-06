import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from club_platform import create_platform
from platform_manage import (
    backup_platform,
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
        with storage.open_db(source) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1
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
                'UPDATE clubs SET subscription="sub_test" WHERE slug="club-one"'
            )
        mock.return_value = dict(status="canceled")
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
