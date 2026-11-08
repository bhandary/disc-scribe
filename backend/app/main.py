from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings
from app.api.routes import auth, cds, settings as settings_routes

app = FastAPI(
    title="DiscVault AI API",
    description="Agentic CD Collection Manager with AI-powered enrichment",
    version="1.0.0"
)

# CORS. The shelf sends Authorization, not a cookie, so the two Railway
# domains do not need to share a session cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OAuth state, nonce, and PKCE verifier. This cookie is only for the redirect
# dance on the API host. SameSite=Lax is sent on Google's top-level return.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET or "missing-session-secret",
    session_cookie="discvault_oauth",
    max_age=10 * 60,
    same_site="lax",
    https_only=settings.SESSION_COOKIE_SECURE,
)

# Routes
app.include_router(auth.router)
app.include_router(cds.router)
app.include_router(settings_routes.router)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "discvault-api"}


@app.get("/")
async def root():
    return {
        "service": "DiscVault AI API",
        "version": "1.0.0",
        "docs": "/docs"
    }
