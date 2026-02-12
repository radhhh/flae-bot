"""Allocation management service for weekly time tracking goals."""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WeeklyAllocation, Subject, Session
from app.session import get_or_create_user, get_or_create_subject


def get_week_start(dt: Optional[datetime] = None, tz: str = "Australia/Sydney") -> datetime:
    """
    Get the Monday (week start) for a given date in the specified timezone.
    
    Returns datetime with date only (no time component).
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    
    # Convert to target timezone
    tz_info = ZoneInfo(tz)
    local_dt = dt.astimezone(tz_info)
    
    # Find Monday
    days_since_monday = local_dt.weekday()  # Monday = 0
    week_start = local_dt.date() - timedelta(days=days_since_monday)
    
    return datetime.combine(week_start, datetime.min.time())


async def set_weekly_allocation(
    db: AsyncSession,
    user_id: str,
    subject_name: str,
    hours: float,
    week_start: Optional[datetime] = None,
) -> WeeklyAllocation:
    """
    Set or update weekly allocation for a subject.
    
    If allocation exists for this user/subject/week, update it.
    Otherwise, create a new one.
    """
    # Ensure user and subject exist
    await get_or_create_user(db, user_id)
    subject = await get_or_create_subject(db, user_id, subject_name)
    
    if week_start is None:
        week_start = get_week_start()
    
    minutes = int(hours * 60)
    
    # Check if allocation exists
    result = await db.execute(
        select(WeeklyAllocation).where(
            WeeklyAllocation.user_id == user_id,
            WeeklyAllocation.subject_id == subject.id,
            WeeklyAllocation.week_start_date == week_start.date()
        )
    )
    allocation = result.scalar_one_or_none()
    
    if allocation:
        # Update existing
        allocation.minutes_allocated = minutes
        allocation.updated_at = datetime.now(timezone.utc)
    else:
        # Create new
        allocation = WeeklyAllocation(
            user_id=user_id,
            subject_id=subject.id,
            week_start_date=week_start.date(),
            minutes_allocated=minutes,
        )
        db.add(allocation)
    
    await db.flush()
    await db.refresh(allocation, ["subject"])
    
    return allocation


async def get_weekly_allocations(
    db: AsyncSession,
    user_id: str,
    week_start: Optional[datetime] = None,
) -> List[tuple]:
    """
    Get all weekly allocations for a user for a specific week.
    
    Returns list of tuples: (WeeklyAllocation, minutes_spent)
    minutes_spent is calculated from confirmed sessions.
    """
    if week_start is None:
        week_start = get_week_start()
    
    week_end = week_start + timedelta(days=7)
    
    # Get all allocations for this week
    result = await db.execute(
        select(WeeklyAllocation)
        .where(
            WeeklyAllocation.user_id == user_id,
            WeeklyAllocation.week_start_date == week_start.date()
        )
        .order_by(WeeklyAllocation.minutes_allocated.desc())
    )
    allocations = result.scalars().all()
    
    # For each allocation, calculate actual time spent
    allocation_data = []
    
    for alloc in allocations:
        await db.refresh(alloc, ["subject"])
        
        # Get confirmed sessions for this subject in this week
        sessions_result = await db.execute(
            select(Session).where(
                Session.user_id == user_id,
                Session.subject_id == alloc.subject_id,
                Session.status == "ENDED_CONFIRMED",
                Session.started_at >= week_start,
                Session.started_at < week_end
            )
        )
        sessions = sessions_result.scalars().all()
        
        # Calculate total time spent
        total_seconds = 0
        for session in sessions:
            if session.effective_override_seconds is not None:
                total_seconds += session.effective_override_seconds
            else:
                if session.ended_at:
                    base = int((session.ended_at - session.started_at).total_seconds())
                    total_seconds += max(0, base - session.total_paused_seconds)
        
        minutes_spent = total_seconds // 60
        allocation_data.append((alloc, minutes_spent))
    
    return allocation_data


async def get_subject_allocation(
    db: AsyncSession,
    user_id: str,
    subject_name: str,
    week_start: Optional[datetime] = None,
) -> Optional[tuple]:
    """
    Get allocation for a specific subject.
    
    Returns tuple: (WeeklyAllocation, minutes_spent) or None if not found.
    """
    if week_start is None:
        week_start = get_week_start()
    
    # Get subject
    result = await db.execute(
        select(Subject).where(
            Subject.user_id == user_id,
            Subject.name == subject_name
        )
    )
    subject = result.scalar_one_or_none()
    
    if not subject:
        return None
    
    # Get allocation
    alloc_result = await db.execute(
        select(WeeklyAllocation).where(
            WeeklyAllocation.user_id == user_id,
            WeeklyAllocation.subject_id == subject.id,
            WeeklyAllocation.week_start_date == week_start.date()
        )
    )
    allocation = alloc_result.scalar_one_or_none()
    
    if not allocation:
        return None
    
    await db.refresh(allocation, ["subject"])
    
    # Calculate time spent
    week_end = week_start + timedelta(days=7)
    sessions_result = await db.execute(
        select(Session).where(
            Session.user_id == user_id,
            Session.subject_id == subject.id,
            Session.status == "ENDED_CONFIRMED",
            Session.started_at >= week_start,
            Session.started_at < week_end
        )
    )
    sessions = sessions_result.scalars().all()
    
    total_seconds = 0
    for session in sessions:
        if session.effective_override_seconds is not None:
            total_seconds += session.effective_override_seconds
        else:
            if session.ended_at:
                base = int((session.ended_at - session.started_at).total_seconds())
                total_seconds += max(0, base - session.total_paused_seconds)
    
    minutes_spent = total_seconds // 60
    
    return (allocation, minutes_spent)
