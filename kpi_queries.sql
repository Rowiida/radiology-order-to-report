-- KPI and data-quality queries for the radiology order-to-report workflow.
-- Run:  psql -f kpi_queries.sql
-- Results describe SYNTHETIC data only.
SET search_path = radiology;

-- ---------------------------------------------------------------
-- Q1. Where does the time go? Median and 90th percentile per stage (minutes)
-- ---------------------------------------------------------------
\echo '--- Q1. Minutes per stage (completed orders) ---'
SELECT stage, round(median::numeric, 1) AS median_min, round(p90::numeric, 1) AS p90_min
FROM (
    SELECT 'Order -> RIS' AS stage, 1 AS ord,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY order_to_ris_min) AS median,
           percentile_cont(0.9) WITHIN GROUP (ORDER BY order_to_ris_min) AS p90 FROM v_stage_minutes
    UNION ALL SELECT 'RIS -> Scheduled', 2,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY ris_to_scheduled_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY ris_to_scheduled_min) FROM v_stage_minutes
    UNION ALL SELECT 'Scheduled -> Arrived', 3,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY scheduled_to_arrived_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY scheduled_to_arrived_min) FROM v_stage_minutes
    UNION ALL SELECT 'Arrived -> Exam start', 4,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY arrived_to_start_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY arrived_to_start_min) FROM v_stage_minutes
    UNION ALL SELECT 'Exam duration', 5,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY exam_duration_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY exam_duration_min) FROM v_stage_minutes
    UNION ALL SELECT 'Exam done -> Images in PACS', 6,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY exam_to_pacs_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY exam_to_pacs_min) FROM v_stage_minutes
    UNION ALL SELECT 'Images in PACS -> Report signed', 7,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min) FROM v_stage_minutes
    UNION ALL SELECT 'Report signed -> Result in EMR', 8,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY signed_to_emr_min),
           percentile_cont(0.9) WITHIN GROUP (ORDER BY signed_to_emr_min) FROM v_stage_minutes
) s ORDER BY ord;

-- ---------------------------------------------------------------
-- Q2. Report turnaround by priority, against the illustrative targets
-- ---------------------------------------------------------------
\echo '--- Q2. Report turnaround (PACS -> signed) by priority ---'
SELECT v.priority,
       count(*)                                                        AS orders,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median_min,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS p90_min,
       t.report_target_min                                             AS target_min,
       round(100.0 * count(*) FILTER (WHERE pacs_to_signed_min <= t.report_target_min) / count(*), 1) AS pct_within_target
FROM v_stage_minutes v
JOIN kpi_targets t USING (priority)
GROUP BY v.priority, t.report_target_min
ORDER BY t.report_target_min;

-- ---------------------------------------------------------------
-- Q3. Day versus night, by priority (shift = hour the images reached PACS)
-- ---------------------------------------------------------------
\echo '--- Q3. Report turnaround by shift ---'
SELECT priority,
       CASE WHEN extract(hour FROM images_in_pacs_at) >= 19
              OR extract(hour FROM images_in_pacs_at) < 7 THEN 'Night (19:00-07:00)'
            ELSE 'Day (07:00-19:00)' END AS shift,
       count(*) AS orders,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median_min,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS p90_min
FROM v_stage_minutes
GROUP BY priority, shift
ORDER BY priority, shift;

-- ---------------------------------------------------------------
-- Q4. Report turnaround by modality
-- ---------------------------------------------------------------
\echo '--- Q4. Report turnaround by modality ---'
SELECT modality,
       count(*) AS orders,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median_min,
       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS p90_min
FROM v_stage_minutes
GROUP BY modality ORDER BY modality;

-- ---------------------------------------------------------------
-- Q5. Interface and data errors at the handoffs
-- ---------------------------------------------------------------
\echo '--- Q5. Interface errors ---'
SELECT error_type, source_system, at_status,
       count(*) AS errors,
       round(100.0 * count(DISTINCT order_id) / (SELECT count(*) FROM orders WHERE current_status = 'RESULT_IN_EMR'), 1) AS pct_of_orders,
       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM resolved_at - occurred_at) / 60)::numeric, 0) AS median_min_to_fix
FROM interface_errors
GROUP BY error_type, source_system, at_status
ORDER BY errors DESC;

-- ---------------------------------------------------------------
-- Q6. Result delivery: signed report that did not reach the EMR within 15 minutes
-- ---------------------------------------------------------------
\echo '--- Q6. Signed -> EMR over 15 minutes ---'
SELECT count(*) FILTER (WHERE signed_to_emr_min > 15) AS late_results,
       count(*) AS orders,
       round(100.0 * count(*) FILTER (WHERE signed_to_emr_min > 15) / count(*), 1) AS pct_late
FROM v_stage_minutes;

-- ---------------------------------------------------------------
-- Q7. Data-quality checks (each should return 0 rows or 0)
-- ---------------------------------------------------------------
\echo '--- Q7a. Completed orders with a timestamp out of order ---'
SELECT count(*) AS out_of_order_orders
FROM v_order_timeline
WHERE received_ris_at   < ordered_at
   OR scheduled_at      < received_ris_at
   OR arrived_at        < scheduled_at
   OR exam_started_at   < arrived_at
   OR exam_completed_at < exam_started_at
   OR images_in_pacs_at < exam_completed_at
   OR report_drafted_at < images_in_pacs_at
   OR report_signed_at  < report_drafted_at
   OR result_in_emr_at  < report_signed_at;

\echo '--- Q7b. Completed orders missing a status event ---'
SELECT count(*) AS orders_missing_events
FROM v_order_timeline
WHERE ordered_at IS NULL OR received_ris_at IS NULL OR scheduled_at IS NULL
   OR arrived_at IS NULL OR exam_started_at IS NULL OR exam_completed_at IS NULL
   OR images_in_pacs_at IS NULL OR report_drafted_at IS NULL
   OR report_signed_at IS NULL OR result_in_emr_at IS NULL;

\echo '--- Q7c. Completed orders without a study or a report ---'
SELECT count(*) AS orders_without_study_or_report
FROM orders o
LEFT JOIN studies s USING (order_id)
LEFT JOIN reports r USING (order_id)
WHERE o.current_status = 'RESULT_IN_EMR' AND (s.order_id IS NULL OR r.order_id IS NULL);

\echo '--- Q7d. Order status that disagrees with its latest event ---'
SELECT count(*) AS status_mismatches
FROM orders o
JOIN LATERAL (SELECT status FROM order_events e WHERE e.order_id = o.order_id
              ORDER BY event_at DESC, event_id DESC LIMIT 1) last ON true
WHERE o.current_status <> last.status;
