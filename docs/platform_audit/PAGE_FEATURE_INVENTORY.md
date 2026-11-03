# JobScout — Page-by-Page Technical Feature Inventory

> **Document:** `PAGE_FEATURE_INVENTORY.md`  
> **Platform Version:** 3.14  
> **Audit Date:** 2026-11-03  
> **Total Pages Audited:** **22 Discovered Interfaces**

---

### Page 1: Search & Discovery Hub

**Purpose:**  
Unified search interface for synchronized multi-portal job scraping (Arbeitsagentur, Ausbildung.de, Azubiyo, Aubi-Plus, IHK) with real-time SSE streaming, radius filtering, linguistic validation, and direct 21-column Excel export.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L169-L500), [`static/spa/sections/search.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L5000-L6700), [`scraper/search_filter_engine.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/search_filter_engine.py)

**Sections and Tabs:**  
- **Search Header & Form:** Keyword, City/Zip, Radius, Opportunity Mode, Source Selector, Published Since Window.
- **Portals vs Google Maps Workspace Switcher:** Dynamically shows portal search or Google Maps scraper interface.
- **Progress Panel:** Live SSE event stream displaying discovered vacancies, portal latencies, and progress bar.
- **Results Table & Filter Controls:** 21-column data grid with inline status badges, email status, and company website links.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Multi-Portal Search | Scrapes 5 major portals simultaneously | Input form & submit button | Multi-threaded scraper in `app.py` | **IMPLEMENTED** | [`search.js#L50`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js#L50), [`app.py#L6425`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6425) |
| Live SSE Job Stream | Streams jobs incrementally to browser | Progress bar & live item counter | `/api/search` SSE generator | **IMPLEMENTED** | [`search.js#L140`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js#L140), [`app.py#L6430`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6430) |
| Haversine Radius Filter | Filters listings strictly within specified commuter km | Radius select dropdown | Geo-distance calculation | **IMPLEMENTED** | [`search.js#L85`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js#L85), [`search_filter_engine.py#L120`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/search_filter_engine.py#L120) |
| Linguistic Relevance Filter | Rejects unrelated job listings | Automatic | Token taxonomy validator | **IMPLEMENTED** | [`search_filter_engine.py#L45`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/search_filter_engine.py#L45) |
| 21-Column Excel Export | Strict schema export formatted to `Ausbildung zum Koch.xlsx` | "Download Excel" button | `/api/search/download` | **IMPLEMENTED** | [`app.py#L7789`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7789) |
| Auto-Save Dataset | Saves search results directly to `data/exports/` | Automatic on search finish | `_save_search_cache_to_disk` | **IMPLEMENTED** | [`app.py#L6390`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6390) |
| Inline Auto-Extraction Trigger | Dispatches background crawler to enrich emails | "Extract Emails" button | `/api/inline/auto-jobs/start` | **IMPLEMENTED** | [`search.js#L420`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js#L420), [`app.py#L6725`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6725) |

**Buttons and Actions:**  
- `search_submit_btn` ("Search"): Submits parameters and initiates live SSE streaming.
- `btn-download-results` ("Download Excel"): Downloads formatted `.xlsx` containing discovered listings.
- `btn-auto-extract-emails` ("Start Auto Extraction"): Initiates parallel headless domain crawler for missing emails.
- `btn-clear-results`: Clears frontend result table and resets search form.

**API Endpoints:**  
- `GET /api/search` (Query parameters: `keyword`, `location`, `radius`, `source`, `mode`, `published_since`)
- `GET /api/search/download` (Universal formatted Excel generator)
- `POST /api/inline/auto-jobs/start` (Starts background email enrichment worker)

**Connected Systems:** Ausbildungen Datasets, Google Maps Scraper, Anschreiben Studio (via "Use in Cover Letters").  
**Known Issues:** Select dropdown `#search_source_1` lacks explicit HTML5 attribute `form="search_form_1"`, triggering test failure in `test_search_maps_consolidation.py`.  
**Missing Functionality:** No option to pause an active live SSE stream mid-flight; user must wait for completion or navigate away.

---

### Page 2: Google Maps Business & Opportunity Intelligence

**Purpose:**  
Discovers local businesses, stores, and training companies across Germany via Google Maps, crawls their websites, extracts verified emails, and plots them on an interactive Leaflet map.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L510-L690), [`static/spa/sections/google-maps.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/google-maps.js)
- **Backend:** [`scraper/google_maps_scraper.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_scraper.py), [`scraper/google_maps_opportunity_verifier.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_opportunity_verifier.py), [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L8350-L8650)

**Sections and Tabs:**  
- **Map Parameters Panel:** Keyword / Industry search, Target City, Search Radius, Custom business categories.
- **Live Discovery Progress:** Headless Selenium status, business card discovery counter, website crawling queue.
- **Interactive Leaflet Map:** Displays discovered businesses with geocoded pins, company name, address, and email status.
- **Results & Export Drawer:** Tabular company list with CSV, JSON, and Excel export options.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Selenium Maps Crawler | Headless browser searches Google Maps | Search form & start button | `GoogleMapsScraper.search_businesses` | **IMPLEMENTED** | [`google_maps_scraper.py#L325`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_scraper.py#L325) |
| Deep Homepage & Impressum Crawl | Crawls company sites for contact emails | Live progress counters | `_discover_contact_pages` & HTTP pool | **IMPLEMENTED** | [`google_maps_scraper.py#L192`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_scraper.py#L192) |
| Cloudflare Email Decoder | Decodes hex-encoded Cloudflare emails | Automatic | `_decode_cloudflare_email` | **IMPLEMENTED** | [`google_maps_scraper.py#L120`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_scraper.py#L120) |
| Interactive Leaflet Map | Renders geocoded pins with popups | Leaflet container | `/api/map-data` geocoded records | **IMPLEMENTED** | [`google-maps.js#L210`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/google-maps.js#L210), [`routes/enhancements.py#L24`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/enhancements.py#L24) |
| Multi-Format Export | Exports results as CSV, JSON, or Excel | Format dropdown & download btn | `/api/google-maps/export/<job_id>/<fmt>` | **IMPLEMENTED** | [`app.py#L8601`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L8601) |

**Buttons and Actions:**  
- `gmaps-search-btn`: Initiates Google Maps search and crawling job.
- `gmaps-stop-btn`: Sends abort signal to running Selenium background worker.
- `gmaps-export-btn`: Downloads discovered companies in selected format (`xlsx`, `csv`, `json`).

**API Endpoints:**  
- `POST /api/google-maps/start` (Starts background crawler job)
- `GET /api/google-maps/status/<job_id>` (Polls status, discovered companies, email count)
- `POST /api/google-maps/stop/<job_id>` (Gracefully aborts job)
- `GET /api/google-maps/export/<job_id>/<fmt>` (Downloads file)

**Connected Systems:** Search Hub (co-located view), Ausbildungen Hub, Anschreiben Studio.  
**Known Issues:** High memory footprint if Selenium instance encounters heavily animated target websites.  
**Missing Functionality:** No proxy rotation UI settings; proxies must be configured in environment variables.

---

### Page 3: Ausbildungen Datasets & Export Manager

**Purpose:**  
Centralized dataset repository for all scraped job collections. Allows administrators to inspect dataset availability, preview listings, enrich files with missing emails, merge multiple datasets with deduplication, and delete stale files.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L1570-L1680), [`static/spa/sections/ausbildungen.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/ausbildungen.js)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2735-L3025)

**Sections and Tabs:**  
- **Dataset Overview Table:** File list, record count, email percentage, file size, last modified date.
- **Dataset Preview Modal:** Interactive modal displaying first 50 rows of selected dataset.
- **Merge & Deduplicate Toolbar:** Select multiple checkboxes to combine files into a single unified export.
- **Email Enrichment Progress:** Monitors background job updating an existing file with newly extracted emails.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Dataset Catalog | Lists all `.xlsx` files in `data/exports/` | Data table with sortable columns | `_list_auto_extraction_export_files` | **IMPLEMENTED** | [`ausbildungen.js#L45`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/ausbildungen.js#L45), [`app.py#L2739`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2739) |
| Dataset Preview | Inspects rows and columns before outreach | "Preview" modal trigger | `/api/ausbildungen/file/<name>/preview` | **IMPLEMENTED** | [`app.py#L2852`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2852) |
| Dataset Deletion | Removes file and purges associated caches | "Delete" button with confirmation | `/api/ausbildungen/file/<name>` DELETE | **IMPLEMENTED** | [`app.py#L2889`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2889) |
| Multi-Dataset Merge | Combines files and deduplicates rows | Multi-select checkboxes & Merge btn | `/api/ausbildungen/merge` | **IMPLEMENTED** | [`app.py#L2914`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2914) |
| Background Email Update | Re-scrapes missing company emails in dataset | "Update Emails" action button | `/api/ausbildungen/update` | **IMPLEMENTED** | [`app.py#L2781`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2781) |

**Buttons and Actions:**  
- `btn-refresh-datasets`: Re-reads `data/exports/` directory.
- `btn-merge-selected`: Merges selected checkboxes into a single deduplicated `.xlsx` file.
- Action Buttons per row: `Download`, `Preview`, `Enrich Emails`, `Delete`.

**API Endpoints:**  
- `GET /api/ausbildungen/files`
- `GET /api/ausbildungen/availability?profession=...`
- `GET /api/ausbildungen/file/<filename>/preview`
- `GET /api/ausbildungen/file/<filename>/download`
- `DELETE /api/ausbildungen/file/<filename>`
- `POST /api/ausbildungen/merge`
- `POST /api/ausbildungen/update`

**Connected Systems:** Supabase Client Cards (availability badges), Anschreiben Studio, Bulk Email Outreach.  
**Known Issues:** None. Tested and verified in `test_ausbildungen_deletion.py`.  
**Missing Functionality:** No column re-mapping tool when merging external files with non-standard column headers.

---

### Page 4: Anschreiben Studio & Cover Letter Engine

**Purpose:**  
High-performance cover letter editor and DIN 5008 PDF rendering engine with AI keyword tailoring, Golden Hook generation, multi-template management, and live in-browser PDF preview.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L1690-L1950), [`static/spa/sections/create-anschreibens.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/create-anschreibens.js)
- **Backend:** [`routes/pdf_routes.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/pdf_routes.py), [`pdf_generator/services/pdf_service.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/services/pdf_service.py), [`pdf_generator/services/ats_service.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/services/ats_service.py)

**Sections and Tabs:**  
- **Data Source Selector:** Upload custom Excel/CSV, choose from Ausbildungen exports, or bootstrap from active candidate.
- **Template Manager & Editor:** Multi-template tab bar (Create, Duplicate, Rename, Delete), Rich textarea with placeholder inserters.
- **AI Enhancement Toolbar:** ATS Tailor, Golden Hook opener, Culture Vibe detector, Match Heatmap.
- **Design & Layout Settings:** DIN 5008 Form A/B presets, Font family & size selector, Margin controls, Watermark text, Background Letterheads.
- **Live Stream Preview:** In-browser live PDF rendering with previous/next company record stepper.
- **Batch Generator & Dispatcher:** Generates ZIP archive or stages PDFs directly into Email Outreach.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| DIN 5008 PDF Rendering | Compiles pixel-perfect DIN 5008 PDFs | In-browser preview iframe | `PDFService.create_pdf_stream` | **IMPLEMENTED** | [`pdf_service.py#L403`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/services/pdf_service.py#L403), [`routes/pdf_routes.py#L31`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/pdf_routes.py#L31) |
| Live PDF Stream Preview | Updates PDF preview without disk writes | Debounced preview updater | `/api/pdf/stream-preview` | **IMPLEMENTED** | [`create-anschreibens.js#L350`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/create-anschreibens.js#L350) |
| ATS Keyword Tailoring | Re-aligns candidate bullets to job requirements | "ATS Tailor" button | `ats_service.tailor_ats_keywords` | **IMPLEMENTED** | [`ats_service.py#L138`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/services/ats_service.py#L138), [`routes/pdf_routes.py#L68`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/pdf_routes.py#L68) |
| Golden Hook Generator | Writes compelling custom opening hook | "Golden Hook" button | `ats_service.generate_golden_hook` | **IMPLEMENTED** | [`ats_service.py#L255`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/services/ats_service.py#L255), [`routes/pdf_routes.py#L91`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/pdf_routes.py#L91) |
| Background Letterhead Templates | Applies 6 professional vector letterheads | Modal gallery selector | `BackgroundTemplateService` | **IMPLEMENTED** | [`create-anschreibens.js#L510`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/create-anschreibens.js#L510), [`app.py#L7051`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7051) |
| Send to Email Outreach | Transfers generated PDFs directly to Campaign Builder | "Transfer to Outreach" button | `/api/prepare-email-transfer` | **IMPLEMENTED** | [`app.py#L7366`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7366) |

**Buttons and Actions:**  
- `btn-generate-all-pdfs`: Triggers batch generation of all candidate cover letters into a ZIP file.
- `btn-transfer-to-outreach`: Prepares campaign staging payload and navigates to `send-emails`.
- `as-record-prev` / `as-record-next`: Steps through candidate rows to inspect real-time placeholder values.
- `btn-ats-tailor`: Executes AI keyword tailoring for active row.

**API Endpoints:**  
- `POST /api/pdf/stream-preview`
- `POST /api/pdf/ats-tailor`
- `POST /api/pdf/golden-hook`
- `POST /api/pdf/culture-vibe`
- `POST /api/pdf/ats-heatmap`
- `GET /api/pdf/fonts`
- `GET /api/pdf-background-templates`
- `POST /api/generate-pdfs`
- `POST /api/prepare-email-transfer`

**Connected Systems:** Client Manager (candidate dossiers), Ausbildungen datasets, Bulk Email Outreach.  
**Known Issues:** None. Full unit and regression test coverage verified in `test_ats_service.py`.  
**Missing Functionality:** No multi-page cover letter overflow indicator; text exceeding 1 page is clipped or pushed to page 2 depending on layout settings.

---

### Page 5: Bulk Email Campaign Builder & Sender

**Purpose:**  
4-step guided wizard for high-deliverability bulk email outreach campaigns with SMTP authentication, attachment matching, anti-spam pre-flight analysis, and domain throttling.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L1960-L2150), [`static/spa/sections/send-emails.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/send-emails.js)
- **Backend:** [`email_sender/sender.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/email_sender/sender.py), [`email_sender/throttler.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/email_sender/throttler.py), [`email_sender/spam_analyzer.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/email_sender/spam_analyzer.py), [`routes/campaigns.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/campaigns.py), [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L4050-L4850)

**Sections and Tabs (Wizard Stepper):**  
- **Step 1: Recipients & Data:** Upload contacts file or load staged Anschreiben batch, select recipient email column, view validation stats.
- **Step 2: Message & Placeholders:** Email subject template, HTML/Text email body, dynamic placeholder pill buttons, attachment directory selection.
- **Step 3: SMTP & Throttling Settings:** SMTP Host, Port, Security (TLS/SSL), Sender Email, App Password, Domain Cooldown (days), Delay Jitter (seconds), Daily Limit.
- **Step 4: Pre-flight Review & Dispatch:** Spam score preview, Send test email to self, Dispatch progress bar, Live success/failed counters, Pause / Stop controls.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| 4-Step Stepper Wizard | Interactive guided workflow | Step indicators & Prev/Next buttons | Frontend view controller | **IMPLEMENTED** | [`send-emails.js#L148`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/send-emails.js#L148) |
| Domain Cooldown Throttler | Prevents emailing same domain within N days | Step 3 cooldown input | `DomainThrottler.can_send` | **IMPLEMENTED** | [`throttler.py#L53`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/email_sender/throttler.py#L53) |
| Pre-Flight Spam Analysis | Evaluates subject/body for spam triggers | Step 4 spam score meter | `SpamAnalyzer.analyze` | **IMPLEMENTED** | [`spam_analyzer.py#L43`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/email_sender/spam_analyzer.py#L43), [`routes/enhancements.py#L69`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/enhancements.py#L69) |
| Test Email Dispatch | Sends actual single email to admin inbox | "Send Test Email" button | `EmailSender.send` | **IMPLEMENTED** | [`send-emails.js#L72`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/send-emails.js#L72), [`app.py#L4250`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L4250) |
| Live SSE Batch Sender | Dispatches emails with jitter & progress events | Live progress bar & ETA | `_execute_bulk_send` SSE | **IMPLEMENTED** | [`app.py#L4740`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L4740) |
| Campaign SQLite Persistence | Saves campaign run details and delivery logs | Visible in Dashboard | `CampaignStore` (`campaigns.db`) | **IMPLEMENTED** | [`services/campaign_store.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/campaign_store.py) |

**Buttons and Actions:**  
- `cb-wizard-next-btn` / `cb-wizard-back-btn`: Step forward and backward through the 4 wizard panes.
- `cb-send-test-btn`: Sends immediate test email using current form settings.
- `send-emails-sendBtn`: Initiates bulk dispatch SSE loop.
- `send-emails-stopSendBtn`: Sends cooperative abort signal to dispatch loop.

**API Endpoints:**  
- `POST /api/send-emails/send-test`
- `POST /api/send-emails/start`
- `GET /api/send-emails/status/<job_id>`
- `POST /api/send-emails/stop/<job_id>`
- `POST /api/email/analyze-spam`
- `GET /api/campaigns`

**Connected Systems:** Anschreiben Studio (PDF attachments), Dashboard (campaign history), Conductor.  
**Known Issues:** None. Verified in `test_app_routes.py` and `test_campaign_store.py`.  
**Missing Functionality:** OAuth2 login flow for Microsoft 365 / Outlook (currently supports username/password and Gmail App Passwords).

---

### Page 6: Conductor Multi-Agent Command Center

**Purpose:**  
Autonomous orchestration hub managing background daily job discovery for active candidates, vacancy matching, human approval staging, auto-application dispatch, IMAP email reply monitoring, and WhatsApp candidate status liaisons.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L2160-L2400), [`static/spa/sections/conductor.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/conductor.js)
- **Backend:** [`routes/conductor.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/conductor.py), [`services/conductor_engine.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_engine.py), [`services/conductor_store.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_store.py), [`services/daily_search_runner.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/daily_search_runner.py), [`services/email_reply_monitor.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/email_reply_monitor.py)

**Sections and Tabs:**  
- **Global Orchestration Header:** Engine status badge, Global Emergency Stop button, Start/Stop Daemon toggle, Check Inbox Now trigger, Run Global Cycle trigger.
- **Top KPI Cards:** Active Candidates, Total Vacancies Matched, Applications Sent, Interviews Detected.
- **Tab 1: Candidate Automations:** Per-candidate configuration cards (Daily limit, auto-apply toggle, search radius, active/paused toggle, manual cycle trigger).
- **Tab 2: Staged Matches & Approvals:** Review discovered job matches, approve for sending, or reject.
- **Tab 3: Email Reply Monitor:** Live IMAP mailbox log, AI intent classification (`interview`, `rejection`, `receipt`), candidate correlation.
- **Tab 4: Queue, Tasks & Settings:** Background task queue table, retry failed tasks button, engine settings form.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Multi-Agent Scheduler Daemon | Background thread running daily cycles | Toggle Daemon button | `ConductorEngine._worker_loop` | **IMPLEMENTED** | [`conductor_engine.py#L110`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_engine.py#L110) |
| Global Emergency Stop | Instantly halts all autonomous sending | Red Emergency Stop button | `ConductorStore.toggle_emergency_stop` | **IMPLEMENTED** | [`conductor_store.py#L420`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_store.py#L420) |
| Match Approval Queue | Staged review before sending applications | Match cards with Approve/Reject | `ConductorEngine.approve_match` | **IMPLEMENTED** | [`conductor_engine.py#L331`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_engine.py#L331) |
| Autonomous Daily Search | Scrapes datasets & portals for each client | Candidate "Run Cycle" button | `DailySearchRunner.run_daily_search_for_client` | **IMPLEMENTED** | [`daily_search_runner.py#L380`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/daily_search_runner.py#L380) |
| IMAP Recruiter Reply Classifier | Polls inbox and categorizes recruiter intent | Tab 3 Inbox Log & Check Now btn | `EmailReplyMonitor.classify_email_content` | **IMPLEMENTED** | [`email_reply_monitor.py#L94`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/email_reply_monitor.py#L94) |
| Candidate WhatsApp Liaison | Sends daily digest & alert on interview | Tab 1 "Send WA Digest" button | `ConductorWhatsAppLiaison` | **IMPLEMENTED** | [`services/conductor_whatsapp_liaison.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_whatsapp_liaison.py) |
| Autonomous Form Submitter | Submits web portal applications via headless browser | Config checkbox | Missing browser worker | **BROKEN / MISSING** | [`conductor_store.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/conductor_store.py) drops `form_link` |

**Buttons and Actions:**  
- `data-cond-action="toggle-engine"`: Starts or pauses background scheduler daemon.
- `data-cond-action="emergency-stop"`: Engages fail-safe kill switch preventing outgoing communication.
- `data-cond-action="check-inbox"`: Triggers immediate IMAP mailbox fetch and email classification.
- `data-cond-action="run-global-cycle"`: Triggers immediate discovery cycle for all active candidates.
- Candidate card buttons: `Run Cycle Now`, `Pause/Resume`, `Send WhatsApp Digest`, `Send Missing Doc Request`.

**API Endpoints:**  
- `GET /api/conductor/status`
- `POST /api/conductor/toggle-engine`
- `POST /api/conductor/toggle-emergency-stop`
- `POST /api/conductor/run-global-cycle`
- `POST /api/conductor/client/<id>/run-cycle`
- `GET /api/conductor/matches`
- `POST /api/conductor/match/<id>/approve`
- `POST /api/conductor/check-inbox-now`
- `POST /api/conductor/sync-applications`
- `POST /api/conductor/task/<id>/retry`

**Connected Systems:** Client Manager, WhatsApp Engine, Email Reply Monitor, Supabase CRM, Daily Search Runner.  
**Known Issues:** Unit test `test_worker_executes_due_search_and_inbox` failed due to strict mock assertion in single loop run.  
**Missing Functionality:** No server-side browser automation to execute application submissions on job portals when only web forms exist.

---

### Page 7: Analytics Dashboard

**Purpose:**  
Executive metrics dashboard displaying campaign performance, delivery rates, open/reply statistics, and historical outreach logs.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L693-L711), [`static/spa/sections/dashboard.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/dashboard.js)
- **Backend:** [`routes/campaigns.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/campaigns.py), [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L3849-L3870)

**Sections and Tabs:**  
- **Metrics Summary Banner:** Total Campaigns, Total Recipient Inboxes Targeted, Successful Deliveries, Failure Rate.
- **Campaign Execution Table:** Lists all campaigns with timestamp, target profession, recipient count, and status badge.
- **Quick Links:** "New Campaign" button redirecting to `send-emails`.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Historical Campaign List | Displays all completed & active outreach runs | Table with status pills | `/api/dashboard/campaigns` | **IMPLEMENTED** | [`dashboard.js#L20`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/dashboard.js#L20), [`app.py#L3849`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L3849) |
| KPI Metric Aggregator | Calculates overall outreach deliverability | 4 metric cards | `_get_enriched_campaigns` | **IMPLEMENTED** | [`dashboard.js#L60`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/dashboard.js#L60) |
| Campaign Detail Inspection | Inspects error logs for failed emails | Modal or drilldown row | `/api/campaigns/<id>` | **IMPLEMENTED** | [`routes/campaigns.py#L21`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/campaigns.py#L21) |

**Buttons and Actions:**  
- `btn-refresh-dashboard`: Refreshes statistics from `campaigns.db`.
- "New Campaign" action link: Switches SPA view to `send-emails`.

**API Endpoints:**  
- `GET /api/dashboard/campaigns`
- `GET /api/campaigns/<id>`
- `DELETE /api/campaigns/<id>`

**Connected Systems:** Bulk Email Campaign Builder (`campaigns.db`), Conductor.  
**Known Issues:** None.  
**Missing Functionality:** No visual time-series charts (e.g. Chart.js) showing daily email volumes over the last 30 days.

---

### Page 8: Supabase Applications & Talent Dossier CRM

**Purpose:**  
Talent onboarding and CRM interface connected to Supabase PostgreSQL. Displays candidate application records, document attachments, and invoice settlement status. Provides one-click candidate onboarding into the local JobScout dossier store.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L712-L1395), [`static/spa/sections/supabase.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/supabase.js)
- **Backend:** [`services/supabase_service.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/supabase_service.py), [`services/onboarding_service.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/onboarding_service.py), [`routes/supabase_onboarding.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/supabase_onboarding.py)

**Sections and Tabs:**  
- **View Switcher & Filter Bar:** Toggle between Card View, Compact List View, and Table View. Search by name/email/profession, filter by payment status (Paid / Open), filter by bank/payment provider.
- **Candidate Application Grid / Cards:** Displays applicant photo, name, email, phone, profession badge, dataset availability badge (Green: Ready, Yellow: Similar, Red: Missing), and payment status pill.
- **Candidate Details Drawer (Slide-out):**
  - Section 1: Candidate Profile & Contact info.
  - Section 2: Profession & Language Preferences.
  - Section 3: JobScout Talent Dossier status & "Import Candidate" action button.
  - Section 4: Application Documents (inspect, preview, download signed URLs).
  - Section 5: Payment Summary & Verification (mark paid, bank transfer details).
  - Section 6: System & Activity timeline.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Multi-View Application Explorer | Card, Compact, and Table representations | View switcher segmented control | `supabase.js` view renderers | **IMPLEMENTED** | [`supabase.js#L859`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/supabase.js#L859) |
| Dataset Availability Badge | Checks if dataset exists for candidate profession | Dynamic Green/Yellow/Red badge | `/api/ausbildungen/availability` | **IMPLEMENTED** | [`supabase.js#L304`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/supabase.js#L304) |
| One-Click Candidate Onboarding | Downloads CV, parses text/AI, builds profile | "Import Candidate" button | `/api/supabase/onboard-candidate` | **IMPLEMENTED** | [`supabase.js#L2174`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/supabase.js#L2174), [`onboarding_service.py#L64`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/onboarding_service.py#L64) |
| Supabase Document Downloader | Fetches candidate CV and certificates | Document list with preview links | `SupabaseService.get_document_bytes` | **IMPLEMENTED** | [`supabase_service.py#L70`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/supabase_service.py#L70) |
| Payment Settlement Toggle | Confirms payment before unlocking onboarding | "Mark Paid" button in drawer | Updates Supabase `is_payed` | **IMPLEMENTED** | [`supabase.js#L1360`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/supabase.js#L1360) |

**Buttons and Actions:**  
- `sp-view-cards-btn` / `sp-view-compact-btn` / `sp-view-table-btn`: Switch layout representation.
- `sp-d-onboard-btn` ("Import Candidate"): Starts automated onboarding pipeline.
- `sp-filter-payment`: Filters candidates by Paid vs Pending.
- Action on missing dataset: Clicking red badge switches view to `search` with pre-filled profession.

**API Endpoints:**  
- `GET /api/firebase/applications` (Supabase applications fetcher)
- `POST /api/supabase/onboard-candidate`
- `GET /api/supabase/onboarding-status/<app_id>`
- `GET /api/ausbildungen/availability`

**Connected Systems:** Supabase Cloud, Onboarding Service, Client Manager, Autofill Hub, WhatsApp Engine, Conductor.  
**Known Issues:** None.  
**Missing Functionality:** No background worker auto-importing paid candidates without requiring an administrator to click the UI button.

---

### Page 9: Revenue & Money Monitor

**Purpose:**  
Financial accounting dashboard displaying gross revenue, settled candidate payments, outstanding invoices, and billing statistics.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L1397-L1565), [`static/spa/sections/money.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/money.js)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2730-L2735)

**Sections and Tabs:**  
- **Financial Metric Cards:** Total Gross Volume (€), Total Collected Revenue (€), Pending Invoices (€), Paid Candidate Count.
- **Payment Method Distribution:** Breakdown across SEPA Bank Transfer, PayPal, Stripe, and Cash.
- **Transactions & Invoice Ledger Table:** Candidate name, profession, invoice date, amount (€), payment method, status pill (Paid / Unpaid).
- **Export Toolbar:** Export financial data as CSV or Excel.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Live Revenue Aggregation | Calculates total collected vs pending revenue | 4 KPI summary cards | Computed from Supabase records | **IMPLEMENTED** | [`money.js#L40`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/money.js#L40) |
| Transaction Ledger Table | Lists all candidate billing items | Data table with filters | Client & Supabase records | **IMPLEMENTED** | [`money.js#L95`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/money.js#L95) |
| Payment Provider Filter | Filters by SEPA, PayPal, Stripe, etc. | Dropdown select | Frontend filter engine | **IMPLEMENTED** | [`money.js#L140`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/money.js#L140) |
| Financial Export | Exports billing ledger to spreadsheet | "Export Ledger" button | Blob download generator | **IMPLEMENTED** | [`money.js#L185`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/money.js#L185) |

**Buttons and Actions:**  
- `money-filter-status`: Filters ledger by Paid vs Open.
- `money-export-btn`: Generates and downloads CSV ledger.

**API Endpoints:** Reads directly from client & application datasets via shared memory and Supabase API.  
**Connected Systems:** Supabase Applications, Client Manager.  
**Known Issues:** None.  
**Missing Functionality:** No direct webhook integration with Stripe or PayPal for real-time automated invoice status webhooks.

---

### Page 10: WhatsApp AI Communication & Takeover Hub

**Purpose:**  
Production-grade Meta WhatsApp Cloud API communication suite. Combines an autonomous AI support agent with real-time SSE chat streaming, instant human takeover locks, draft response suggestion, and knowledge base CRUD.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L2410-L2600), [`static/spa/sections/whatsapp.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/whatsapp.js)
- **Backend:** [`routes/whatsapp.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py), [`services/whatsapp_service.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_service.py), [`services/whatsapp_ai_engine.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_ai_engine.py), [`services/whatsapp_store.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_store.py), [`services/whatsapp_tools.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_tools.py)

**Sections and Tabs:**  
- **Tab 1: Inbox (Live Support Desk):** Two-pane interface with conversation list (unread counters, AI/Human badges) on left and active chat thread on right.
  - Chat Actions: Human Takeover button, Resume AI button, Escalate to Admin, Close Conversation, Suggest Draft generator.
  - Quick Info Drawer: Associated candidate dossier, verification status, applications sent count, interviews detected.
- **Tab 2: Overview & Metrics:** Real-time messages count, AI automation percentage, intent breakdown chart, audit log table.
- **Tab 3: Configuration:** AI auto-reply toggle, emergency pause, cooldown minutes, system prompt editor.
- **Tab 4: Knowledge Base:** Q&A pairs, trigger keywords, Add/Edit/Delete modal dialog.
- **Tab 5: Meta Setup & Verification:** Webhook callback URL, verify token, test ping tool.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Meta Cloud API Webhook | Handles incoming WhatsApp webhook events | Automatic | `/api/whatsapp/webhook` | **IMPLEMENTED** | [`routes/whatsapp.py#L37`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py#L37), [`whatsapp_service.py#L120`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_service.py#L120) |
| Live SSE Message Stream | Real-time chat updates without polling | In-chat message stream | `/api/whatsapp/stream` | **IMPLEMENTED** | [`routes/whatsapp.py#L85`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py#L85) |
| Automated Tool Calling | AI checks application stats and dossiers | Automatic during AI reply | `WhatsAppTools` (10 tools) | **IMPLEMENTED** | [`services/whatsapp_tools.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/whatsapp_tools.py) |
| Instant Human Takeover | Silences AI immediately and grants human control | "Takeover" button | `/api/whatsapp/conversation/<id>/takeover` | **IMPLEMENTED** | [`whatsapp.js#L58`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/whatsapp.js#L58), [`routes/whatsapp.py#L239`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py#L239) |
| AI Draft Suggestion | Generates proposed response for agent review | "Suggest Draft" button | `WhatsAppAIEngine.generate_draft_suggestion` | **IMPLEMENTED** | [`routes/whatsapp.py#L388`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py#L388) |
| Knowledge Base CRUD | Manages custom business answers | KB data table & modal | `/api/whatsapp/knowledge-base` | **IMPLEMENTED** | [`routes/whatsapp.py#L399`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/whatsapp.py#L399) |

**Buttons and Actions:**  
- `wa-btn-takeover`: Locks conversation in human mode and disables AI generation.
- `wa-btn-resume-ai`: Returns conversation to automated AI handling.
- `wa-btn-emergency-pause-header`: Global toggle freezing all outgoing WhatsApp AI messages.
- `wa-btn-generate-draft`: Requests AI recommendation for agent review without sending.
- `wa-btn-add-kb`: Opens modal to insert new knowledge base snippet.

**API Endpoints:**  
- `GET/POST /api/whatsapp/webhook`
- `GET /api/whatsapp/stream`
- `GET /api/whatsapp/conversations`
- `GET /api/whatsapp/conversation/<id>/messages`
- `POST /api/whatsapp/conversation/<id>/reply`
- `POST /api/whatsapp/conversation/<id>/takeover`
- `POST /api/whatsapp/conversation/<id>/resume-ai`
- `POST /api/whatsapp/conversation/<id>/suggest-draft`
- `GET/POST/PUT/DELETE /api/whatsapp/knowledge-base`

**Connected Systems:** Client Manager (phone verification), Conductor (liaison alerts), AI Provider Manager.  
**Known Issues:** None. 17 of 17 tests passed in `test_whatsapp_support.py`.  
**Missing Functionality:** Sending rich WhatsApp interactive button templates (currently sends plain text and document attachments).

---

### Page 7: AI Gateway & Model Settings

**Purpose:**  
Centralized AI configuration control room managing OpenAI and Google Gemini credentials, model routing, zero-token connectivity testing, usage accounting, and cache management.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L2610-L2710), [`static/spa/sections/ai-settings.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/ai-settings.js)
- **Backend:** [`services/ai_provider_manager.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py), [`routes/ai_settings.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/ai_settings.py)

**Sections and Tabs:**  
- **Primary Provider Selection:** Radio buttons for OpenAI vs Google Gemini.
- **OpenAI Configuration Card:** API Key input (masked), Show/Hide toggle, Model selection dropdown (`gpt-4o`, `gpt-4o-mini`, `gpt-5.6-luna`), Test Connection button.
- **Google Gemini Configuration Card:** API Key input (masked), Show/Hide toggle, Model selection dropdown (`gemini-1.5-flash`, `gemini-1.5-pro`, `gemini-2.0-flash`), Test Connection button.
- **Token & Cost Usage Accounting:** Total Input Tokens, Total Output Tokens, Total Estimated Cost ($/€), Per-task cost breakdown table (CV Parsing, ATS Tailor, WhatsApp, Conductor).
- **Zero-Cost Cache Control:** Cache entry count, Cache size, "Clear AI Cache" button.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Centralized Model Routing | Routes all AI tasks through active provider | Provider radio buttons | `AIProviderManager.complete` | **IMPLEMENTED** | [`ai_provider_manager.py#L497`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py#L497) |
| Secret Key Masking | Never exposes raw API keys to browser | Masked inputs (`sk-...****`) | `AIProviderManager.mask_key` | **IMPLEMENTED** | [`ai_provider_manager.py#L179`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py#L179) |
| Zero-Token Connectivity Test | Tests API credentials without inference spend | "Test Connection" button | Model list ping | **IMPLEMENTED** | [`ai_provider_manager.py#L246`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py#L246), [`routes/ai_settings.py#L101`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/ai_settings.py#L101) |
| Granular Spend Accounting | Tracks token usage and financial cost per task | Usage table with timestamps | `_record_usage` (`ai_usage.json`) | **IMPLEMENTED** | [`ai_provider_manager.py#L415`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py#L415) |
| SHA-256 Zero-Cost Cache | Returns cached completions for identical prompts | Cache stats & reset button | `_get_cached` (`ai_cache.json`) | **IMPLEMENTED** | [`ai_provider_manager.py#L360`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/services/ai_provider_manager.py#L360) |
| Autofill Node.js Bridge | Proxies AI calls for local Node.js server | Internal endpoint | `/api/ai/bridge-autofill` | **IMPLEMENTED** | [`routes/ai_settings.py#L160`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/ai_settings.py#L160) |

**Buttons and Actions:**  
- `ai-openai-test-btn` / `ai-gemini-test-btn`: Pings respective AI provider.
- `ai-openai-save-btn` / `ai-gemini-save-btn`: Persists configuration to `data/ai_config.json`.
- `ai-btn-reset-cache`: Purges `data/ai_cache.json`.
- `ai-btn-refresh-usage`: Reloads real-time token spend table.

**API Endpoints:**  
- `GET /api/ai/settings`
- `POST /api/ai/settings`
- `POST /api/ai/test-connection`
- `GET /api/ai/usage`
- `POST /api/ai/reset-cache`
- `POST /api/ai/bridge-autofill`

**Connected Systems:** CV Parser, Anschreiben ATS Service, WhatsApp AI Engine, Daily Search Runner, Autofill Node Server.  
**Known Issues:** None. 12 of 12 tests passed in `test_ai_provider_manager.py`.  
**Missing Functionality:** No alert threshold setting to automatically pause AI calls if monthly spend exceeds a dollar cap.

---

### Page 12: Autofill Hub & Candidate Profiles

**Purpose:**  
Candidate dossier editing hub, CV resume importer, and testing ground for the JobScout Chrome Extension. Features interactive application sandbox iframes with German and French forms.

**Source Files:**  
- **Frontend:** [`templates/app_shell.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/app_shell.html#L2720-L2950), [`static/spa/sections/autofill-hub.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/autofill-hub.js)
- **Backend:** [`routes/autofill.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py), [`routes/clients.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/clients.py)

**Sections and Tabs:**  
- **Profile Selector & Dossier Header:** Candidate select dropdown, Active candidate badge, "Set Active" button, "Import CV" upload button, "New Profile" button.
- **Tab 1: Personal Info:** Name, Birthday, Email, Phone, Street, House Number, Postal Code, City, Country, LinkedIn, GitHub.
- **Tab 2: Education & Experience:** Schools, degrees, employers, job titles, start/end dates, key skill tags.
- **Tab 3: Documents:** Uploaded candidate files (Lebenslauf, Anschreiben, Zeugnisse) with download/preview buttons.
- **Tab 4: Raw JSON Editor:** Full JSON schema editor for manual fine-tuning with syntax validation.
- **Tab 5: AI Corrections & Learnings:** Shows user-corrected form field mappings persisted for future auto-fill tasks.
- **Tab 6: Application Sandbox:** Interactive embedded iframe running `test-form.html` (German) or `french-form.html` (French) with split-screen extension simulation.
- **Tab 7: Application History:** Log of submitted job applications with company, portal URL, and timestamp.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Candidate Dossier CRUD | Complete management of candidate records | Tabbed forms & save button | `/api/clients` & `/api/autofill/save-profile` | **IMPLEMENTED** | [`clients.py#L28`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/clients.py#L28), [`autofill.py#L290`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L290) |
| Active Candidate Pointer | Switches global active candidate | "Set as Active" button | `ClientManager.set_active_client_id` | **IMPLEMENTED** | [`clients.py#L68`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/clients.py#L68) |
| Multi-Format Document Storage | Saves candidate PDFs and images | Documents tab file grid | `ClientManager.save_document` | **IMPLEMENTED** | [`clients.py#L249`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/clients.py#L249) |
| Interactive Form Sandbox | Tests autofill behavior on mock application portals | Split iframe sandbox | `/api/autofill/test-form` & `french-form` | **IMPLEMENTED** | [`autofill.py#L703`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L703) |
| Deterministic & AI Field Matching | Maps form input fields to candidate data | Extension bridge | `python_deterministic_matcher` | **IMPLEMENTED** | [`autofill.py#L355`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L355) |
| Submitted Application Logger | Logs successfully submitted job applications | Application History tab | `data/autofill_applications.json` | **IMPLEMENTED** | [`autofill.py#L669`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L669) |

**Buttons and Actions:**  
- `autofill-btn-new-profile`: Creates a blank candidate dossier.
- `autofill-btn-save-profile`: Persists form edits to `profile.json`.
- `autofill-btn-set-active`: Sets current profile as the active platform candidate.
- `btn-load-de-form` / `btn-load-fr-form`: Switches sandbox iframe between German and French test application forms.
- `af-btn-clear-corrections`: Clears cached field correction overrides.

**API Endpoints:**  
- `GET /api/autofill/profiles`
- `GET /api/autofill/profile/<id>`
- `POST /api/autofill/save-profile`
- `POST /api/autofill/ingest-cv`
- `POST /api/autofill/map-fields`
- `POST /api/autofill/log-application`
- `GET /api/autofill/logged-applications`
- `GET /api/autofill/test-form`
- `GET /api/autofill/french-form`

**Connected Systems:** Chrome Extension, Client Manager, Supabase Onboarding, Anschreiben Studio.  
**Known Issues:** None. Verified in `test_autofill_routes.py`.  
**Missing Functionality:** No visual diff tool when comparing a candidate's CV data against manual edits.

---

### Page 13: Standalone Anschreiben Studio (`/pdf`)

**Purpose:**  
Independent, full-page fallback interface for generating DIN 5008 cover letters directly without the full JobScout SPA shell.

**Source Files:**  
- **Frontend:** [`pdf_generator/frontend/index.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/frontend/index.html), [`pdf_generator/frontend/script.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/frontend/script.js), [`pdf_generator/frontend/styles.css`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/frontend/styles.css)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L3032-L3045)

**Sections and Tabs:**  
- Header toolbar, Editor pane, Real-time PDF preview canvas, Typography & margin settings modal.

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Standalone Cover Letter Editor | Dedicated non-SPA PDF generation UI | Standalone HTML/CSS/JS page | Serves `pdf_generator/frontend/` | **DEPRECATED** | [`app.py#L3032`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L3032) |
| Custom Background Upload | Uploads custom letterhead PDF | File picker | `/api/upload-design-pdf` | **IMPLEMENTED** | [`script.js#L140`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/pdf_generator/frontend/script.js#L140) |

**Connected Systems:** PDF Service, Template Service.  
**Known Issues:** Superseded by the unified SPA section `create-anschreibens`.  
**Missing Functionality:** Not connected to Supabase candidate onboarding or Conductor automations.

---

### Page 14: Extraction Progress Monitor (`/extraction_progress`)

**Purpose:**  
Server-rendered progress view for legacy single-run email extraction tasks.

**Source Files:**  
- **Frontend:** [`templates/extraction_progress.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/extraction_progress.html)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7612-L7625)

**Sections and Tabs:** Single card container with progress bar, status text, and Abort / Continue controls.  
**Status:** **DEPRECATED**. Replaced by modern inline SSE progress panels inside `search` and `ausbildungen`.

---

### Page 15: Auto-Extraction Live Progress (`/auto_extraction_progress`)

**Purpose:**  
Server-rendered progress screen for multi-stage automated batch scraping runs.

**Source Files:**  
- **Frontend:** [`templates/auto_extraction_progress.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/auto_extraction_progress.html)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7619-L7645)

**Sections and Tabs:** Live progress bar, domain crawl counter, emails found counter, error log list.  
**Status:** **DEPRECATED**. Replaced by unified SSE streaming in the SPA shell.

---

### Page 16: Manual Captcha Solver Screen (`/captcha_solve`)

**Purpose:**  
Emergency user-facing screen presented when automated headless scrapers encounter Cloudflare Turnstile or reCAPTCHA challenges that cannot be resolved automatically.

**Source Files:**  
- **Frontend:** [`templates/captcha_solve.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/captcha_solve.html)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7664-L7688), [`scraper/captcha_handler.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/captcha_handler.py)

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| Manual CAPTCHA Resolution | Prompts user to solve blocked webpage | Embedded iframe / screenshot | `/api/captcha_solved` | **IMPLEMENTED** | [`app.py#L7669`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L7669) |
| TrueCaptcha Automated Solver | Resolves image captchas via solver API | Automatic background | `scraper/true_captcha_solver.py` | **IMPLEMENTED** | [`true_captcha_solver.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/true_captcha_solver.py) |

**Connected Systems:** Scraper core, Browser driver.

---

### Page 17: Server-Rendered Search Results View (`/search`)

**Purpose:**  
Legacy multi-page search results view rendered server-side via Jinja2 when POSTing the original `/search` form.

**Source Files:**  
- **Frontend:** [`templates/results.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/results.html)
- **Backend:** [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6350-L6425)

**Features:** Standard 21-column HTML table displaying search results with Excel download button.  
**Status:** **DEPRECATED**. Superseded by client-side SSE table rendering in `static/spa/sections/search.js`.

---

### Page 18: Global Error Page (`templates/error.html`)

**Purpose:**  
Displays unhandled backend exceptions, 404s, or fatal configuration errors with error details and a navigation return link.

**Source Files:**  
- **Frontend:** [`templates/error.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/error.html)
- **Backend:** Flask error handlers in [`app.py`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L6422)

**Status:** **IMPLEMENTED**. Clean, responsive fallback screen.

---

### Page 19: Legacy Unrouted Landing (`templates/index.html`)

**Purpose:**  
Original static HTML landing page created prior to the single-page application refactoring.

**Source Files:**  
- **Frontend:** [`templates/index.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/templates/index.html)
- **Backend:** None (not referenced by any route in `app.py`).

**Status:** **DEPRECATED / UNROUTED**. Preserved for historical reference; safe to archive.

---

### Page 20: JobScout Chrome Extension Popup

**Purpose:**  
Browser extension popup UI allowing candidates and administrators to trigger autofill actions directly while viewing third-party application portals.

**Source Files:**  
- **Extension Files:** [`ai-job-autofill/extension/popup.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/popup.html), [`popup.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/popup.js), [`popup.css`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/popup.css), [`content.js`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/content.js)

**Features:**

| Feature | Description | UI | Backend | Status | Source |
|---|---|---|---|---|---|
| One-Click Autofill Button | Injects candidate details into web page | Primary action button in popup | Injected script (`content.js`) | **IMPLEMENTED** | [`popup.js#L50`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/popup.js#L50), [`content.js#L120`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/content.js#L120) |
| Active Candidate Switcher | Selects candidate profile to fill | Profile select dropdown | `/api/autofill/profiles` | **IMPLEMENTED** | [`popup.js#L95`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/popup.js#L95) |
| Document Uploader Trigger | Automatically attaches CV to file inputs | "Upload Resume" button | Base64 file dispatcher | **IMPLEMENTED** | [`content.js#L450`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/content.js#L450) |
| Field Mapping Review | Visual overlay highlighting filled fields | Green field outline styling | DOM manipulation | **IMPLEMENTED** | [`content.js#L680`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/extension/content.js#L680) |

**Connected Systems:** Autofill Hub API (`routes/autofill.py`), Client Manager.  
**Known Issues:** Requires user to enable Developer Mode and load unpacked extension in Chrome/Edge.  
**Missing Functionality:** No automated one-click installation script.

---

### Page 21: German Application Sandbox Form (`test-form.html`)

**Purpose:**  
Comprehensive German job application form simulation used to verify regex matchers, date formats, and AI answering before live deployment.

**Source Files:**  
- **Source:** [`ai-job-autofill/server/test-form.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/server/test-form.html)
- **Backend:** [`routes/autofill.py#L703`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L703) (`GET /api/autofill/test-form`)

**Features:** Personal info, German address format (`Straße`, `Hausnummer`, `PLZ`), educational degrees (`Abitur`, `Realschule`), radio buttons, multi-select checkboxes, file upload inputs, and German open-ended questions ("Warum möchten Sie bei uns arbeiten?").  
**Status:** **IMPLEMENTED**. Fully integrated into Autofill Hub Sandbox tab.

---

### Page 22: French Application Sandbox Form (`french-form.html`)

**Purpose:**  
French job application form simulation used to verify international multilingual matching, French date parsing, and phone number normalization.

**Source Files:**  
- **Source:** [`ai-job-autofill/server/french-form.html`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/ai-job-autofill/server/french-form.html)
- **Backend:** [`routes/autofill.py#L715`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/routes/autofill.py#L715) (`GET /api/autofill/french-form`)

**Features:** French input fields (`Nom`, `Prénom`, `Adresse`, `Code Postal`, `Ville`, `Téléphone`, `Lettre de motivation`, `Télécharger CV`).  
**Status:** **IMPLEMENTED**. Fully integrated into Autofill Hub Sandbox tab.
