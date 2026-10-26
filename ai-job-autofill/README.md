# AI Job Autofill

Chrome extension and local Node.js server for accurately and safely filling job application forms across German, French, and English, powered by applicant JSON profiles and OpenAI (GPT-5.6 Luna).

---

## Key Features

1. **Intelligent Field Discovery**:
   - Discovers visible and enabled text inputs, textareas, selects, radio groups, checkboxes, date fields, and file upload controls.
   - Extracts rich contextual signals: field labels, nearby question instructions, placeholders, accessible names (`aria-label`, `aria-labelledby`), available dropdown options, validation constraints (`required`, `pattern`, `min`, `max`), and surrounding section headings.
   - Generates stable, deterministic identifiers for fields across re-renders and form steps.
   - Discovers accessible `iframes` and reports cross-origin inaccessible frames clearly.
   - Detects dynamic form mutations (fields shown conditionally after selecting options).

2. **Three-Stage Matching Engine**:
   - **Stage 1 (Deterministic Rules)**: Fast, zero-cost matching for standard fields in German, French, and English (names, contact info, addresses, birth dates, gender/salutation, nationality, links, and documents).
   - **Stage 2 (AI Structured Fill Plan)**: Calls GPT-5.6 Luna only for ambiguous fields or open questions. Returns structured JSON containing field ID, proposed value, profile source path, confidence, reason, fact verification status, and review flags. Never executes or generates JavaScript.
   - **Stage 3 (User Review Screen)**: Unconfident or sensitive fields are presented for review rather than guessing.

3. **Interactive Review Screen Before Filling**:
   - Displays all proposed answers in an editable review table before touching the page.
   - Visual badges distinguish **Verified Profile Facts** (`✓ Verified Fact`) from **AI Synthesized Text** (`✦ AI Draft`) and **Manual Confirmations** (`⚠️ Review Required`).
   - Confidence meters (e.g. `98% High`) and exact profile source paths (`applicant.contact.email`).
   - Lets you edit any proposed answer inline, approve or skip fields individually, or click **✓ Approve All Verified**.

4. **Multi-Step Form Support**:
   - Tracks application progress across multi-page forms (e.g., Step 1: Personal Data ➔ Step 2: Experience ➔ Step 3: Questions).
   - Automatically remembers previously approved answers on the domain for the selected candidate.
   - Discovers new fields as the user navigates between steps.
   - **Never clicks the final Submit / Apply button automatically**.

5. **Correction Memory**:
   - Remembers when you customize or correct a proposed value for a specific website and field pattern.
   - Automatically recalls your preferred answers on future visits.
   - Inspect, modify, or delete saved corrections anytime via the **🧠 Memory** popup drawer.

6. **Open-Ended Application Questions**:
   - For prompts such as *"Why are you interested in this role?"* or *"Über mich"*, drafts concise, tailored answers based strictly on the selected applicant's verified experience, summary, and the visible job context.
   - Strictly marked as `AI Draft - Review Required`.
   - Anti-hallucination guardrail: Never invents unverified skills, certificates, salary expectations, or work authorization.

7. **Failure Diagnostics & Field Retry**:
   - If a website rejects a value, has missing dropdown options, or fails validation, a diagnostics panel details the exact reason:
     - `no matching profile value`
     - `low confidence`
     - `unsupported control`
     - `inaccessible frame`
     - `missing dropdown option`
     - `rejected value`
     - `validation error`
   - Edit the value and click **Edit & Retry** immediately.

8. **Strict Document & Sensitive Data Safeguards**:
   - Dedicated folder isolation (`server/profiles/<id>/`): candidates' documents never mix.
   - Confirmation required before attaching ordinary documents (CV, Cover Letter, Diplomas, Transcripts).
   - **Sensitive Documents Protected**: National IDs, Passports, and CINs are **never auto-uploaded** and strictly flagged for manual user handling.
   - Privacy and terms checkboxes are **never auto-checked**.

---

## Setup & Getting Started

### 1. Start the Local Server

```bash
cd server
npm ci
npm start
```

The server runs on `http://localhost:8787`. You can also run `npm run dev` to enable watch mode during development.

### 2. Configure Environment

Ensure `server/.env` contains your OpenAI API key:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

### 3. Load the Chrome Extension

1. Open Google Chrome and navigate to `chrome://extensions`.
2. Toggle on **Developer mode** in the top-right corner.
3. Click **Load unpacked** and select the [`extension`](file:///c:/Users/provincesettat/Desktop/auto%20fill%20job/extension) folder.

### 4. Test with the Built-in Trilingual Form

Open `http://localhost:8787/test-form` in Chrome and open the extension popup:
1. Select an applicant profile (e.g. `Boumlik_Chamseddine` or upload a new candidate JSON).
2. Click **Scan & Match Form**.
3. Inspect the **Review Screen**: review verified facts vs AI drafts, edit answers if desired, and click **Fill Approved Fields**.
4. Navigate through Steps 1, 2, and 3 to test multi-step forms, document uploads, and dynamic fields.

---

## Managing Candidate Profiles & Documents

Each applicant profile has an isolated JSON file and a dedicated matching document directory:

```text
server/
├── profiles/
│   ├── template.json
│   ├── Boumlik_Chamseddine.json
│   └── Boumlik_Chamseddine/
│       ├── CV.pdf
│       ├── bac.jpeg
│       ├── relver de note bac.jpeg
│       ├── attestation de reussite.jpeg
│       ├── cin recto.jpeg         (Strictly protected)
│       └── cin verso.jpeg         (Strictly protected)
```

- **Add New Candidate**: Copy `server/profiles/template.json` to `server/profiles/<name>.json`, or click **➕ New** in the extension popup to upload any JSON file directly.
- **Upload Documents**: Click **➕ Add Documents** in the extension popup to attach PDFs or images directly into that applicant's folder.
- **Preview Documents**: Click **Preview** in the extension popup to inspect files inline in a new tab.

---

## Automated Test Suites

Run the complete test suite verifying trilingual matching, profile isolation, sensitive document blocking, correction memory, and schema integrity:

```bash
cd server
npm test
```

This runs:
- `test-autofill-regression.js`: Verifies local matching, approval safeguards, DOM re-render recovery, event lifecycle, custom comboboxes, split dates, and frame routing.
- `test-server-autofill.js`: Verifies phone formatting, address splitting, matching-data isolation, and missing-data safeguards with a temporary profile.
- `test-documents.js`: Verifies document detection, path traversal protection, isolation, and preview headers.
- `test-calendar-regression.js`: Verifies custom calendar interaction.

The older candidate-specific integration checks remain available with `npm run test:legacy`.
