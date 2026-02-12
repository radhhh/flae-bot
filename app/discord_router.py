"""Discord interaction router and handlers."""
import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.session import (
    clock_in,
    clock_out,
    pause_session,
    resume_session,
    get_active_session,
    calculate_effective_time,
    format_duration,
    get_session_by_id,
    adjust_effective_time,
    confirm_session,
    reopen_session,
    update_session_goal,
)
from app.allocation import (
    set_weekly_allocation,
    get_weekly_allocations,
)
from app.dependencies import verify_discord_request


router = APIRouter()


def create_session_status_message(session, effective_seconds: int) -> Dict[str, Any]:
    """Create a message showing session status with action buttons."""
    status_emoji = {
        "RUNNING": "▶️",
        "PAUSED": "⏸️",
        "ENDED_UNCONFIRMED": "⏹️",
        "ENDED_CONFIRMED": "✅",
    }
    
    emoji = status_emoji.get(session.status, "⏺️")
    status_text = session.status.replace("_", " ").title()
    
    lines = [
        f"{emoji} **Session Status: {status_text}**",
        f"**Subject:** {session.subject.name}",
    ]
    
    if session.goal:
        lines.append(f"**Goal:** {session.goal}")
    
    lines.append(f"**Effective Time:** {format_duration(effective_seconds)}")
    
    if session.total_paused_seconds > 0:
        lines.append(f"**Paused Time:** {format_duration(session.total_paused_seconds)}")
    
    message = "\n".join(lines)
    
    # Add buttons based on status
    components = []
    if session.status == "RUNNING":
        components = [
            {
                "type": 1,  # Action Row
                "components": [
                    {
                        "type": 2,  # Button
                        "style": 2,  # Secondary
                        "label": "Pause",
                        "custom_id": f"pause:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 4,  # Danger
                        "label": "Clock Out",
                        "custom_id": f"out:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 1,  # Primary
                        "label": "Edit Goal",
                        "custom_id": f"edit_goal:{session.id}",
                    },
                ]
            }
        ]
    elif session.status == "PAUSED":
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 3,  # Success
                        "label": "Resume",
                        "custom_id": f"resume:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 4,  # Danger
                        "label": "Clock Out",
                        "custom_id": f"out:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 1,
                        "label": "Edit Goal",
                        "custom_id": f"edit_goal:{session.id}",
                    },
                ]
            }
        ]
    elif session.status == "ENDED_UNCONFIRMED":
        components = [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 3,  # Success
                        "label": "✅ Confirm",
                        "custom_id": f"confirm:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 2,  # Secondary
                        "label": "↩️ Reopen",
                        "custom_id": f"reopen:{session.id}",
                    },
                ]
            },
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 1,  # Primary
                        "label": "✏️ Adjust Time",
                        "custom_id": f"adjust_time:{session.id}",
                    },
                    {
                        "type": 2,
                        "style": 1,
                        "label": "✏️ Edit Goal",
                        "custom_id": f"edit_goal:{session.id}",
                    },
                ]
            }
        ]
    
    return {
        "content": message,
        "components": components,
    }


def create_allocation_summary_message(allocations: List[tuple]) -> str:
    """Create a summary message for weekly allocations."""
    if not allocations:
        return "No allocations set for this week. Use `/alloc set` to create one."
    
    lines = ["**📊 Weekly Time Allocation**\n"]
    
    for alloc, minutes_spent in allocations:
        minutes_allocated = alloc.minutes_allocated
        hours_allocated = minutes_allocated / 60
        hours_spent = minutes_spent / 60
        
        percentage = (minutes_spent / minutes_allocated * 100) if minutes_allocated > 0 else 0
        
        # Progress bar
        bar_length = 10
        filled = int(bar_length * min(percentage, 100) / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        lines.append(
            f"**{alloc.subject.name}:** {hours_spent:.1f}h / {hours_allocated:.1f}h "
            f"({percentage:.0f}%)\n{bar}"
        )
    
    return "\n".join(lines)


@router.post("/interactions")
async def discord_interactions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    payload: Dict[str, Any] = Depends(verify_discord_request),
    background_task: BackgroundTasks,
):
    """Handle all Discord interactions."""
    interaction_type = payload.get("type")
    
    # 1 = PING
    if interaction_type == 1:
        return JSONResponse({"type": 1})
    
    user_id = payload.get("member", {}).get("user", {}).get("id") or payload.get("user", {}).get("id")
    
    # 2 = APPLICATION_COMMAND (slash command)
    if interaction_type == 2:
        return await handle_command(payload, user_id, db)
    
    # 3 = MESSAGE_COMPONENT (button click)
    if interaction_type == 3:
        return await handle_button(payload, user_id, db)
    
    # 5 = MODAL_SUBMIT
    if interaction_type == 5:
        return await handle_modal(payload, user_id, db)
    
    return JSONResponse({"type": 4, "data": {"content": "Unhandled interaction type."}})


async def handle_command(
    payload: Dict[str, Any],
    user_id: str,
    db: AsyncSession,
) -> JSONResponse:
    """Handle slash commands."""
    data = payload.get("data", {})
    command_name = data.get("name")
    
    # Parse subcommand if exists
    options = data.get("options", [])
    subcommand = None
    subcommand_options = {}
    
    if options and options[0].get("type") == 1:  # SUB_COMMAND
        subcommand = options[0].get("name")
        for opt in options[0].get("options", []):
            subcommand_options[opt["name"]] = opt["value"]
    else:
        for opt in options:
            subcommand_options[opt["name"]] = opt["value"]
    
    # /session commands
    if command_name == "session":
        if subcommand == "in":
            return await handle_session_in(user_id, subcommand_options, db)
        elif subcommand == "out":
            return await handle_session_out(user_id, subcommand_options, db)
        elif subcommand == "pause":
            return await handle_session_pause(user_id, db)
        elif subcommand == "resume":
            return await handle_session_resume(user_id, db)
        elif subcommand == "status":
            return await handle_session_status(user_id, db)
    
    # /alloc commands
    elif command_name == "alloc":
        if subcommand == "set":
            return await handle_alloc_set(user_id, subcommand_options, db)
        elif subcommand == "show":
            return await handle_alloc_show(user_id, db)
    
    return JSONResponse({"type": 4, "data": {"content": "Unknown command."}})


async def handle_session_in(
    user_id: str,
    options: Dict[str, Any],
    db: AsyncSession,
) -> JSONResponse:
    """Handle /session in command."""
    subject = options.get("subject")
    goal = options.get("goal")
    
    if not subject:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Subject is required."}
        })
    
    session, is_new = await clock_in(db, user_id, subject, goal)
    
    if not is_new:
        effective = calculate_effective_time(session)
        msg = create_session_status_message(session, effective)
        msg["content"] = "⚠️ You already have an active session!\n\n" + msg["content"]
        return JSONResponse({"type": 4, "data": msg})
    
    await db.commit()
    
    effective = calculate_effective_time(session)
    msg = create_session_status_message(session, effective)
    msg["content"] = "✅ Clocked in!\n\n" + msg["content"]
    
    return JSONResponse({"type": 4, "data": msg})


async def handle_session_out(
    user_id: str,
    options: Dict[str, Any],
    db: AsyncSession,
) -> JSONResponse:
    """Handle /session out command."""
    note = options.get("note")
    
    session = await clock_out(db, user_id, note)
    
    if not session:
        return JSONResponse({
            "type": 4,
            "data": {"content": "❌ No active session to clock out."}
        })
    
    await db.commit()
    
    effective = calculate_effective_time(session)
    msg = create_session_status_message(session, effective)
    msg["content"] = "⏹️ Clocked out!\n\n" + msg["content"]
    
    return JSONResponse({"type": 4, "data": msg})


async def handle_session_pause(user_id: str, db: AsyncSession) -> JSONResponse:
    """Handle /session pause command."""
    session = await pause_session(db, user_id)
    
    if not session:
        return JSONResponse({
            "type": 4,
            "data": {"content": "❌ No running session to pause."}
        })
    
    await db.commit()
    
    effective = calculate_effective_time(session)
    msg = create_session_status_message(session, effective)
    msg["content"] = "⏸️ Session paused!\n\n" + msg["content"]
    
    return JSONResponse({"type": 4, "data": msg})


async def handle_session_resume(user_id: str, db: AsyncSession) -> JSONResponse:
    """Handle /session resume command."""
    session = await resume_session(db, user_id)
    
    if not session:
        return JSONResponse({
            "type": 4,
            "data": {"content": "❌ No paused session to resume."}
        })
    
    await db.commit()
    
    effective = calculate_effective_time(session)
    msg = create_session_status_message(session, effective)
    msg["content"] = "▶️ Session resumed!\n\n" + msg["content"]
    
    return JSONResponse({"type": 4, "data": msg})


async def handle_session_status(user_id: str, db: AsyncSession) -> JSONResponse:
    """Handle /session status command."""
    session = await get_active_session(db, user_id)
    
    if not session:
        return JSONResponse({
            "type": 4,
            "data": {"content": "No active session."}
        })
    
    effective = calculate_effective_time(session)
    msg = create_session_status_message(session, effective)
    
    return JSONResponse({"type": 4, "data": msg})


async def handle_alloc_set(
    user_id: str,
    options: Dict[str, Any],
    db: AsyncSession,
) -> JSONResponse:
    """Handle /alloc set command."""
    subject = options.get("subject")
    hours = options.get("hours")
    
    if not subject or hours is None:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Subject and hours are required."}
        })
    
    try:
        hours_float = float(hours)
        if hours_float < 0:
            raise ValueError("Hours must be positive")
    except ValueError:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Invalid hours value."}
        })
    
    allocation = await set_weekly_allocation(db, user_id, subject, hours_float)
    await db.commit()
    
    return JSONResponse({
        "type": 4,
        "data": {
            "content": f"✅ Set weekly allocation for **{allocation.subject.name}**: {hours_float}h"
        }
    })


async def handle_alloc_show(user_id: str, db: AsyncSession) -> JSONResponse:
    """Handle /alloc show command."""
    allocations = await get_weekly_allocations(db, user_id)
    message = create_allocation_summary_message(allocations)
    
    return JSONResponse({
        "type": 4,
        "data": {"content": message}
    })


async def handle_button(
    payload: Dict[str, Any],
    user_id: str,
    db: AsyncSession,
) -> JSONResponse:
    """Handle button clicks."""
    custom_id = payload.get("data", {}).get("custom_id", "")
    
    # Parse custom_id: "action:session_id"
    parts = custom_id.split(":", 1)
    if len(parts) != 2:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Invalid button."}
        })
    
    action, session_id_str = parts
    
    try:
        session_id = UUID(session_id_str)
    except ValueError:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Invalid session ID."}
        })
    
    # Verify session ownership
    session = await get_session_by_id(db, session_id, user_id)
    if not session:
        return JSONResponse({
            "type": 4,
            "data": {"content": "❌ Session not found or access denied."}
        })
    
    # Handle actions
    if action == "pause":
        session = await pause_session(db, user_id)
        if session:
            await db.commit()
            effective = calculate_effective_time(session)
            msg = create_session_status_message(session, effective)
            msg["content"] = "⏸️ Session paused!\n\n" + msg["content"]
            msg["flags"] = 0  # Make visible
            return JSONResponse({"type": 7, "data": msg})  # UPDATE_MESSAGE
        
    elif action == "resume":
        session = await resume_session(db, user_id)
        if session:
            await db.commit()
            effective = calculate_effective_time(session)
            msg = create_session_status_message(session, effective)
            msg["content"] = "▶️ Session resumed!\n\n" + msg["content"]
            msg["flags"] = 0
            return JSONResponse({"type": 7, "data": msg})
        
    elif action == "out":
        session = await clock_out(db, user_id)
        if session:
            await db.commit()
            effective = calculate_effective_time(session)
            msg = create_session_status_message(session, effective)
            msg["content"] = "⏹️ Clocked out!\n\n" + msg["content"]
            msg["flags"] = 0
            return JSONResponse({"type": 7, "data": msg})
        
    elif action == "confirm":
        session = await confirm_session(db, session_id, user_id)
        if session:
            await db.commit()
            effective = calculate_effective_time(session)
            msg = create_session_status_message(session, effective)
            msg["content"] = "✅ Session confirmed!\n\n" + msg["content"]
            msg["components"] = []  # Remove buttons
            msg["flags"] = 0
            return JSONResponse({"type": 7, "data": msg})
        
    elif action == "reopen":
        session = await reopen_session(db, session_id, user_id)
        if session:
            await db.commit()
            effective = calculate_effective_time(session)
            msg = create_session_status_message(session, effective)
            msg["content"] = "↩️ Session reopened!\n\n" + msg["content"]
            msg["flags"] = 0
            return JSONResponse({"type": 7, "data": msg})
        else:
            return JSONResponse({
                "type": 4,
                "data": {"content": "❌ Cannot reopen: you have another active session.", "flags": 64}
            })
        
    elif action == "adjust_time":
        # Show modal for time adjustment
        return JSONResponse({
            "type": 9,  # MODAL
            "data": {
                "custom_id": f"modal_adjust:{session_id}",
                "title": "Adjust Effective Time",
                "components": [
                    {
                        "type": 1,  # Action Row
                        "components": [
                            {
                                "type": 4,  # Text Input
                                "custom_id": "duration",
                                "label": "Effective Duration",
                                "style": 1,  # Short
                                "placeholder": "e.g., 1h 20m, 80m, 1:20",
                                "required": True,
                            }
                        ]
                    }
                ]
            }
        })
        
    elif action == "edit_goal":
        # Show modal for editing goal
        current_goal = session.goal or ""
        return JSONResponse({
            "type": 9,  # MODAL
            "data": {
                "custom_id": f"modal_goal:{session_id}",
                "title": "Edit Session Goal",
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 4,
                                "custom_id": "goal",
                                "label": "Goal / Purpose",
                                "style": 2,  # Paragraph
                                "value": current_goal,
                                "placeholder": "What are you working on?",
                                "required": False,
                                "max_length": 1000,
                            }
                        ]
                    }
                ]
            }
        })
    
    return JSONResponse({
        "type": 4,
        "data": {"content": "Action failed.", "flags": 64}
    })


async def handle_modal(
    payload: Dict[str, Any],
    user_id: str,
    db: AsyncSession,
) -> JSONResponse:
    """Handle modal submissions."""
    custom_id = payload.get("data", {}).get("custom_id", "")
    
    # Parse custom_id: "modal_action:session_id"
    parts = custom_id.split(":", 1)
    if len(parts) != 2:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Invalid modal."}
        })
    
    modal_type, session_id_str = parts
    
    try:
        session_id = UUID(session_id_str.split("_")[-1] if "_" in session_id_str else session_id_str)
    except ValueError:
        return JSONResponse({
            "type": 4,
            "data": {"content": "Invalid session ID."}
        })
    
    # Extract form values
    components = payload.get("data", {}).get("components", [])
    values = {}
    for action_row in components:
        for component in action_row.get("components", []):
            values[component["custom_id"]] = component["value"]
    
    if modal_type == "modal_adjust":
        duration_str = values.get("duration", "").strip()
        if not duration_str:
            return JSONResponse({
                "type": 4,
                "data": {"content": "❌ Duration is required.", "flags": 64}
            })
        
        session = await adjust_effective_time(db, session_id, user_id, duration_str)
        if not session:
            return JSONResponse({
                "type": 4,
                "data": {"content": "❌ Failed to adjust time. Check your format.", "flags": 64}
            })
        
        await db.commit()
        
        effective = calculate_effective_time(session)
        msg = create_session_status_message(session, effective)
        msg["content"] = "✏️ Time adjusted!\n\n" + msg["content"]
        
        return JSONResponse({"type": 4, "data": msg})
        
    elif modal_type == "modal_goal":
        goal = values.get("goal", "").strip()
        
        session = await update_session_goal(db, session_id, user_id, goal)
        if not session:
            return JSONResponse({
                "type": 4,
                "data": {"content": "❌ Failed to update goal.", "flags": 64}
            })
        
        await db.commit()
        
        effective = calculate_effective_time(session)
        msg = create_session_status_message(session, effective)
        msg["content"] = "✏️ Goal updated!\n\n" + msg["content"]
        
        return JSONResponse({"type": 4, "data": msg})
    
    return JSONResponse({
        "type": 4,
        "data": {"content": "Unknown modal type.", "flags": 64}
    })
