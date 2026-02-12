"""SQLAlchemy models for the time-tracking bot."""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

from app.database import Base


class User(Base):
    """Discord user."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # Discord user ID
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    subjects: Mapped[list["Subject"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    allocations: Mapped[list["WeeklyAllocation"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Subject(Base):
    """User-defined subject for time tracking."""
    __tablename__ = "subjects"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subjects")
    allocations: Mapped[list["WeeklyAllocation"]] = relationship(back_populates="subject", cascade="all, delete-orphan")
    sessions: Mapped[list["Session"]] = relationship(back_populates="subject", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_subject_name"),
        Index("ix_subjects_user_name", "user_id", "name"),
    )


class WeeklyAllocation(Base):
    """Weekly time allocation target for a subject."""
    __tablename__ = "weekly_allocations"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    week_start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    minutes_allocated: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="allocations")
    subject: Mapped["Subject"] = relationship(back_populates="allocations")

    __table_args__ = (
        UniqueConstraint("user_id", "subject_id", "week_start_date", name="uq_user_subject_week"),
        CheckConstraint("minutes_allocated >= 0", name="ck_minutes_allocated_positive"),
        Index("ix_allocations_user_week", "user_id", "week_start_date"),
        Index("ix_allocations_subject_week", "subject_id", "week_start_date"),
    )


class Session(Base):
    """Focus session with pause/resume and time tracking."""
    __tablename__ = "sessions"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    subject_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="RUNNING",
    )  # RUNNING, PAUSED, ENDED_UNCONFIRMED, ENDED_CONFIRMED
    total_paused_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    pause_started_at: Mapped[Optional[datetime]] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    effective_override_seconds: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="sessions")
    subject: Mapped["Subject"] = relationship(back_populates="sessions")

    __table_args__ = (
        CheckConstraint("total_paused_seconds >= 0", name="ck_total_paused_seconds_positive"),
        CheckConstraint(
            "effective_override_seconds IS NULL OR effective_override_seconds >= 0",
            name="ck_effective_override_seconds_positive",
        ),
        Index("ix_sessions_user_status", "user_id", "status"),
        Index("ix_sessions_user_started", "user_id", "started_at"),
    )
