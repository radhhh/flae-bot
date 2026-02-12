"""Session management service for time tracking."""
import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Session, Subject, User


def parse_duration(duration_str: str) -> int:
    """
    Parse duration string to seconds.
    
    Supports formats:
    - "1h 20m" or "2h" or "30m" or "45s"
    - "1:20" (H:MM format)
    - "80" (plain number = minutes)
    
    Returns total seconds.
    """
    duration_str = duration_str.strip().lower()
    
    # Try H:MM format first
    if ":" in duration_str:
        parts = duration_str.split(":")
        if len(parts) == 2:
            try:
                hours = int(parts[0])
                minutes = int(parts[1])
                return hours * 3600 + minutes * 60
            except ValueError:
                pass
    
    # Try parsing with h/m/s suffixes
    total_seconds = 0
    
    # Find all patterns like "2h", "30m", "45s"
    pattern = r'(\d+\.?\d*)\s*([hms])'
    matches = re.findall(pattern, duration_str)
    
    if matches:
        for value, unit in matches:
            value = float(value)
            if unit == 'h':
                total_seconds += int(value * 3600)
            elif unit == 'm':
                total_seconds += int(value * 60)
            elif unit == 's':
                total_seconds += int(value)
        return total_seconds
    
    # If just a plain number, treat as minutes
    try:
        minutes = float(duration_str)
        return int(minutes * 60)
    except ValueError:
        raise ValueError(f"Cannot parse duration: {duration_str}")


def format_duration(seconds: int) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 0:
        return "0m"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 and hours == 0:  # Only show seconds if less than an hour
        parts.append(f"{secs}s")
    
    return " ".join(parts) if parts else "0m"


def calculate_effective_time(session: Session, now: Optional[datetime] = None) -> int:
    """
    Calculate effective time for a session in seconds.
    
    If effective_override_seconds is set, use that.
    Otherwise: (now - started_at) - total_paused_seconds - current_pause_duration
    """
    if now is None:
        now = datetime.now(timezone.utc)
    
    # If override is set, use it
    if session.effective_override_seconds is not None:
        return session.effective_override_seconds
    
    # Calculate end time
    end_time = session.ended_at if session.ended_at else now
    
    # Base duration
    base_seconds = int((end_time - session.started_at).total_seconds())
    
    # Total paused time
    paused_seconds = session.total_paused_seconds
    
    # Add current pause if session is paused
    if session.status == "PAUSED" and session.pause_started_at:
        current_pause = int((now - session.pause_started_at).total_seconds())
        paused_seconds += current_pause
    
    # Effective time
    effective = max(0, base_seconds - paused_seconds)
    return effective


async def get_or_create_user(db: AsyncSession, user_id: str) -> User:
    """Get or create a user."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(id=user_id)
        db.add(user)
        await db.flush()
    
    return user


async def get_or_create_subject(
    db: AsyncSession, user_id: str, subject_name: str
) -> Subject:
    """Get or create a subject for a user."""
    result = await db.execute(
        select(Subject).where(
            Subject.user_id == user_id,
            Subject.name == subject_name
        )
    )
    subject = result.scalar_one_or_none()
    
    if not subject:
        subject = Subject(user_id=user_id, name=subject_name)
        db.add(subject)
        await db.flush()
    
    return subject


async def get_active_session(db: AsyncSession, user_id: str) -> Optional[Session]:
    """Get the active session for a user (RUNNING or PAUSED)."""
    result = await db.execute(
        select(Session).where(
            Session.user_id == user_id,
            Session.status.in_(["RUNNING", "PAUSED"])
        )
    )
    return result.scalar_one_or_none()


async def clock_in(
    db: AsyncSession,
    user_id: str,
    subject_name: str,
    goal: Optional[str] = None,
) -> Tuple[Session, bool]:
    """
    Clock in to a new session.
    
    Returns (session, is_new).
    If user already has an active session, returns (existing_session, False).
    """
    # Ensure user exists
    await get_or_create_user(db, user_id)
    
    # Check for active session
    existing = await get_active_session(db, user_id)
    if existing:
        return existing, False
    
    # Get or create subject
    subject = await get_or_create_subject(db, user_id, subject_name)
    
    # Create new session
    session = Session(
        user_id=user_id,
        subject_id=subject.id,
        started_at=datetime.now(timezone.utc),
        goal=goal,
        status="RUNNING",
        total_paused_seconds=0,
    )
    db.add(session)
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session, True


async def clock_out(
    db: AsyncSession,
    user_id: str,
    note: Optional[str] = None,
) -> Optional[Session]:
    """
    Clock out of active session.
    
    Returns the session if successful, None if no active session.
    """
    session = await get_active_session(db, user_id)
    if not session:
        return None
    
    now = datetime.now(timezone.utc)
    
    # If paused, accrue the pause time
    if session.status == "PAUSED" and session.pause_started_at:
        pause_duration = int((now - session.pause_started_at).total_seconds())
        session.total_paused_seconds += pause_duration
        session.pause_started_at = None
    
    session.ended_at = now
    session.status = "ENDED_UNCONFIRMED"
    if note:
        session.note = note
    
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def pause_session(db: AsyncSession, user_id: str) -> Optional[Session]:
    """
    Pause the active session.
    
    Returns the session if successful, None if no RUNNING session.
    """
    session = await get_active_session(db, user_id)
    if not session or session.status != "RUNNING":
        return None
    
    session.status = "PAUSED"
    session.pause_started_at = datetime.now(timezone.utc)
    
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def resume_session(db: AsyncSession, user_id: str) -> Optional[Session]:
    """
    Resume a paused session.
    
    Returns the session if successful, None if no PAUSED session.
    """
    session = await get_active_session(db, user_id)
    if not session or session.status != "PAUSED":
        return None
    
    now = datetime.now(timezone.utc)
    
    # Accrue pause time
    if session.pause_started_at:
        pause_duration = int((now - session.pause_started_at).total_seconds())
        session.total_paused_seconds += pause_duration
    
    session.status = "RUNNING"
    session.pause_started_at = None
    
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def adjust_effective_time(
    db: AsyncSession,
    session_id: UUID,
    user_id: str,
    duration_str: str,
) -> Optional[Session]:
    """
    Adjust effective time for a session.
    
    Returns the session if successful, None if session not found or not owned by user.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return None
    
    # Parse duration
    try:
        seconds = parse_duration(duration_str)
        session.effective_override_seconds = seconds
        await db.flush()
        await db.refresh(session, ["subject"])
        return session
    except ValueError:
        return None


async def confirm_session(
    db: AsyncSession,
    session_id: UUID,
    user_id: str,
) -> Optional[Session]:
    """
    Confirm a session (mark as ENDED_CONFIRMED).
    
    Returns the session if successful, None if not found or not owned by user.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return None
    
    session.status = "ENDED_CONFIRMED"
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def reopen_session(
    db: AsyncSession,
    session_id: UUID,
    user_id: str,
) -> Optional[Session]:
    """
    Reopen an ended session (change from ENDED_* to RUNNING).
    
    Returns the session if successful, None if not found or not owned by user.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return None
    
    # Check no other active session
    active = await get_active_session(db, user_id)
    if active:
        return None
    
    session.status = "RUNNING"
    session.ended_at = None
    session.effective_override_seconds = None  # Clear override when reopening
    
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def update_session_goal(
    db: AsyncSession,
    session_id: UUID,
    user_id: str,
    goal: str,
) -> Optional[Session]:
    """
    Update the goal/purpose of a session.
    
    Returns the session if successful, None if not found or not owned by user.
    """
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    
    if not session:
        return None
    
    session.goal = goal
    await db.flush()
    await db.refresh(session, ["subject"])
    
    return session


async def get_session_by_id(
    db: AsyncSession,
    session_id: UUID,
    user_id: str,
) -> Optional[Session]:
    """Get a session by ID, ensuring it belongs to the user."""
    result = await db.execute(
        select(Session).where(
            Session.id == session_id,
            Session.user_id == user_id
        )
    )
    session = result.scalar_one_or_none()
    if session:
        await db.refresh(session, ["subject"])
    return session
