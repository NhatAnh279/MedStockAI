# MedStock AI

Hospital inventory + demand forecasting. Hackathon prototype (no auth).

- `backend/` — FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16
- `frontend/` — Next.js, Tailwind, shadcn/ui (skeleton)

## Run

```bash
docker compose up --build        # db :5432, backend :8000, frontend :3000
docker compose exec backend python seed.py
```

Migrations run automatically when the backend container starts. `seed.py` truncates and reloads every table, so it can be re-run.

- API health: http://localhost:8000/health (docs at `/docs`)
- UI: http://localhost:3000

## Data conventions

- Australian market: prices in AUD, suppliers identified by ABN, patients by Medicare number. All identifiers are synthetic (valid check digits, random values; phones use the ACMA drama range).
- All quantities are in the item's base `unit` (tablet, vial, each…); `pack_size` is base units per pack, `moq` is in base units.
- `protocol_items.qty_per_cycle` is base units per cycle. If `dose_per_kg` is set, qty = ceil(`dose_per_kg` × patient `weight_kg`).
- `protocols.total_cycles` NULL means chronic / ongoing (hemodialysis, T2DM).
- `treatment_plans.current_cycle` is the cycle in progress (its supplies were already dispensed); `next_due_date` is when the next cycle's supplies are due.
- Seed history: 90 days of `stock_txns`; batch `qty_on_hand` always equals the sum of that batch's `qty_delta`.

## Migrations

```bash
docker compose exec backend alembic revision --autogenerate -m "message"
docker compose exec backend alembic upgrade head
```
