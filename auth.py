"""Google OAuth (OIDC) authentication — opt-in.

Auth is enabled only when GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET
are set. When they are absent the app runs in single-user mode: every request is
bound to the bootstrap user (the Phase 1b behaviour), so local development and
existing deployments keep working without any OAuth setup.

When enabled:
  - /auth/login   -> redirect to Google's consent screen
  - /auth/callback-> exchange code, upsert the user, store user_id in the session
  - /auth/logout  -> clear the session
  - /login        -> minimal "Sign in with Google" page (public)
  - all other routes require a session; API routes get 401, pages redirect to /login

An optional ALLOWED_EMAILS allowlist (comma-separated) restricts who may sign in.
"""

import os

from flask import Blueprint, g, jsonify, redirect, request, session

from db.database import (
    clear_current_user_id,
    get_bootstrap_user_id,
    get_connection,
    get_or_create_user,
    reset_current_user_id,
    set_current_user_id,
)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
AUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

# Optional local-only bearer token so the Expo simulator can call the API while
# OAuth is enabled. Set MOBILE_DEV_TOKEN in .env and the same value as
# EXPO_PUBLIC_MOBILE_DEV_TOKEN in mobile/.env. Never enable on production.
MOBILE_DEV_TOKEN = os.environ.get("MOBILE_DEV_TOKEN", "").strip()

# Optional allowlist: only these emails may sign in. Empty = any Google account.
_ALLOWED_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWED_EMAILS", "").split(",")
    if e.strip()
}

# Paths reachable without a session.
_PUBLIC_EXACT = {"/health", "/login", "/favicon.ico", "/manifest.webmanifest"}
_PUBLIC_PREFIXES = ("/auth/", "/assets/", "/docs/")

auth_bp = Blueprint("auth", __name__)
_oauth = None  # set in init_auth when enabled


def _email_allowed(email: str | None) -> bool:
    if not _ALLOWED_EMAILS:
        return True
    return bool(email) and email.lower() in _ALLOWED_EMAILS


def _redirect_uri() -> str:
    # Prefer an explicit, registered redirect URI (required to match Google's
    # console exactly, especially behind proxies/ngrok). Fall back to deriving it.
    override = os.environ.get("OAUTH_REDIRECT_URI", "").strip()
    if override:
        return override
    return request.url_root.rstrip("/") + "/auth/callback"


def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _mobile_dev_user_id() -> int:
    """Portfolio user bound to a mobile dev-token request."""
    email = (
        os.environ.get("MOBILE_DEV_USER_EMAIL", "").strip()
        or os.environ.get("AUTHOR_EMAIL", "").strip()
    ).lower()
    if email:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE lower(email) = %s",
                (email,),
            ).fetchone()
        if row:
            return int(row["id"])
    return get_bootstrap_user_id()


def _mobile_dev_token_valid() -> bool:
    if not MOBILE_DEV_TOKEN:
        return False
    auth_header = request.headers.get("Authorization", "")
    return auth_header == f"Bearer {MOBILE_DEV_TOKEN}"


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Portfolio Dashboard Agent</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1220;
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#e6edf6}
  .card{background:#121a2b;border:1px solid #1f2a40;border-radius:16px;padding:40px 36px;
        text-align:center;max-width:360px;box-shadow:0 12px 40px rgba(0,0,0,.4)}
  h1{font-size:20px;margin:0 0 6px}
  p{color:#9aa8bc;font-size:14px;margin:0 0 24px}
  a.btn{display:inline-flex;align-items:center;gap:10px;background:#fff;color:#1f2937;
        text-decoration:none;font-weight:600;font-size:15px;padding:11px 18px;border-radius:10px}
  a.btn:hover{background:#f1f3f5}
  .g{width:18px;height:18px}
</style></head>
<body><div class="card">
  <h1>Portfolio Dashboard Agent</h1>
  <p>Sign in to access your portfolio.</p>
  <a class="btn" href="/auth/login">
    <svg class="g" viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.6 30.1 0 24 0 14.6 0 6.4 5.4 2.5 13.3l7.8 6c1.9-5.6 7.1-9.8 13.7-9.8z"/><path fill="#4285F4" d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.5 3-2.2 5.5-4.7 7.2l7.3 5.7c4.3-3.9 6.8-9.7 6.8-17.4z"/><path fill="#FBBC05" d="M10.3 28.3c-.5-1.4-.8-2.9-.8-4.3s.3-3 .8-4.3l-7.8-6C.9 16.7 0 20.2 0 24s.9 7.3 2.5 10.3l7.8-6z"/><path fill="#34A853" d="M24 48c6.1 0 11.3-2 15-5.5l-7.3-5.7c-2 1.4-4.7 2.3-7.7 2.3-6.6 0-11.8-4.2-13.7-9.8l-7.8 6C6.4 42.6 14.6 48 24 48z"/></svg>
    Sign in with Google
  </a>
</div></body></html>"""


@auth_bp.route("/login")
def login_page():
    if not AUTH_ENABLED or session.get("user_id"):
        return redirect("/")
    return LOGIN_PAGE


@auth_bp.route("/auth/login")
def auth_login():
    if not AUTH_ENABLED:
        return redirect("/")
    return _oauth.google.authorize_redirect(_redirect_uri())


@auth_bp.route("/auth/callback")
def auth_callback():
    if not AUTH_ENABLED:
        return redirect("/")
    token = _oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or _oauth.google.userinfo()
    sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not sub:
        return "Authentication failed: no subject in token.", 400
    if not _email_allowed(email):
        return f"Access denied for {email}.", 403
    user = get_or_create_user(sub, email, userinfo.get("name"), userinfo.get("picture"))
    session["user_id"] = int(user["id"])
    session.permanent = True
    return redirect("/")


@auth_bp.route("/auth/logout")
def auth_logout():
    session.clear()
    return redirect("/login" if AUTH_ENABLED else "/")


def init_auth(app) -> None:
    """Configure sessions + OAuth and install the per-request auth guard."""
    app.secret_key = (
        os.environ.get("SESSION_SECRET")
        or os.environ.get("SECRET_KEY")
        or "dev-insecure-secret-change-me"
    )
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Secure cookies require HTTPS; enable in production via env. Off by
        # default so local http:// login works.
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0").lower()
        in ("1", "true", "yes"),
    )

    if AUTH_ENABLED:
        from authlib.integrations.flask_client import OAuth

        global _oauth
        _oauth = OAuth(app)
        _oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    app.register_blueprint(auth_bp)

    @app.before_request
    def _bind_current_user():
        if request.method == "OPTIONS":
            return None
        if not AUTH_ENABLED:
            # Single-user mode: everyone is the bootstrap user.
            g._user_ctx_token = set_current_user_id(get_bootstrap_user_id())
            return None
        if _is_public(request.path):
            g._user_ctx_token = None
            clear_current_user_id()
            return None
        user_id = session.get("user_id")
        if user_id is None:
            if _mobile_dev_token_valid():
                g._user_ctx_token = set_current_user_id(_mobile_dev_user_id())
                return None
            clear_current_user_id()
            if request.path.startswith("/api/"):
                return jsonify({"status": "error", "message": "Authentication required."}), 401
            return redirect("/login")
        g._user_ctx_token = set_current_user_id(int(user_id))
        return None

    @app.teardown_request
    def _unbind_current_user(_exc):
        token = getattr(g, "_user_ctx_token", None)
        if token is not None:
            reset_current_user_id(token)
        elif AUTH_ENABLED:
            clear_current_user_id()
        return None
