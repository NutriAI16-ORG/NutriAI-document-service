"""
Document Service - Database Models
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Enum
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as pgUUID

from app.database import Base

class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringified uuid.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(pgUUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            if isinstance(value, uuid.UUID):
                return value
            return uuid.UUID(value)
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)


class Document(Base):
    __tablename__ = "documents"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), nullable=False)
    document_type = Column(
        Enum("lab_report", "prescription", "other", name="document_type_enum", create_type=False),
        default="other",
        nullable=False,
    )
    original_filename = Column(String(500), nullable=False)
    blob_name = Column(String(500), nullable=False, unique=True)
    blob_url = Column(String(1000), nullable=False)
    ocr_content = Column(Text, nullable=True)
    ocr_status = Column(
        Enum("pending", "processing", "completed", "failed", name="ocr_status_enum", create_type=False),
        default="pending",
        nullable=False,
    )
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
