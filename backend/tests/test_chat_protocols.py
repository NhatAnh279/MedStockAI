"""Chat tools and protocol upload/confirm. In-memory SQLite, no network."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import PlanStatus, Protocol, ProtocolItem
from app.services.chat import get_low_stock, get_order_status, get_patient_summary
from tests.test_forecast import make_item, make_patient, make_plan, make_supplier


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


def _protocol(session, name, icd, phase):
    p = Protocol(name=name, icd_code=icd, phase=phase, cycle_length_days=30, total_cycles=2)
    session.add(p)
    session.flush()
    return p


# ── chat tools ───────────────────────────────────────────────────────────────


def test_patient_summary_counts_active_plans_by_phase(session):
    intensive = _protocol(session, "TB - Intensive phase (2RHZE)", "A15.0", "intensive")
    maint = _protocol(session, "TB - Maintenance phase (4RH)", "A15.0", "maintenance")
    for proto, status in [
        (intensive, PlanStatus.active),
        (intensive, PlanStatus.active),
        (maint, PlanStatus.active),
        (maint, PlanStatus.completed),
    ]:
        make_plan(session, make_patient(session), proto, status=status)

    for cond in ("TB", "tuberculosis", "A15"):
        r = get_patient_summary(session, cond)
        assert r["patients_in_treatment"] == 3, cond
        assert r["by_phase"]["intensive"] == {"active": 2}
        assert r["by_phase"]["maintenance"] == {"active": 1, "completed": 1}


def test_patient_summary_unknown_condition_lists_protocols(session):
    _protocol(session, "TB - Intensive phase (2RHZE)", "A15.0", "intensive")
    r = get_patient_summary(session, "asthma")
    assert "error" in r and r["available_protocols"] == ["TB - Intensive phase (2RHZE)"]


def test_low_stock_and_orders_on_empty_db(session):
    assert get_low_stock(session, 30) == {"threshold_days": 30, "count": 0, "items": []}
    assert get_order_status(session)["count"] == 0


def test_chat_without_api_key_is_503(client):
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 503


# ── protocol upload / confirm ────────────────────────────────────────────────


def _upload(client, data: bytes, name="p.pdf", ctype="application/pdf"):
    return client.post("/protocols/upload", files={"file": (name, data, ctype)})


def test_upload_rejects_non_pdf(client):
    assert _upload(client, b"hello", "notes.txt", "text/plain").status_code == 415
    assert _upload(client, b"not really a pdf", "fake.pdf").status_code == 415


def test_upload_rejects_over_10mb(client):
    r = _upload(client, b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024 + 1))
    assert r.status_code == 413


def test_valid_pdf_without_api_key_is_503(client):
    assert _upload(client, b"%PDF-1.4\n%%EOF").status_code == 503


def _body(item_id, name="Anaemia - correction", phase="correction"):
    return {
        "protocols": [
            {
                "name": name,
                "icd_code": "D63.1",
                "phase": phase,
                "cycle_length_days": 28,
                "total_cycles": None,
                "items": [{"item_id": item_id, "qty_per_cycle": 12, "dose_per_kg": None}],
            }
        ]
    }


def test_confirm_saves_protocol_and_items(client, session):
    item = make_item(session, make_supplier(session))
    r = client.post("/protocols/confirm", json=_body(item.id))
    assert r.status_code == 201
    saved = r.json()["saved"][0]
    assert saved["item_count"] == 1
    proto = session.get(Protocol, saved["id"])
    assert proto.total_cycles is None and proto.cycle_length_days == 28
    pi = session.execute(select(ProtocolItem).where(ProtocolItem.protocol_id == proto.id)).scalar_one()
    assert (pi.item_id, pi.qty_per_cycle) == (item.id, 12)


def test_confirm_rejects_unknown_item_duplicate_and_bad_qty(client, session):
    item = make_item(session, make_supplier(session))
    assert client.post("/protocols/confirm", json=_body(9999)).status_code == 422
    bad_qty = _body(item.id)
    bad_qty["protocols"][0]["items"][0]["qty_per_cycle"] = 0
    assert client.post("/protocols/confirm", json=bad_qty).status_code == 422

    assert client.post("/protocols/confirm", json=_body(item.id)).status_code == 201
    assert client.post("/protocols/confirm", json=_body(item.id)).status_code == 409
