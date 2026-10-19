from sqlalchemy import Column, String, TIMESTAMP
from datetime import datetime
from app.core.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"
    
    key_name = Column(String(100), primary_key=True)
    encrypted_value = Column(String, nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
