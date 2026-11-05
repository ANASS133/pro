# Architecture Audit — 10: Workers, Concurrency, Proxies & Queue Management

> **Primary Source Files:** `app.py`, `services/worker_network_router.py`  
> **Key Routines:** `_run_auto_extraction_job` (`app.py:2775`), `_worker_task_job` (`app.py:2924`), `load_worker_network_profiles` (`services/worker_network_router.py:268`)  
> **Implementation Status:** `Implemented` (High Maturity)

---

### 1. Worker Threading & Queue Orchestration

Auto-extraction executes asynchronously in background worker threads managed by Python's `concurrent.futures.ThreadPoolExecutor`.

```mermaid
flowchart TD
    subgraph UI ["Client Browser / SPA"]
        StartBtn["User Clicks 'Auto-Extraction Starten'"]
        UIStream["SSE / Polling (/api/inline/auto-jobs/status/{id})"]
    end

    subgraph Backend ["app.py Background Task"]
        Init["_run_auto_extraction_job(job_id)"]
        Slots["worker_slots Queue (Queue(maxsize=4))"]
        Executor["ThreadPoolExecutor(max_workers=4)"]
        Tasks["Queue of Pending Job Records (0..N)"]
    end

    subgraph Workers ["Worker Slots 1..4"]
        W1["Worker 1 (Proxy Egress IP 1)"]
        W2["Worker 2 (Proxy Egress IP 2)"]
        W3["Worker 3 (Proxy Egress IP 3)"]
        W4["Worker 4 (Proxy Egress IP 4)"]
    end

    StartBtn --> Init
    Init --> Slots
    Slots -->|Worker Tokens (1, 2, 3, 4)| Tasks
    Tasks --> Executor
    Executor --> W1 & W2 & W3 & W4
    W1 & W2 & W3 & W4 -->|Stage Telemetry & Results| UIStream
```

#### A. Slot Management & Concurrency
- **Pool Size:** Defaults to 4 concurrent worker threads (`DEFAULT_WORKER_COUNT = 4`).
- **Slot Reservation (`worker_slots`):** A synchronized `queue.Queue` holds tokens `[1, 2, 3, 4]`.
- A worker acquires a slot ID via `w_id = worker_slots.get()`, retrieves its dedicated extractor instance from `worker_extractors[w_id]`, and releases the slot in a `finally:` block via `worker_slots.put(w_id)`.

---

### 2. Webshare Proxy Network Routing & Fail-Closed Security

#### A. Profile Loading & Verification
- **File:** `services/worker_network_router.py:50-160`, `268-360`
- Proxies are provisioned from the Webshare API (`https://proxy.webshare.io/api/v2/proxy/list/`) using `WEBSHARE_API_KEY`.
- The router selects 4 distinct proxy endpoints with unique public IP addresses.
- Assigns one static proxy profile per worker ID (`WorkerNetworkProfile`).

#### B. Fail-Closed Network Security
- Before launching workers, `verify_all_worker_connections` checks HTTP/HTTPS connectivity and confirms egress IP anonymity.
- **Fail-Closed Policy:** If a proxy becomes unresponsive or fails authentication, its worker transitions to `blocked` or `failed`. Direct fallback to local host network is strictly prohibited when `WORKER_REQUIRE_PROXIES=true`.

---

### 3. Pause, Resume & Cancellation Lifecycle

- **Pause (`/api/inline/auto-jobs/pause/<job_id>`):**
  - Sets `current_job["paused"] = True`.
  - In-flight jobs finish processing cooperatively.
  - Active worker states are preserved, and telemetry shows `status: "paused"`.
- **Resume (`/api/inline/auto-jobs/continue/<job_id>`):**
  - Validates that the original total jobs count and processed counters are preserved.
  - Re-enqueues only unfinished job indices (`current_index` to `total_jobs`).
- **Stop (`/api/inline/auto-jobs/stop/<job_id>`):**
  - Sets `stop_requested = True`, terminates remaining tasks, and flushes results to disk.
