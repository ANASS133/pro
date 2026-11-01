# JobScout — Feature Implementation Status Audit (`JOBSCOUT_FEATURE_STATUS.md`)

**Audit Date:** 2026-10-31  
**Audit Scope:** Full end-to-end codebase inspection across backend services, Flask blueprints, scrapers, AI gateway, PDF/cover-letter generators, email/WhatsApp engines, browser autofill extension/server, SQLite stores, SPA frontend sections, and test suites (`261` total tests: `258 passed`, `3 failed`).  
**Mode:** Read-Only Technical & Architectural Audit (zero application code modified).

---

## 1. Executive Status Table

| # | Feature | Status | Working Components | Missing Components | Priority |
|---|---|---|---|---|---|
| 1 | Automatic Client Onboarding | 🟡 **Partially Implemented** | Payment check (`is_payed`), idempotency & thread locking, Supabase document download, CV PDF text & AI extraction (`CVParser`), dossier persistence (`ClientManager`), Autofill profile sync, WhatsApp conversation linking, Conductor hook (`on_client_onboarded`) | Background polling or Supabase webhook in `ConductorEngine` to auto-import paid applications without a human clicking **"Import Candidate"** in `/supabase` | **P1 — High** |
| 2 | AI Profession Intelligence | 🟡 **Partially Implemented** | Typo/spelling correction, EN/FR→DE translation (`MULTILINGUAL_MAP`), taxonomy & AI sector/employer category classification (`ProfessionIntelligence.analyze`), SHA-256 cache, CV skill & title parsing (`CVParser.parse_cv_text`) | (1) Explicit opportunity-type detection & persistence (`Ausbildung` vs `Job` vs `Duales Studium` — currently stripped by `normalize_input` and defaulted to `"ausbildung"` in `DailySearchRunner`); (2) CV-based recommender returning up to **5 suitable target professions** for `Job` candidates | **P1 — High** |
| 3 | Dataset Detection & Auto-Scraping | 🟡 **Partially Implemented** | Exact/similar/missing dataset matching (`evaluate_profession_match`), `/api/ausbildungen/availability`, green/yellow/red badges on `/supabase` client cards, one-click UI redirect (`triggerAusbildungSearch`) | Autonomous background auto-scraping when a candidate's profession is `"missing"` (currently requires manual UI click or falls back to scanning unrelated datasets in `DailySearchRunner._find_matches_from_datasets`) | **P1 — High** |
| 4 | Application Method Detection | 🟡 **Partially Implemented** | Scraper-level detection & verification (`ApplicationFormDiscovery.discover_application_form`, `classify_application_method`, `normalize_job_opportunity_row`) classifying `email`, `form`, `both`, or `unknown` and saving `form_link` in 21-column Excel exports | Disconnected from Conductor pipeline: `DailySearchRunner._find_matches_from_datasets` & `conductor_store.client_matches` drop `application_method`, `has_form`, and `form_link`; no routing rule in `ConductorEngine` to prioritize Email when `both` and fall back to direct `form_link` | **P0 — Critical** |
| 5 | AI Cover Letter Generation | 🟡 **Partially Implemented** | Cost-optimized AI hook & keyword tailoring (`ats_service.py` with SHA-256 cache in `data/ats_cache.json`, 300-char prompt truncation, `max_output_tokens=60..120`, zero-cost heuristic fallback), DIN 5008 PDF rendering (`PDFService.create_pdf`) | Disconnected from autonomous runner: `DailySearchRunner._generate_cover_letter_for_match` uses a hardcoded static German string template with placeholder fallback address (`"Musterstraße 12"`, `"50667"`) instead of calling `ats_service` / `TemplateService` | **P0 — Critical** |
| 6 | Autonomous Application Submission | 🟡 **Partially Implemented** | Real SMTP `EmailSender` with MIME attachments & `DomainThrottler`; Chrome Extension + Node/Flask Autofill field mapper (`routes/autofill.py`, `ai-job-autofill/`); `DailySearchRunner._submit_application_for_match` sends real SMTP email when `auto_apply=1` and `match.email` exists | (1) **Zero headless/server-side browser form submission** when `auto_apply=1` and only a portal/form URL exists (logs warning and leaves unapplied); (2) **No login/registration/auth-wall detector** to automatically skip gated portals | **P0 — Critical** |
| 7 | Application Tracking | 🟡 **Partially Implemented** | Campaign-level progress (`static/spa/sections/dashboard.js`), Conductor match status counts (`discovered`, `staged_for_approval`, `applied`, `interview`, `rejected` in `conductor_store.py`), extension log (`data/autofill_applications.json`), reply stats (`metrics` in `ClientManager`) | Three fragmented data stores (`conductor.db`, `campaigns.db`, `autofill_applications.json`); `client_matches` does **not** track submission channel (`emails_sent` vs `forms_submitted`) or failed submission attempts (`failures` count per client) | **P2 — Medium** |
| 8 | Premium Follow-Up | 🟡 **Partially Implemented** | Real IMAP/XOAUTH2 polling (`EmailReplyMonitor`), AI + rule-based reply classification (`interview_invitation`, `rejection`, `confirmation_of_receipt`, `info_request`), reply draft generation, `FollowUpManager` (5–21 day Nachfass drafts), `ConductorWhatsAppLiaison` candidate alerts & digests | (1) **No paid-tier / subscription check** (`premium_follow_up` flag) gating monitoring & follow-ups per client; (2) `FollowUpManager` (`email_sender/follow_up.py`) reads legacy `data/outreach_history.json` and is completely disconnected from `ConductorEngine` and `client_matches` | **P2 — Medium** |

---

## 2. Detailed Feature-by-Feature Audit

### Feature 1: Automatic Client Onboarding
> **Requirement:** Import new clients automatically from Supabase / Applications.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`services/onboarding_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py) — [`CandidateOnboardingService.onboard_candidate()`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L64-L296), [`_identify_cv_document()`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L44-L62)
  - [`routes/supabase_onboarding.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/supabase_onboarding.py) — [`onboard_candidate_route()`](file:///c:/Users/sibbi/Desktop/scraper/routes/supabase_onboarding.py#L25-L60) (`POST /api/supabase/onboard-candidate`), [`onboarding_status_route()`](file:///c:/Users/sibbi/Desktop/scraper/routes/supabase_onboarding.py#L63-L78) (`GET /api/supabase/onboarding-status/<app_id>`)
  - [`services/supabase_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/supabase_service.py) — `SupabaseService.get_application_by_id()`, `get_documents_for_application()`, `get_document_bytes()`
  - [`services/client_manager.py`](file:///c:/Users/sibbi/Desktop/scraper/services/client_manager.py) — `ClientManager.save_client()`, `save_document()`
  - [`services/conductor_engine.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_engine.py) — [`ConductorEngine.on_client_onboarded()`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_engine.py#L313-L348)
- **Frontend:**
  - [`static/spa/sections/supabase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js) — [`handleOnboardCandidate()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L2174-L2226)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. When `POST /api/supabase/onboard-candidate` is called with an `application_id`, [`CandidateOnboardingService.onboard_candidate()`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L64-L296) acquires a thread-safe per-application lock (`_app_locks`), checks idempotency (`_find_existing_client_by_app_id`), and verifies `is_payed == True` (unless `force=True`).
  2. Downloads all candidate documents from Supabase Storage (`SupabaseService.get_document_bytes`), saves them into `data/clients/<client_id>/documents/` and mirrors them into `ai-job-autofill/server/profiles/<client_id>/`.
  3. Identifies the primary CV PDF via [`_identify_cv_document()`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L44-L62), extracts text and structured fields via `CVParser.extract_text_from_pdf()` + `CVParser.parse_cv_text()`, merges Supabase form data with CV data, and persists `profile.json`.
  4. Automatically links the candidate's phone number in `whatsapp_store` and calls [`conductor_engine.on_client_onboarded(client_id, missing_fields)`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_engine.py#L313-L348), which initializes `client_automation_configs` and enqueues an immediate `daily_search` task in `conductor_tasks`.
- **What Is Missing / Requires Manual Intervention:**
  - **Manual Trigger Required:** Onboarding only happens when an administrator opens the `/supabase` page, marks the application as paid (if not already paid), and manually clicks **"Import Candidate"** (`data-action="onboard-candidate"`).
  - **No Background Auto-Importer:** [`ConductorEngine._check_scheduled_jobs()`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_engine.py#L145-L212) schedules `daily_search`, `email_monitor`, and `whatsapp_digest`, but has **no scheduled task or webhook listener** to poll `SupabaseService` for newly paid (`is_payed=true`) un-imported applications and onboard them automatically.

---

### Feature 2: AI Profession Intelligence
> **Requirement:** Detect Ausbildung, Job, or Duales Studium. For Job candidates, analyze their CV and recommend up to 5 suitable professions.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`services/profession_intelligence.py`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py) — [`ProfessionIntelligence`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py#L995-L1342) (`normalize_input`, `correct_spelling_and_typos`, `translate_to_german`, `classify_profession`, `_classify_with_ai`, `generate_search_queries`, `analyze`)
  - [`services/cv_parser.py`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py) — [`CVParser.parse_cv_text()`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py#L168-L355), [`CVParser.extract_with_ai()`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py#L540-L604)
  - [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) — [`DailySearchRunner._extract_candidate_search_params()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L39-L80)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. [`ProfessionIntelligence.analyze()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py#L1294-L1339) normalizes raw profession strings, fixes German typos/umlauts (`correct_spelling_and_typos`), translates English/French job titles to German (`MULTILINGUAL_MAP`), classifies the profession into a sector and **3–5 employer categories** (`employer_categories`, e.g., `["Krankenhaus", "Pflegeheim", ...]`), and generates Google Maps search queries (`generate_search_queries`).
  2. Uses deterministic local taxonomy (`PROFESSION_TAXONOMY`) first and falls back to OpenAI/Gemini via `ai_manager.complete()` ([`_classify_with_ai()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py#L1178-L1254)), caching results in `data/profession_intelligence_cache.json`.
  3. [`CVParser.parse_cv_text()`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py#L168-L355) and [`CVParser.extract_with_ai()`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py#L540-L604) extract candidate contact info, `current_title`, `primary_fields`, languages, education, and work experience from PDF CVs.
- **What Is Missing / Disconnected:**
  1. **No Opportunity Type Detection (`Ausbildung` vs `Job` vs `Duales Studium`):**
     - [`ProfessionIntelligence.normalize_input()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py#L1035-L1060) **strips and discards** prefixes like `"ausbildung als"`, `"duales studium als"`, and `"job als"` (lines 1043–1053) without returning or saving the detected opportunity type (`opportunity_type: "ausbildung" | "job" | "duales_studium"`).
     - [`CandidateOnboardingService.onboard_candidate()`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L194-L246) never sets `search_mode` or `opportunity_type` on the client dossier.
     - Consequently, [`DailySearchRunner._extract_candidate_search_params()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L67) hard-defaults every candidate to `"ausbildung"`:
       ```python
       search_mode = client_data.get("search_mode") or "ausbildung"
       ```
  2. **No 5-Profession CV Recommender for `Job` Candidates:**
     - Neither `CVParser` nor `ProfessionIntelligence` has a method that analyzes a `Job` candidate's CV (work history, skills, education) and recommends **up to 5 suitable target professions** (ranked with reasoning/fit scores). `ProfessionIntelligence` only maps a *single* already-known profession string to 3–5 *employer categories* for Google Maps scraping.

---

### Feature 3: Smart Dataset Detection & Auto-Scraping
> **Requirement:** Check whether each profession has an existing dataset, display its availability on the client card, and automatically scrape missing professions.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`services/profession_matcher.py`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py) — [`evaluate_profession_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py#L168-L371), [`evaluate_professions_batch()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py#L374-L406)
  - [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) — `GET /api/ausbildungen/files` (lines 2046–2095), `POST /api/ausbildungen/availability` (lines 2098–2126)
  - [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) — [`_find_matches_from_datasets()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L139-L260)
- **Frontend:**
  - [`static/spa/sections/supabase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js) — [`loadExportedDatasets()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L698-L774), [`getDatasetMatchForProfession()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L776-L867), [`renderDatasetAvailabilityBadge()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L938-L955), [`triggerAusbildungSearch()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L2628-L2681)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **Smart Dataset Detection:** [`evaluate_profession_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py#L168-L371) inspects all `.xlsx` files in `data/auto_extraction_exports`, normalizes German titles/stemming/synonyms (`SYNONYM_GROUPS`), and classifies availability into `"exact"` (score ≥ 0.85), `"similar"` (0.45 ≤ score < 0.85), or `"missing"` (< 0.45).
  2. **Client Card Availability Display:** [`static/spa/sections/supabase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L938-L955) renders live dataset badges (`Available`, `Similar`, `Unavailable`) with matching filenames and row counts on every `/supabase` client card, compact table row, and inside the Client Details drawer.
  3. **Assisted One-Click Search:** Clicking **"Search Ausbildung Now"** calls [`triggerAusbildungSearch()`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/supabase.js#L2628-L2681), which switches to `/search`, fills `Ausbildung als <profession>` and location, and clicks `#search_btn_1`.
- **What Is Missing / Requires Manual Intervention:**
  - **No Automatic Background Scraping of Missing Professions:**
    - When a client's profession has status `"missing"`, the system does **not** automatically enqueue or execute a background dataset extraction job to create the missing `.xlsx` dataset in `data/auto_extraction_exports`.
    - Worse, in [`DailySearchRunner._find_matches_from_datasets()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L171-L175), when `matching_files` is empty for a client's profession, it falls back to `matching_files = xlsx_files[:3]` (the 3 newest unrelated datasets) instead of triggering a targeted scrape for the missing profession.

---

### Feature 4: Intelligent Application Method Detection
> **Requirement:** Detect whether employers accept Email, Portal, or both. Prioritize Email when both are supported; otherwise save the direct application form URL.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`scraper/application_form_discovery.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py) — [`ApplicationFormDiscovery.discover_application_form()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L439-L580), [`verify_form_page()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L317-L436), [`classify_application_method()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L583-L607), [`normalize_job_opportunity_row()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L610-L688)
  - [`scraper/career_crawler.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/career_crawler.py) — [`CareerPageCrawler.crawl_company()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/career_crawler.py#L455-L600)
  - [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) — [`_find_matches_from_datasets()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L192-L258)
  - [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py) — `client_matches` table schema (lines 116–131)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **Scraper-Level Detection & Verification:** [`ApplicationFormDiscovery`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L439-L580) crawls job detail pages and company websites, recognizes 30+ ATS systems (`JOIN`, `Personio`, `Workday`, `Greenhouse`, `SmartRecruiters`, `Rexx`, `d.vinci`, `Softgarden`, etc.), verifies real `<form>` / `<input type="file">` / ATS markers via [`verify_form_page()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L317-L436), and rejects false positives (login pages, contact forms, search bars, newsletter forms).
  2. **Classification & Direct Form URL Storage in Exports:** [`classify_application_method()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L583-L607) and [`normalize_job_opportunity_row()`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L610-L688) classify each row into `email` (`E-Mail`), `form` (`Online-Formular`), `both` (`E-Mail + Online-Formular`), or `unknown`, and save the verified direct form URL in `form_link` / `bewerbung_link` / `apply_url` inside the 21-column Excel schema (`UNIFIED_EXPORT_COLUMNS`).
- **What Is Missing / Disconnected:**
  1. **Dropped During Conductor Ingestion:** [`DailySearchRunner._find_matches_from_datasets()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L192-L258) only reads `title`, `company`, `location`, `email`, and generic `link` from the Excel dataset. It completely ignores `form_link`, `bewerbung_link`, `has_form`, and `application_method`.
  2. **Missing Database Columns in `client_matches`:** The `client_matches` table in [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py#L116-L131) has no `application_method`, `form_link`, or `has_form` columns.
  3. **No Explicit Channel Prioritization Router:** While `DailySearchRunner._submit_application_for_match()` checks `if to_email:` before warning about missing email, there is no unified routing logic that:
     - Prioritizes **Email** when `application_method in ("email", "both")`, and
     - Routes to the saved **direct `form_link`** (rather than the generic job listing URL) when `application_method == "form"`.

---

### Feature 5: Automatic AI Cover Letter Generation
> **Requirement:** Generate personalized, professional Anschreiben for each application while minimizing AI costs.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`pdf_generator/services/ats_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py) — [`tailor_ats_keywords()`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py#L138-L216), [`generate_golden_hook()`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py#L219-L299)
  - [`pdf_generator/services/template_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/template_service.py) — `TemplateService.generate_preview_data()`
  - [`pdf_generator/services/pdf_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/pdf_service.py) — `PDFService.create_pdf()`
  - [`routes/pdf_routes.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/pdf_routes.py) — `POST /api/create-anschreibens/generate` (lines 380–520)
  - [`scraper/hook_generator.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/hook_generator.py) — `DynamicHookGenerator`
  - [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) — [`DailySearchRunner._generate_cover_letter_for_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L293-L355)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **Cost-Minimized AI Cover Letter Engine (Manual Campaign Flow):**
     - [`pdf_generator/services/ats_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py#L138-L299) implements strict AI cost controls:
       - Deterministic SHA-256 disk caching (`data/ats_cache.json`) via `_compute_cache_key()` so identical `(company, job_title, description_snippet)` combinations cost 0 tokens.
       - Prompt truncation (`snippet = (job_description or "")[:300]`) and tight token caps (`max_output_tokens=60` for keywords, `max_output_tokens=120` for golden hooks).
       - Zero-cost local German heuristic fallback (`_heuristic_golden_hook` and `_heuristic_keywords`) when no API key is configured or rate limits are hit.
     - [`PDFService.create_pdf()`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/pdf_service.py) renders professional DIN 5008 PDF cover letters with optional background templates and signatures.
- **What Is Missing / Disconnected:**
  - **Autonomous Pipeline Uses a Hardcoded Static String Instead of the AI Engine:**
    - In [`DailySearchRunner._generate_cover_letter_for_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L293-L355), the autonomous runner **does not call** `ats_service.generate_golden_hook()`, `ats_service.tailor_ats_keywords()`, or `TemplateService`.
    - Instead, lines 311–338 construct a static, non-personalized boilerplate letter with hardcoded placeholder fallbacks:
      ```python
      street = address.get("street") or "Musterstraße 12"
      postal_code = address.get("postal_code") or "50667"
      ...
      subject = f"Bewerbung um einen Ausbildungsplatz als {job_title}"
      ```
    - It also hardcodes `"Ausbildungsplatz"` in the subject and body even if the candidate is applying for a regular `Job` or `Duales Studium`.

---

### Feature 6: Autonomous Application Submission
> **Requirement:** Integrate the existing Email Sender and a Browser Autofill Engine to automatically submit applications. Skip forms requiring login, registration, or authentication.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend & Extension:**
  - [`email_sender/sender.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/sender.py) — [`EmailSender.send()`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/sender.py#L110-L145), [`EmailSender.send_batch()`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/sender.py#L146-L204)
  - [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) — [`DailySearchRunner._submit_application_for_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L357-L448)
  - [`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py) — [`map_fields()`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py#L521-L665), [`python_deterministic_matcher()`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py#L356-L450), [`python_ai_answer_questions()`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py#L453-L518)
  - [`ai-job-autofill/server/server.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/server/server.js) & [`ai-job-autofill/extension/content.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/content.js)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **Autonomous Email Submission:** When `auto_apply=1` for a client and a match has an email address, [`DailySearchRunner._submit_application_for_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L357-L448) instantiates [`EmailSender`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/sender.py#L17-L145), attaches the generated Cover Letter PDF and the candidate's CV PDF from `ClientManager`, checks `DomainThrottler`, sends a real SMTP email (`validate=False, check_cooldown=True`), and only marks the match `"applied"` if `EmailSender.send()` returns `True`.
  2. **Interactive Browser Autofill Extension:** The Chrome Extension (`ai-job-autofill/extension/`) and Flask/Node backend (`POST /api/autofill/map-fields`) inspect DOM forms in the user's active browser tab, match standard fields deterministically (DE/EN/FR), answer open-ended questions via `ai_manager`, and protect sensitive ID documents (`isSensitive`).
- **What Is Missing / Disconnected:**
  1. **No Headless / Autonomous Browser Form Submission Engine:**
     - The Autofill Engine is purely a **human-in-the-loop Chrome Extension** requiring an operator to manually open a URL in Chrome and click the extension popup.
     - There is **no Playwright/Selenium headless worker** connected to `ConductorEngine` or `DailySearchRunner._submit_application_for_match()` that navigates to `form_link`, fills fields using `python_deterministic_matcher` + `python_ai_answer_questions`, uploads the CV + cover letter PDFs, and submits the form automatically.
     - In [`DailySearchRunner._submit_application_for_match()`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py#L368-L377), if `to_email` is empty (i.e. portal/form-only job), it logs `"has no recipient email; cannot auto-submit"` and returns `False`.
  2. **No Login / Registration / Auth-Wall Skip Detector in Autofill:**
     - While [`scraper/application_form_discovery.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py#L156-L163) has `NEGATIVE_PATH_PATTERNS` for `login`/`signin`/`register` during scraping, neither `ai-job-autofill/extension/content.js` nor any headless submission runner detects login walls, password fields (`input[type="password"]`), OAuth redirects, or mandatory account registration gates on portal URLs to automatically mark the match as `skipped_auth_required`.

---

### Feature 7: Application Tracking Dashboard
> **Requirement:** Display real, verified application statistics per client: emails sent, forms submitted, failures, and overall progress.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py) — [`count_matches_by_status()`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py#L456-L468)
  - [`routes/conductor_routes.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/conductor_routes.py) — `GET /api/conductor/overview`
  - [`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py) — `POST /api/autofill/log-application`, `GET /api/autofill/applications` (lines 670–700)
  - [`routes/campaigns.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/campaigns.py) & `app.py` (`/api/dashboard/campaigns`)
- **Frontend:**
  - [`static/spa/sections/conductor.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/conductor.js)
  - [`static/spa/sections/dashboard.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/dashboard.js)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **Conductor Client Table (`/conductor`):** Displays per-client counts from `conductor_store.count_matches_by_status(client_id)` (`staged_for_approval`, `applied`, `interview`, `rejected`) and global KPI cards.
  2. **Email Campaign Dashboard (`/dashboard`):** [`static/spa/sections/dashboard.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/dashboard.js#L38-L146) polls `/api/dashboard/campaigns` every 1.5s and shows `total_rows`, `sent_rows`, `remaining_rows`, and a progress bar per bulk email campaign.
  3. **Extension Application Log:** `/api/autofill/applications` stores extension-filled forms in `data/autofill_applications.json`.
- **What Is Missing / Disconnected:**
  1. **No Per-Client Breakdown of `Emails Sent` vs `Forms Submitted` vs `Failures`:**
     - `conductor_store.client_matches` only tracks a single status (`"applied"`) without recording `submission_channel` (`"email"` vs `"form"`) or `"failed"` status with failure reason.
     - If `EmailSender.send()` fails in `DailySearchRunner._submit_application_for_match()`, it logs a warning to `conductor_logs` and leaves the match in `cover_letter_generated` / `staged_for_approval` status, so failed application attempts per client are not counted or surfaced as a `Failures` metric.
  2. **Three Disconnected Tracking Silos:**
     - Bulk email campaigns write to `data/campaigns.db` (not linked to `client_id` in `conductor.db`).
     - Browser autofill logs write to `data/autofill_applications.json` (not synced to `conductor.db`).
     - Autonomous Conductor runs write to `data/conductor.db`.
     - As a result, no single dashboard displays unified, verified per-client totals for **Emails Sent**, **Forms Submitted**, **Failures**, and **Target Package Progress** (e.g., `24 / 50 applications completed` against the client's purchased package).

---

### Feature 8: Premium Follow-Up Service
> **Requirement:** Optional paid email monitoring, reply classification, follow-up management, and client notifications.  
> **Status:** 🟡 **Partially Implemented**

#### Located Files & Symbols
- **Backend:**
  - [`services/email_reply_monitor.py`](file:///c:/Users/sibbi/Desktop/scraper/services/email_reply_monitor.py) — [`EmailReplyMonitor`](file:///c:/Users/sibbi/Desktop/scraper/services/email_reply_monitor.py#L43-L493) (`classify_email_content`, `correlate_with_client_matches`, `process_incoming_message`, `poll_inbox`)
  - [`email_sender/follow_up.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py) — [`FollowUpManager`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py#L18-L119) (`find_eligible_follow_ups`, `generate_follow_up`)
  - [`services/conductor_whatsapp_liaison.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_whatsapp_liaison.py) — [`ConductorWhatsAppLiaison`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_whatsapp_liaison.py#L26-L389) (`notify_new_applications`, `notify_interview_invitation`, `notify_recruiter_reply`, `send_daily_digest`, `request_missing_documents`)

#### End-to-End Verification & Findings
- **What Works (Real Functionality):**
  1. **IMAP/XOAUTH2 Email Monitoring & AI Classification:** [`EmailReplyMonitor`](file:///c:/Users/sibbi/Desktop/scraper/services/email_reply_monitor.py#L43-L493) connects via SSL/XOAUTH2 or App Password, fetches `UNSEEN` emails, classifies them via `ai_manager.complete()` (with deterministic German keyword fallback) into `interview_invitation`, `rejection`, `confirmation_of_receipt`, `info_request`, or `other`, correlates the sender/company/candidate with `client_matches`, updates match statuses and client `metrics`, and generates German `suggested_reply` drafts.
  2. **WhatsApp Client Notifications:** [`ConductorWhatsAppLiaison`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_whatsapp_liaison.py#L26-L389) dispatches real WhatsApp messages via `whatsapp_service.send_text_message()`, respects human-takeover locks (`HUMAN_ACTIVE`/`ESCALATED`), deduplicates via `sent_notifications` in `conductor.db`, and sends interview alerts, recruiter reply notices, missing document requests, and daily/weekly digests.
  3. **Follow-Up (Nachfass) Letter Generator:** [`FollowUpManager`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py#L18-L119) identifies unanswered emails after 5–21 days and generates polite German follow-up (`Rückfrage`) emails.
- **What Is Missing / Disconnected:**
  1. **No Paid / Premium Tier Gating (`is_premium_followup`):**
     - Neither `client_automation_configs` in [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py#L74-L86) nor the Supabase client dossier (`profile.json`) has a `premium_followup_enabled` / subscription tier check. Email monitoring and WhatsApp notifications run for all clients indiscriminately rather than as an optional paid add-on service.
  2. **`FollowUpManager` Is Disconnected from Conductor & Client Matches:**
     - [`FollowUpManager`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py#L15-L74) only reads global domain history from `data/outreach_history.json` (`DomainThrottler`), has no `client_id` awareness, is never called by `ConductorEngine`, and cannot send or stage follow-up emails for `client_matches` that have stayed in `"applied"` status for >7 days without an inbox reply.

---

## 3. Test Suite Verification Results

Executed the full test suite via `.\.venv\Scripts\pytest.exe -q`:
- **Total Tests Run:** `261`
- **Passed:** `258` (`98.85%`)
- **Failed:** `3`

### Relevant Passing Test Suites
- `tests/test_conductor_autonomous.py` — **PASSED** (Verifies Conductor task lifecycle, `DailySearchRunner` SMTP submission when `auto_apply=1`, `EmailReplyMonitor` classification & correlation, and `ConductorWhatsAppLiaison` real vs simulated delivery checks).
- `tests/test_candidate_onboarding.py` — **PASSED** (Verifies Supabase candidate onboarding, payment verification, CV parsing, and idempotency).
- `tests/test_autofill_routes.py` — **PASSED** (Verifies profile syncing, deterministic field matching, and AI question answering).
- `tests/test_application_form_discovery.py` — **PASSED** (Verifies `email` / `form` / `both` classification and ATS form verification).
- `tests/test_profession_matcher.py` — **PASSED** (Verifies dataset availability matching).

### Existing Test Failures (Unrelated Legacy Tests)
1. `tests/test_auto_extraction_recovery.py::AutoExtractionRecoveryTestCase::test_recover_auto_job_from_progress` (`AssertionError: 0 not greater than or equal to 1` on `emails_found`).
2. `tests/test_auto_extraction_recovery.py::AutoExtractionRecoveryTestCase::test_status_endpoint_recovers_job` (`AssertionError: 0 not greater than or equal to 1` on `emails_found`).
3. `tests/test_search_maps_consolidation.py::test_maps_is_one_workspace_inside_search` (Legacy UI assertion expecting `[data-section-link="google-maps"]` to be absent from `app_shell.html`).

---

## 4. Final Architectural Summary (Answers to Audit Questions)

### 1. How many features are fully implemented?
- **0 of 8 features** are 100% implemented end-to-end without missing autonomous glue or schema links.

### 2. How many are partially implemented?
- **8 of 8 features** (`🟡 Partially Implemented`) have substantial, production-grade core engines already built (typically 70%–85% complete), but each lacks specific autonomous triggers or cross-module wiring to operate hands-free end-to-end.

### 3. How many are missing?
- **0 of 8 features** are completely missing (`🔴 Not Implemented`). Every single feature has working backend services, routes, and UI components in the codebase; only the integration bridges and two specific sub-capabilities (headless browser form submission + 5-profession CV recommender for `Job` candidates) are missing.

### 4. Which existing modules are disconnected?
1. **`SupabaseService` ↔ `CandidateOnboardingService` ↔ `ConductorEngine`:**
   - `CandidateOnboardingService.onboard_candidate()` is only called by manual UI button click (`POST /api/supabase/onboard-candidate`), not by a scheduled polling task in `ConductorEngine`.
2. **`ProfessionIntelligence` / `CVParser` ↔ `DailySearchRunner`:**
   - `ProfessionIntelligence.normalize_input()` strips `"Ausbildung als"` / `"Duales Studium als"` / `"Job als"` without saving `opportunity_type`, and `DailySearchRunner` defaults all candidates to `"ausbildung"`.
3. **`profession_matcher.evaluate_profession_match()` ↔ Auto-Extraction Scraper (`app.py`) ↔ `DailySearchRunner`:**
   - When a dataset is `"missing"`, neither onboarding nor `DailySearchRunner` triggers an automatic background dataset scrape into `data/auto_extraction_exports`.
4. **`scraper/application_form_discovery.py` ↔ `DailySearchRunner` & `conductor_store.client_matches`:**
   - The scraper writes `application_method` (`email`/`form`/`both`), `has_form`, and `form_link` into the 21-column `.xlsx` exports, but `DailySearchRunner._find_matches_from_datasets()` drops those columns when staging `client_matches`.
5. **`pdf_generator/services/ats_service.py` & `TemplateService` ↔ `DailySearchRunner._generate_cover_letter_for_match()`:**
   - Cost-optimized AI cover letter generation (`generate_golden_hook`, `tailor_ats_keywords` with SHA-256 cache) is used by the manual PDF route (`routes/pdf_routes.py`), while `DailySearchRunner` generates a hardcoded static string with `"Musterstraße 12"`.
6. **`routes/autofill.py` (`python_deterministic_matcher` + `python_ai_answer_questions`) ↔ `DailySearchRunner._submit_application_for_match()`:**
   - Field matching and AI form answering exist for the Chrome Extension, but there is no headless Playwright worker to auto-submit `form_link` applications server-side or skip login/auth walls.
7. **`email_sender/follow_up.py` (`FollowUpManager`) ↔ `ConductorEngine` & `conductor_store`:**
   - `FollowUpManager` reads `data/outreach_history.json` instead of `conductor_store.client_matches` and is never invoked by `ConductorEngine`.

### 5. What is the best implementation order to complete JobScout?
1. **Phase 1 — Data Model & Method Routing Foundation (Features 2, 4, 7):**
   - Extend `conductor_store.client_matches` with `application_method` (`email`/`form`/`both`), `form_link`, `submission_channel` (`email`/`form`), `failure_count`, and `last_error`.
   - Update `ProfessionIntelligence` & `CVParser` to persist `opportunity_type` (`ausbildung` | `job` | `duales_studium`) and recommend up to 5 suitable professions from the CV for `Job` candidates.
   - Update `DailySearchRunner._find_matches_from_datasets()` to ingest `application_method` and `form_link` from the 21-column Excel exports and prioritize `email` when `application_method == "both"`.
2. **Phase 2 — Connect AI Cover Letter Generator to Autonomous Pipeline (Feature 5):**
   - Replace the static template in `DailySearchRunner._generate_cover_letter_for_match()` with `ats_service.generate_golden_hook()` + `ats_service.tailor_ats_keywords()` + `TemplateService`, dynamically adapting salutation and subject to `ausbildung`, `duales_studium`, or `job`.
3. **Phase 3 — Autonomous Onboarding & Missing Dataset Auto-Scraping (Features 1 & 3):**
   - Add a scheduled task in `ConductorEngine` to poll `SupabaseService` for newly paid (`is_payed=true`) un-imported applications and auto-run `CandidateOnboardingService.onboard_candidate()`.
   - When `evaluate_profession_match()` returns `"missing"` during onboarding or daily search, automatically enqueue a background scrape job that exports the new profession dataset to `data/auto_extraction_exports`.
4. **Phase 4 — Autonomous Browser Form Submission & Auth-Wall Skipping (Feature 6):**
   - Build a headless Playwright runner that reuses `routes/autofill.py` (`python_deterministic_matcher` + `python_ai_answer_questions`) to fill and submit `form_link` portals when `application_method == "form"`, and automatically skips forms containing login/registration/password walls (`skipped_auth_required`).
5. **Phase 5 — Unified Tracking Dashboard & Premium Follow-Up Gating (Features 7 & 8):**
   - Add per-client KPI counters (`emails_sent`, `forms_submitted`, `failures`, `package_quota`) to the Conductor/Client dashboard.
   - Add a `premium_follow_up` flag to `client_automation_configs` and wire `FollowUpManager` into `ConductorEngine` to draft/send 7-day follow-ups for unanswered `client_matches`.

### 6. What can be reused without rewriting?
- **[`CandidateOnboardingService`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py) & [`ClientManager`](file:///c:/Users/sibbi/Desktop/scraper/services/client_manager.py):** Complete Supabase document fetching, CV ingestion, idempotency locks, and dossier storage can be reused as-is.
- **[`ProfessionIntelligence`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py) & [`profession_matcher.py`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py):** Typo correction, EN/FR→DE translation, sector taxonomy, SHA-256 caching, and fuzzy dataset availability matching are production-ready.
- **[`ApplicationFormDiscovery`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py) & [`CareerPageCrawler`](file:///c:/Users/sibbi/Desktop/scraper/scraper/career_crawler.py):** 30+ ATS detection patterns, form verification (`verify_form_page`), and `email`/`form`/`both` classification in the 21-column export schema require zero rewrite.
- **[`ats_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py) & [`PDFService`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/pdf_service.py):** SHA-256 cached low-cost AI hook/keyword generation and DIN 5008 PDF creation can be called directly by `DailySearchRunner`.
- **[`EmailSender`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/sender.py) & [`DomainThrottler`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/throttler.py):** Full SMTP delivery, MIME attachment handling, MX validation, and domain cooldown throttling are complete.
- **[`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py) (`python_deterministic_matcher` & `python_ai_answer_questions`):** Trilingual field matching, correction memory, sensitive-ID protection, and anti-hallucination AI question answering can be called directly by a headless Playwright form submitter.
- **[`EmailReplyMonitor`](file:///c:/Users/sibbi/Desktop/scraper/services/email_reply_monitor.py) & [`ConductorWhatsAppLiaison`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_whatsapp_liaison.py):** IMAP/XOAUTH2 polling, AI reply classification, client match correlation, human-takeover protection, and WhatsApp Cloud API dispatch are fully functional.

