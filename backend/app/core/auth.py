"""Google OIDC sign-in and the session JWT the frontend sends as a bearer token.

The browser navigates to this API to start the Authorization Code flow with
PKCE. The state, nonce, and code_verifier live in a short-lived cookie on the
API host (SameSite=Lax). That cookie is first-party during the redirect from
Google back to the API, so it is not a third-party cookie.

The user session is not that cookie. The API and the shelf are different
sites, and a cookie set here would not be sent on the shelf's fetch calls.
After the ID token checks out, the API redirects to the frontend with a
signed JWT in the URL fragment. The shelf stores it and sends
Authorization: Bearer.
"""

import time
from typing import Any, Optional
from uuid import UUID

from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

_bearer = HTTPBearer(auto_error=False)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url=GOOGLE_DISCOVERY_URL,
    client_kwargs={
        "scope": "openid email profile",
        "code_challenge_method": "S256",
    },
)


def _session_key() -> str:
    if not settings.SESSION_SECRET:
        raise HTTPException(status_code=500, detail="SESSION_SECRET is not set")
    return settings.SESSION_SECRET


def encode_session(user: User) -> str:
    now = int(time.time())
    token = jwt.encode(
        {"alg": "HS256"},
        {
            "sub": str(user.id),
            "email": user.email,
            "name": user.name,
            "picture": user.picture,
            "iat": now,
            "exp": now + SESSION_TTL_SECONDS,
        },
        _session_key(),
    )
    if isinstance(token, bytes):
        return token.decode()
    return token


def decode_session(token: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, _session_key())
        claims.validate()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return dict(claims)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    claims = decode_session(credentials.credentials)
    try:
        user_id = UUID(claims["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Not authenticated")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
