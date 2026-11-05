# Architecture Audit — 12: Extraction Metrics, Counters & Accuracy Audit

> **Primary Source Files:** `app.py`, `static/spa/sections/search.js`, `services/captcha_monitor.py`  
> **Key Routines:** `_run_auto_extraction_job` (`app.py:2775-3120`), `renderAutoProgress` (`static/spa/sections/search.js:1150-1360`)  
> **Implementation Status:** `Implemented` (High Maturity)

---

### 1. Extraction Metrics & Counter Inventory

The JobScout auto-extraction dashboard surfaces 14 distinct real-time telemetry metrics. Below is the technical audit of how each metric is collected, calculated, and represented:

| Metric Name | Backend Variable / Expression | Scope / Calculation Semantics | Representation in UI |
|---|---|---|---|
| **Processed Jobs** | `job_data["processed_jobs"]` (`app.py:3045`) | Cumulative count of finished job records in the current task. Updated atomically after each worker completes a job. | Primary Hero Card (`114 / 963`) |
| **Emails Found** | `job_data["emails_found"]` (`app.py:3055`) | Count of jobs where a valid, non-excluded email address was extracted (`bool(email)` and not `ERROR:`). | Primary Hero Card |
| **Recruitment Emails** | `job_data["recruitment_emails"]` (`app.py:3060`) | Count of jobs where extracted email has high-confidence recruiter prefix (`bewerbung@`, `karriere@`, `jobs@`, etc.). | Secondary Metric Pill |
| **Forms Found** | `job_data["forms_found"]` (`app.py:3068`) | Count of jobs where an interactive application form was verified (`has_form == True` or `application_method in ('form', 'both')`). | Primary Hero Card |
| **External Apply Links** | `job_data["external_apply_links"]` (`app.py:3075`) | Jobs redirecting to an external ATS or career portal (`direct_application_url` present without raw DOM form). | Secondary Metric Pill |
| **HTTP Fast-Path Hits** | `job_data["fast_path_hits"]` (`app.py:3080`) | Jobs successfully extracted via Fast-Path HTTP (`extraction_method == "fast_http"`), bypassing Selenium. | Secondary Metric Pill |
| **Selenium Fallbacks** | `job_data["selenium_fallbacks"]` (`app.py:3085`) | Jobs requiring full headless Selenium browser launch due to JS rendering or missing contact in static HTML. | Secondary Metric Pill |
| **Average Time / Job** | `job_data["avg_time_per_job"]` (`app.py:3095`) | Rolling average duration in seconds: `total_elapsed_processing_time / processed_jobs`. | Secondary Metric Pill (`2.4s/job`) |
| **Failed Jobs** | `job_data["failed_jobs"]` (`app.py:3100`) | Jobs that encountered uncaught exceptions, network aborts, or fatal 5xx errors during extraction. | Secondary Metric Pill |
| **Pending Jobs** | `total_jobs - processed_jobs` (`app.py:3105`) | Remaining jobs in the extraction queue awaiting worker execution. | Secondary Metric Pill |
| **Manual Required** | `job_data["manual_required"]` (`app.py:3110`) | Jobs flagged with `manual_review_required = True` due to unresolved CAPTCHAs, bot challenges, or postal-only applications. | Secondary Metric Pill |
| **Verified by Site** | `job_data["verified_by_site"]` (`app.py:3115`) | Jobs confirmed active via employer career page verification (primarily Google Maps discovery). | Secondary Metric Pill |
| **Rate Limited (429)** | `job_data["rate_limited_count"]` (`app.py:3118`) | Requests receiving HTTP 429 Too Many Requests, prompting backoff delays or proxy profile rotation. | Secondary Metric Pill |
| **Worker Completed** | `worker["completed_count"]` (`app.py:3040`) | Number of jobs individually processed by Worker 1, 2, 3, or 4 during the current extraction session. | Parallel Worker Cards |

---

### 2. Discrepancy & Edge Case Analysis

#### A. Attempt Count vs. Unique Contact Count
- **Finding:** A job is counted as `Processed` as soon as the worker completes execution, regardless of whether contact details were found.
- If an employer has 5 vacancies in the search list:
  - All 5 count towards `Processed Jobs`.
  - If all 5 share the same recruitment email, `Emails Found` increments 5 times in the raw counter, but the UI deduplication layer displays unique emails in the filtered table view.

#### B. Pause/Resume State Preservation
- In earlier versions, invoking Resume recomputed `total_jobs` from the remaining queue size, falsely showing premature `100% (114/114)` completion.
- Under the current verified implementation (`app.py:8286-8330`), `total_jobs` remains immutable from the original search dataset, and `processed_jobs` increments monotonically from the last valid checkpoint.
