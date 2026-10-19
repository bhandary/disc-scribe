from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime


class CDBase(BaseModel):
    artist: str = Field(..., min_length=1, max_length=255)
    album_name: str = Field(..., min_length=1, max_length=255)
    lyricist: Optional[str] = Field(None, max_length=255)
    genre: str = Field(..., min_length=1, max_length=100)
    num_discs: int = Field(1, ge=1)
    cover_art_url: Optional[str] = None
    release_year: Optional[int] = Field(None, ge=1900, le=2100)
    
    @field_validator("artist", "album_name", "lyricist", "genre", mode="before")
    def strip_strings(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class CDCreate(CDBase):
    pass


class CDResponse(CDBase):
    id: UUID
    ai_summary: Optional[str] = None
    ai_sources: Optional[List[Dict[str, str]]] = None
    created_at: datetime
    updated_at: datetime
    needs_enrichment: bool = False
    
    model_config = {"from_attributes": True}


class CDSearchResponse(BaseModel):
    cds: List[CDResponse]
    total: int
    page: int
    limit: int
    needs_enrichment_count: int
