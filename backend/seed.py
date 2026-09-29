"""Populate every table with a realistic 90-day Australian hospital dataset. Re-runnable (truncates first).

All identifiers (ABNs, Medicare numbers, phone numbers, contacts, patient names) are synthetic:
ABNs and Medicare numbers pass their check-digit algorithms but are randomly generated, phone numbers
use the ACMA drama range (xx 5550 xxxx).
"""

import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import text

from app import models as m
from app.database import Base, SessionLocal, engine

random.seed(42)

TODAY = date.today()
DAYS = 90
START = TODAY - timedelta(days=DAYS)
UTC = timezone.utc


def at(d: date, hour: int | None = None) -> datetime:
    h = hour if hour is not None else random.randint(8, 16)
    return datetime.combine(d, time(h, random.randint(0, 59)), tzinfo=UTC)


def ceil_pack(n: float, pack: int) -> int:
    return math.ceil(n / pack) * pack


def make_abn() -> str:
    weights = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
    while True:
        d = [random.randint(1, 9)] + [random.randint(0, 9) for _ in range(10)]
        if (sum(w * x for w, x in zip(weights, [d[0] - 1] + d[1:]))) % 89 == 0:
            s = "".join(map(str, d))
            return f"{s[:2]} {s[2:5]} {s[5:8]} {s[8:]}"


def make_medicare(used: set[str]) -> str:
    """10 digits: 8 random (first 2-6), check digit, issue number. Printed as '2123 45670 1'."""
    while True:
        d = [random.randint(2, 6)] + [random.randint(0, 9) for _ in range(7)]
        check = sum(w * x for w, x in zip((1, 3, 7, 9, 1, 3, 7, 9), d)) % 10
        s = "".join(map(str, d)) + str(check) + str(random.randint(1, 9))
        if s not in used:
            used.add(s)
            return f"{s[:4]} {s[4:9]} {s[9]}"


# --------------------------------------------------------------------------- static data

SUPPLIERS = [
    dict(key="sig", name="Sigma Healthcare", email="hospitalorders@sigma.example", phone="+61 3 5550 0142",
         contact_person="Rebecca Hartley", address="25 Industrial Way, Laverton North VIC 3026",
         lead_time_days=3, payment_terms="NET-30", reliability_score=0.96, backup="sym"),
    dict(key="api", name="Australian Pharmaceutical Industries (API)", email="hospital.supply@api.example",
         phone="+61 2 5550 0187", contact_person="Daniel Foster",
         address="88 Logistics Drive, Huntingwood NSW 2148",
         lead_time_days=5, payment_terms="NET-45", reliability_score=0.93, backup="ch2"),
    dict(key="sym", name="Symbion", email="orders@symbion.example", phone="+61 7 5550 0123",
         contact_person="Priya Raman", address="15 Commerce Court, Eagle Farm QLD 4009",
         lead_time_days=7, payment_terms="NET-30", reliability_score=0.88, backup="sig"),
    dict(key="ch2", name="CH2", email="hospital@ch2.example", phone="+61 3 5550 0199",
         contact_person="Tom Kavanagh", address="60 Enterprise Boulevard, Dandenong South VIC 3175",
         lead_time_days=10, payment_terms="NET-45", reliability_score=0.80, backup="api"),
]

# code, name, type, unit, pack_size, moq, unit_cost (AUD), shelf_life_days, supplier
D, C = m.ItemType.drug, m.ItemType.consumable
ITEMS = [
    ("RIF", "Rifampicin 300mg (Rifadin) capsule", D, "capsule", 60, 600, 1.10, 1095, "sig"),
    ("INH", "Isoniazid 300mg tablet", D, "tablet", 100, 500, 0.25, 1095, "sig"),
    ("PZA", "Pyrazinamide 500mg tablet", D, "tablet", 100, 500, 0.80, 1095, "sig"),
    ("EMB", "Ethambutol 400mg (Myambutol) tablet", D, "tablet", 56, 560, 0.70, 1095, "sig"),
    ("DOXO", "Doxorubicin 50mg/25mL vial", D, "vial", 1, 10, 65.00, 730, "sym"),
    ("CYC", "Cyclophosphamide 1g vial", D, "vial", 1, 10, 32.00, 1095, "sym"),
    ("HEP", "Heparin sodium 5000IU/mL", D, "ampoule", 10, 50, 3.50, 730, "sym"),
    ("EPO", "Epoetin alfa 4000IU (Eprex) syringe", D, "syringe", 6, 30, 38.00, 730, "sym"),
    ("INS", "Insulin glargine (Lantus SoloStar) 100IU/mL 3mL pen", D, "pen", 5, 20, 12.80, 730, "sig"),
    ("MET", "Metformin 500mg tablet", D, "tablet", 100, 1000, 0.06, 1095, "sig"),
    ("BIC", "Bicarbonate concentrate dialysis solution", D, "litre", 10, 200, 1.15, 730, "sym"),
    ("ONDA", "Ondansetron 8mg/4mL injection", D, "ampoule", 10, 50, 1.80, 1095, "sig"),
    ("SYR5", "Syringe 5mL Luer lock", C, "each", 100, 500, 0.15, 1825, "api"),
    ("NACL", "Sodium chloride 0.9% 250mL IV bag", C, "bag", 20, 100, 1.90, 730, "api"),
    ("IVSET", "IV infusion set", C, "each", 50, 200, 1.60, 1825, "api"),
    ("CATH20", "IV cannula 20G", C, "each", 50, 100, 1.30, 1825, "api"),
    ("GLOVE", "Sterile gloves", C, "pair", 50, 200, 1.10, 1095, "api"),
    ("BLOODLINE", "Haemodialysis bloodline set", C, "set", 25, 100, 14.00, 1095, "ch2"),
    ("FISTULA", "AV fistula needle 15G", C, "each", 50, 100, 2.60, 1095, "ch2"),
    ("DIALYZER", "Dialyser (high-flux)", C, "each", 24, 48, 17.50, 1095, "ch2"),
    ("PENNEEDLE", "Insulin syringe 31G", C, "each", 100, 500, 0.45, 1825, "ch2"),
    ("STRIP", "Blood glucose test strip", C, "strip", 50, 200, 0.55, 540, "ch2"),
    ("LANCET", "Lancet", C, "each", 100, 500, 0.09, 1825, "ch2"),
    ("ALCOHOL", "Alcohol swab", C, "swab", 200, 1000, 0.04, 1095, "api"),
    ("N95", "N95 respirator", C, "each", 20, 100, 2.40, 1095, "api"),
    ("PARA", "Paracetamol 500mg", D, "tablet", 100, 100, 0.04, 730, "sig"),
]

# Items seeded with explicit QR-demo batches instead of the 90-day simulation.
QR_DEMO_ITEMS = {"PARA"}

# key -> (name, icd, phase, cycle_days, total_cycles, [(item_code, qty_per_cycle, dose_per_kg)])
PROTOCOLS = {
    "tb_int": ("TB - Intensive phase (2RHZE)", "A15.0", "intensive", 30, 2,
               [("RIF", 60, None), ("INH", 30, None), ("PZA", 90, None), ("EMB", 90, None),
                ("N95", 4, None), ("GLOVE", 2, None), ("ALCOHOL", 2, None), ("SYR5", 2, None)]),
    "tb_maint": ("TB - Maintenance phase (4RH)", "A15.0", "maintenance", 30, 4,
                 [("RIF", 60, None), ("INH", 30, None), ("N95", 4, None), ("GLOVE", 2, None)]),
    "chemo": ("Breast cancer - AC (Doxorubicin + Cyclophosphamide)", "C50.9", "AC", 21, 4,
              [("DOXO", 2, None), ("CYC", 1, None), ("ONDA", 3, None), ("NACL", 2, None),
               ("IVSET", 1, None), ("CATH20", 1, None), ("GLOVE", 2, None), ("ALCOHOL", 4, None),
               ("SYR5", 4, None)]),
    "hd": ("Haemodialysis (3x/week)", "N18.5", "maintenance", 2, None,
           [("DIALYZER", 1, None), ("BLOODLINE", 1, None), ("FISTULA", 2, None), ("HEP", 1, None),
            ("EPO", 1, None), ("BIC", 8, None), ("NACL", 2, None), ("IVSET", 1, None),
            ("GLOVE", 2, None), ("ALCOHOL", 4, None), ("SYR5", 2, None)]),
    "ins": ("T2DM - Insulin glargine", "E11.9", "basal_insulin", 30, None,
            # 0.3 IU/kg/day * 30 days / 300 IU per pen = 0.03 pens per kg per cycle
            [("INS", 2, 0.03), ("PENNEEDLE", 30, None), ("STRIP", 60, None), ("LANCET", 60, None),
             ("ALCOHOL", 60, None)]),
    "oral": ("T2DM - Metformin", "E11.9", "oral", 30, None,
             [("MET", 60, None), ("STRIP", 30, None), ("LANCET", 30, None), ("ALCOHOL", 30, None)]),
}

# Items deliberately left with only a few days of cover / with a batch about to expire.
TIGHT_STOCK = {"INS", "RIF", "HEP", "DIALYZER", "STRIP"}
NEAR_EXPIRY = ["EPO", "ONDA", "DOXO", "HEP", "NACL", "BIC"]

FEMALE_NAMES = ["Olivia", "Charlotte", "Amelia", "Isla", "Mia", "Grace", "Chloe", "Sophie", "Emily", "Hannah",
                "Jessica", "Sarah", "Priya", "Mei", "Linh", "Aroha", "Eleni", "Maria", "Fatima", "Kylie",
                "Michelle", "Karen", "Donna", "Tracey", "Lauren", "Jennifer", "Margaret", "Sandra", "Anh", "Sunita"]
MALE_NAMES = ["Oliver", "Jack", "William", "Noah", "Lachlan", "Thomas", "Liam", "Ethan", "Mitchell", "Daniel",
              "Minh", "Wei", "Rohan", "Arjun", "Dimitri", "Giuseppe", "Tane", "Ahmed", "Brett", "Craig",
              "Wayne", "Shane", "Gary", "Trevor", "Andrew", "Peter", "Robert", "David", "Hung", "Vikram"]
SURNAMES = ["Smith", "Jones", "Williams", "Brown", "Wilson", "Taylor", "Anderson", "Thompson", "Martin",
            "Campbell", "Nguyen", "Tran", "Le", "Chen", "Wang", "Singh", "Patel", "Kumar", "Papadopoulos",
            "Rossi", "Ferrari", "Kelly", "O'Brien", "Murphy", "Ryan", "Walker", "Hughes", "Harris",
            "Robinson", "Clarke", "Mitchell", "Kaur", "Hussain", "Ali", "Tupou", "Whitehead", "Stewart",
            "Fraser", "Baker", "Morgan"]


# --------------------------------------------------------------------------- seeding steps


def reset_db() -> None:
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))


def seed_suppliers_items(s):
    suppliers = {}
    for d in SUPPLIERS:
        fields = {k: v for k, v in d.items() if k not in ("key", "backup")}
        suppliers[d["key"]] = m.Supplier(abn=make_abn(), **fields)
    s.add_all(suppliers.values())
    s.flush()
    for d in SUPPLIERS:
        suppliers[d["key"]].backup_supplier_id = suppliers[d["backup"]].id

    items = {}
    for code, name, typ, unit, pack, moq, cost, shelf, sup in ITEMS:
        items[code] = m.Item(name=name, type=typ, unit=unit, pack_size=pack, moq=moq, unit_cost=cost,
                             shelf_life_days=shelf, supplier_id=suppliers[sup].id)
    s.add_all(items.values())
    s.flush()

    valid_from, valid_to = TODAY - timedelta(days=180), TODAY + timedelta(days=185)
    sup_by_id = {sp.id: sp for sp in suppliers.values()}
    for code, *_ in ITEMS:
        it = items[code]
        default = sup_by_id[it.supplier_id]
        base = float(it.unit_cost)
        s.add(m.SupplierPrice(supplier_id=default.id, item_id=it.id, unit_price=base, currency="AUD",
                              valid_from=valid_from, valid_to=valid_to, min_order_qty=it.moq))
        s.add(m.SupplierPrice(supplier_id=default.backup_supplier_id, item_id=it.id, currency="AUD",
                              unit_price=round(base * random.uniform(1.03, 1.12), 4),
                              valid_from=valid_from, valid_to=valid_to, min_order_qty=it.moq * 2))
    s.flush()
    return suppliers, items


def seed_protocols(s, items):
    protocols = {}
    for key, (name, icd, phase, cycle, total, pitems) in PROTOCOLS.items():
        p = m.Protocol(name=name, icd_code=icd, phase=phase, cycle_length_days=cycle, total_cycles=total)
        s.add(p)
        s.flush()
        for code, qty, dose in pitems:
            s.add(m.ProtocolItem(protocol_id=p.id, item_id=items[code].id, qty_per_cycle=qty, dose_per_kg=dose))
        protocols[key] = p
    s.flush()
    return protocols


def cycle_items(key: str, weight: float):
    out = []
    for code, qty, dose in PROTOCOLS[key][5]:
        out.append((code, math.ceil(dose * weight) if dose else qty))
    return out


# group key, n, age range, share female, weight range (kg), extra comorbidities [(icd, prob)]
GROUPS = [
    ("tb_int", 8, (18, 70), 0.45, (45, 80), []),
    ("tb_maint", 6, (18, 70), 0.45, (45, 82), []),
    ("chemo", 10, (35, 70), 1.0, (55, 95), []),
    ("hd", 12, (35, 80), 0.4, (55, 100), [("I10", 0.6), ("E11.2", 0.3)]),
    ("ins", 12, (40, 75), 0.5, (65, 110), [("I10", 0.4), ("E78.5", 0.3)]),
    ("oral", 12, (35, 75), 0.5, (65, 115), [("I10", 0.4), ("E78.5", 0.3)]),
]
TB_MAINT_CYCLES = [1, 2, 3, 4, 4, 4]
TB_MAINT_COMPLETED = {4, 5}
CHEMO_CYCLES = [1, 1, 2, 2, 2, 3, 3, 3, 4, 4]
CHEMO_PAUSED = {4, 7}


def seed_patients(s, protocols, items):
    """Returns per-item daily dispense demand (item_code -> date -> qty)."""
    demand = defaultdict(lambda: defaultdict(int))
    used_medicare: set[str] = set()
    used_names: set[str] = set()

    def unique_name(sex: str) -> str:
        while True:
            first = random.choice(FEMALE_NAMES if sex == "F" else MALE_NAMES)
            name = f"{first} {random.choice(SURNAMES)}"
            if name not in used_names:
                used_names.add(name)
                return name

    for key, n, age, p_female, wrange, extras in GROUPS:
        proto = protocols[key]
        L = proto.cycle_length_days
        for idx in range(n):
            sex = "F" if random.random() < p_female else "M"
            weight = round(random.uniform(*wrange), 1)
            dob = TODAY - timedelta(days=random.randint(*age) * 365 + random.randint(0, 364))
            patient = m.Patient(medicare_no=make_medicare(used_medicare), full_name=unique_name(sex),
                                dob=dob, sex=sex, weight_kg=weight)
            s.add(patient)
            s.flush()

            status = m.PlanStatus.active
            if key == "tb_int":
                cycle = random.choice([1, 2])
            elif key == "tb_maint":
                cycle = TB_MAINT_CYCLES[idx]
                if idx in TB_MAINT_COMPLETED:
                    status = m.PlanStatus.completed
            elif key == "chemo":
                cycle = CHEMO_CYCLES[idx]
                if idx in CHEMO_PAUSED:
                    status = m.PlanStatus.paused
            elif key == "hd":
                cycle = random.randint(20, 150)
            elif key == "ins":
                cycle = random.randint(2, 30)
            else:
                cycle = random.randint(1, 36)

            if status == m.PlanStatus.completed:
                last = TODAY - timedelta(days=random.randint(31, 60))
                next_due = None
            else:
                last = TODAY - timedelta(days=random.randint(1, L))
                next_due = last + timedelta(days=L)

            events = [(key, last - timedelta(days=L * k)) for k in range(cycle)]
            if key == "tb_maint":
                first = last - timedelta(days=L * (cycle - 1))
                events += [("tb_int", first - timedelta(days=30 * k)) for k in (1, 2)]
            for ekey, d in events:
                if d >= START:
                    for code, qty in cycle_items(ekey, weight):
                        demand[code][d] += qty

            diagnosed = TODAY - timedelta(days=cycle * L + random.randint(0, 30))
            if key in ("ins", "oral"):
                diagnosed = TODAY - timedelta(days=random.randint(365 * (5 if key == "ins" else 1), 365 * 15))
            cond_status = "resolved" if status == m.PlanStatus.completed else "active"
            s.add(m.Condition(patient_id=patient.id, icd_code=proto.icd_code, diagnosed_at=diagnosed,
                              status=cond_status))
            for icd, prob in extras:
                if random.random() < prob:
                    s.add(m.Condition(patient_id=patient.id, icd_code=icd,
                                      diagnosed_at=TODAY - timedelta(days=random.randint(180, 365 * 10)),
                                      status="active"))
            s.add(m.TreatmentPlan(patient_id=patient.id, protocol_id=proto.id, current_phase=proto.phase,
                                  current_cycle=cycle, next_due_date=next_due, status=status))
    s.flush()
    return demand


def simulate_item(s, item, code, per_day):
    """Walk 90 days: scheduled receives, FIFO dispensing, emergency top-ups, waste/adjust.

    Returns (lots, receives) where lots = [{"batch", "qty"}] and receives = [(date, qty, emergency)].
    """
    pack, moq = item.pack_size, item.moq
    rate = sum(per_day.values()) / DAYS
    tight = code in TIGHT_STOCK
    lots: list[dict] = []
    receives: list[tuple[date, int, bool]] = []
    seq = 0

    def stock() -> int:
        return sum(lot["qty"] for lot in lots)

    def receive(day: date, qty: int, hour: int, emergency: bool = False) -> dict:
        nonlocal seq
        seq += 1
        expiry = day + timedelta(days=int(item.shelf_life_days * random.uniform(0.5, 0.9)))
        batch = m.Batch(item=item, lot_no=f"{code}-{day:%y%m}{chr(64 + seq)}{random.randint(10, 99)}",
                        qty_on_hand=0, expiry_date=expiry, received_at=at(day, hour))
        s.add(batch)
        s.add(m.StockTxn(item=item, batch=batch, qty_delta=qty, reason=m.TxnReason.receive,
                         created_at=at(day, hour)))
        lot = {"batch": batch, "qty": qty}
        lots.append(lot)
        receives.append((day, qty, emergency))
        return lot

    def consume(day: date, qty: int, reason: m.TxnReason, hour: int | None = None) -> int:
        for lot in lots:
            if qty <= 0:
                break
            take = min(lot["qty"], qty)
            if take:
                lot["qty"] -= take
                qty -= take
                s.add(m.StockTxn(item=item, batch=lot["batch"], qty_delta=-take, reason=reason,
                                 created_at=at(day, hour)))
        return qty

    receive_idx = [0, random.randint(26, 32), random.randint(56, 62), random.randint(80, 85)]
    end_cover_days = random.randint(2, 5) if tight else random.randint(10, 35)
    waste_idx = random.randrange(DAYS) if random.random() < 0.4 else None
    adjust_idx = random.randrange(DAYS) if random.random() < 0.25 else None

    for i in range(DAYS):
        day = START + timedelta(days=i)
        if i in receive_idx:
            if i == 0:
                n = ceil_pack(max(moq, rate * (34 if tight else 36)), pack)
            elif i == receive_idx[-1]:
                future = sum(v for d, v in per_day.items() if d >= day)
                need = end_cover_days * rate + future - stock()
                n = 0 if tight or need <= 0 else max(ceil_pack(need, pack), moq)
            else:
                n = ceil_pack(max(moq, rate * (29 if tight else 30)), pack)
            if n > 0:
                receive(day, n, 7)

        want = per_day.get(day, 0)
        if want:
            short = consume(day, want, m.TxnReason.dispense)
            if short > 0:
                lot = receive(day, ceil_pack(short + rate * 3, pack), 6, emergency=True)
                lot["qty"] -= short
                s.add(m.StockTxn(item=item, batch=lot["batch"], qty_delta=-short, reason=m.TxnReason.dispense,
                                 created_at=at(day)))

        if i == waste_idx:
            consume(day, random.randint(1, max(2, int(rate * 1.5))), m.TxnReason.waste, hour=17)
        if i == adjust_idx:
            delta = random.choice([-3, -2, -1, 1, 2])
            live = next((lot for lot in lots if lot["qty"] > 0), None)
            if live and (delta > 0 or live["qty"] >= -delta):
                live["qty"] += delta
                s.add(m.StockTxn(item=item, batch=live["batch"], qty_delta=delta, reason=m.TxnReason.adjust,
                                 created_at=at(day, 17)))

    for lot in lots:
        lot["batch"].qty_on_hand = lot["qty"]
    return lots, receives


def seed_stock(s, items, demand):
    all_lots, all_receives = {}, {}
    for code, item in items.items():
        if code in QR_DEMO_ITEMS:
            all_lots[code] = []   # explicit batches seeded separately
            all_receives[code] = []
            continue
        all_lots[code], all_receives[code] = simulate_item(s, item, code, demand[code])

    for code in NEAR_EXPIRY:
        live = next(lot for lot in all_lots[code] if lot["qty"] > 0)
        live["batch"].expiry_date = TODAY + timedelta(days=random.randint(3, 13))
    s.flush()
    return all_lots, all_receives


def make_po(s, supplier, lines, status, created_by, created_at, rationale):
    """lines: [(item, qty, unit_price)]; rationale: callable(item, qty) -> str."""
    po = m.PurchaseOrder(supplier_id=supplier.id, status=status, created_by=created_by,
                         total=round(sum(q * p for _, q, p in lines), 2), created_at=created_at)
    s.add(po)
    s.flush()
    for item, qty, price in lines:
        s.add(m.POLine(po_id=po.id, item_id=item.id, qty=qty, unit_price=price, rationale=rationale(item, qty)))
    return po


def seed_purchasing(s, suppliers, items, all_lots, all_receives, demand):
    sup_by_id = {sp.id: sp for sp in suppliers.values()}
    code_of = {it.id: c for c, it in items.items()}

    # Historic POs that produced the receives in the stock ledger.
    grouped = defaultdict(list)
    for code, receives in all_receives.items():
        for day, qty, emergency in receives:
            grouped[(items[code].supplier_id, day)].append((items[code], qty, emergency))
    for (sup_id, day), rows in sorted(grouped.items(), key=lambda kv: kv[0][1]):
        supplier = sup_by_id[sup_id]
        placed = at(day - timedelta(days=supplier.lead_time_days), 9)
        emergency = all(e for _, _, e in rows)
        rationale = (lambda it, q: "Urgent replenishment: stock reached zero") if emergency else \
                    (lambda it, q: "Routine reorder based on 30-day demand")
        make_po(s, supplier, [(it, q, float(it.unit_cost)) for it, q, _ in rows], m.POStatus.received,
                m.POCreator.human, placed, rationale)

    # AI-drafted POs for items whose cover is shorter than lead time + buffer.
    on_hand = {c: sum(l["qty"] for l in lots) for c, lots in all_lots.items()}
    rate30 = {c: sum(v for d, v in demand[c].items() if d >= TODAY - timedelta(days=30)) / 30 for c in items}
    cover = {c: on_hand[c] / rate30[c] if rate30[c] else 999 for c in items}

    by_supplier = defaultdict(list)
    for c, it in items.items():
        lead = sup_by_id[it.supplier_id].lead_time_days
        if cover[c] < lead + 10:
            need = rate30[c] * (45 + lead) - on_hand[c]
            qty = max(ceil_pack(need, it.pack_size), it.moq)
            by_supplier[it.supplier_id].append((it, qty, c))

    def ai_reason(it, qty):
        c = code_of[it.id]
        lead = sup_by_id[it.supplier_id].lead_time_days
        return (f"On hand {on_hand[c]} {it.unit} ≈ {cover[c]:.1f} days (avg demand {rate30[c]:.1f}/day, "
                f"lead time {lead} days). Suggest ordering {qty} {it.unit} to cover ~45 days.")

    ai_pos = []
    statuses = [m.POStatus.pending_approval, m.POStatus.pending_approval, m.POStatus.draft, m.POStatus.draft]
    for n, (sup_id, rows) in enumerate(sorted(by_supplier.items())):
        po = make_po(s, sup_by_id[sup_id], [(it, q, float(it.unit_cost)) for it, q, _ in rows],
                     statuses[n % len(statuses)], m.POCreator.ai, at(TODAY, 6), ai_reason)
        ai_pos.append((po, rows))

    # One PO already sent (AI-drafted, user approved) and one confirmed (human).
    n95, nacl = items["N95"], items["NACL"]
    sent = make_po(s, suppliers["api"], [(n95, 400, float(n95.unit_cost)), (nacl, 300, float(nacl.unit_cost))],
                   m.POStatus.sent, m.POCreator.ai, at(TODAY - timedelta(days=2), 8),
                   lambda it, q: f"Forecast demand for {it.name} rising with treatment schedule; "
                                 f"ordering {q} {it.unit} (~30 days).")
    met, emb = items["MET"], items["EMB"]
    confirmed = make_po(s, suppliers["sig"], [(met, 3000, float(met.unit_cost)), (emb, 1120, float(emb.unit_cost))],
                        m.POStatus.confirmed, m.POCreator.human, at(TODAY - timedelta(days=2), 10),
                        lambda it, q: "Routine reorder based on 30-day demand")
    s.flush()
    return ai_pos, sent, confirmed, on_hand, rate30, cover


def seed_qr_demo_batches(s, items):
    """Create Paracetamol batches and 30 days of usage history for the anomaly engine."""
    from sqlalchemy import select as sa_select, func as sa_func
    para = items["PARA"]

    # Idempotency guard — skip if batches already exist (e.g. called on a live DB).
    already = s.execute(sa_select(sa_func.count(m.Batch.id)).where(m.Batch.item_id == para.id)).scalar()
    if already:
        return

    received_at = datetime.combine(date(2024, 6, 1), time(9, 0), tzinfo=UTC)
    # LOT-PARA-2024-B expires sooner — FEFO will pick it first.
    b_sooner = m.Batch(item=para, lot_no="LOT-PARA-2024-B", qty_on_hand=200,
                       expiry_date=date(2026, 12, 15), received_at=received_at)
    b_later  = m.Batch(item=para, lot_no="LOT-PARA-2024-A", qty_on_hand=500,
                       expiry_date=date(2027, 6, 30), received_at=received_at)
    s.add_all([b_sooner, b_later])
    s.flush()

    # ── 30-day history ──────────────────────────────────────────────────────────
    now = datetime.now(UTC)
    day_minus_30 = now - timedelta(days=30)

    # Pharmacy initial receive 30 days ago — establishes the stock context.
    s.add(m.StockTxn(item=para, batch=b_later, qty_delta=1000, reason=m.TxnReason.receive,
                     department="Pharmacy", created_at=day_minus_30.replace(hour=8, minute=0, second=0)))

    # Daily dispenses over the last 30 days — gives the anomaly engine a clear baseline:
    #   Ward A  avg = 10 / day  →  dispensing 500 =  50x avg  → warning
    #   Ward B  avg =  5 / day  →  dispensing 500 = 100x avg  → warning
    #   ICU     avg =  2 / day  →  dispensing 500 = 250x avg  → warning (or alert)
    dept_daily = [("Ward A", 10), ("Ward B", 5), ("ICU", 2)]
    for day_offset in range(30):
        txn_dt = now - timedelta(days=30 - day_offset)
        txn_dt = txn_dt.replace(hour=10, minute=0, second=0, microsecond=0)
        for dept, qty in dept_daily:
            s.add(m.StockTxn(item=para, batch=b_sooner, qty_delta=-qty, reason=m.TxnReason.dispense,
                             department=dept, created_at=txn_dt))

    s.flush()


def seed_forecast_audit(s, items, ai_pos, sent, confirmed, on_hand, rate30, cover):
    snapshot = {
        "source": "seed-baseline (30-day moving average of dispense history)",
        "items": [
            {"item_id": it.id, "name": it.name, "on_hand": on_hand[c], "avg_daily_demand": round(rate30[c], 2),
             "projected_demand_horizon": round(rate30[c] * 30), "days_of_cover": round(cover[c], 1)}
            for c, it in items.items()
        ],
    }
    s.add(m.ForecastRun(run_at=at(TODAY, 6), horizon_days=30, snapshot=snapshot))

    for po, rows in ai_pos:
        s.add(m.AuditLog(actor=m.Actor.ai, action="create_po", entity="purchase_orders", entity_id=po.id,
                         before=None, after={"status": po.status.value, "supplier_id": po.supplier_id,
                                             "lines": len(rows), "total": float(po.total)},
                         ts=at(TODAY, 6)))
        for it, _, c in rows:
            s.add(m.AuditLog(actor=m.Actor.ai, action="flag_low_stock", entity="items", entity_id=it.id,
                             before=None, after={"on_hand": on_hand[c], "days_of_cover": round(cover[c], 1)},
                             ts=at(TODAY, 6)))
    s.add(m.AuditLog(actor=m.Actor.ai, action="create_po", entity="purchase_orders", entity_id=sent.id,
                     before=None, after={"status": "pending_approval", "total": float(sent.total)},
                     ts=at(TODAY - timedelta(days=2), 8)))
    s.add(m.AuditLog(actor=m.Actor.user, action="approve_po", entity="purchase_orders", entity_id=sent.id,
                     before={"status": "pending_approval"}, after={"status": "sent"},
                     ts=at(TODAY - timedelta(days=2), 9)))
    s.add(m.AuditLog(actor=m.Actor.user, action="update_po_status", entity="purchase_orders",
                     entity_id=confirmed.id, before={"status": "sent"}, after={"status": "confirmed"},
                     ts=at(TODAY - timedelta(days=1), 11)))


def main() -> None:
    reset_db()
    with SessionLocal() as s:
        suppliers, items = seed_suppliers_items(s)
        protocols = seed_protocols(s, items)
        demand = seed_patients(s, protocols, items)
        all_lots, all_receives = seed_stock(s, items, demand)
        seed_qr_demo_batches(s, items)
        po_out = seed_purchasing(s, suppliers, items, all_lots, all_receives, demand)
        seed_forecast_audit(s, items, *po_out)
        s.commit()

    with engine.connect() as conn:
        print("Seeded:")
        for t in Base.metadata.sorted_tables:
            print(f"  {t.name:22s} {conn.execute(text(f'SELECT COUNT(*) FROM {t.name}')).scalar():>6}")


if __name__ == "__main__":
    main()
