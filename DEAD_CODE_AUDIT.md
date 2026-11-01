# JobScout — Full Dead Code Audit & Safe Cleanup Report (`DEAD_CODE_AUDIT.md`)

**Audit Date:** 2026-11-01  
**Branch:** `audit/dead-code-cleanup-20261031`  
**Reversible Pre-Cleanup Checkpoint Object:** `c18285941b83be391a7f5f58fc73cea6455e3a4f` (`git stash create` object) & [`docs/DEAD_CODE_CLEANUP.patch`](file:///c:/Users/sibbi/Desktop/scraper/docs/DEAD_CODE_CLEANUP.patch)  
**Dependency & Reference Map:** [`docs/DEAD_CODE_REFERENCE_MAP.json`](file:///c:/Users/sibbi/Desktop/scraper/docs/DEAD_CODE_REFERENCE_MAP.json)

---

## 1. Executive Summary & Repository Scope

A comprehensive static, dynamic, and cross-file dependency audit was conducted across the entire JobScout repository to identify and safely remove dead functions, unused imports/variables, obsolete standalone HTML templates, orphaned frontend helpers, and unused CSS selectors left behind after feature migrations (multi-page Jinja views → SPA Shell, manual SMTP helpers → `EmailSender` + `CampaignStore`, OpenRouter → OpenAI/Gemini `AIProviderManager`).

### Total Files Analyzed (`183` Authored Repository Files)

| Category | File Count | Scope Covered |
|---|---:|---|
| **Python Modules (`.py`)** | `113` | [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py), [`config.py`](file:///c:/Users/sibbi/Desktop/scraper/config.py), `routes/` (11 blueprints), `services/` (20 modules), `scraper/` (22 modules), `email_sender/` (6 modules), `pdf_generator/` (11 modules), `tests/` (41 test modules) |
| **JavaScript / CommonJS (`.js`, `.cjs`)** | `34` | `static/` (`shared_nav.js`, `auto_continue.js`, `dashboard_firebase.js`, `spa/app.js`, `spa/utils.js`, `spa/supabase-client.js`, 13 SPA section controllers), `pdf_generator/frontend/script.js`, `ai-job-autofill/extension/` (4 scripts), `ai-job-autofill/server/` (7 scripts), `tests/*.test.cjs` |
| **HTML Templates (`.html`)** | `11` | `templates/` (`app_shell.html`, `index.html`, `results.html`, `extraction_progress.html`, `auto_extraction_progress.html`, `captcha_solve.html`, `error.html`, plus 5 legacy standalone templates removed), `pdf_generator/frontend/index.html`, `ai-job-autofill/` (`popup.html`, `test-form.html`, `french-form.html`) |
| **CSS Stylesheets (`.css`)** | `4` | [`static/spa/app.css`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/app.css), [`static/shared_nav.css`](file:///c:/Users/sibbi/Desktop/scraper/static/shared_nav.css), [`pdf_generator/frontend/styles.css`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/frontend/styles.css), [`ai-job-autofill/extension/popup.css`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/popup.css) |
| **Database Migrations (`.sql`)** | `2` | [`migrations/supabase_onboarding_migration.sql`](file:///c:/Users/sibbi/Desktop/scraper/migrations/supabase_onboarding_migration.sql), [`migrations/whatsapp_schema.sql`](file:///c:/Users/sibbi/Desktop/scraper/migrations/whatsapp_schema.sql) |
| **Configuration & Manifests (`.json`, `.txt`, `.ini`, `.md`)** | `19` | [`requirements.txt`](file:///c:/Users/sibbi/Desktop/scraper/requirements.txt), [`pytest.ini`](file:///c:/Users/sibbi/Desktop/scraper/pytest.ini), [`ai-job-autofill/extension/manifest.json`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/manifest.json), [`ai-job-autofill/server/package.json`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/server/package.json), profile templates, documentation |
| **Total Authored Files Analyzed** | **`183`** | Excludes `.venv/`, `node_modules/`, `__pycache__/`, and runtime SQLite/JSON data in `data/` |

---

## 2. Phase 2 — Dependency & Dynamic Reference Verification

Before classifying any symbol or file as unused, the following dynamic and runtime mechanisms were verified across the repository:

1. **Flask Blueprints & URL Map (`241` Rules across `11` Blueprints):**
   - Verified all `app.register_blueprint(...)` registrations in [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py#L81-L91) (`health_bp`, `jobs_bp`, `pdf_bp`, `enhancements_bp`, `autofill_bp`, `campaigns_bp`, `clients_bp`, `supabase_onboarding_bp`, `ai_settings_bp`, `whatsapp_bp`, `conductor_bp`).
   - Verified template literal endpoint construction in SPA controllers (e.g., `` `/api/whatsapp/conversations/${encodeURIComponent(convId)}/takeover` `` and `${API_BASE}/upload-excel` in [`pdf_generator/frontend/script.js`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/frontend/script.js)).
2. **Dynamic Reflection (`globals()` and `getattr()`):**
   - [`services/onboarding_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py#L48-L49) resolves default service singletons dynamically via `globals().get("client_manager")` and `globals().get("supabase_service")`. Although static linters (`ruff F401/F811`) flag module-level `client_manager` and `supabase_service` imports as shadowed by `__init__` parameter names, removing them would break default instantiation of `CandidateOnboardingService()`. Both imports were **preserved (`KEEP`)**.
   - Thread-local SQLite connections in [`services/campaign_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/campaign_store.py), [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py), [`services/job_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/job_store.py), and [`services/whatsapp_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_store.py) use `getattr(self._local, "connection", None)`.
3. **Background Daemons & Worker Threads:**
   - Verified `ConductorEngine._worker_loop` ([`services/conductor_engine.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_engine.py)), `WhatsAppService` outbound queue worker ([`services/whatsapp_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_service.py)), and `threading.Thread` workers in [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) (`_run_async_bulk_send_job`, `_run_auto_extraction_job`, `_run_google_maps_discovery`, `_run_google_maps_job`, `_run_google_maps_extraction`).
4. **Chrome Extension Runtime Messaging & Dynamic Injection:**
   - Verified [`ai-job-autofill/extension/manifest.json`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/manifest.json), [`background.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/background.js), [`client.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/client.js), [`matching.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/matching.js), [`content.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/content.js), and [`popup.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/popup.js). `chrome.scripting.executeScript` injects `matching.js` and `content.js` dynamically across frames, and `window.AutofillMatching` is shared across extension scripts and Node JSDOM regression tests.

---

## 3. Phase 3 — Full Audit Classification Table

| File | Function / Component | Reason | Risk | Recommended Action |
|---|---|---|---|---|
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `_list_available_ausbildung_domains` | Legacy helper superseded by `_list_auto_extraction_export_files()` and `profession_matcher`; zero references across repo | Low | **SAFE TO REMOVE** (Removed) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `_extract_arbeitsgeber_from_text`, `_build_anrede` | Duplicate helpers superseded by `WorkingEmailExtractor` and `pdf_generator/services/template_service.py`; zero callers | Low | **SAFE TO REMOVE** (Removed) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `_load_previously_collected_emails` | Obsolete CSV/XLSX email loader from pre-SQLite extraction flow; zero callers | Low | **SAFE TO REMOVE** (Removed) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `_create_email_message`, `_send_single_email`, `_parse_recipient_lines`, `_send_bulk_email_jobs`, `_render_template_with_context`, `_load_recipients_from_spreadsheet` | Obsolete inline SMTP & spreadsheet helpers replaced by `EmailSender` (`email_sender/sender.py`) and `_run_async_bulk_send_job`; zero callers | Low | **SAFE TO REMOVE** (Removed) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `_company_name_from_row`, `_get_running_email_send_job_for_campaign` | Unused wrapper functions with zero internal or external callers | Low | **SAFE TO REMOVE** (Removed) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | `smtplib`, `MIMEBase`, `MIMEMultipart`, `MIMEText`, `encoders`, `ApplicationFormDiscovery`, `classify_application_method` imports; `existing_email_count`, `saved_dataset_file` locals | Unused top-level imports and unread local variables after helper cleanup | Low | **SAFE TO REMOVE** (Removed) |
| [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py) | `_generate_synthetic_verified_matches` & `hashlib`, `json`, `os` imports | Obsolete synthetic/mock match generator removed in favor of real dataset & live scraper discovery | Low | **SAFE TO REMOVE** (Removed) |
| [`pdf_generator/services/browser_pool.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/browser_pool.py) | `io`, `time`, `Tuple`, `PdfReader`, `PdfWriter` imports | Unused imports in headless browser pool module | Low | **SAFE TO REMOVE** (Removed) |
| [`pdf_generator/services/ats_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/ats_service.py) | `os` import | Unused standard library import | Low | **SAFE TO REMOVE** (Removed) |
| [`pdf_generator/services/background_templates.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/background_templates.py) | `os` import | Unused standard library import | Low | **SAFE TO REMOVE** (Removed) |
| [`pdf_generator/services/pdf_service.py`](file:///c:/Users/sibbi/Desktop/scraper/pdf_generator/services/pdf_service.py) | `Optional`, `Union` typing imports | Unused typing imports | Low | **SAFE TO REMOVE** (Removed) |
| [`email_sender/follow_up.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py) | `timedelta` import | Unused import | Low | **SAFE TO REMOVE** (Removed) |
| [`email_sender/throttler.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/throttler.py) | `os` import | Unused import | Low | **SAFE TO REMOVE** (Removed) |
| [`routes/ai_settings.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/ai_settings.py) | `saved_config`, `cache_file` local variables | Assigned but never read in `update_ai_settings()` and `reset_ai_cache()` | Low | **SAFE TO REMOVE** (Removed) |
| [`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py) | `urllib.error` import; `prof`, `exc`, `updated_profile` local variables; missing `logging` import | Unused import and unread local variables; added `import logging` to fix `F821` undefined name in exception handler | Low | **SAFE TO REMOVE** (Removed / Fixed) |
| [`routes/clients.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/clients.py) | `io`, `json`, `Path` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`routes/pdf_routes.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/pdf_routes.py) | `io` import | Unused import | Low | **SAFE TO REMOVE** (Removed) |
| [`routes/supabase_onboarding.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/supabase_onboarding.py) | `SupabaseServiceError` import | Unused exception import | Low | **SAFE TO REMOVE** (Removed) |
| [`routes/whatsapp.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/whatsapp.py) | `datetime`, `timezone`, `Any`, `Dict`, `Optional`, `ConcurrencyConflictError` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/application_form_discovery.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/application_form_discovery.py) | `url_lower`, `netloc_lower`, `title` local variables | Assigned but never read in `verify_form_page()` and `discover_application_form()` | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/azubiyo_scraper.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/azubiyo_scraper.py) | `time`, `is_location_relevant` imports; `search_loc` local variable | Unused imports and unread local variable | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/career_crawler.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/career_crawler.py) | `Optional` import | Unused typing import | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/cookie_handler.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/cookie_handler.py) | `Optional` import | Unused typing import | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/email_pattern_guesser.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/email_pattern_guesser.py) | `Optional` import | Unused typing import | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/google_maps_ausbildung_verifier.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/google_maps_ausbildung_verifier.py) | `Tuple`, `clean_extracted_location` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/google_maps_opportunity_verifier.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/google_maps_opportunity_verifier.py) | `JOB_PORTAL_DOMAINS`, `clean_extracted_location` imports; `url_lower`, `netloc_lower`, `candidate_education`, `maps_url` locals | Unused imports and unread local variables | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/google_maps_scraper.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/google_maps_scraper.py) | `urlparse`, `webdriver`, `Keys` imports; `total` local variable | Unused imports and unread local variable | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/search_filter_engine.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/search_filter_engine.py) | `primary_match` local variable | Computed boolean never read in `is_profession_relevant()` | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/tech_detector.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/tech_detector.py) | `List`, `BeautifulSoup` imports | Unused imports (uses regex matching on HTML text) | Low | **SAFE TO REMOVE** (Removed) |
| [`scraper/working_email_extractor.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/working_email_extractor.py) | `webdriver`, `classify_application_method` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/ai_provider_manager.py`](file:///c:/Users/sibbi/Desktop/scraper/services/ai_provider_manager.py) | `List`, `Tuple`, `Union` imports; `effective_model` local variable | Unused typing imports and unread local variable in `test_gemini_connection()` | Low | **SAFE TO REMOVE** (Removed) |
| [`services/campaign_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/campaign_store.py) | `os`, `Tuple` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/client_manager.py`](file:///c:/Users/sibbi/Desktop/scraper/services/client_manager.py) | `io`, `os` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/conductor_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_store.py) | `json`, `Tuple` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/conductor_whatsapp_liaison.py`](file:///c:/Users/sibbi/Desktop/scraper/services/conductor_whatsapp_liaison.py) | `Any`, `Dict` imports | Unused typing imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/cv_parser.py`](file:///c:/Users/sibbi/Desktop/scraper/services/cv_parser.py) | `country` local variable | Assigned in `parse_cv_text()` AI fallback block but never read | Low | **SAFE TO REMOVE** (Removed) |
| [`services/email_reply_monitor.py`](file:///c:/Users/sibbi/Desktop/scraper/services/email_reply_monitor.py) | `re`, `List` imports; `sender_clean` local variable | Unused imports and unread local variable | Low | **SAFE TO REMOVE** (Removed) |
| [`services/geographic_batching.py`](file:///c:/Users/sibbi/Desktop/scraper/services/geographic_batching.py) | `List`, `Tuple` imports | Unused typing imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/onboarding_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py) | `Path`, `ApplicationNotFoundError`, `DocumentDownloadError`, `SupabaseServiceError` imports; `email`, `field_label`, `lang_level`, `record` locals | Unused imports and unread local variables in `onboard_candidate()` | Low | **SAFE TO REMOVE** (Removed) |
| [`services/profession_intelligence.py`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_intelligence.py) | `os`, `Tuple` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/profession_matcher.py`](file:///c:/Users/sibbi/Desktop/scraper/services/profession_matcher.py) | `re`, `Optional`, `Tuple`, `PROFESSION_KNOWLEDGE_BASE`, `GERMAN_STOP_WORDS` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/supabase_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/supabase_service.py) | `os` import | Unused import | Low | **SAFE TO REMOVE** (Removed) |
| [`services/whatsapp_ai_engine.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_ai_engine.py) | `time`, `Tuple` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/whatsapp_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_service.py) | `json`, `re`, `timedelta`, `Path` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`services/whatsapp_store.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_store.py) | `Union` import | Unused typing import | Low | **SAFE TO REMOVE** (Removed) |
| [`services/whatsapp_tools.py`](file:///c:/Users/sibbi/Desktop/scraper/services/whatsapp_tools.py) | `json`, `re` imports | Unused imports | Low | **SAFE TO REMOVE** (Removed) |
| [`ai-job-autofill/extension/popup.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/popup.js) | `MAP_FIELDS_URL` variable | Assigned twice but never read (`client.js` handles `/api/map-fields` requests) | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/app.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/app.js) | `checkActiveJobs` & `liveJobWidget` variables | Defined but never invoked (`checkActiveJobs` had zero calls and `#sidebar-live-job` does not exist in `app_shell.html`) | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/sections/create-anschreibens.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/create-anschreibens.js) | `getCachedFirebaseApplication` | Unused alias wrapper around `getCachedApplication()` with zero calls | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/sections/google-maps.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/google-maps.js) | `discoverBusinesses` & `discoveryCount` | Unreferenced inner function and DOM lookup superseded by unified `runCombinedSearch()` / `startExtraction()` | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/sections/money.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/money.js) | `fmtDateShort` | Unused date formatting helper (`fmtDate` and `fmtDateISO` are used instead) | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/sections/search.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/search.js) | `defaultCategoriesList` | Write-only array variable never read | Low | **SAFE TO REMOVE** (Removed) |
| [`static/spa/app.css`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/app.css) | `.firebase-hero` selector | Orphaned CSS rule from removed Firebase section header | Low | **SAFE TO REMOVE** (Removed) |
| `templates/ausbildungen.html`, `templates/create_anschreibens.html`, `templates/dashboard.html`, `templates/firebase.html`, `templates/send_emails.html` | 5 legacy standalone Jinja templates (`2,498` lines total) | Completely replaced by `templates/app_shell.html` (`render_template("app_shell.html", initial_section=...)`); zero `render_template` calls in Python | Low | **SAFE TO REMOVE** (Removed) |
| [`static/dashboard_firebase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/dashboard_firebase.js) & [`static/spa/sections/firebase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/firebase.js) | Legacy Firebase frontend scripts | Not loaded by `templates/app_shell.html`, but exposed via Flask `/static/<path:filename>` while backend `/api/firebase/*` routes remain active | Medium | **REVIEW REQUIRED** (Retained) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | Legacy Firebase routes (`/firebase`, `/api/firebase/applications`, `/api/firebase/delete/<id>`, `/api/create-anschreibens/firebase-bootstrap`) | Superseded in primary UI by Supabase (`/supabase`), but still referenced by `create-anschreibens.js` fallback bootstrap and `config.py` | Medium | **REVIEW REQUIRED** (Retained) |
| [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py) | Parallel scrape endpoints (`/api/parallel-scrape/*`) & legacy multipage templates (`templates/index.html`, `templates/results.html`, `templates/extraction_progress.html`, `templates/auto_extraction_progress.html`) | Public Flask routes and fallback server-rendered templates; external bookmarks or scripts may call them | Medium | **REVIEW REQUIRED** (Retained) |
| [`email_sender/follow_up.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/follow_up.py), [`email_sender/spam_analyzer.py`](file:///c:/Users/sibbi/Desktop/scraper/email_sender/spam_analyzer.py), [`scraper/career_crawler.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/career_crawler.py), [`scraper/email_pattern_guesser.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/email_pattern_guesser.py), [`scraper/hook_generator.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/hook_generator.py), [`scraper/tech_detector.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/tech_detector.py) | Enhancement modules & [`routes/enhancements.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/enhancements.py) | Exposed via `/api/enhancements/*` blueprint and covered by `tests/test_new_enhancements.py` & `tests/test_scraping_enhancements.py` | Low | **KEEP** |
| [`services/onboarding_service.py`](file:///c:/Users/sibbi/Desktop/scraper/services/onboarding_service.py) | Module-level `client_manager` & `supabase_service` imports | Dynamically resolved at runtime via `globals().get("client_manager")` and `globals().get("supabase_service")` in `CandidateOnboardingService.__init__` | High | **KEEP** |
| [`scraper/google_maps_opportunity_verifier.py`](file:///c:/Users/sibbi/Desktop/scraper/scraper/google_maps_opportunity_verifier.py) | `page_title` parameter in `classify_application_url(cls, url, html_content="", page_title="")` | Part of public classmethod signature called with keyword arguments | Medium | **KEEP** |
| [`requirements.txt`](file:///c:/Users/sibbi/Desktop/scraper/requirements.txt) & [`ai-job-autofill/server/package.json`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/server/package.json) | All 11 Python dependencies & 6 Node packages | Every listed package (`flask`, `requests`, `pandas`, `selenium`, `webdriver-manager`, `python-dotenv`, `fpdf2`, `pypdf`, `openpyxl`, `firebase-admin`, `beautifulsoup4`; `cors`, `dotenv`, `express`, `libphonenumber-js`, `openai`, `jsdom`) is actively imported | High | **KEEP** |

---

## 4. Summary of Removed Items (Phase 4 Safe Cleanup)

### 4.1 Removed Obsolete Files (`5` Templates — `2,498` Lines)
- `templates/ausbildungen.html` (`442` lines) — superseded by `app_shell.html` (`initial_section="ausbildungen"`).
- `templates/create_anschreibens.html` (`73` lines) — superseded by `app_shell.html` (`initial_section="create-anschreibens"`).
- `templates/dashboard.html` (`737` lines) — superseded by `app_shell.html` (`initial_section="dashboard"`).
- `templates/firebase.html` (`209` lines) — `/firebase` route redirects to `supabase_page`.
- `templates/send_emails.html` (`1,037` lines) — superseded by `app_shell.html` (`initial_section="send-emails"`).
- Also cleaned `11` temporary lint/test scratch log files from the repository root (`audit-*.log`, `audit-*.txt`, `deadcode-*.log`, `targeted.log`).

### 4.2 Removed Dead Python Functions (`13` Functions)
- [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py):
  - `_list_available_ausbildung_domains()`
  - `_extract_arbeitsgeber_from_text()`
  - `_build_anrede()`
  - `_load_previously_collected_emails()`
  - `_create_email_message()`
  - `_send_single_email()`
  - `_parse_recipient_lines()`
  - `_send_bulk_email_jobs()`
  - `_render_template_with_context()`
  - `_load_recipients_from_spreadsheet()`
  - `_company_name_from_row()`
  - `_get_running_email_send_job_for_campaign()`
- [`services/daily_search_runner.py`](file:///c:/Users/sibbi/Desktop/scraper/services/daily_search_runner.py):
  - `DailySearchRunner._generate_synthetic_verified_matches()`

### 4.3 Removed Dead JavaScript Functions & Variables (`7` Symbols)
- [`ai-job-autofill/extension/popup.js`](file:///c:/Users/sibbi/Desktop/scraper/ai-job-autofill/extension/popup.js): `MAP_FIELDS_URL`
- [`static/spa/app.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/app.js): `checkActiveJobs()`, `liveJobWidget`, `jobTitle`, `jobPercent`, `jobFill`, `jobMeta`
- [`static/spa/sections/create-anschreibens.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/create-anschreibens.js): `getCachedFirebaseApplication()`
- [`static/spa/sections/google-maps.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/google-maps.js): `discoverBusinesses()`, `discoveryCount`
- [`static/spa/sections/money.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/money.js): `fmtDateShort()`
- [`static/spa/sections/search.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/search.js): `defaultCategoriesList`

### 4.4 Removed Unused Python Imports & Unread Local Variables (`80+` Symbols across `39` Python Files)
- Cleaned all confirmed unused imports (`F401`) and unread local variable assignments (`F841`) across `app.py`, `email_sender/`, `pdf_generator/services/`, `routes/`, `scraper/`, and `services/`.
- Fixed missing `import logging` (`F821`) in [`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py).

---

## 5. Phase 5 — Regression & Verification Results

### 5.1 Syntax, Import, Route & Extension Checks

| Verification Check | Before Cleanup | After Cleanup | Status |
|---|---|---|---|
| **Python Compilation (`py_compile`)** | `113 / 113` files compiled | `113 / 113` files compiled | ✅ **PASS** |
| **JavaScript Syntax (`node --check`)** | `34 / 34` files valid | `34 / 34` files valid | ✅ **PASS** |
| **Flask Blueprints & URL Map** | `11` blueprints, `241` URL rules | `11` blueprints, `241` URL rules | ✅ **PASS (0 routes broken)** |
| **Chrome Extension (`manifest.json`)** | Valid MV3 (`AI Job Autofill v1.0.0`) | Valid MV3 (`AI Job Autofill v1.0.0`) | ✅ **PASS** |
| **Ruff (`F401`, `F811`, `F821`, `F841`)** | `51` issues (incl. `1` `F821` undefined `logging`) | `0` actionable issues (only `2` intentional `globals().get` imports in `onboarding_service.py`) | ✅ **PASS** |
| **Vulture (`--min-confidence 80`)** | `3` issues | `0` actionable issues (only `1` public method signature arg `page_title`) | ✅ **PASS** |

### 5.2 Automated Test Suites (Before vs. After Cleanup)

| Test Suite | Before Cleanup | After Cleanup | Regression Introduced? |
|---|---|---|---|
| **Python Test Suite (`pytest`)** | `258 passed`, `3 failed` (`261` total) | `258 passed`, `3 failed` (`261` total) | **No (`0` new failures)** |
| **Node Test Suite (`node --test`)** | `8 passed`, `0 failed` (`8` total) | `8 passed`, `0 failed` (`8` total) | **No (`0` new failures)** |

#### Pre-Existing Baseline Test Failures (Unrelated to Dead Code Cleanup)
1. `tests/test_auto_extraction_recovery.py::AutoExtractionRecoveryTestCase::test_recover_auto_job_from_progress` — `AssertionError: 0 not greater than or equal to 1` on `recovered["emails_found"]` (depends on mutable runtime data in `data/progress/auto_extraction_progress.csv`).
2. `tests/test_auto_extraction_recovery.py::AutoExtractionRecoveryTestCase::test_status_endpoint_recovers_job` — `AssertionError: 0 not greater than or equal to 1` on `job.get("emails_found")` (same runtime CSV fixture state).
3. `tests/test_search_maps_consolidation.py::test_maps_is_one_workspace_inside_search` — Fails because [`templates/app_shell.html`](file:///c:/Users/sibbi/Desktop/scraper/templates/app_shell.html) retains `[data-section-link="google-maps"]` in the sidebar navigation.

---

## 6. Unresolved Risks & Remaining Cleanup Opportunities

1. **Legacy Firebase Integration (`REVIEW REQUIRED`):**
   - [`static/dashboard_firebase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/dashboard_firebase.js), [`static/spa/sections/firebase.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/firebase.js), and the `/api/firebase/*` endpoints in [`app.py`](file:///c:/Users/sibbi/Desktop/scraper/app.py#L192-L331) are superseded by the Supabase workflow (`/supabase`), but were intentionally preserved because `firebase-admin` and `/api/create-anschreibens/firebase-bootstrap` remain wired into [`config.py`](file:///c:/Users/sibbi/Desktop/scraper/config.py) and [`static/spa/sections/create-anschreibens.js`](file:///c:/Users/sibbi/Desktop/scraper/static/spa/sections/create-anschreibens.js). Once Firebase is fully decommissioned in production, `firebase-admin`, `FIREBASE_CONFIG`, `/api/firebase/*`, `static/dashboard_firebase.js`, and `static/spa/sections/firebase.js` can be removed together.
2. **Legacy Non-SPA Fallback Templates (`REVIEW REQUIRED`):**
   - `templates/index.html`, `templates/results.html`, `templates/extraction_progress.html`, and `templates/auto_extraction_progress.html` are still referenced by legacy POST/progress routes (`/search`, `/extract_emails`, `/auto_extract_emails`, `/extraction_progress`, `/auto_extraction_progress`) and tested by `tests/test_redesigned_search_interface.py`. They can be retired if those legacy form POST endpoints are migrated to pure JSON/SPA endpoints.
3. **Standalone Node Autofill Server (`ai-job-autofill/server/server.js`):**
   - Port `5000` Flask ([`routes/autofill.py`](file:///c:/Users/sibbi/Desktop/scraper/routes/autofill.py)) now natively serves all Chrome Extension endpoints, but `ai-job-autofill/server/server.js` (port `8787`) is still used by the Node regression test suite (`ai-job-autofill/server/test-*.js`) and as a standalone fallback in `popup.js` / `client.js`. Keep until Node tests are pointed directly at Flask.

