"""Main FastAPI application for Discord time-tracking bot."""
from contextlib import asynccontextmanager
import os
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI
from dotenv import load_dotenv

from app.discord_router import router as discord_router

load_dotenv()

DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DISCORD_APP_ID = os.environ.get("DISCORD_APP_ID")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")  # Optional for faster dev updates

if not DISCORD_BOT_TOKEN:
    raise RuntimeError("Set DISCORD_BOT_TOKEN env var")
if not DISCORD_APP_ID:
    raise RuntimeError("Set DISCORD_APP_ID env var")


async def register_commands() -> None:
    """
    Register Discord slash commands on startup.
    
    - If DISCORD_GUILD_ID is set: register as guild commands (instant updates)
    - Else: register as global commands (slower propagation)
    """
    commands: List[Dict[str, Any]] = [
        {
            "name": "session",
            "description": "Manage time tracking sessions",
            "type": 1,  # CHAT_INPUT
            "options": [
                {
                    "name": "in",
                    "description": "Clock in to a new session",
                    "type": 1,  # SUB_COMMAND
                    "options": [
                        {
                            "name": "subject",
                            "description": "Subject/topic name",
                            "type": 3,  # STRING
                            "required": True,
                        },
                        {
                            "name": "goal",
                            "description": "Session goal or purpose",
                            "type": 3,  # STRING
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "out",
                    "description": "Clock out of current session",
                    "type": 1,
                    "options": [
                        {
                            "name": "note",
                            "description": "Optional note about the session",
                            "type": 3,
                            "required": False,
                        },
                    ],
                },
                {
                    "name": "pause",
                    "description": "Pause the current session",
                    "type": 1,
                },
                {
                    "name": "resume",
                    "description": "Resume the paused session",
                    "type": 1,
                },
                {
                    "name": "status",
                    "description": "Show current session status",
                    "type": 1,
                },
            ],
        },
        {
            "name": "alloc",
            "description": "Manage weekly time allocations",
            "type": 1,
            "options": [
                {
                    "name": "set",
                    "description": "Set weekly allocation for a subject",
                    "type": 1,
                    "options": [
                        {
                            "name": "subject",
                            "description": "Subject name",
                            "type": 3,
                            "required": True,
                        },
                        {
                            "name": "hours",
                            "description": "Hours allocated per week",
                            "type": 10,  # NUMBER
                            "required": True,
                            "min_value": 0,
                        },
                    ],
                },
                {
                    "name": "show",
                    "description": "Show weekly allocations and progress",
                    "type": 1,
                },
            ],
        },
    ]

    # Choose endpoint based on guild vs global registration
    if DISCORD_GUILD_ID:
        url = f"https://discord.com/api/v10/applications/{DISCORD_APP_ID}/guilds/{DISCORD_GUILD_ID}/commands"
    else:
        url = f"https://discord.com/api/v10/applications/{DISCORD_APP_ID}/commands"

    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.put(url, headers=headers, json=commands)
        if r.status_code >= 400:
            raise RuntimeError(f"Command registration failed: {r.status_code} {r.text}")

    scope = "guild" if DISCORD_GUILD_ID else "global"
    print(f"✅ Registered {len(commands)} commands ({scope})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: register commands on startup."""
    await register_commands()
    yield


app = FastAPI(
    title="Flae Time Tracking Bot",
    description="Discord bot for personal time tracking with sessions and weekly allocations",
    lifespan=lifespan,
)

# Include Discord interactions router
app.include_router(discord_router, prefix="/discord")


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "flae-bot"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}
