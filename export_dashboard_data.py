#!/usr/bin/env python3
"""Run the KPI queries and write the results to dashboard_data.json.

Uses the standard PG* environment variables (PGHOST, PGPORT, PGUSER, PGDATABASE).
"""
import json
import subprocess
import sys

QUERIES = {
    "totals": """
        SELECT json_build_object(
          'orders',     (SELECT count(*) FROM radiology.orders),
          'completed',  (SELECT count(*) FROM radiology.orders WHERE current_status = 'RESULT_IN_EMR'),
          'cancelled',  (SELECT count(*) FROM radiology.orders WHERE current_status = 'CANCELLED'),
          'first_day',  (SELECT min(ordered_at)::date FROM radiology.orders),
          'last_day',   (SELECT max(ordered_at)::date FROM radiology.orders),
          'median_exam_to_emr_min', (SELECT round(percentile_cont(0.5) WITHIN GROUP (ORDER BY exam_to_emr_min)::numeric, 0) FROM radiology.v_stage_minutes),
          'interface_error_orders', (SELECT count(DISTINCT order_id) FROM radiology.interface_errors)
        )""",
    "stages": """
        SELECT json_agg(json_build_object('stage', stage, 'median', round(median::numeric, 1), 'p90', round(p90::numeric, 1)) ORDER BY ord)
        FROM (
          SELECT 1 ord, 'Order to RIS' stage, percentile_cont(0.5) WITHIN GROUP (ORDER BY order_to_ris_min) median, percentile_cont(0.9) WITHIN GROUP (ORDER BY order_to_ris_min) p90 FROM radiology.v_stage_minutes
          UNION ALL SELECT 2, 'RIS to scheduled', percentile_cont(0.5) WITHIN GROUP (ORDER BY ris_to_scheduled_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY ris_to_scheduled_min) FROM radiology.v_stage_minutes
          UNION ALL SELECT 3, 'Arrival to exam start', percentile_cont(0.5) WITHIN GROUP (ORDER BY arrived_to_start_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY arrived_to_start_min) FROM radiology.v_stage_minutes
          UNION ALL SELECT 4, 'Exam duration', percentile_cont(0.5) WITHIN GROUP (ORDER BY exam_duration_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY exam_duration_min) FROM radiology.v_stage_minutes
          UNION ALL SELECT 5, 'Exam done to PACS', percentile_cont(0.5) WITHIN GROUP (ORDER BY exam_to_pacs_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY exam_to_pacs_min) FROM radiology.v_stage_minutes
          UNION ALL SELECT 6, 'PACS to report signed', percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min) FROM radiology.v_stage_minutes
          UNION ALL SELECT 7, 'Report signed to EMR', percentile_cont(0.5) WITHIN GROUP (ORDER BY signed_to_emr_min), percentile_cont(0.9) WITHIN GROUP (ORDER BY signed_to_emr_min) FROM radiology.v_stage_minutes
        ) s""",
    "by_priority": """
        SELECT json_agg(r ORDER BY target_min) FROM (
          SELECT v.priority, count(*) AS orders,
                 round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median,
                 round(percentile_cont(0.9) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS p90,
                 t.report_target_min AS target_min,
                 round(100.0 * count(*) FILTER (WHERE pacs_to_signed_min <= t.report_target_min) / count(*), 1) AS pct_within_target
          FROM radiology.v_stage_minutes v JOIN radiology.kpi_targets t USING (priority)
          GROUP BY v.priority, t.report_target_min) r""",
    "by_shift": """
        SELECT json_agg(r ORDER BY priority_ord, shift) FROM (
          SELECT priority,
                 CASE priority WHEN 'STAT' THEN 1 WHEN 'URGENT' THEN 2 ELSE 3 END AS priority_ord,
                 CASE WHEN extract(hour FROM images_in_pacs_at) >= 19 OR extract(hour FROM images_in_pacs_at) < 7
                      THEN 'Night' ELSE 'Day' END AS shift,
                 count(*) AS orders,
                 round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median
          FROM radiology.v_stage_minutes GROUP BY 1, 2, 3) r""",
    "by_modality": """
        SELECT json_agg(r ORDER BY modality) FROM (
          SELECT modality, count(*) AS orders,
                 round(percentile_cont(0.5) WITHIN GROUP (ORDER BY pacs_to_signed_min)::numeric, 0) AS median
          FROM radiology.v_stage_minutes GROUP BY modality) r""",
    "interface_errors": """
        SELECT json_agg(r ORDER BY errors DESC) FROM (
          SELECT error_type, source_system, at_status, count(*) AS errors,
                 round(100.0 * count(DISTINCT order_id) / (SELECT count(*) FROM radiology.orders WHERE current_status = 'RESULT_IN_EMR'), 1) AS pct_of_orders,
                 round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM resolved_at - occurred_at) / 60)::numeric, 0) AS median_min_to_fix
          FROM radiology.interface_errors GROUP BY 1, 2, 3) r""",
}


def run(sql):
    out = subprocess.run(["psql", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(out.stderr)
    return json.loads(out.stdout.strip())


data = {name: run(sql) for name, sql in QUERIES.items()}
with open("dashboard_data.json", "w") as f:
    json.dump(data, f, indent=2)
print("wrote dashboard_data.json")
