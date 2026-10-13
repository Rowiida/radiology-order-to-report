# Radiology Order-to-Report Workflow

A health informatics portfolio project. It maps how an imaging order travels from the EMR through the RIS, the imaging device and PACS, back to a signed report in the EMR. It defines the requirements, builds the PostgreSQL database behind the path, and measures where time is lost.

**All data is synthetic.** No real patient or hospital data is used. The timings come from assumptions written in `generate_data.py`, so the results show that the queries find delays, not how any real hospital performs.

## What is in the folder

| File | What it is |
| --- | --- |
| `schema.sql` | PostgreSQL schema: 9 tables, constraints, and two views that turn status history into minutes per stage |
| `generate_data.py` | Generates 5,000 synthetic orders with realistic statuses, HL7 and DICOM message types, and interface errors |
| `load.sql` | Loads the generated CSV files into the schema |
| `kpi_queries.sql` | KPI queries (stage times, targets, shift, modality, interface errors) and data-quality checks |
| `export_dashboard_data.py` | Runs the KPI queries and writes `dashboard_data.json` |
| `dashboard_template.html`, `build_dashboard.py` | Dashboard page and the script that inserts the JSON into it |
| `dashboard.html` | The finished self-contained dashboard (open it in a browser) |
| `run_all.sh` | Runs the whole pipeline |

The case study with the workflow diagram, requirements and data model is a separate document.

## How to run

You need PostgreSQL 14 or newer (with `psql`) and Python 3.

```bash
createdb radiology_demo
export PGDATABASE=radiology_demo      # plus PGHOST, PGPORT, PGUSER if needed
./run_all.sh
```

To test another situation, change the assumptions at the top of `generate_data.py` (failure rates, night-shift effect, reading times) and run the script again.

## The path being measured

1. The doctor places the order in the EMR (HL7 ORM^O01).
2. The RIS receives and acknowledges it.
3. The exam is scheduled (HL7 SIU^S12).
4. The radiographer performs the exam from the modality worklist (DICOM MPPS).
5. Images are stored in PACS and linked to the order by accession number (DICOM C-STORE).
6. The radiologist reads the study and signs the report.
7. The result returns to the EMR (HL7 ORU^R01).

Every status change is one row in `order_events`. Interface failures at three handoffs (order not received, patient ID mismatch, result not delivered) are logged in `interface_errors`.

## Data-quality checks

`kpi_queries.sql` ends with four checks that should each return 0: timestamps out of order, completed orders missing a status event, completed orders without a study or report, and an order status that disagrees with its latest event.

## Limits

The model follows one clean path per order. It has no repeat exams, report addenda, system downtime or orders with several exams. The stakeholder needs, service targets and failure rates are assumptions to confirm with radiology staff.
