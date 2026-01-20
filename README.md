# Theseus Mail Wrapper API

A FastAPI-based wrapper API for [Theseus](https://mail.hackclub.com) (Hack Club's mail system) that manages multiple events, tracks costs, and integrates with Slack for notifications and management.

## Features

- **Multi-event support**: Each event gets its own API key and queue
- **Cost tracking**: Automatic postage cost calculation for lettermail, bubble packets, and parcels
- **Slack integration**: Real-time notifications, financial canvas updates, and interactive buttons
- **Background jobs**: Hourly status checks for pending letters
- **Admin tools**: Financial summaries and payment tracking
- **Email notifications**: Automatic confirmation emails via Airtable automation when letters/orders are placed

## Quick Start

### Prerequisites

- Python 3.10+
- PostgreSQL
- Slack Bot Token with appropriate permissions

### Local Development

1. Clone the repository:
```bash
git clone https://github.com/your-org/theseus-wrapper.git
cd theseus-wrapper
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Copy environment file and configure:
```bash
cp .env.example .env
# Edit .env with your credentials
```

5. Generate an admin API key:
```bash
python scripts/create_admin_key.py
# Add the generated key to your .env as ADMIN_API_KEY
```

6. Run the server:
```bash
uvicorn app.main:app --reload
```

7. Create your first event API key:
```bash
python scripts/create_api_key.py \
  --event-name "Your Event" \
  --queue-name "your-event-letters"
```

### Docker Deployment

1. Build and run with Docker Compose:
```bash
docker-compose up -d
```

2. Or build manually:
```bash
docker build -t theseus-wrapper .
docker run -p 8000:8000 --env-file .env theseus-wrapper
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | PostgreSQL connection URL (use `postgresql+asyncpg://...`) | Yes |
| `THESEUS_API_KEY` | Bearer token for Theseus API | Yes |
| `THESEUS_BASE_URL` | Theseus API base URL | No (default: https://mail.hackclub.com/api/v1) |
| `SLACK_BOT_TOKEN` | Slack Bot OAuth token | Yes |
| `SLACK_NOTIFICATION_CHANNEL` | Channel ID for notifications | Yes |
| `SLACK_CANVAS_ID` | Canvas ID for financial summary | Yes |
| `SLACK_JENIN_USER_ID` | Jenin's user ID for parcel DMs | No |
| `AIRTABLE_API_KEY` | Airtable API key for email automation | No |
| `ADMIN_API_KEY` | Admin API key for admin endpoints | Yes |
| `API_HOST` | Host to bind to | No (default: 0.0.0.0) |
| `API_PORT` | Port to bind to | No (default: 8000) |
| `DEBUG` | Enable debug logging | No (default: false) |

## API Endpoints

### Letter Operations

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/api/v1/letters` | Create a new letter | Event API Key |
| POST | `/api/v1/calculate-cost` | Calculate shipping cost | None |

### Admin Operations

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| POST | `/admin/events/{id}/mark-paid` | Mark event as paid | Admin Key |
| GET | `/admin/financial-summary` | Get unpaid events summary | Admin Key |
| POST | `/admin/check-letter-status` | Manually check letter statuses | Admin Key |

### Slack & Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/slack/interactions` | Slack interactive component handler |
| GET | `/health` | Health check |
| GET | `/docs-page` | Custom documentation page |

## Creating Letters

```bash
curl -X POST https://your-api.com/api/v1/letters \
  -H "Authorization: Bearer YOUR_EVENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "John",
    "last_name": "Doe",
    "address_line_1": "123 Main St",
    "city": "Burlington",
    "state": "VT",
    "postal_code": "05401",
    "country": "Canada",
    "mail_type": "lettermail",
    "rubber_stamps": "1x pack of stickers\n1x Postcard"
  }'
```

## Rubber Stamps Field

The `rubber_stamps` field specifies what items should be packed in the envelope. This text gets printed on the fulfillment label.

**Format:**
- List each item on its own line
- Use clear, descriptive text
- Include quantities if applicable
- Maximum 11 characters per line (auto-formatted)

**Examples:**
```
"1x pack of stickers\n1x Postcard of Euan eating a Bread"
"3x Hack Club stickers\n1x Thank you card\n1x Event badge"
"Haxmas 2024 Winner Prize Package"
```

## Postage Rates

### Lettermail (up to 30g)
| Destination | Cost |
|-------------|------|
| Canada | $1.19 USD |
| United States | $1.45 USD |
| International | $3.02 USD |

### Bubble Packet (up to 500g)

**Canada:**
| Weight | Cost |
|--------|------|
| ≤100g | $2.16 |
| ≤200g | $3.56 |
| ≤300g | $4.96 |
| ≤400g | $5.67 |
| ≤500g | $6.10 |

**United States:**
| Weight | Cost |
|--------|------|
| ≤100g | $3.56 |
| ≤200g | $6.21 |
| ≤500g | $12.43 |

**International:**
| Weight | Cost |
|--------|------|
| ≤100g | $7.13 |
| ≤200g | $12.43 |
| ≤500g | $24.85 |

### Parcel
Custom quote required - contact @hermes on Slack.

## Slack Bot Setup

1. Create a Slack App at https://api.slack.com/apps
2. Enable the following Bot Token Scopes:
   - `chat:write`
   - `chat:write.public`
   - `canvases:write`
   - `im:write` (for parcel DMs)
3. Enable Interactivity and set the Request URL to `https://your-api.com/slack/interactions`
4. Install the app to your workspace
5. Copy the Bot User OAuth Token to `SLACK_BOT_TOKEN`

## Coolify Deployment

1. Create a new service in Coolify
2. Connect to your Git repository
3. Set the Dockerfile path to `Dockerfile`
4. Configure environment variables in Coolify's settings
5. Set up a PostgreSQL database in Coolify and connect it
6. Deploy

## Project Structure

```
theseus-wrapper/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app & routes
│   ├── models.py               # SQLAlchemy models
│   ├── database.py             # DB connection & session
│   ├── config.py               # Settings from env vars
│   ├── schemas.py              # Pydantic models for API
│   ├── theseus_client.py       # Theseus API wrapper
│   ├── slack_bot.py            # Slack notifications & canvas
│   ├── cost_calculator.py      # Postage rate logic
│   ├── rubber_stamp_formatter.py  # Text formatting utility
│   └── background_jobs.py      # Status checker cron
├── scripts/
│   ├── create_api_key.py       # CLI to generate event keys
│   └── create_admin_key.py     # CLI to generate admin key
├── docs/
│   └── static_docs.html        # Custom documentation page
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## License

MIT License - See LICENSE file for details.
