from typing import Optional, Dict, Any
from pydantic_settings import BaseSettings, SettingsConfigDict
from cryptography.fernet import Fernet
import os


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)
    
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/discvault"
    ENCRYPTION_SECRET: str = ""
    TAVILY_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    LLM_MODEL: str = "claude-haiku-5-5"
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    # Signs the OAuth state cookie and the session JWT the frontend stores.
    SESSION_SECRET: str = ""
    FRONTEND_PUBLIC_URL: str = "http://localhost:3000"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    # The OAuth state cookie is set on the API host during a top-level redirect.
    # Railway is HTTPS, so set this true there. Local http must leave it false.
    SESSION_COOKIE_SECURE: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def google_redirect_uri(self) -> str:
        return self.BACKEND_PUBLIC_URL.rstrip("/") + "/api/auth/callback"

    @property
    def frontend_callback_url(self) -> str:
        return self.FRONTEND_PUBLIC_URL.rstrip("/") + "/auth/callback"
    
    def get_fernet(self) -> Fernet:
        """Get Fernet cipher for encryption/decryption"""
        if not self.ENCRYPTION_SECRET:
            key = Fernet.generate_key()
            self.ENCRYPTION_SECRET = key.decode()
        return Fernet(self.ENCRYPTION_SECRET.encode())


settings = Settings()


async def get_runtime_keys(db, request_headers: Dict[str, str]) -> Dict[str, Optional[str]]:
    """
    Resolve API keys with priority:
    1. Encrypted keys from app_settings DB table
    2. Custom request headers (X-Tavily-Key, X-LLM-Key, X-Anthropic-Key, X-OpenAI-Key)
    3. Server environment variables
    """
    from app.models.app_settings import AppSetting
    from sqlalchemy import select
    
    keys = {
        "tavily": None,
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
            if key_name == "TAVILY_API_KEY":
                keys["tavily"] = decrypted
            elif key_name == "ANTHROPIC_API_KEY":
                keys["anthropic"] = decrypted
            elif key_name == "OPENAI_API_KEY":
                keys["openai"] = decrypted
            elif key_name == "LLM_MODEL":
                keys["llm_model"] = decrypted
        except Exception:
            pass
    
    # Priority 2: Request headers
    if "x-tavily-key" in request_headers:
        keys["tavily"] = request_headers["x-tavily-key"]
    if "x-anthropic-key" in request_headers:
        keys["anthropic"] = request_headers["x-anthropic-key"]
    if "x-openai-key" in request_headers:
        keys["openai"] = request_headers["x-openai-key"]
    if "x-llm-model" in request_headers:
        keys["llm_model"] = request_headers["x-llm-model"]
    
    # Priority 3: Environment variables (fallback)
    if not keys["tavily"]:
        keys["tavily"] = settings.TAVILY_API_KEY
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
