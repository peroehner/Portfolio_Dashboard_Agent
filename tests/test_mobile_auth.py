"""Tests for mobile JWT auth and Google id_token exchange."""

import os
import unittest
from unittest.mock import MagicMock, patch

from services import mobile_auth_service as mas


class MobileAuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env = os.environ.copy()
        os.environ["SESSION_SECRET"] = "test-secret-for-mobile-jwt"
        os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "web-client.apps.googleusercontent.com"
        os.environ["GOOGLE_OAUTH_IOS_CLIENT_ID"] = "ios-client.apps.googleusercontent.com"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env)

    def test_jwt_roundtrip(self) -> None:
        token, ttl = mas.issue_access_token(42, "user@example.com")
        self.assertGreater(ttl, 0)
        self.assertEqual(mas.user_id_from_access_token(token), 42)
        self.assertIsNone(mas.user_id_from_access_token("not-a-jwt"))

    def test_jwt_rejects_wrong_typ(self) -> None:
        import time

        import jwt

        bad = jwt.encode(
            {"sub": "1", "typ": "other", "exp": int(time.time()) + 3600},
            "test-secret-for-mobile-jwt",
            algorithm="HS256",
        )
        self.assertIsNone(mas.user_id_from_access_token(bad))

    @patch("services.mobile_auth_service.requests.get")
    def test_verify_google_id_token_audience(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "aud": "ios-client.apps.googleusercontent.com",
                "sub": "google-sub-1",
                "email": "tester@example.com",
                "email_verified": "true",
            },
        )
        claims = mas.verify_google_id_token("fake-id-token")
        self.assertEqual(claims["email"], "tester@example.com")

    @patch("services.mobile_auth_service.requests.get")
    def test_verify_rejects_bad_audience(self, mock_get: MagicMock) -> None:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "aud": "unknown-client.apps.googleusercontent.com",
                "sub": "google-sub-1",
                "email": "tester@example.com",
                "email_verified": "true",
            },
        )
        with self.assertRaises(ValueError):
            mas.verify_google_id_token("fake-id-token")

    @patch("services.mobile_auth_service.get_or_create_user")
    @patch("services.mobile_auth_service.verify_google_id_token")
    @patch("auth._email_allowed", return_value=True)
    def test_exchange_returns_access_token(
        self,
        _allowed: MagicMock,
        mock_verify: MagicMock,
        mock_upsert: MagicMock,
    ) -> None:
        mock_verify.return_value = {
            "sub": "google-sub-1",
            "email": "tester@example.com",
            "name": "Tester",
            "picture": "https://example.com/p.png",
        }
        mock_upsert.return_value = {
            "id": 7,
            "email": "tester@example.com",
            "name": "Tester",
            "picture": "https://example.com/p.png",
            "plan": "free",
        }
        result = mas.exchange_google_id_token("id-token")
        self.assertIn("accessToken", result)
        self.assertEqual(result["user"]["id"], 7)
        self.assertEqual(mas.user_id_from_access_token(result["accessToken"]), 7)


if __name__ == "__main__":
    unittest.main()
