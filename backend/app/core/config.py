from typing import Optional, Dict, Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import base64
import hashlib
import os


def normalize_database_url(url: str) -> str:
    """Accept Railway's postgres:// URL and make it usable with asyncpg."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url.split("://", 1)[0]:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    if sslmode in {"require", "verify-ca", "verify-full"}:
        query["ssl"] = "require"
    return urlunparse(parsed._replace(query=urlencode(query)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")
    
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/discvault"
    ENCRYPTION_SECRET: str = ""
    BRAVE_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    LLM_MODEL: str = "claude-haiku-5-5"
    DISCOGS_TOKEN: Optional[str] = None
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    FRONTEND_URL: Optional[str] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_db_url(cls, value: str) -> str:
        return normalize_database_url(value or "")
    
    @property
    def cors_origins_list(self) -> list[str]:
        origins = [origin.strip().rstrip("/") for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        if self.FRONTEND_URL:
            frontend = self.FRONTEND_URL.strip().rstrip("/")
            if frontend and not frontend.startswith("http"):
                frontend = f"https://{frontend}"
            if frontend:
                origins.append(frontend)
        return list(dict.fromkeys(origins))
    
    def get_fernet(self) -> Fernet:
        """Get Fernet cipher for encryption/decryption"""
        secret = self.ENCRYPTION_SECRET
        if not secret:
            if os.environ.get("RAILWAY_ENVIRONMENT"):
                raise RuntimeError("ENCRYPTION_SECRET must be set on Railway")
            key = Fernet.generate_key()
            self.ENCRYPTION_SECRET = key.decode()
            return Fernet(key)
        try:
            return Fernet(secret.encode() if isinstance(secret, str) else secret)
        except Exception:
            digest = hashlib.sha256(secret.encode()).digest()
            return Fernet(base64.urlsafe_b64encode(digest))


settings = Settings()


async def get_runtime_keys(db, request_headers: Dict[str, str]) -> Dict[str, Optional[str]]:
    """
    Resolve API keys with priority:
    1. Encrypted keys from app_settings DB table
    2. Custom request headers (X-Brave-Key, X-LLM-Model, X-Anthropic-Key, X-OpenAI-Key)
    3. Server environment variables
    """
    from app.models.app_settings import AppSetting
    from sqlalchemy import select

    keys = {
        "brave": None,
        "anthropic": None,
        "openai": None,
        "llm_model": settings.LLM_MODEL,
    }

    # Priority 1: Database encrypted keys
    result = await db.execute(select(AppSetting))
    db_settings = {row.key_name: row for row in result.scalars().all()}

    fernet = settings.get_fernet()

    for key_name, setting in db_settings.items():
        try:
            decrypted = fernet.decrypt(setting.encrypted_value.encode()).decode()
            if key_name == "BRAVE_API_KEY":
                keys["brave"] = decrypted
            elif key_name == "ANTHROPIC_API_KEY":
                keys["anthropic"] = decrypted
            elif key_name == "OPENAI_API_KEY":
                keys["openai"] = decrypted
            elif key_name == "LLM_MODEL":
                keys["llm_model"] = decrypted
        except Exception:
            pass

    # Priority 2: Request headers
    if "x-brave-key" in request_headers:
        keys["brave"] = request_headers["x-brave-key"]
    if "x-anthropic-key" in request_headers:
        keys["anthropic"] = request_headers["x-anthropic-key"]
    if "x-openai-key" in request_headers:
        keys["openai"] = request_headers["x-openai-key"]
    if "x-llm-model" in request_headers:
        keys["llm_model"] = request_headers["x-llm-model"]

    # Priority 3: Environment variables (fallback)
    if not keys["brave"]:
        keys["brave"] = settings.BRAVE_API_KEY
    if not keys["anthropic"]:
        keys["anthropic"] = settings.ANTHROPIC_API_KEY
    if not keys["openai"]:
        keys["openai"] = settings.OPENAI_API_KEY

    return keys


def mask_api_key(key: Optional[str]) -> str:
    """Mask API key for display (show prefix and last 4 chars)"""
    if not key or len(key) < 8:
        return "Not configured"
    return f"{key[:8]}...{key[-4:]}"
