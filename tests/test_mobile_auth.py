"""Tests for mobile Google session issuance helpers."""

import unittest
from unittest.mock import patch

from auth import _accepted_google_audiences, verify_google_id_token


class MobileAuthAudienceTests(unittest.TestCase):
    def test_accepted_audiences_include_web_and_mobile_ids(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "GOOGLE_OAUTH_CLIENT_ID": "web-client.apps.googleusercontent.com",
                "GOOGLE_MOBILE_IOS_CLIENT_ID": "ios-client.apps.googleusercontent.com",
                "GOOGLE_MOBILE_CLIENT_IDS": "extra-a.apps.googleusercontent.com, extra-b.apps.googleusercontent.com",
            },
            clear=False,
        ):
            # Re-import audience helper reads env at call time.
            audiences = _accepted_google_audiences()
        self.assertIn("web-client.apps.googleusercontent.com", audiences)
        self.assertIn("ios-client.apps.googleusercontent.com", audiences)
        self.assertIn("extra-a.apps.googleusercontent.com", audiences)
        self.assertIn("extra-b.apps.googleusercontent.com", audiences)

    def test_verify_rejects_bad_audience(self) -> None:
        class FakeResp:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "aud": "wrong-client",
                    "sub": "123",
                    "email": "a@example.com",
                    "email_verified": "true",
                }

        with patch.dict(
            "os.environ",
            {"GOOGLE_OAUTH_CLIENT_ID": "web-client.apps.googleusercontent.com"},
            clear=False,
        ), patch("auth.requests.get", return_value=FakeResp()):
            with self.assertRaises(ValueError):
                verify_google_id_token("fake-token")


if __name__ == "__main__":
    unittest.main()
