from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.app_settings import AppSetting
from app.schemas.settings import APIKeyUpdate, APIKeyStatus
from app.core.config import settings, mask_api_key, get_runtime_keys

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status", response_model=APIKeyStatus)
async def get_api_key_status(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get masked status of all API keys"""
    
    headers = dict(request.headers)
    keys = await get_runtime_keys(db, headers)
    
    return APIKeyStatus(
        tavily_configured=keys["tavily"] is not None,
        tavily_masked=mask_api_key(keys["tavily"]),
        anthropic_configured=keys["anthropic"] is not None,
        anthropic_masked=mask_api_key(keys["anthropic"]),
        openai_configured=keys["openai"] is not None,
        openai_masked=mask_api_key(keys["openai"]),
        llm_model=keys["llm_model"]
    )


@router.post("/keys")
async def update_api_keys(
    key_update: APIKeyUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Encrypt and store API keys in database"""
    
    fernet = settings.get_fernet()
    updated_keys = []
    
    # Update Tavily key
    if key_update.tavily_api_key:
        encrypted = fernet.encrypt(key_update.tavily_api_key.encode()).decode()
        stmt = select(AppSetting).where(AppSetting.key_name == "TAVILY_API_KEY")
        result = await db.execute(stmt)
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.encrypted_value = encrypted
        else:
            setting = AppSetting(key_name="TAVILY_API_KEY", encrypted_value=encrypted)
            db.add(setting)
        updated_keys.append("TAVILY_API_KEY")
    
    # Update Anthropic key
    if key_update.anthropic_api_key:
        encrypted = fernet.encrypt(key_update.anthropic_api_key.encode()).decode()
        stmt = select(AppSetting).where(AppSetting.key_name == "ANTHROPIC_API_KEY")
        result = await db.execute(stmt)
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.encrypted_value = encrypted
        else:
            setting = AppSetting(key_name="ANTHROPIC_API_KEY", encrypted_value=encrypted)
            db.add(setting)
        updated_keys.append("ANTHROPIC_API_KEY")
    
    # Update OpenAI key
    if key_update.openai_api_key:
        encrypted = fernet.encrypt(key_update.openai_api_key.encode()).decode()
        stmt = select(AppSetting).where(AppSetting.key_name == "OPENAI_API_KEY")
        result = await db.execute(stmt)
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.encrypted_value = encrypted
        else:
            setting = AppSetting(key_name="OPENAI_API_KEY", encrypted_value=encrypted)
            db.add(setting)
        updated_keys.append("OPENAI_API_KEY")
    
    # Update LLM model
    if key_update.llm_model:
        encrypted = fernet.encrypt(key_update.llm_model.encode()).decode()
        stmt = select(AppSetting).where(AppSetting.key_name == "LLM_MODEL")
        result = await db.execute(stmt)
        setting = result.scalar_one_or_none()
        
        if setting:
            setting.encrypted_value = encrypted
        else:
            setting = AppSetting(key_name="LLM_MODEL", encrypted_value=encrypted)
            db.add(setting)
        updated_keys.append("LLM_MODEL")
    
    await db.commit()
    
    return {
        "message": "API keys updated successfully",
        "updated": updated_keys
    }
