from pydantic import BaseModel
from typing import Optional


class APIKeyUpdate(BaseModel):
    tavily_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    llm_model: Optional[str] = None


class APIKeyStatus(BaseModel):
    tavily_configured: bool
    tavily_masked: str
    anthropic_configured: bool
    anthropic_masked: str
    openai_configured: bool
    openai_masked: str
    llm_model: str
