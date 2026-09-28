"""PO workflow tests: generate -> approve (simulated supplier reply) -> receive.

In-memory SQLite, no network; the LLM layer runs its deterministic fallbacks.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Batch, PurchaseOrder, Supplier
from app.services.llm import parse_supplier_reply
from app.services.simulator import simulate_supplier_reply
from tests.test_forecast import (
    make_item,
    make_patient,
    make_plan,
    make_protocol,
    make_protocol_item,
    make_supplier,
)


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_db] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def seed_needing_order(session, reliability: float) -> tuple[Supplier, Supplier]:
    """One item with scheduled demand and zero stock, so the forecast asks for an order."""
    backup = make_supplier(session)
    backup.name = "Backup Pharma"
    supplier = make_supplier(session)
    supplier.name = "Primary Pharma"
    supplier.reliability_score = reliability
    supplier.backup_supplier_id = backup.id
    item = make_item(session, supplier)
    proto = make_protocol(session)
    make_protocol_item(session, proto, item, qty_per_cycle=60)
    make_plan(session, make_patient(session), proto, next_due_offset_days=10)
    session.commit()
    return supplier, backup


# ── parser / simulator ───────────────────────────────────────────────────────

LINES = [
    {"item_id": 1, "item_name": "Rifampicin 300mg", "qty": 600},
    {"item_id": 2, "item_name": "Isoniazid 100mg", "qty": 300},
]


def test_parse_full_and_partial_reply():
    full = "- Rifampicin 300mg: confirmed 600 of 600 units\n- Isoniazid 100mg: confirmed 300 of 300 units"
    assert parse_supplier_reply(full, LINES)["status"] == "full"

    partial = "- Rifampicin 300mg: confirmed 240 of 600 units\n- Isoniazid 100mg: confirmed 300 of 300 units\nNote: rest on backorder"
    parsed = parse_supplier_reply(partial, LINES)
    assert parsed["status"] == "partial"
    assert parsed["lines"][0]["confirmed_qty"] == 240
    assert parsed["notes"] == "rest on backorder"


def test_parse_unrecognised_reply_is_unparsed():
    assert parse_supplier_reply("Thanks, will look into it.", LINES)["status"] == "unparsed"


def test_simulator_round_trips_through_parser_and_is_deterministic():
    lines = [{"item_name": l["item_name"], "qty": l["qty"], "pack_size": 60} for l in LINES]
    args = dict(po_id=7, supplier_name="S", contact_person=None, lead_time_days=5, lines=lines)

    always_short = simulate_supplier_reply(reliability_score=0.0, **args)
    assert always_short == simulate_supplier_reply(reliability_score=0.0, **args)
    parsed = parse_supplier_reply(always_short, LINES)
    assert parsed["status"] == "partial"
    assert all(l["confirmed_qty"] % 60 == 0 for l in parsed["lines"])

    assert parse_supplier_reply(simulate_supplier_reply(reliability_score=1.0, **args), LINES)["status"] == "full"


# ── workflow ─────────────────────────────────────────────────────────────────


def test_generate_creates_draft_po_with_rationale_and_is_not_duplicated(client, session):
    seed_needing_order(session, reliability=1.0)

    res = client.post("/purchase-orders/generate")
    assert res.status_code == 201
    body = res.json()
    assert body["created"] == 1

    po = client.get(f"/purchase-orders/{body['po_ids'][0]}").json()
    assert po["status"] == "draft" and po["created_by"] == "ai"
    line = po["lines"][0]
    assert line["qty"] == 600  # MOQ
    assert line["rationale"] and "Rifampicin" in line["rationale"]
    assert po["total"] == pytest.approx(line["qty"] * line["unit_price"])

    again = client.post("/purchase-orders/generate").json()
    assert again["created"] == 0
    assert again["skipped_items"] == ["Rifampicin 300mg"]


def test_full_flow_full_delivery(client, session):
    seed_needing_order(session, reliability=1.0)
    po_id = client.post("/purchase-orders/generate").json()["po_ids"][0]

    po = client.patch(f"/purchase-orders/{po_id}/approve").json()
    assert po["status"] == "confirmed"
    assert po["reply_parsed"]["status"] == "full"
    assert po["supplier_reply"].startswith("Subject: Re: Purchase Order")
    assert po["backup_po_id"] is None

    assert client.patch(f"/purchase-orders/{po_id}/approve").status_code == 409  # not re-approvable

    recv = client.post(f"/purchase-orders/{po_id}/receive")
    assert recv.status_code == 200
    assert recv.json()["po"]["status"] == "received"
    assert recv.json()["units_received"] == 600
    assert session.execute(select(Batch.qty_on_hand)).scalar() == 600

    assert client.post(f"/purchase-orders/{po_id}/receive").status_code == 409  # only once


def test_partial_reply_creates_backup_po_and_receives_confirmed_qty_only(client, session):
    supplier, backup = seed_needing_order(session, reliability=0.0)
    po_id = client.post("/purchase-orders/generate").json()["po_ids"][0]

    po = client.patch(f"/purchase-orders/{po_id}/approve").json()
    assert po["status"] == "confirmed"
    assert po["reply_parsed"]["status"] == "partial"
    confirmed = po["reply_parsed"]["lines"][0]["confirmed_qty"]
    assert 0 < confirmed < 600

    backup_po = client.get(f"/purchase-orders/{po['backup_po_id']}").json()
    assert backup_po["status"] == "draft"
    assert backup_po["backup_of_po_id"] == po_id
    assert backup_po["supplier"]["id"] == backup.id  # routed to the backup supplier
    assert backup_po["lines"][0]["qty"] == 600 - confirmed

    recv = client.post(f"/purchase-orders/{po_id}/receive").json()
    assert recv["units_received"] == confirmed

    listing = client.get("/purchase-orders").json()
    assert {p["id"] for p in listing} == {po_id, backup_po["id"]}


def test_unknown_po_is_404(client):
    assert client.get("/purchase-orders/999").status_code == 404
    assert client.post("/purchase-orders/999/receive").status_code == 404
