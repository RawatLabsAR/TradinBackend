# Tradin Backend

FastAPI backend for the Tradin crypto research platform: market data, analytics, AI insights, strategy backtesting, and paper trading.

## Requirements

- Python 3.12+
- PostgreSQL 14+

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set DATABASE_URL, JWT_SECRET, etc.
python scripts/init_db.py
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs (dev only): http://localhost:8000/docs

## Environment

See `.env.example` for all variables. Production essentials:

- `DEBUG=false`
- Strong `JWT_SECRET` (32+ characters)
- `DATABASE_URL` pointing to PostgreSQL
- `FRONTEND_URL` and `ALLOWED_ORIGINS` for CORS
- SMTP settings if `REQUIRE_EMAIL_VERIFICATION=true`

## Database migrations

```bash
alembic upgrade head
```

On startup, the app also runs idempotent schema patches via SQLAlchemy.

## Tests

```bash
pip install aiosqlite
pytest tests/ -v
```

## Docker

```bash
docker compose up --build
```

## Production deploy

See [`../deploy/README.md`](../deploy/README.md) for full-stack deployment with Caddy TLS and Postgres.
