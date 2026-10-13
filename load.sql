-- Load the generated CSV files into the radiology schema.
-- Run from the project folder:  psql -f schema.sql  then  psql -f load.sql
SET search_path = radiology;

\copy exam_catalog from 'data/exam_catalog.csv' csv
\copy providers (provider_id, provider_code, role, department) from 'data/providers.csv' csv
\copy patients from 'data/patients.csv' csv
\copy orders from 'data/orders.csv' csv
\copy studies from 'data/studies.csv' csv
\copy reports from 'data/reports.csv' csv
\copy order_events from 'data/order_events.csv' csv
\copy interface_errors from 'data/interface_errors.csv' csv

INSERT INTO kpi_targets VALUES ('STAT', 60), ('URGENT', 240), ('ROUTINE', 1440);

-- keep the serial counters in step with the loaded ids
SELECT setval('providers_provider_id_seq',  (SELECT max(provider_id) FROM providers));
SELECT setval('patients_patient_id_seq',    (SELECT max(patient_id)  FROM patients));
SELECT setval('orders_order_id_seq',        (SELECT max(order_id)    FROM orders));
SELECT setval('studies_study_id_seq',       (SELECT max(study_id)    FROM studies));
SELECT setval('reports_report_id_seq',      (SELECT max(report_id)   FROM reports));
SELECT setval('order_events_event_id_seq',  (SELECT max(event_id)    FROM order_events));
SELECT setval('interface_errors_error_id_seq', (SELECT max(error_id) FROM interface_errors));

ANALYZE;
