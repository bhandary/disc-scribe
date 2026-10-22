from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Literal
from uuid import UUID
from datetime import datetime


class Track(BaseModel):
    position: str
    title: str
    duration: Optional[str] = None


class CDBase(BaseModel):
    artist: str = Field(..., min_length=1, max_length=255)
    album_name: str = Field(..., min_length=1, max_length=255)
    lyricist: Optional[str] = Field(None, max_length=255)
    genre: str = Field(..., min_length=1, max_length=100)
    num_discs: int = Field(1, ge=1)
    cover_art_url: Optional[str] = None
    release_year: Optional[int] = Field(None, ge=1900, le=2100)
    barcode: Optional[str] = Field(None, max_length=32)
    label: Optional[str] = Field(None, max_length=255)
    tracks: Optional[List[Track]] = None
    
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


class BarcodeLookupRequest(BaseModel):
    barcode: str = Field(..., min_length=8, max_length=32)


class BarcodeLookupResponse(BaseModel):
    barcode: str
    artist: str
    album_name: str
    lyricist: Optional[str] = None
    genre: str
    num_discs: int = 1
    cover_art_url: Optional[str] = None
    release_year: Optional[int] = None
    label: Optional[str] = None
    tracks: List[Track] = []
    source: Literal["musicbrainz", "discogs"]
    already_in_collection: bool = False
    existing_id: Optional[UUID] = None
