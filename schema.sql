-- Radiology order-to-report workflow: PostgreSQL schema
-- All data in this project is SYNTHETIC. No real patient or hospital data is used.

DROP SCHEMA IF EXISTS radiology CASCADE;
CREATE SCHEMA radiology;
SET search_path = radiology;

-- ---------------------------------------------------------------
-- Reference data
-- ---------------------------------------------------------------
CREATE TABLE exam_catalog (
    exam_code    text PRIMARY KEY,
    description  text NOT NULL,
    modality     text NOT NULL CHECK (modality IN ('XR', 'CT', 'MR')),
    body_part    text NOT NULL
);

CREATE TABLE providers (
    provider_id    serial PRIMARY KEY,
    provider_code  text NOT NULL UNIQUE,           -- synthetic code, no real names
    role           text NOT NULL CHECK (role IN ('ORDERING_DOCTOR', 'RADIOLOGIST', 'RADIOGRAPHER')),
    department     text NOT NULL
);

-- Illustrative service-level targets (minutes), IMAGES_IN_PACS -> REPORT_SIGNED.
-- These are example targets, not a standard. A real hospital sets its own.
CREATE TABLE kpi_targets (
    priority            text PRIMARY KEY CHECK (priority IN ('STAT', 'URGENT', 'ROUTINE')),
    report_target_min   integer NOT NULL CHECK (report_target_min > 0)
);

-- ---------------------------------------------------------------
-- Patients, orders, studies, reports
-- ---------------------------------------------------------------
CREATE TABLE patients (
    patient_id  serial PRIMARY KEY,
    mrn         text NOT NULL UNIQUE,              -- synthetic medical record number
    birth_year  integer NOT NULL CHECK (birth_year BETWEEN 1920 AND 2026),
    sex         text NOT NULL CHECK (sex IN ('F', 'M'))
);

CREATE TABLE orders (
    order_id              serial PRIMARY KEY,
    patient_id            integer NOT NULL REFERENCES patients,
    ordering_provider_id  integer NOT NULL REFERENCES providers,
    exam_code             text    NOT NULL REFERENCES exam_catalog,
    priority              text    NOT NULL CHECK (priority IN ('STAT', 'URGENT', 'ROUTINE')),
    patient_class         text    NOT NULL CHECK (patient_class IN ('ED', 'INPATIENT', 'OUTPATIENT')),
    clinical_indication   text,
    ordered_at            timestamp NOT NULL,
    current_status        text    NOT NULL
);

-- One study per completed exam. The accession number is the key that links the
-- RIS order to the PACS images (a mismatch here is a classic integration failure).
CREATE TABLE studies (
    study_id          serial PRIMARY KEY,
    order_id          integer NOT NULL UNIQUE REFERENCES orders,
    accession_number  text    NOT NULL UNIQUE,
    modality          text    NOT NULL CHECK (modality IN ('XR', 'CT', 'MR')),
    radiographer_id   integer NOT NULL REFERENCES providers,
    image_count       integer NOT NULL CHECK (image_count > 0)
);

CREATE TABLE reports (
    report_id         serial PRIMARY KEY,
    order_id          integer NOT NULL UNIQUE REFERENCES orders,
    radiologist_id    integer NOT NULL REFERENCES providers,
    critical_finding  boolean NOT NULL DEFAULT false
);

-- ---------------------------------------------------------------
-- Status history: every handoff between systems is one row.
-- This table is the single source of truth for all timestamps.
-- ---------------------------------------------------------------
CREATE TABLE order_events (
    event_id        bigserial PRIMARY KEY,
    order_id        integer   NOT NULL REFERENCES orders,
    status          text      NOT NULL CHECK (status IN (
                        'ORDERED', 'RECEIVED_RIS', 'SCHEDULED', 'ARRIVED',
                        'EXAM_STARTED', 'EXAM_COMPLETED', 'IMAGES_IN_PACS',
                        'REPORT_DRAFTED', 'REPORT_SIGNED', 'RESULT_IN_EMR', 'CANCELLED')),
    event_at        timestamp NOT NULL,
    source_system   text      NOT NULL CHECK (source_system IN ('EMR', 'RIS', 'MODALITY', 'PACS')),
    message_type    text      NOT NULL,            -- e.g. HL7 ORM^O01, DICOM MPPS, HL7 ORU^R01
    UNIQUE (order_id, status)                      -- each status is reached at most once
);
CREATE INDEX idx_events_order  ON order_events (order_id);
CREATE INDEX idx_events_status ON order_events (status, event_at);

-- Interface or data problems detected at a handoff.
CREATE TABLE interface_errors (
    error_id       serial PRIMARY KEY,
    order_id       integer   NOT NULL REFERENCES orders,
    at_status      text      NOT NULL,             -- the handoff that failed
    source_system  text      NOT NULL CHECK (source_system IN ('EMR', 'RIS', 'MODALITY', 'PACS')),
    error_type     text      NOT NULL CHECK (error_type IN (
                       'ORDER_NOT_RECEIVED', 'PATIENT_ID_MISMATCH', 'RESULT_NOT_DELIVERED')),
    occurred_at    timestamp NOT NULL,
    resolved_at    timestamp NOT NULL,
    CHECK (resolved_at >= occurred_at)
);
CREATE INDEX idx_errors_order ON interface_errors (order_id);

-- ---------------------------------------------------------------
-- Views
-- ---------------------------------------------------------------
-- One row per completed order, with the timestamp of every status.
CREATE VIEW v_order_timeline AS
SELECT
    o.order_id,
    o.priority,
    o.patient_class,
    e.modality,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'ORDERED')         AS ordered_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'RECEIVED_RIS')    AS received_ris_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'SCHEDULED')       AS scheduled_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'ARRIVED')         AS arrived_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'EXAM_STARTED')    AS exam_started_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'EXAM_COMPLETED')  AS exam_completed_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'IMAGES_IN_PACS')  AS images_in_pacs_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'REPORT_DRAFTED')  AS report_drafted_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'REPORT_SIGNED')   AS report_signed_at,
    MIN(ev.event_at) FILTER (WHERE ev.status = 'RESULT_IN_EMR')   AS result_in_emr_at
FROM orders o
JOIN exam_catalog e ON e.exam_code = o.exam_code
JOIN order_events ev ON ev.order_id = o.order_id
WHERE o.current_status = 'RESULT_IN_EMR'
GROUP BY o.order_id, o.priority, o.patient_class, e.modality;

-- Minutes spent in each stage of the path.
CREATE VIEW v_stage_minutes AS
SELECT
    order_id, priority, patient_class, modality,
    ordered_at, exam_completed_at, images_in_pacs_at, report_signed_at,
    EXTRACT(EPOCH FROM received_ris_at   - ordered_at)        / 60 AS order_to_ris_min,
    EXTRACT(EPOCH FROM scheduled_at      - received_ris_at)   / 60 AS ris_to_scheduled_min,
    EXTRACT(EPOCH FROM arrived_at        - scheduled_at)      / 60 AS scheduled_to_arrived_min,
    EXTRACT(EPOCH FROM exam_started_at   - arrived_at)        / 60 AS arrived_to_start_min,
    EXTRACT(EPOCH FROM exam_completed_at - exam_started_at)   / 60 AS exam_duration_min,
    EXTRACT(EPOCH FROM images_in_pacs_at - exam_completed_at) / 60 AS exam_to_pacs_min,
    EXTRACT(EPOCH FROM report_signed_at  - images_in_pacs_at) / 60 AS pacs_to_signed_min,
    EXTRACT(EPOCH FROM result_in_emr_at  - report_signed_at)  / 60 AS signed_to_emr_min,
    EXTRACT(EPOCH FROM result_in_emr_at  - exam_completed_at) / 60 AS exam_to_emr_min
FROM v_order_timeline;
