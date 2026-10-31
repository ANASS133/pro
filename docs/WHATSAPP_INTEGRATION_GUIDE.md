# WhatsApp AI Customer Support Center — Meta API Setup & Deployment Guide

## 1. Architectural Overview

The JobScout WhatsApp AI Customer Support Center is deeply integrated into the existing Flask + SPA architecture:
- **Cloud API Service (`services/whatsapp_service.py`)**: Official Meta Graph API v21.0 integration with HMAC-SHA256 payload signature verification, asynchronous outbound dispatching with exponential backoff retries, and strict 24-hour service window handling (Meta Error Code 131047).
- **Thread-Safe Conversation Store (`services/whatsapp_store.py`)**: SQLite with Write-Ahead Logging (`WAL`), optimistic version locking (`version` column), idempotent deduplication via `provider_message_id`, audit logging, and realtime metrics aggregation.
- **Hybrid AI / Human Routing Engine (`services/whatsapp_ai_engine.py`)**: Concurrency-safe state transitions (`AI_ACTIVE`, `HUMAN_ACTIVE`, `ESCALATED`, `AI_PAUSED`, `CLOSED`). Proves with atomic version gating that delayed AI inference cannot send outbound messages after an administrator takes manual control.
- **JobScout Service Tools (`services/whatsapp_tools.py`)**: Read-only, verified tools for client profile, application volume and progress, profession dataset availability (integrating with `profession_service`), document status, payment status, and human escalation. Requires customer account verification before disclosing confidential dossier details.
- **Real-Time Synchronization**: Native Server-Sent Events (SSE) via `/api/whatsapp/stream` pushing instant updates to connected administrator dashboards.
- **Dashboard UI (`static/spa/sections/whatsapp.js`, `templates/app_shell.html`, `static/spa/app.css`)**: 3-pane inbox, live metrics, AI configuration, knowledge base manager, and interactive Meta simulator.

---

## 2. Meta WhatsApp Business Cloud API Setup

### Step 1: Create Meta Developer App
1. Navigate to the [Meta for Developers Portal](https://developers.facebook.com/).
2. Log in with your Facebook account and select **My Apps** > **Create App**.
3. Select **Other** as the app use case > Select **Business** as the app type.
4. Name the application (e.g. `JobScout WhatsApp Support`) and link it to your verified **Meta Business Account (Business Manager)**.

### Step 2: Add WhatsApp Product
1. On the App Dashboard, find **WhatsApp** under *Add products to your app* and click **Set up**.
2. Meta will automatically generate a **Test WhatsApp Business Account** and a **Test Phone Number** with temporary credentials for testing.

### Step 3: Production Phone Number Configuration & Coexistence
When configuring a permanent phone number:
- **Clean / Unregistered Number (Recommended)**: A new virtual mobile or landline number that has never been registered on WhatsApp. Enter it in **WhatsApp** > **Configuration** > **Phone Numbers** and verify via SMS or Voice call.
- **Existing WhatsApp Business App Number (Coexistence Onboarding)**:
  - Meta supports **WhatsApp Business App Coexistence** allowing eligible businesses to use both the mobile WhatsApp Business App and Cloud API simultaneously on the same number for selected regions.
  - *Eligibility*: Check Meta's coexistence feature status in your Business Manager under *WhatsApp Accounts*. If coexistence is not yet enabled for your region/WABA, migrating the number to Cloud API requires deleting the existing WhatsApp account on the mobile app before registering it in Meta Cloud API.

### Step 4: Generate a Permanent System User Access Token
*Do not use temporary 24-hour developer tokens in production.*
1. Go to [Meta Business Settings](https://business.facebook.com/settings).
2. Under **Users** > **System Users**, click **Add** (Role: **Admin**).
3. Assign assets to the system user:
   - Your WhatsApp App (Full control).
   - Your WhatsApp Business Account (Full control).
4. Click **Generate New Token**:
   - App: Select `JobScout WhatsApp Support`.
   - Expiration: **Never**.
   - Permissions: Select `whatsapp_business_messaging` and `whatsapp_business_management`.
5. Copy the generated token immediately and store it securely in your server `.env` file.

### Step 5: Webhook Configuration
1. In the Meta App Dashboard, go to **WhatsApp** > **Configuration** > **Webhooks**.
2. Click **Edit**:
   - **Callback URL**: `https://<your-jobscout-domain>/api/whatsapp/webhook`
   - **Verify Token**: Set a strong random string (e.g., `openssl rand -hex 32`) matching `WHATSAPP_VERIFY_TOKEN` in your environment.
3. Click **Verify and Save**. Meta will send a `GET` request with challenge validation.
4. Under **Webhook fields**, click **Manage** and subscribe to:
   - `messages` (Inbound messages and media)
   - `message_deliveries` (Delivery receipts, read status, and delivery failures)

---

## 3. Environment Variables Configuration

Add the following keys to your `.env` file on the production server:

```ini
# -----------------------------------------------------------------------------
# Meta WhatsApp Cloud API Configuration
# -----------------------------------------------------------------------------
WHATSAPP_ACCESS_TOKEN=EAAG...YOUR_PERMANENT_SYSTEM_USER_TOKEN...
WHATSAPP_PHONE_NUMBER_ID=109283746501928
WHATSAPP_BUSINESS_ACCOUNT_ID=982734610293847
WHATSAPP_APP_SECRET=a1b2c3d4e5f6g7h8...YOUR_APP_SECRET...
WHATSAPP_VERIFY_TOKEN=jobscout_meta_webhook_verify_secure_key_2026
WHATSAPP_API_VERSION=v21.0

# -----------------------------------------------------------------------------
# Central AI Gateway Providers (Reused from JobScout)
# -----------------------------------------------------------------------------
OPENAI_API_KEY=sk-proj-...
GEMINI_API_KEY=AIzaSy...
```

---

## 4. Reverse Proxy & Server-Sent Events (SSE) Setup

The WhatsApp Center utilizes SSE (`/api/whatsapp/stream`) to deliver real-time messages and status updates to agents. Configure Nginx to disable buffering on streaming routes:

```nginx
# Nginx Configuration snippet for JobScout
server {
    server_name jobscout.example.com;

    location /api/whatsapp/stream {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 5. Concurrency & Safety Proof

The routing engine implements strict optimistic locking and atomic version gating:
1. When an incoming message arrives, the worker captures `conversation.version` (e.g. `version=1`).
2. While the LLM generates an answer (which can take 1–3 seconds), an agent can click **"Take Over"** in the dashboard.
3. The `atomic_takeover` transaction executes:
   - Sets `mode = 'HUMAN_ACTIVE'`
   - Increments `version = version + 1` (e.g. `version=2`)
   - Logs the event in `whatsapp_audit_logs`.
4. When the AI inference returns, `verify_conversation_version(conversation_id, expected_version=1)` evaluates to `False`.
5. The pending message is discarded immediately with a warning log, ensuring zero race condition replies after human intervention.

---

## 6. Verification and Automated Test Suite

To verify the entire WhatsApp system and all 17 critical scenarios:

```bash
# Run unit & integration tests
.\.venv\Scripts\python.exe -m unittest tests.test_whatsapp_support -v
```

All 17 tests validate:
- Webhook signature verification and deduplication
- Autonomous AI handling with multi-language fallback
- Authenticated client tools vs. unverified protection
- Escalation handling and admin notification
- Concurrency race prevention during takeover
- 24-hour service window error handling
- Prompt injection defenses
- Multi-agent takeover conflict handling
