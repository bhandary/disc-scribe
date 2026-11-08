from sqlalchemy import Column, String, Integer, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid
from datetime import datetime
from app.core.database import Base


class CD(Base):
    __tablename__ = "cds"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null only for rows that existed before accounts. Those stay hidden:
    # every query filters on the signed-in user, and NULL matches nobody.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    artist = Column(String(255), nullable=False)
    album_name = Column(String(255), nullable=False)
    lyricist = Column(String(255), nullable=True)
    genre = Column(String(100), nullable=False)
    num_discs = Column(Integer, nullable=False, default=1)
    cover_art_url = Column(Text, nullable=True)
    release_year = Column(Integer, nullable=True)
    ai_summary = Column(Text, nullable=True)
    ai_sources = Column(JSONB, nullable=True)
    embedding = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
