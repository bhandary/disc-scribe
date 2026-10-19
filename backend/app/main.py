from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import cds, settings as settings_routes

app = FastAPI(
    title="DiscVault AI API",
    description="Agentic CD Collection Manager with AI-powered enrichment",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
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
