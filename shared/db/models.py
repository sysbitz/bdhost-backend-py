import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from shared.db.base import Base
from shared.enums import AppStatus, PaymentStatus, UserRole

# JSON type compatible across PostgreSQL and SQLite
JSONType = JSONB().with_variant(JSON(), "sqlite")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[UserRole] = mapped_column(String(20), nullable=False, default=UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    apps: Mapped[list["App"]] = relationship("App", back_populates="owner")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken", back_populates="user"
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    app_limit: Mapped[int] = mapped_column(nullable=False, default=1)
    storage_limit_mb: Mapped[int] = mapped_column(nullable=False, default=100)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    features: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    apps: Mapped[list["App"]] = relationship("App", back_populates="plan")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="plan")


class App(Base):
    __tablename__ = "apps"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subdomain: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)
    status: Mapped[AppStatus] = mapped_column(String(20), nullable=False, default=AppStatus.ACTIVE)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    storage_bytes_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    custom_index: Mapped[str] = mapped_column(String(255), nullable=False, default="index.html")
    spa_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        server_default=func.now(),
    )

    owner: Mapped["User"] = relationship("User", back_populates="apps")
    plan: Mapped["Plan"] = relationship("Plan", back_populates="apps")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        server_default=func.now(),
    )

    user: Mapped["User"] = relationship("User", back_populates="payments")
    plan: Mapped["Plan"] = relationship("Plan", back_populates="payments")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    jti: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
