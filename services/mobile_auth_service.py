"""Mobile Google Sign-In → JWT access tokens (per-user API auth).

Web uses Flask sessions; mobile uses Bearer JWT after verifying a Google id_token.
See docs/MOBILE.md.
"""

from __future__ import annotations

import os
import time
from typing import Any

import jwt
import requests

from db.database import get_or_create_user

JWT_ALGORITHM = "HS256"
JWT_TYP = "mobile_access"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


def _jwt_secret() -> str:
    secret = (
        os.environ.get("SESSION_SECRET")
        or os.environ.get("SECRET_KEY")
        or ""
    ).strip()
    if not secret:
        raise RuntimeError("SESSION_SECRET (or SECRET_KEY) is required for mobile JWT auth.")
    return secret


def jwt_ttl_seconds() -> int:
    raw = os.environ.get("MOBILE_JWT_TTL_SECONDS", "").strip()
    if raw:
        try:
            return max(300, int(raw))
        except ValueError:
            pass
    return DEFAULT_TTL_SECONDS


def google_client_ids() -> set[str]:
    """OAuth client IDs whose id_token ``aud`` we accept (web + iOS + extras)."""
    ids: set[str] = set()
    for key in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_IOS_CLIENT_ID",
        "GOOGLE_OAUTH_ANDROID_CLIENT_ID",
    ):
        value = os.environ.get(key, "").strip()
        if value:
            ids.add(value)
    extras = os.environ.get("GOOGLE_OAUTH_CLIENT_IDS", "").strip()
    if extras:
        ids.update(part.strip() for part in extras.split(",") if part.strip())
    return ids


def issue_access_token(user_id: int, email: str | None) -> tuple[str, int]:
    ttl = jwt_ttl_seconds()
    now = int(time.time())
    payload = {
        "typ": JWT_TYP,
        "sub": str(user_id),
        "email": (email or "").lower() or None,
        "iat": now,
        "exp": now + ttl,
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return token, ttl


def user_id_from_access_token(token: str) -> int | None:
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != JWT_TYP:
        return None
    try:
        return int(payload["sub"])
    except (TypeError, ValueError, KeyError):
        return None


def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """Validate a Google OIDC id_token via Google's tokeninfo endpoint."""
    token = (id_token or "").strip()
    if not token:
        raise ValueError("idToken is required.")

    allowed = google_client_ids()
    if not allowed:
        raise RuntimeError(
            "Google OAuth client IDs are not configured (GOOGLE_OAUTH_CLIENT_ID / IOS / …)."
        )

    resp = requests.get(
        "https://oauth2.googleapis.com/tokeninfo",
        params={"id_token": token},
        timeout=15,
    )
    if resp.status_code != 200:
        raise ValueError("Invalid or expired Google sign-in token.")

    data: dict[str, Any] = resp.json()
    aud = str(data.get("aud") or "")
    if aud not in allowed:
        raise ValueError("Google token audience is not allowed for this app.")

    email_verified = data.get("email_verified")
    if str(email_verified).lower() not in ("true", "1") and email_verified is not True:
        raise ValueError("Google account email is not verified.")

    if not data.get("sub"):
        raise ValueError("Google token missing subject.")

    return data


def exchange_google_id_token(id_token: str) -> dict[str, Any]:
    """Verify Google token, upsert user, return API access token + profile."""
    from auth import _email_allowed

    claims = verify_google_id_token(id_token)
    email = str(claims.get("email") or "").strip()
    if not _email_allowed(email):
        raise PermissionError(f"Access denied for {email or 'unknown'}.")

    user = get_or_create_user(
        str(claims["sub"]),
        email or None,
        claims.get("name"),
        claims.get("picture"),
    )
    access_token, expires_in = issue_access_token(int(user["id"]), email)
    return {
        "accessToken": access_token,
        "expiresIn": expires_in,
        "tokenType": "Bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name"),
            "picture": user.get("picture"),
            "plan": user.get("plan"),
        },
    }
