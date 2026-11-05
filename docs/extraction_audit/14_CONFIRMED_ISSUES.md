# Architecture Audit — 14: Confirmed Issues, Bugs & Architecture Limitations

> **Audit Type:** Technical Defect & Architecture Limitation Inventory  
> **Source Evidence:** Source code inspection, line citations, error logs, and regression tests  
> **Status:** Current Production Version (Investigation Only)

---

### Top 10 Confirmed Issues & Technical Root Causes

#### 1. Temporal Dead Zone (TDZ) Reference Error in `search.js`
- **File & Line:** [`static/spa/sections/search.js:1285`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/sections/search.js#L1285)
- **Symptom:** UI displays pink alert banner: `Cannot access 'isCompleted' before initialization`.
- **Root Cause:** Variable `isCompleted` was referenced during ETA calculation before its `const isCompleted = ...` declaration. (Fixed in current working tree).

#### 2. Pause/Resume False Premature Completion (114/114 Bug)
- **File & Line:** [`app.py:2350-2365`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2350-L2365) (`_is_job_finished`)
- **Symptom:** Clicking Resume after pausing at 114 jobs caused task to immediately flip to "Completed (114/114)" with 0 emails/forms.
- **Root Cause:** `_is_job_finished` checked `job_record.get("email_extracted") is not None`. Since pending jobs had `"email_extracted": False`, the condition evaluated to `True`, causing the queue to consider all pending jobs finished. (Fixed in current working tree by checking `is True`).

#### 3. Low Contrast / Invisible Text on Previous Tasks Action Button
- **File & Line:** [`static/spa/app.css:21960-21970`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/static/spa/app.css#L21960-L21970)
- **Symptom:** In the "Previous Tasks" card, the "Dashboard öffnen" button text is rendered with near-invisible low-contrast styling on light backgrounds.
- **Root Cause:** Parent button has `background: #ffffff`, but the inner text element was subjected to conflicting low-specificity text color rules.

#### 4. Ausbildung.de JavaScript Refresh Redirect Masking
- **File & Line:** [`scraper/ausbildung_de_scraper.py:170-195`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/ausbildung_de_scraper.py#L170-L195)
- **Symptom:** Fast-Path HTTP fails to resolve destination ATS URL when Ausbildung.de serves client-side `<meta http-equiv="refresh">` redirect pages.
- **Root Cause:** `requests.get()` follows HTTP 301/302 headers but does not evaluate HTML meta-refresh tags, necessitating an expensive Selenium fallback.

#### 5. Arbeitsagentur Partner Redirect Timeouts (`arbeitsagentur.de/partner`)
- **File & Line:** [`scraper/arbeitsagentur_extractor.py:480-515`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/arbeitsagentur_extractor.py#L480-L515)
- **Symptom:** Worker spends 15+ seconds on partner listings before reporting `redirect_unresolved`.
- **Root Cause:** Certain partner aggregators (e.g. StepStone) deploy strict Cloudflare Turnstile anti-bot checks on incoming redirect links.

#### 6. Azubiyo Profile-Only Gating
- **File & Line:** [`scraper/azubiyo_scraper.py:220-250`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/azubiyo_scraper.py#L220-L250)
- **Symptom:** Vacancies marked as `portal` cannot be converted to direct email outreach or automated ATS forms.
- **Root Cause:** Azubiyo natively hosts the application form behind user login and does not expose external contact links for certain premium employer tiers.

#### 7. Postal-Only Applications on IHK Listings
- **File & Line:** [`scraper/ihk_scraper.py:145-165`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/ihk_scraper.py#L145-L165)
- **Symptom:** IHK listings for traditional craft trades finish with 0 emails and 0 forms.
- **Root Cause:** Chamber records specify `Bewerbungsart: Schriftlich` (paper mail only). The system correctly sets `application_method = "none"`, but users perceive 0 results as an extraction failure.

#### 8. Google Maps Businesses Lacking Corporate Domains
- **File & Line:** [`scraper/google_maps_scraper.py:440-470`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/google_maps_scraper.py#L440-L470)
- **Symptom:** Up to 15% of discovered local businesses yield no website or link to a dead URL.
- **Root Cause:** SME owners frequently list Facebook/Instagram URLs or outdated domains in Google Business profiles.

#### 9. Memory Footprint During Long-Running Extraction Tasks
- **File & Line:** [`scraper/working_email_extractor.py:748-758`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/scraper/working_email_extractor.py#L748-L758)
- **Symptom:** Headless Chrome browser processes accumulate memory over 1,000+ job extraction runs.
- **Root Cause:** Selenium WebDriver session is reused indefinitely across a worker's lifetime without periodic recycling (restart every 100 jobs).

#### 10. Worker Slot Acquisition Deadlock on Abrupt Socket Disconnect
- **File & Line:** [`app.py:2930-2940`](file:///c:/Users/provincesettat/Desktop/ftr/pro-main/app.py#L2930-L2940)
- **Symptom:** If a worker thread experiences a catastrophic unhandled termination before reaching `worker_slots.put(w_id)`, the slot is permanently lost.
- **Root Cause:** Slot acquisition occurred prior to the comprehensive inner `try ... finally` block.
