import asyncio
import bcrypt
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server
from fastapi import HTTPException


class FakeUsersCollection:
    def __init__(self, user=None):
        self.user = user

    async def find_one(self, query):
        if self.user and self.user["_id"] == query.get("_id"):
            return self.user
        return None

    async def insert_one(self, user):
        self.user = user

    async def delete_one(self, query):
        if self.user and self.user["_id"] == query.get("_id"):
            self.user = None

    async def update_one(self, query, update):
        if (
            not self.user
            or self.user["_id"] != query["_id"]
            or self.user["password_hash"] != query["password_hash"]
        ):
            return SimpleNamespace(matched_count=0)
        self.user.update(update["$set"])
        for field in update["$unset"]:
            self.user.pop(field, None)
        return SimpleNamespace(matched_count=1)


class FakeCompaniesCollection:
    def __init__(self):
        self.companies = []

    async def find_one(self, query):
        if "cnpj" in query:
            return next((company for company in self.companies if company["cnpj"] == query["cnpj"]), None)
        criteria = query.get("$or", [])
        return next(
            (
                company
                for company in self.companies
                if any(
                    company.get(key) == value
                    for criterion in criteria
                    for key, value in criterion.items()
                )
            ),
            None,
        )

    async def insert_one(self, company):
        self.companies.append(company)

    async def delete_one(self, query):
        self.companies = [
            company for company in self.companies if company["cnpj"] != query["cnpj"]
        ]

    async def update_one(self, query, update):
        company = await self.find_one(query)
        if company:
            company.update(update["$set"])


class FakeSettingsCollection:
    async def update_one(self, query, update, upsert=False):
        return None


class FakeTenantDatabase:
    def __init__(self, users):
        self.users = users
        self.settings = FakeSettingsCollection()


class FakeRegistry:
    def __init__(self):
        self.companies = FakeCompaniesCollection()


class FakeClient:
    def __init__(self, tenant):
        self.tenant = tenant

    def __getitem__(self, _name):
        return self.tenant


class CompanyPasswordTests(unittest.TestCase):
    def test_registration_generates_a_temporary_password_without_smtp(self):
        users = FakeUsersCollection()
        tenant = FakeTenantDatabase(users)
        registry = FakeRegistry()
        request = SimpleNamespace(headers={"X-Setup-Secret": "setup-secret"})
        registration = server.CompanyRegistrationInput(
            cnpj="12345678000199",
            store_name="Loja de teste",
            email="owner@example.com",
        )

        with (
            patch.object(server, "PLATFORM_SETUP_SECRET", "setup-secret"),
            patch.object(server, "registry_db", registry),
            patch.object(server, "client", FakeClient(tenant)),
        ):
            result = asyncio.run(server.register_company(registration, request))

        self.assertGreaterEqual(len(result["temporary_password"]), 12)
        self.assertTrue(
            bcrypt.checkpw(
                result["temporary_password"].encode(),
                users.user["password_hash"].encode(),
            )
        )
        self.assertTrue(users.user["password_change_required"])
        self.assertNotIn("temporary_password", users.user)
        self.assertTrue(registry.companies.companies[0]["owner_password_change_pending"])

    def test_password_change_removes_first_login_requirement(self):
        old_password = "TemporaryPassword123"
        user = {
            "_id": "admin-1",
            "role": "admin",
            "password_hash": bcrypt.hashpw(old_password.encode(), bcrypt.gensalt()).decode(),
            "password_change_required": True,
        }
        users = FakeUsersCollection(user)
        tenant = FakeTenantDatabase(users)
        registry = FakeRegistry()
        registry.companies.companies.append(
            {"cnpj": "12345678000199", "owner_password_change_pending": True}
        )
        db_context = server.tenant_db.set(tenant)
        cnpj_context = server.tenant_cnpj.set("12345678000199")
        try:
            with patch.object(server, "registry_db", registry):
                result = asyncio.run(
                    server.change_password(
                        server.PasswordChangeInput(
                            current_password=old_password,
                            new_password="A-new-secure-password-2026",
                        ),
                        user,
                    )
                )
        finally:
            server.tenant_db.reset(db_context)
            server.tenant_cnpj.reset(cnpj_context)

        self.assertEqual(result, {"ok": True})
        self.assertTrue(
            bcrypt.checkpw(
                b"A-new-secure-password-2026",
                users.user["password_hash"].encode(),
            )
        )
        self.assertNotIn("password_change_required", users.user)
        self.assertFalse(registry.companies.companies[0]["owner_password_change_pending"])

    def test_password_change_rejects_an_incorrect_current_password(self):
        user = {
            "_id": "admin-1",
            "role": "staff",
            "password_hash": bcrypt.hashpw(b"Current-password-123", bcrypt.gensalt()).decode(),
        }
        users = FakeUsersCollection(user)
        db_context = server.tenant_db.set(FakeTenantDatabase(users))
        try:
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    server.change_password(
                        server.PasswordChangeInput(
                            current_password="incorrect-password",
                            new_password="A-new-secure-password-2026",
                        ),
                        user,
                    )
                )
        finally:
            server.tenant_db.reset(db_context)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(
            bcrypt.checkpw(
                b"Current-password-123",
                users.user["password_hash"].encode(),
            )
        )

    def test_password_change_requires_at_least_twelve_characters(self):
        with self.assertRaises(ValueError):
            server.PasswordChangeInput(
                current_password="current-password",
                new_password="Too-short",
            )

    def test_temporary_password_is_random_and_long_enough(self):
        first = server.new_temporary_password()
        second = server.new_temporary_password()

        self.assertGreaterEqual(len(first), 12)
        self.assertNotEqual(first, second)

    def test_temporary_password_user_cannot_access_admin_routes(self):
        user = {
            "_id": "admin-1",
            "role": "admin",
            "password_change_required": True,
        }
        tenant = FakeTenantDatabase(FakeUsersCollection(user))
        db_context = server.tenant_db.set(tenant)
        cnpj_context = server.tenant_cnpj.set("12345678000199")
        request = SimpleNamespace(
            cookies={"access_token": "session-token"},
            headers={},
            url=SimpleNamespace(path="/api/admin/products"),
        )
        try:
            with patch.object(
                server.jwt,
                "decode",
                return_value={
                    "scope": "tenant",
                    "cnpj": "12345678000199",
                    "sub": "admin-1",
                },
            ):
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(server.current_user(request))
        finally:
            server.tenant_db.reset(db_context)
            server.tenant_cnpj.reset(cnpj_context)

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
