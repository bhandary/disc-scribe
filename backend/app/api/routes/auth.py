from authlib.integrations.base_client import OAuthError
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from app.core.auth import GOOGLE_ISSUER, encode_session, get_current_user, oauth
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _login_error(reason: str) -> RedirectResponse:
    url = settings.FRONTEND_PUBLIC_URL.rstrip("/") + "/login?error=" + reason
    return RedirectResponse(url, status_code=302)


@router.get("/google")
async def google_login(request: Request):
    """Start the Authorization Code flow with PKCE. Authlib stores state, nonce, and the verifier."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        return _login_error("config")
    if not settings.SESSION_SECRET:
        return _login_error("config")
    return await oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Exchange the code, verify the ID token, and hand the shelf a session JWT."""
    if request.query_params.get("error"):
        return _login_error("google")

    # Authlib checks the state cookie, sends the PKCE verifier, and verifies the
    # ID token signature against the discovery jwks_uri. CodeIDToken then checks
    # iss, aud (the client id), exp, iat, and nonce. claims_options pins iss to
    # Google even if a test discovery document is hosted somewhere else.
    try:
        token = await oauth.google.authorize_access_token(
            request,
            claims_options={"iss": {"essential": True, "values": [GOOGLE_ISSUER]}},
        )
    except (OAuthError, Exception):
        return _login_error("google")

    claims = token.get("userinfo") or {}
    audience = claims.get("aud")
    if isinstance(audience, list):
        audience_ok = settings.GOOGLE_CLIENT_ID in audience
    else:
        audience_ok = audience == settings.GOOGLE_CLIENT_ID
    if (
        claims.get("iss") != GOOGLE_ISSUER
        or not audience_ok
        or not claims.get("sub")
        or "exp" not in claims
    ):
        return _login_error("google")

    result = await db.execute(select(User).where(User.google_sub == claims["sub"]))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            google_sub=claims["sub"],
            email=claims.get("email"),
            name=claims.get("name"),
            picture=claims.get("picture"),
        )
        db.add(user)
    else:
        if claims.get("email"):
            user.email = claims["email"]
        if claims.get("name"):
            user.name = claims["name"]
        if claims.get("picture"):
            user.picture = claims["picture"]
    await db.commit()
    await db.refresh(user)

    session = encode_session(user)
    # Fragment, not a query string: the token is not sent to the frontend server
    # and is not attached as a Referer.
    target = settings.frontend_callback_url + "#token=" + session
    return RedirectResponse(target, status_code=302)


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
    }
