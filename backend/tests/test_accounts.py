"""Per-user shelves and the Google OIDC callback.

Needs DATABASE_URL (default below) and skips when that Postgres is down.
Google's token and JWKS endpoints are a local stand-in, not accounts.google.com.
There is no dev login in the app.
"""

import json
import os
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

os.environ["DATABASE_URL"] = os.environ.get(
    "AUTH_DATABASE_URL",
    "postgresql+asyncpg://discvault:discvault@127.0.0.1:5432/discvault_auth_test",
)
os.environ["ENCRYPTION_SECRET"] = Fernet.generate_key().decode()
os.environ["SESSION_SECRET"] = "test-session-secret-for-auth-only"
os.environ["GOOGLE_CLIENT_ID"] = "test-client"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"
os.environ["FRONTEND_PUBLIC_URL"] = "http://localhost:3000"
os.environ["BACKEND_PUBLIC_URL"] = "http://127.0.0.1:8000"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")

from authlib.jose import jwk, jwt
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.auth import encode_session, oauth
from app.core.database import engine
from app.main import app

# The app always loads Google's discovery document. This test points that
# client at the local stand-in before any request. It is not an app setting.
oauth.google._server_metadata_url = (
    "http://127.0.0.1:8765/.well-known/openid-configuration"
)

MOCK_PORT = 8765
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_JWK = jwk.dumps(_PRIVATE_KEY.public_key(), kty="RSA")
_PUBLIC_JWK.update({"kid": "test-key", "use": "sig", "alg": "RS256"})


class _GoogleState:
    nonce = None
    token_form = ""
    aud = "test-client"
    sub = "google-sub-ada"
    name = "Ada Lovelace"
    email = "ada@example.com"
    picture = "https://example.com/ada.png"


def _id_token() -> str:
    import time

    now = int(time.time())
    payload = {
        "iss": "https://accounts.google.com",
        "aud": _GoogleState.aud,
        "sub": _GoogleState.sub,
        "email": _GoogleState.email,
        "name": _GoogleState.name,
        "picture": _GoogleState.picture,
        "nonce": _GoogleState.nonce,
        "iat": now,
        "exp": now + 300,
    }
    token = jwt.encode({"alg": "RS256", "kid": "test-key"}, payload, _PRIVATE_KEY)
    return token.decode() if isinstance(token, bytes) else token


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/.well-known/openid-configuration":
            body = {
                "issuer": "https://accounts.google.com",
                "authorization_endpoint": f"http://127.0.0.1:{MOCK_PORT}/authorize",
                "token_endpoint": f"http://127.0.0.1:{MOCK_PORT}/token",
                "jwks_uri": f"http://127.0.0.1:{MOCK_PORT}/jwks",
                "id_token_signing_alg_values_supported": ["RS256"],
            }
            self._json(body)
            return
        if path == "/jwks":
            self._json({"keys": [_PUBLIC_JWK]})
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode()
        _GoogleState.token_form = raw
        body = {
            "access_token": "mock-access",
            "token_type": "Bearer",
            "expires_in": 3600,
            "id_token": _id_token(),
        }
        self._json(body)

    def _json(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class AccountTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", MOCK_PORT), _Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    async def asyncSetUp(self):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            self.skipTest(f"Postgres is not reachable: {exc}")

        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS cds"))
            await conn.execute(text("DROP TABLE IF EXISTS app_settings"))
            await conn.execute(text("DROP TABLE IF EXISTS users"))
            await conn.execute(
                text(
                    """
                    CREATE TABLE users (
                        id UUID PRIMARY KEY,
                        google_sub VARCHAR(255) NOT NULL UNIQUE,
                        email VARCHAR(320),
                        name VARCHAR(255),
                        picture TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE cds (
                        id UUID PRIMARY KEY,
                        user_id UUID REFERENCES users(id) ON DELETE CASCADE,
                        artist VARCHAR(255) NOT NULL,
                        album_name VARCHAR(255) NOT NULL,
                        lyricist VARCHAR(255),
                        genre VARCHAR(100) NOT NULL,
                        num_discs INTEGER NOT NULL DEFAULT 1,
                        cover_art_url TEXT,
                        release_year INTEGER,
                        ai_summary TEXT,
                        ai_sources JSONB,
                        embedding TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX uq_artist_album_lowercase
                    ON cds (user_id, LOWER(artist), LOWER(album_name))
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE app_settings (
                        key_name VARCHAR(100) PRIMARY KEY,
                        encrypted_value VARCHAR NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
            )
        _GoogleState.aud = "test-client"
        _GoogleState.sub = "google-sub-ada"
        _GoogleState.name = "Ada Lovelace"
        _GoogleState.email = "ada@example.com"
        _GoogleState.nonce = None
        _GoogleState.token_form = ""

    async def asyncTearDown(self):
        await engine.dispose()

    def _client(self):
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    async def _insert_user(self, google_sub: str, email: str, name: str):
        user_id = uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO users (id, google_sub, email, name)
                    VALUES (:id, :sub, :email, :name)
                    """
                ),
                {"id": user_id, "sub": google_sub, "email": email, "name": name},
            )
        return user_id

    def _token(self, user_id, email, name):
        class _User:
            pass

        user = _User()
        user.id = user_id
        user.email = email
        user.name = name
        user.picture = None
        return encode_session(user)

    async def test_unauthenticated_requests_are_401(self):
        async with self._client() as client:
            search = await client.get("/api/cds/search")
            missing = await client.get(f"/api/cds/{uuid.uuid4()}")
            upload = await client.post(
                "/api/cds/upload-csv",
                files={"file": ("collection.csv", b"artist,album_name,genre\n", "text/csv")},
            )
            enrich = await client.get(f"/api/cds/{uuid.uuid4()}/enrich-stream")
            status = await client.get("/api/settings/status")
            me = await client.get("/api/auth/me")
        for response in (search, missing, upload, enrich, status, me):
            self.assertEqual(response.status_code, 401, response.text)

    async def test_users_cannot_see_each_others_cds_and_same_album_is_two_rows(self):
        ada_id = await self._insert_user("sub-ada", "ada@example.com", "Ada")
        grace_id = await self._insert_user("sub-grace", "grace@example.com", "Grace")
        ada = {"Authorization": f"Bearer {self._token(ada_id, 'ada@example.com', 'Ada')}"}
        grace = {"Authorization": f"Bearer {self._token(grace_id, 'grace@example.com', 'Grace')}"}
        csv_body = b"artist,album_name,lyricist,genre,num_discs\nThe Beatles,Abbey Road,Lennon,Rock,1\n"

        async with self._client() as client:
            ada_upload = await client.post(
                "/api/cds/upload-csv",
                files={"file": ("collection.csv", csv_body, "text/csv")},
                headers=ada,
            )
            grace_upload = await client.post(
                "/api/cds/upload-csv",
                files={"file": ("collection.csv", csv_body, "text/csv")},
                headers=grace,
            )
            self.assertEqual(ada_upload.status_code, 200, ada_upload.text)
            self.assertEqual(grace_upload.status_code, 200, grace_upload.text)
            self.assertEqual(ada_upload.json()["inserted"], 1)
            self.assertEqual(grace_upload.json()["inserted"], 1)

            ada_search = await client.get("/api/cds/search", headers=ada)
            grace_search = await client.get("/api/cds/search", headers=grace)
            self.assertEqual(ada_search.status_code, 200)
            self.assertEqual(len(ada_search.json()["cds"]), 1)
            self.assertEqual(len(grace_search.json()["cds"]), 1)
            ada_cd = ada_search.json()["cds"][0]["id"]
            grace_cd = grace_search.json()["cds"][0]["id"]
            self.assertNotEqual(ada_cd, grace_cd)

            stolen = await client.get(f"/api/cds/{grace_cd}", headers=ada)
            stolen_stream = await client.get(f"/api/cds/{grace_cd}/enrich-stream", headers=ada)
            own = await client.get(f"/api/cds/{ada_cd}", headers=ada)
            self.assertEqual(stolen.status_code, 404)
            self.assertEqual(stolen_stream.status_code, 404)
            self.assertEqual(own.status_code, 200)
            self.assertEqual(own.json()["album_name"], "Abbey Road")

        async with engine.connect() as conn:
            count = await conn.execute(text("SELECT count(*) FROM cds"))
            self.assertEqual(count.scalar(), 2)

    async def test_google_callback_verifies_id_token_and_reuses_sub(self):
        async with self._client() as client:
            start = await client.get("/api/auth/google", follow_redirects=False)
            self.assertEqual(start.status_code, 302)
            location = urlparse(start.headers["location"])
            query = parse_qs(location.query)
            self.assertEqual(query["code_challenge_method"], ["S256"])
            self.assertIn("code_challenge", query)
            _GoogleState.nonce = query["nonce"][0]
            state = query["state"][0]

            callback = await client.get(
                "/api/auth/callback",
                params={"code": "auth-code", "state": state},
                follow_redirects=False,
            )
            self.assertEqual(callback.status_code, 302, callback.text)
            self.assertIn("code_verifier=", _GoogleState.token_form)
            landed = urlparse(callback.headers["location"])
            self.assertEqual(landed.path, "/auth/callback")
            token = parse_qs(landed.fragment)["token"][0]

            me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            self.assertEqual(me.status_code, 200)
            self.assertEqual(me.json()["email"], "ada@example.com")
            self.assertEqual(me.json()["name"], "Ada Lovelace")
            first_id = me.json()["id"]

            _GoogleState.name = "Ada King"
            again = await client.get("/api/auth/google", follow_redirects=False)
            again_query = parse_qs(urlparse(again.headers["location"]).query)
            _GoogleState.nonce = again_query["nonce"][0]
            second = await client.get(
                "/api/auth/callback",
                params={"code": "auth-code-2", "state": again_query["state"][0]},
                follow_redirects=False,
            )
            second_token = parse_qs(urlparse(second.headers["location"]).fragment)["token"][0]
            me_again = await client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {second_token}"},
            )
            self.assertEqual(me_again.json()["id"], first_id)
            self.assertEqual(me_again.json()["name"], "Ada King")

            _GoogleState.aud = "someone-else"
            bad_start = await client.get("/api/auth/google", follow_redirects=False)
            bad_query = parse_qs(urlparse(bad_start.headers["location"]).query)
            _GoogleState.nonce = bad_query["nonce"][0]
            rejected = await client.get(
                "/api/auth/callback",
                params={"code": "bad", "state": bad_query["state"][0]},
                follow_redirects=False,
            )
            self.assertIn("/login?error=google", rejected.headers["location"])

        async with engine.connect() as conn:
            count = await conn.execute(text("SELECT count(*) FROM users"))
            self.assertEqual(count.scalar(), 1)


if __name__ == "__main__":
    unittest.main()
