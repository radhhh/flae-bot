# Flae Time Tracking Bot

A Discord-based personal time tracking assistant built with FastAPI, SQLAlchemy, and PostgreSQL.

## Features

- **Session Tracking**: Clock in/out with subjects and goals
- **Pause/Resume**: Pause and resume sessions without losing time
- **Time Adjustment**: Adjust effective time after clock-out
- **Weekly Allocations**: Set and track weekly time goals per subject
- **Interactive UI**: Use buttons and modals for session management
- **Serverless-Ready**: HTTP-only interactions (no WebSocket gateway)

## Setup

### 1. Prerequisites

- Python 3.11+
- PostgreSQL database
- Discord Bot application

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Get your Discord credentials from the [Discord Developer Portal](https://discord.com/developers/applications):
- Create a new application
- Get the **Public Key** and **Application ID** from the General Information page
- Go to the Bot page and create a bot, then copy the **Bot Token**
- (Optional) Get your test server's **Guild ID** for faster command updates during development

### 4. Set Up Database

Run Alembic migrations:

```bash
alembic upgrade head
```

### 5. Run the Bot

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Configure Discord Webhook

Set your interactions endpoint URL in Discord Developer Portal:
- Go to your application → General Information
- Set **Interactions Endpoint URL** to: `https://your-domain.com/discord/interactions`
- Discord will verify the endpoint with a PING request

For local development, use a tunnel service like ngrok:

```bash
ngrok http 8000
```

Then use the ngrok URL: `https://your-ngrok-url.ngrok.io/discord/interactions`

## Usage

### Session Commands

- `/session in subject:math goal:"homework"` - Clock in to a session
- `/session out note:"completed chapter 5"` - Clock out
- `/session pause` - Pause current session
- `/session resume` - Resume paused session
- `/session status` - Show current session status

### Allocation Commands

- `/alloc set subject:math hours:10` - Set weekly allocation
- `/alloc show` - Show weekly allocations and progress

### Interactive Buttons

After clocking in, use buttons to:
- ⏸️ **Pause** / ▶️ **Resume** sessions
- ⏹️ **Clock Out**
- ✏️ **Edit Goal** (opens modal)

After clocking out:
- ✅ **Confirm** session
- ↩️ **Reopen** session
- ✏️ **Adjust Time** (opens modal)

## Project Structure

```
flae-bot/
├── app/
│   ├── main.py              # FastAPI application
│   ├── database.py          # Database configuration
│   ├── models.py            # SQLAlchemy models
│   ├── dependencies.py      # FastAPI dependencies
│   ├── discord_router.py    # Discord interaction handlers
│   ├── session.py           # Session management logic
│   └── allocation.py        # Allocation management logic
├── alembic/
│   ├── versions/           # Database migrations
│   └── env.py              # Alembic configuration
├── spec/
│   └── 1-minimum-feature.md # Design document
├── alembic.ini             # Alembic config
├── requirements.txt        # Python dependencies
└── .env.example           # Environment template
```

## Architecture

- **HTTP-only interactions**: No WebSocket gateway required
- **Serverless-ready**: Can be deployed to Vercel, AWS Lambda, etc.
- **PostgreSQL**: Single source of truth for all data
- **Async SQLAlchemy**: Non-blocking database operations
- **Alembic migrations**: Version-controlled schema changes

## Development

### Run migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1
```

### Run tests

```bash
pytest
```

## License

MIT
