import asyncio
import bcrypt
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import server
from fastapi import HTTPException


class FakeTokenCollection:
    def __init__(self, record):
        self.record = record

    async def find_one_and_delete(self, query):
        if (
            self.record
            and self.record["token_hash"] == query["token_hash"]
            and self.record["expires_at"] > query["expires_at"]["$gt"]
        ):
            record = self.record
            self.record = None
            return record
        return None


class FakeUsersCollection:
    def __init__(self, user):
        self.user = user

    async def update_one(self, query, update):
        if (
            self.user["_id"] != query["_id"]
            or self.user["role"] != query["role"]
            or "password_hash" in self.user
        ):
            return type("UpdateResult", (), {"matched_count": 0})()
        self.user.update(update["$set"])
        for field in update["$unset"]:
            self.user.pop(field, None)
        return type("UpdateResult", (), {"matched_count": 1})()


class FakeCompaniesCollection:
    def __init__(self):
        self.company = {"cnpj": "12345678000199", "owner_setup_pending": True}

    async def update_one(self, query, update):
        if query["cnpj"] == self.company["cnpj"]:
            self.company.update(update["$set"])


class FakeTenantDatabase:
    def __init__(self, token_collection, users_collection):
        self.password_setup_tokens = token_collection
        self.users = users_collection


class PasswordSetupTests(unittest.TestCase):
    def setUp(self):
        self.raw_token = "A" * 43
        self.token_hash = server.hashlib.sha256(self.raw_token.encode()).hexdigest()
        self.user = {"_id": "owner-1", "role": "admin", "setup_pending": True}
        self.tokens = FakeTokenCollection(
            {
                "user_id": self.user["_id"],
                "token_hash": self.token_hash,
                "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            }
        )
        self.users = FakeUsersCollection(self.user)
        self.companies = FakeCompaniesCollection()
        tenant = FakeTenantDatabase(self.tokens, self.users)
        self.tenant_context = server.tenant_db.set(tenant)
        self.cnpj_context = server.tenant_cnpj.set("12345678000199")
        self.registry_patch = patch.object(
            server,
            "registry_db",
            type("FakeRegistry", (), {"companies": self.companies})(),
        )
        self.registry_patch.start()

    def tearDown(self):
        self.registry_patch.stop()
        server.tenant_db.reset(self.tenant_context)
        server.tenant_cnpj.reset(self.cnpj_context)

    def test_password_is_set_and_invitation_is_single_use(self):
        asyncio.run(
            server.setup_company_password(
                server.PasswordSetupInput(token=self.raw_token, password="A-secure-demo-password")
            )
        )

        self.assertTrue(
            bcrypt.checkpw(
                b"A-secure-demo-password",
                self.user["password_hash"].encode(),
            )
        )
        self.assertNotIn("setup_pending", self.user)
        self.assertFalse(self.companies.company["owner_setup_pending"])
        self.assertIsNone(self.tokens.record)

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                server.setup_company_password(
                    server.PasswordSetupInput(token=self.raw_token, password="Another-secure-password")
                )
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_expired_invitation_cannot_set_password(self):
        self.tokens.record["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

        with self.assertRaises(HTTPException) as raised:
            asyncio.run(
                server.setup_company_password(
                    server.PasswordSetupInput(token=self.raw_token, password="A-secure-demo-password")
                )
            )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertNotIn("password_hash", self.user)

    def test_setup_password_requires_twelve_characters(self):
        with self.assertRaises(ValueError):
            server.PasswordSetupInput(token=self.raw_token, password="short")

    def test_invitation_email_uses_tls_and_keeps_token_in_url_fragment(self):
        patches = (
            patch.object(server, "SMTP_HOST", "smtp.example.test"),
            patch.object(server, "SMTP_PORT", 587),
            patch.object(server, "SMTP_USERNAME", "mailer"),
            patch.object(server, "SMTP_PASSWORD", "mail-secret"),
            patch.object(server, "SMTP_FROM", "Vitrine Virtual <no-reply@example.test>"),
            patch.object(server, "SMTP_USE_SSL", False),
            patch.object(server, "FRONTEND_URL", "https://shop.example.test/Loja-Virtual"),
            patch.object(server.smtplib, "SMTP"),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7] as smtp:
            server_connection = smtp.return_value.__enter__.return_value
            asyncio.run(
                server.send_password_setup_email(
                    "owner@example.test",
                    "Loja de demonstração",
                    "12345678000199",
                    self.raw_token,
                )
            )

        server_connection.starttls.assert_called_once()
        server_connection.login.assert_called_once_with("mailer", "mail-secret")
        message = server_connection.send_message.call_args.args[0]
        self.assertIn(f"#token={self.raw_token}", message.get_content())
        self.assertNotIn(self.raw_token, message["To"])

    def test_invitation_delivery_requires_smtp_configuration(self):
        with patch.object(server, "SMTP_HOST", ""):
            with self.assertRaises(HTTPException) as raised:
                server.ensure_email_delivery_configured()
        self.assertEqual(raised.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
