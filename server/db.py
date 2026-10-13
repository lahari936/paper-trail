import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, create_engine, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from server.config import DATABASE_URL

DOC_TYPES = ("warranty", "insurance", "lease", "subscription", "bill", "other")

engine = create_engine(DATABASE_URL)
Session = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(index=True)
    doc_type: Mapped[str]
    title: Mapped[str]
    s3_key: Mapped[str | None]
    vendor: Mapped[str | None]
    item_name: Mapped[str | None]
    item_category: Mapped[str | None]
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    renewal_date: Mapped[date | None]
    notice_days: Mapped[int | None]
    amount: Mapped[Decimal | None]
    currency: Mapped[str | None]
    auto_renews: Mapped[bool | None]
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int]
    text: Mapped[str]
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str]
    sent: Mapped[bool] = mapped_column(default=False)


def init_db() -> None:
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
