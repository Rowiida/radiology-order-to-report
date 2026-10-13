#!/usr/bin/env python3
"""Generate SYNTHETIC radiology order-to-report data as CSV files.

No real patient or hospital data is used. All timings come from the assumptions
written in this file (see ASSUMPTIONS below), so the results show that the
method can surface delays, not how any real hospital performs.

Usage:  python3 generate_data.py [output_dir]
"""
import csv
import math
import os
import random
import sys
from datetime import datetime, timedelta

SEED = 42
N_ORDERS = 5000
START = datetime(2026, 7, 1)
DAYS = 92                       # 1 Jul - 30 Sep 2026
OUT = sys.argv[1] if len(sys.argv) > 1 else "data"

# ---------------------------------------------------------------------------
# ASSUMPTIONS (change these and re-run to test other situations)
# ---------------------------------------------------------------------------
P_CANCELLED = 0.02              # share of orders cancelled before the exam
P_ORDER_NOT_RECEIVED = 0.03     # EMR -> RIS order message fails, fixed later
P_PATIENT_ID_MISMATCH = 0.02    # images not linked to the order in PACS
P_RESULT_NOT_DELIVERED = 0.03   # RIS -> EMR result message fails, fixed later
NIGHT_START, NIGHT_END = 19, 7  # radiologist cover is thinner at night
# Median minutes from IMAGES_IN_PACS to REPORT_DRAFTED, before shift effects
READ_MEDIAN = {"STAT": 15, "URGENT": 60, "ROUTINE": 240}
READ_MODALITY_FACTOR = {"XR": 0.7, "CT": 1.0, "MR": 1.5}
NIGHT_FACTOR = {"STAT": 1.6, "URGENT": 2.2}   # routine night studies wait for the morning
WEEKEND_FACTOR = 1.4            # Sat/Sun, non-STAT (UAE weekend)
# ---------------------------------------------------------------------------

rng = random.Random(SEED)
M = timedelta(minutes=1)


def lognorm(median, sigma):
    return median * math.exp(rng.gauss(0, sigma))


def clip(x, lo, hi):
    return max(lo, min(hi, x))


def pick(options, weights):
    return rng.choices(options, weights=weights, k=1)[0]


# ---- reference data -------------------------------------------------------
EXAMS = [
    ("XR-CHEST", "Chest X-ray, 2 views", "XR", "Chest", 30),
    ("XR-ABD", "Abdomen X-ray", "XR", "Abdomen", 10),
    ("XR-KNEE", "Knee X-ray", "XR", "Knee", 15),
    ("XR-SPINE-L", "Lumbar spine X-ray", "XR", "Spine", 10),
    ("XR-HAND", "Hand X-ray", "XR", "Hand", 10),
    ("CT-HEAD", "CT head without contrast", "CT", "Head", 25),
    ("CT-CHEST", "CT chest", "CT", "Chest", 15),
    ("CT-ABD-PELVIS", "CT abdomen and pelvis with contrast", "CT", "Abdomen", 20),
    ("CT-CHEST-ANGIO", "CT chest angiography", "CT", "Chest", 10),
    ("MR-BRAIN", "MRI brain", "MR", "Head", 40),
    ("MR-SPINE-L", "MRI lumbar spine", "MR", "Spine", 35),
    ("MR-KNEE", "MRI knee", "MR", "Knee", 25),
]
INDICATIONS = {
    "Chest": ["Cough and fever", "Shortness of breath", "Chest pain", "Follow-up of known finding"],
    "Abdomen": ["Abdominal pain", "Vomiting", "Suspected obstruction", "Follow-up of known finding"],
    "Knee": ["Knee pain after fall", "Swelling", "Sports injury"],
    "Spine": ["Low back pain", "Radiating leg pain", "Trauma"],
    "Hand": ["Injury", "Pain and swelling"],
    "Head": ["Head injury", "Headache", "Dizziness", "Suspected stroke"],
}
EXAMS_BY_MOD = {m: [e for e in EXAMS if e[2] == m] for m in ("XR", "CT", "MR")}
DEPTS = ["Emergency", "Internal Medicine", "Surgery", "Orthopedics", "Neurology", "Oncology"]

providers = []   # (id, code, role, department)
for i in range(1, 41):
    providers.append((len(providers) + 1, f"DR-{i:03d}", "ORDERING_DOCTOR", DEPTS[i % len(DEPTS)]))
doctor_ids = [p[0] for p in providers if p[2] == "ORDERING_DOCTOR"]
for i in range(1, 13):
    providers.append((len(providers) + 1, f"RAD-{i:02d}", "RADIOLOGIST", "Radiology"))
radiologist_ids = [p[0] for p in providers if p[2] == "RADIOLOGIST"]
for i in range(1, 21):
    providers.append((len(providers) + 1, f"TECH-{i:02d}", "RADIOGRAPHER", "Radiology"))
radiographer_ids = [p[0] for p in providers if p[2] == "RADIOGRAPHER"]

patients = []    # (id, mrn, birth_year, sex)
for i in range(1, 3501):
    patients.append((i, f"SYN-{100000 + i}", rng.randint(1935, 2010), rng.choice("FM")))

HOUR_W = {
    "ED": [2, 1.5, 1.2, 1, 1, 1.2, 2, 3, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4, 3.5, 3, 2.5],
    "INPATIENT": [0, 0, 0, 0, 0, 0, 2, 4, 6, 6, 6, 5, 5, 5, 5, 4, 3, 2, 2, 1, 0, 0, 0, 0],
    "OUTPATIENT": [0, 0, 0, 0, 0, 0, 0, 3, 5, 6, 6, 6, 5, 5, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0],
}
PRIORITY_W = {
    "ED": (["STAT", "URGENT", "ROUTINE"], [0.30, 0.50, 0.20]),
    "INPATIENT": (["STAT", "URGENT", "ROUTINE"], [0.10, 0.35, 0.55]),
    "OUTPATIENT": (["URGENT", "ROUTINE"], [0.10, 0.90]),
}

MSG = {
    "ORDERED": ("EMR", "HL7 ORM^O01 (new order)"),
    "RECEIVED_RIS": ("RIS", "HL7 ORM^O01 (acknowledged)"),
    "SCHEDULED": ("RIS", "HL7 SIU^S12 (appointment booked)"),
    "ARRIVED": ("RIS", "RIS check-in"),
    "EXAM_STARTED": ("MODALITY", "DICOM MPPS (in progress)"),
    "EXAM_COMPLETED": ("MODALITY", "DICOM MPPS (completed)"),
    "IMAGES_IN_PACS": ("PACS", "DICOM C-STORE"),
    "REPORT_DRAFTED": ("RIS", "RIS report draft saved"),
    "REPORT_SIGNED": ("RIS", "HL7 ORU^R01 (final report)"),
    "RESULT_IN_EMR": ("EMR", "HL7 ORU^R01 (result filed)"),
    "CANCELLED": ("EMR", "HL7 ORM^O01 (cancel)"),
}


def is_night(t):
    return t.hour >= NIGHT_START or t.hour < NIGHT_END


def next_morning(t):
    d = t.replace(hour=8, minute=0, second=0, microsecond=0)
    return d if t.hour < NIGHT_END else d + timedelta(days=1)


orders, studies, reports, events, errors = [], [], [], [], []
used_acc = set()

for oid in range(1, N_ORDERS + 1):
    cls = pick(["ED", "INPATIENT", "OUTPATIENT"], [0.30, 0.25, 0.45])
    pri = pick(*PRIORITY_W[cls])
    mod = pick(["XR", "CT", "MR"], [0.55, 0.30, 0.15])
    exam = rng.choice(EXAMS_BY_MOD[mod])
    day = START + timedelta(days=rng.randrange(DAYS))
    hour = pick(list(range(24)), HOUR_W[cls])
    t0 = day.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60))
    pid = rng.randint(1, len(patients))
    doc = rng.choice(doctor_ids)
    indication = rng.choice(INDICATIONS[exam[3]])

    ev = [("ORDERED", t0)]

    # 1. EMR -> RIS
    d = clip(lognorm(1.0, 0.5), 0.2, 8)
    failed = rng.random() < P_ORDER_NOT_RECEIVED
    if failed:
        d = rng.uniform(20, 180)
    t_ris = t0 + d * M
    ev.append(("RECEIVED_RIS", t_ris))
    if failed:
        errors.append((oid, "RECEIVED_RIS", "EMR", "ORDER_NOT_RECEIVED", t0 + M, t_ris))

    # 2. scheduling
    if pri == "STAT":
        d = rng.uniform(1, 5)
    elif pri == "URGENT":
        d = rng.uniform(5, 30)
    elif cls == "OUTPATIENT":
        d = rng.uniform(5, 90)
    else:
        d = clip(lognorm(60, 0.6), 10, 360)
    t_sched = t_ris + d * M
    ev.append(("SCHEDULED", t_sched))

    # cancelled before the exam
    if rng.random() < P_CANCELLED:
        t_c = t_sched + rng.uniform(10, 600) * M
        ev.append(("CANCELLED", t_c))
        orders.append((oid, pid, doc, exam[0], pri, cls, indication, t0, "CANCELLED"))
        events.extend((oid, s, t, *MSG[s]) for s, t in ev)
        continue

    # 3. patient arrives at radiology
    if cls == "OUTPATIENT":
        appt_day = (t0 + timedelta(days=pick([0, 1, 2, 3], [0.2, 0.35, 0.3, 0.15]))).replace(
            hour=rng.randint(8, 15), minute=rng.choice([0, 15, 30, 45]), second=0)
        t_arr = appt_day - rng.uniform(0, 10) * M
        if t_arr < t_sched + 5 * M:
            t_arr = t_sched + rng.uniform(5, 20) * M
    elif pri == "STAT":
        t_arr = t_sched + rng.uniform(5, 20) * M
    elif pri == "URGENT":
        t_arr = t_sched + rng.uniform(15, 60) * M
    else:
        t_arr = t_sched + clip(lognorm(75, 0.6), 20, 360) * M
    ev.append(("ARRIVED", t_arr))

    # 4. exam
    wait_med = {"XR": 8, "CT": 20, "MR": 30}[mod] * (0.5 if pri == "STAT" else 1)
    t_start = t_arr + clip(lognorm(wait_med, 0.5), 2, 120) * M
    lo, hi = {"XR": (5, 15), "CT": (10, 25), "MR": (25, 60)}[mod]
    t_done = t_start + rng.uniform(lo, hi) * M
    ev.append(("EXAM_STARTED", t_start))
    ev.append(("EXAM_COMPLETED", t_done))

    # 5. modality -> PACS
    d = clip(lognorm(2.5, 0.5), 0.5, 12)
    mismatch = rng.random() < P_PATIENT_ID_MISMATCH
    if mismatch:
        d = rng.uniform(30, 240)
    t_pacs = t_done + d * M
    ev.append(("IMAGES_IN_PACS", t_pacs))
    if mismatch:
        errors.append((oid, "IMAGES_IN_PACS", "PACS", "PATIENT_ID_MISMATCH", t_done + 3 * M, t_pacs))

    # 6. radiologist reads and signs
    wait = lognorm(READ_MEDIAN[pri] * READ_MODALITY_FACTOR[mod], 0.6)
    if is_night(t_pacs):
        if pri == "ROUTINE":
            morning = next_morning(t_pacs) + rng.uniform(0, 150) * M
            wait = max(wait, (morning - t_pacs) / M)
        else:
            wait *= NIGHT_FACTOR[pri]
    if t_pacs.weekday() >= 5 and pri != "STAT":
        wait *= WEEKEND_FACTOR
    t_draft = t_pacs + clip(wait, 3, 3000) * M
    sign = clip(lognorm(12, 0.8), 2, 240) * (0.5 if pri == "STAT" else 1)
    t_sign = t_draft + max(sign, 1.5) * M
    ev.append(("REPORT_DRAFTED", t_draft))
    ev.append(("REPORT_SIGNED", t_sign))

    # 7. RIS -> EMR
    d = clip(lognorm(2.0, 0.5), 0.5, 10)
    undelivered = rng.random() < P_RESULT_NOT_DELIVERED
    if undelivered:
        d = rng.uniform(30, 360)
    t_emr = t_sign + d * M
    ev.append(("RESULT_IN_EMR", t_emr))
    if undelivered:
        errors.append((oid, "RESULT_IN_EMR", "RIS", "RESULT_NOT_DELIVERED", t_sign + M, t_emr))

    orders.append((oid, pid, doc, exam[0], pri, cls, indication, t0, "RESULT_IN_EMR"))
    while True:
        acc = f"ACC2026{rng.randrange(10**6):06d}"
        if acc not in used_acc:
            used_acc.add(acc)
            break
    imgs = {"XR": rng.randint(1, 4), "CT": rng.randint(150, 600), "MR": rng.randint(200, 900)}[mod]
    studies.append((oid, oid, acc, mod, rng.choice(radiographer_ids), imgs))
    crit = rng.random() < (0.06 if mod == "CT" else 0.03)
    reports.append((oid, oid, rng.choice(radiologist_ids), "t" if crit else "f"))
    events.extend((oid, s, t, *MSG[s]) for s, t in ev)


def fmt(v):
    return v.strftime("%Y-%m-%d %H:%M:%S") if isinstance(v, datetime) else v


def write(name, rows):
    with open(os.path.join(OUT, name + ".csv"), "w", newline="") as f:
        csv.writer(f).writerows([[fmt(c) for c in r] for r in rows])


os.makedirs(OUT, exist_ok=True)
write("exam_catalog", [e[:4] for e in EXAMS])
write("providers", providers)
write("patients", patients)
write("orders", orders)
write("studies", studies)
write("reports", reports)
events.sort(key=lambda r: (r[0], r[2]))
write("order_events", [(i + 1, *r) for i, r in enumerate(events)])
write("interface_errors", [(i + 1, *r) for i, r in enumerate(errors)])
print(f"orders={len(orders)} studies={len(studies)} events={len(events)} errors={len(errors)}")
