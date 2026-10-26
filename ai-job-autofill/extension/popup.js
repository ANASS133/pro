// popup.js - Compact Single-Column Review Screen, Multi-step forms, Correction Memory & Safeguards

let BACKEND_BASE = "http://localhost:5000";
let MAP_FIELDS_URL = `${BACKEND_BASE}/api/map-fields`;
let PROFILES_URL = `${BACKEND_BASE}/api/profiles`;
let TEMPLATE_URL = `${BACKEND_BASE}/api/template`;
let CORRECTIONS_URL = `${BACKEND_BASE}/api/corrections`;

async function detectBackend() {
  const candidates = ["http://localhost:5000", "http://localhost:8787"];
  for (const base of candidates) {
    try {
      const res = await fetch(`${base}/api/profiles`, { method: "GET", signal: AbortSignal.timeout(800) });
      if (res.ok) {
        BACKEND_BASE = base;
        MAP_FIELDS_URL = `${BACKEND_BASE}/api/map-fields`;
        PROFILES_URL = `${BACKEND_BASE}/api/profiles`;
        TEMPLATE_URL = `${BACKEND_BASE}/api/template`;
        CORRECTIONS_URL = `${BACKEND_BASE}/api/corrections`;
        globalThis._autofillBackendBase = base;
        return base;
      }
    } catch (e) {}
  }
  return BACKEND_BASE;
}
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Safe storage wrapper for extension & standalone browser contexts
const safeStorage = {
  get: async (keys) => {
    if (window.chrome?.storage?.local) {
      return chrome.storage.local.get(keys);
    }
    const res = {};
    const keyArr = Array.isArray(keys) ? keys : [keys];
    keyArr.forEach(k => {
      try { res[k] = JSON.parse(localStorage.getItem(k) || "null"); } catch { res[k] = null; }
    });
    return res;
  },
  set: async (obj) => {
    if (window.chrome?.storage?.local) {
      return chrome.storage.local.set(obj);
    }
    Object.entries(obj).forEach(([k, v]) => {
      try { localStorage.setItem(k, JSON.stringify(v)); } catch {}
    });
  },
  remove: async (keys) => {
    if (window.chrome?.storage?.local) {
      return chrome.storage.local.remove(keys);
    }
    const keyArr = Array.isArray(keys) ? keys : [keys];
    keyArr.forEach(k => localStorage.removeItem(k));
  }
};

// Views
const setupView = document.getElementById("setupView");
const reviewView = document.getElementById("reviewView");
const diagnosticsView = document.getElementById("diagnosticsView");

// Setup controls
const scanBtn = document.getElementById("scanBtn");
const statusEl = document.getElementById("status");
const serverIndicator = document.getElementById("serverIndicator");
const serverStatusText = document.getElementById("serverStatusText");
const profileSelect = document.getElementById("profileSelect");
const refreshProfilesBtn = document.getElementById("refreshProfilesBtn");
const profileFileInput = document.getElementById("profileFileInput");
const previewName = document.getElementById("previewName");
const previewTitle = document.getElementById("previewTitle");
const framesWarning = document.getElementById("framesWarning");

// Document management
const docFileInput = document.getElementById("docFileInput");
const docWarningBanner = document.getElementById("docWarningBanner");
const documentsList = document.getElementById("documentsList");

// Multi-step session banner
const multiStepBanner = document.getElementById("multiStepBanner");
const multiStepTitle = document.getElementById("multiStepTitle");
const multiStepDesc = document.getElementById("multiStepDesc");
const clearSessionBtn = document.getElementById("clearSessionBtn");

// JSON Template
const toggleTemplateBtn = document.getElementById("toggleTemplateBtn");
const templateBody = document.getElementById("templateBody");
const copyTemplateBtn = document.getElementById("copyTemplateBtn");
const copyBtnIcon = document.getElementById("copyBtnIcon");
const copyBtnText = document.getElementById("copyBtnText");
const copySuccessMsg = document.getElementById("copySuccessMsg");
const templateCodeArea = document.getElementById("templateCodeArea");

// Review Screen controls
const backToSetupBtn = document.getElementById("backToSetupBtn");
const reviewApplicantName = document.getElementById("reviewApplicantName");
const statTotalCount = document.getElementById("statTotalCount");
const statVerifiedCount = document.getElementById("statVerifiedCount");
const statReviewCount = document.getElementById("statReviewCount");
const reviewList = document.getElementById("reviewList");
const filterTabs = document.querySelectorAll(".filter-tab");
const tabCountAll = document.getElementById("tabCountAll");
const tabCountVerified = document.getElementById("tabCountVerified");
const tabCountReview = document.getElementById("tabCountReview");
const tabCountDocs = document.getElementById("tabCountDocs");
const docProposalsCard = document.getElementById("docProposalsCard");
const docProposalsList = document.getElementById("docProposalsList");
const approveAllVerifiedBtn = document.getElementById("approveAllVerifiedBtn");
const deselectAllBtn = document.getElementById("deselectAllBtn");
const fillApprovedBtn = document.getElementById("fillApprovedBtn");
const fillApprovedText = document.getElementById("fillApprovedText");

// Corrections Memory Modal
const openCorrectionsBtn = document.getElementById("openCorrectionsBtn");
const correctionsBadge = document.getElementById("correctionsBadge");
const correctionsModal = document.getElementById("correctionsModal");
const closeCorrectionsBtn = document.getElementById("closeCorrectionsBtn");
const closeCorrectionsBtn2 = document.getElementById("closeCorrectionsBtn2");
const clearAllCorrectionsBtn = document.getElementById("clearAllCorrectionsBtn");
const correctionsList = document.getElementById("correctionsList");

// Applications History Modal
const openAppsBtn = document.getElementById("openAppsBtn");
const appsBadge = document.getElementById("appsBadge");
const appsModal = document.getElementById("appsModal");
const closeAppsBtn = document.getElementById("closeAppsBtn");
const closeAppsBtn2 = document.getElementById("closeAppsBtn2");
const clearAppsBtn = document.getElementById("clearAppsBtn");
const exportAppsBtn = document.getElementById("exportAppsBtn");
const appsList = document.getElementById("appsList");
const captchaWarningBanner = document.getElementById("captchaWarningBanner");

// Diagnostics View
const backFromDiagBtn = document.getElementById("backFromDiagBtn");
const diagnosticsSummary = document.getElementById("diagnosticsSummary");
const diagnosticsList = document.getElementById("diagnosticsList");

// State
let cachedProfiles = [];
let cachedTemplateJson = "";
let currentPageContext = null;
const dockParams = new URLSearchParams(location.search);
let currentTabId = dockParams.has("tabId") ? Number(dockParams.get("tabId")) : null;
async function targetTab() {
  return currentTabId !== null ? chrome.tabs.get(currentTabId) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
}
let currentDomain = "localhost";
let currentScannedFields = [];
let currentActions = [];
let currentDocProposals = [];
let currentFilter = "all";

function setServerStatus(online) {
  if (online) {
    serverIndicator.className = "indicator online";
    serverStatusText.textContent = "Online";
  } else {
    serverIndicator.className = "indicator offline";
    serverStatusText.textContent = "Offline";
  }
}

function updatePreview(profileId) {
  const profile = cachedProfiles.find(p => p.id === profileId);
  const profileAvatar = document.getElementById("profileAvatar");
  if (profile) {
    previewName.textContent = profile.name || profile.id;
    previewTitle.textContent = profile.title ? profile.title : (profile.email || profile.fileName);
    if (profileAvatar) {
      const initials = (profile.name || profile.id)
        .split(/[\s_]+/)
        .map(w => w[0])
        .filter(Boolean)
        .slice(0, 2)
        .join("")
        .toUpperCase();
      profileAvatar.textContent = initials || "AI";
    }
  } else {
    previewName.textContent = "No profile selected";
    previewTitle.textContent = "";
    if (profileAvatar) profileAvatar.textContent = "AI";
  }
}

/**
 * Loads applicant documents for selected profile
 */
async function loadApplicantDocuments(profileId) {
  if (!profileId) {
    documentsList.innerHTML = '<div class="doc-empty-state">No applicant selected</div>';
    docWarningBanner.style.display = "none";
    return;
  }

  try {
    const url = `${BACKEND_BASE}/api/profiles/${encodeURIComponent(profileId)}/documents`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    const docs = data.documents || [];

    if (!data.hasFolder || docs.length === 0) {
      docWarningBanner.textContent = `⚠️ No documents found in profiles/${profileId}/. Click "➕ Add Documents" to upload CV, certificates, etc.`;
      docWarningBanner.style.display = "block";
    } else if (data.missingRecommended && data.missingRecommended.length > 0) {
      docWarningBanner.textContent = `⚠️ Missing recommended document: ${data.missingRecommended.join(", ")}`;
      docWarningBanner.style.display = "block";
    } else {
      docWarningBanner.style.display = "none";
    }

    if (docs.length === 0) {
      documentsList.innerHTML = '<div class="doc-empty-state">No documents uploaded yet</div>';
      return;
    }

    documentsList.innerHTML = "";
    docs.forEach(doc => {
      const itemEl = document.createElement("div");
      itemEl.className = "doc-item";

      const fileIcon = doc.extension === "pdf" ? "📄" : (doc.isSensitive ? "🪪" : "🖼️");
      const badgeClass = `doc-badge doc-badge-${doc.type}`;

      itemEl.innerHTML = `
        <div class="doc-item-left">
            <span class="doc-file-icon">${escapeHtml(fileIcon)}</span>
          <div class="doc-details">
            <span class="doc-name" title="${escapeHtml(doc.fileName)}">${escapeHtml(doc.fileName)}</span>
            <div class="doc-meta">
              <span class="${escapeHtml(badgeClass)}">${escapeHtml(doc.typeLabel)}</span>
              <span>${escapeHtml(doc.sizeFormatted)}</span>
            </div>
          </div>
        </div>
        <button class="doc-preview-btn" data-url="${escapeHtml(doc.previewUrl)}" type="button" title="Preview document">Preview</button>
      `;

      itemEl.querySelector(".doc-preview-btn").addEventListener("click", () => {
        if (window.chrome?.tabs?.create) {
          chrome.tabs.create({ url: doc.previewUrl });
        } else {
          window.open(doc.previewUrl, "_blank");
        }
      });

      documentsList.appendChild(itemEl);
    });

  } catch (err) {
    documentsList.innerHTML = `<div class="doc-empty-state">Failed to load documents: ${escapeHtml(err.message)}</div>`;
    docWarningBanner.style.display = "none";
  }
}

/**
 * Loads applicant profiles from server
 */
async function loadProfiles() {
  try {
    await detectBackend();
    const res = await fetch(PROFILES_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const data = await res.json();
    setServerStatus(true);

    cachedProfiles = data.profiles || [];
    profileSelect.innerHTML = "";

    if (cachedProfiles.length === 0) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "No profiles found";
      profileSelect.appendChild(opt);
      updatePreview(null);
      loadApplicantDocuments(null);
      return;
    }

    cachedProfiles.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = `${p.name} (${p.fileName || p.id})`;
      profileSelect.appendChild(opt);
    });

    const stored = await safeStorage.get(["selectedProfileId"]);
    const savedId = stored?.selectedProfileId;

    if (savedId && cachedProfiles.some(p => p.id === savedId)) {
      profileSelect.value = savedId;
    } else {
      profileSelect.value = cachedProfiles[0].id;
      await safeStorage.set({ selectedProfileId: profileSelect.value });
    }

    const currentId = profileSelect.value;
    updatePreview(currentId);
    loadApplicantDocuments(currentId);
    checkMultiStepSession(currentId);
    checkCorrectionsBadge(currentId);

  } catch (err) {
    setServerStatus(false);
    profileSelect.innerHTML = '<option value="">Server offline</option>';
    previewName.textContent = "Server unreachable";
    previewTitle.textContent = "Check if Flask server (5000) or Node (8787) is running";
    loadApplicantDocuments(null);
  }
}

/**
 * Checks and displays multi-step session progress if available
 */
async function checkMultiStepSession(profileId) {
  if (!currentDomain || !profileId) return;
  const key = `session_${currentDomain}_${profileId}`;
  const stored = await safeStorage.get([key]);
  const session = stored?.[key];

  if (session && session.filledHistory && session.filledHistory.length > 0) {
    multiStepTitle.textContent = `Multi-Step: ${session.filledHistory.length} fields filled`;
    multiStepDesc.textContent = `Active application on ${currentDomain}.`;
    multiStepBanner.style.display = "flex";
  } else {
    multiStepBanner.style.display = "none";
  }
}

/**
 * Clears multi-step session for current domain and candidate
 */
clearSessionBtn.addEventListener("click", async () => {
  const profileId = profileSelect.value;
  if (!currentDomain || !profileId) return;
  const key = `session_${currentDomain}_${profileId}`;
  await safeStorage.remove([key]);
  multiStepBanner.style.display = "none";
  statusEl.textContent = "Application session reset.";
});

/**
 * Checks count of saved site corrections and updates badge
 */
async function checkCorrectionsBadge(profileId) {
  if (!profileId) return;
  try {
    const res = await fetch(`${CORRECTIONS_URL}?profileId=${encodeURIComponent(profileId)}&domain=${encodeURIComponent(currentDomain)}`);
    if (res.ok) {
      const data = await res.json();
      const count = (data.corrections || []).length;
      if (count > 0) {
        correctionsBadge.textContent = count;
        correctionsBadge.style.display = "inline-block";
      } else {
        correctionsBadge.style.display = "none";
      }
    }
  } catch {}
}

// Profile selection change
profileSelect.addEventListener("change", async () => {
  const selectedId = profileSelect.value;
  await safeStorage.set({ selectedProfileId: selectedId });
  updatePreview(selectedId);
  loadApplicantDocuments(selectedId);
  checkMultiStepSession(selectedId);
  checkCorrectionsBadge(selectedId);
});

refreshProfilesBtn.addEventListener("click", () => {
  loadProfiles();
});

// Upload profile JSON
profileFileInput.addEventListener("change", async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;

  try {
    statusEl.textContent = `Uploading profile ${file.name}...`;
    const text = await file.text();
    const profileJson = JSON.parse(text);
    const safeId = file.name.replace(/\.json$/i, "").replace(/[^a-zA-Z0-9_-]/g, "_").toLowerCase();

    const res = await fetch(PROFILES_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: safeId, profileData: profileJson })
    });

    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    const saved = await res.json();
    statusEl.textContent = `Profile "${saved.name || saved.id}" added!`;

    await loadProfiles();
    profileSelect.value = saved.id;
    await safeStorage.set({ selectedProfileId: saved.id });
    updatePreview(saved.id);
    loadApplicantDocuments(saved.id);

  } catch (err) {
    statusEl.textContent = `Upload error: ${err.message}`;
  } finally {
    profileFileInput.value = "";
  }
});

// Upload applicant documents
docFileInput.addEventListener("change", async (event) => {
  const files = Array.from(event.target.files || []);
  if (files.length === 0) return;

  const selectedProfileId = profileSelect.value;
  if (!selectedProfileId) {
    statusEl.textContent = "Please select an applicant profile first.";
    return;
  }

  try {
    statusEl.textContent = `Uploading ${files.length} document(s)...`;
    const filePayloads = [];

    for (const f of files) {
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const res = reader.result;
          resolve(res.split(",")[1]);
        };
        reader.onerror = reject;
        reader.readAsDataURL(f);
      });

      filePayloads.push({ name: f.name, contentBase64: base64 });
    }

    const res = await fetch(`${BACKEND_BASE}/api/profiles/${encodeURIComponent(selectedProfileId)}/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: filePayloads })
    });

    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
    const result = await res.json();
    statusEl.textContent = `Uploaded ${result.uploadedCount || 0} document(s) successfully!`;
    await loadApplicantDocuments(selectedProfileId);

  } catch (err) {
    statusEl.textContent = `Document upload error: ${err.message}`;
  } finally {
    docFileInput.value = "";
  }
});

// Template loading & copy
async function loadTemplate() {
  if (cachedTemplateJson) {
    templateCodeArea.value = cachedTemplateJson;
    return;
  }
  try {
    templateCodeArea.value = "Loading template from server...";
    const res = await fetch(TEMPLATE_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    cachedTemplateJson = data.formattedJson;
    templateCodeArea.value = cachedTemplateJson;
  } catch (err) {
    templateCodeArea.value = `// Failed to load template: ${err.message}`;
  }
}

toggleTemplateBtn.addEventListener("click", () => {
  const isHidden = templateBody.style.display === "none";
  if (isHidden) {
    templateBody.style.display = "flex";
    toggleTemplateBtn.textContent = "Hide Template";
    loadTemplate();
  } else {
    templateBody.style.display = "none";
    toggleTemplateBtn.textContent = "Show Template";
  }
});

copyTemplateBtn.addEventListener("click", async () => {
  const textToCopy = cachedTemplateJson || templateCodeArea.value;
  if (!textToCopy) return;

  try {
    await navigator.clipboard.writeText(textToCopy);
    copyBtnIcon.textContent = "✓";
    copyBtnText.textContent = "Copied!";
    copySuccessMsg.style.display = "block";
    setTimeout(() => {
      copyBtnIcon.textContent = "📋";
      copyBtnText.textContent = "Copy JSON";
      copySuccessMsg.style.display = "none";
    }, 2000);
  } catch (err) {
    templateCodeArea.select();
    document.execCommand("copy");
  }
});

// ---------------------------------------------------------------------------
// VIEW SWITCHING
// ---------------------------------------------------------------------------

function showView(viewName) {
  setupView.style.display = viewName === "setup" ? "flex" : "none";
  reviewView.style.display = viewName === "review" ? "flex" : "none";
  diagnosticsView.style.display = viewName === "diagnostics" ? "flex" : "none";
}

backToSetupBtn.addEventListener("click", () => {
  showView("setup");
});

backFromDiagBtn.addEventListener("click", () => {
  showView("review");
});

// ---------------------------------------------------------------------------
// MAIN SCAN & MATCH WORKFLOW
// ---------------------------------------------------------------------------

scanBtn.addEventListener("click", async () => {
  try {
    scanBtn.disabled = true;
    framesWarning.style.display = "none";

    const selectedProfileId = profileSelect.value;
    if (!selectedProfileId) {
      statusEl.textContent = "Please select an applicant profile first.";
      scanBtn.disabled = false;
      return;
    }

    statusEl.textContent = "Scanning page fields & frames...";

    let fields = [];
    let inaccessibleFrames = [];
    let pageContext = null;

    if (window.chrome?.tabs?.query) {
      const tab = await targetTab();
      if (!tab || !tab.id) throw new Error("No active tab found");
      currentTabId = tab.id;

      try {
        const parsedUrl = new URL(tab.url || "http://localhost");
        currentDomain = parsedUrl.hostname;
      } catch {
        currentDomain = "unknown";
      }

      const scanResponse = await AutofillClient.scan(tab.id);
      fields = scanResponse?.fields || [];
      inaccessibleFrames = scanResponse?.inaccessible_frames || [];
      pageContext = scanResponse?.page_context || null;
      currentPageContext = pageContext;
      if (captchaWarningBanner) {
        captchaWarningBanner.style.display = scanResponse?.has_captcha ? "block" : "none";
      }
    } else {
      // Standalone browser demonstration/testing fallback
      currentDomain = window.location.hostname || "test-portal.de";
      fields = [
        { field_id: "f_prenom", type: "text", label: "Votre prénom", section_heading: "COMPLÉTEZ VOTRE PROFIL" },
        { field_id: "f_nom", type: "text", label: "Votre nom", section_heading: "COMPLÉTEZ VOTRE PROFIL" },
        { field_id: "f_ville", type: "text", label: "Votre ville", section_heading: "COMPLÉTEZ VOTRE PROFIL" },
        { field_id: "f_nationalite", type: "select", tag: "select", label: "Nationalité", section_heading: "COMPLÉTEZ VOTRE PROFIL", options: [{ value: "Moroccan", text: "Marocaine" }, { value: "French", text: "Française" }, { value: "German", text: "Allemande" }] },
        { field_id: "f_dob", type: "date", label: "Date de naissance", is_date_picker: true, section_heading: "COMPLÉTEZ VOTRE PROFIL", placeholder: "Sélectionner une date" },
        { field_id: "ai_7g07d6_3", type: "text", label: "Champ sans libellé (Complément d'information / Remarques)", section_heading: "COMPLÉTEZ VOTRE PROFIL", placeholder: "Complément d'information / Remarques" }
      ];
    }

    const quickField = dockParams.get("field");
    if (quickField) fields = fields.filter(f => f.field_id === quickField);
    currentScannedFields = fields;

    if (inaccessibleFrames.length > 0) {
      framesWarning.textContent = `⚠️ Note: ${inaccessibleFrames.length} cross-origin iframe(s) cannot be accessed directly due to browser security restrictions.`;
      framesWarning.style.display = "block";
    }

    if (fields.length === 0) {
      statusEl.textContent = "No fillable form fields found on this page.";
      scanBtn.disabled = false;
      return;
    }

    const candidate = cachedProfiles.find(p => p.id === selectedProfileId);
    const candidateName = candidate?.name || selectedProfileId;
    statusEl.textContent = `Matching ${fields.length} fields for ${candidateName}...`;

    // 2. Request three-stage mapping from backend
    const data = await AutofillClient.map(fields, selectedProfileId, currentDomain, pageContext);
    const actions = data.actions || [];

    // Separate ordinary actions and document proposals
    currentActions = actions.filter(a => a.action !== "propose_upload");
    currentDocProposals = actions.filter(a => a.action === "propose_upload" && a.proposed_file);

    currentActions.forEach(act => {
      act.isApproved = act.action === "fill" && !act.review_required && AutofillMatching.ready(act, fields.find(f => f.field_id === act.field_id));
      act.saveCorrection = false;
    });

    currentDocProposals.forEach(prop => {
      prop.isApproved = false;
    });

    // 3. Render Review Screen
    renderReviewScreen(candidateName);
    showView("review");

  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  } finally {
    scanBtn.disabled = false;
  }
});

// ---------------------------------------------------------------------------
// REVIEW SCREEN RENDERING & INTERACTIONS (Compact Single-Column)
// ---------------------------------------------------------------------------

function renderReviewScreen(applicantName) {
  reviewApplicantName.textContent = applicantName;

  // Stats calculation
  const totalCount = currentActions.length + currentDocProposals.length;
  const verifiedCount = currentActions.filter(a => a.is_verified_fact && !a.review_required).length;
  const reviewCount = currentActions.filter(a => a.review_required || !a.is_verified_fact).length;

  statTotalCount.textContent = totalCount;
  statVerifiedCount.textContent = verifiedCount;
  statReviewCount.textContent = reviewCount;

  tabCountAll.textContent = totalCount;
  tabCountVerified.textContent = verifiedCount;
  tabCountReview.textContent = reviewCount;
  tabCountDocs.textContent = currentDocProposals.length;

  // Render Document proposals card
  if (currentDocProposals.length > 0) {
    docProposalsCard.style.display = "flex";
    docProposalsList.innerHTML = "";

    currentDocProposals.forEach((prop, idx) => {
      const file = prop.proposed_file;
      const row = document.createElement("div");
      row.className = "doc-prop-row";

      row.innerHTML = `
        <div class="review-toggle-wrap">
          <input type="checkbox" id="docPropCheck_${idx}" ${prop.isApproved ? "checked" : ""}>
          <label for="docPropCheck_${idx}" class="doc-prop-label">${escapeHtml(file.label || "Document")}</label>
        </div>
        <div class="doc-prop-file">
          <span>📎 ${escapeHtml(file.fileName)}</span>
          <button class="doc-preview-btn preview-prop-btn" type="button">Preview</button>
        </div>
      `;

      row.querySelector(`#docPropCheck_${idx}`).addEventListener("change", (e) => {
        prop.isApproved = e.target.checked;
        updateFillButtonCount();
      });

      row.querySelector(".preview-prop-btn").addEventListener("click", () => {
        if (window.chrome?.tabs?.create) {
          chrome.tabs.create({ url: file.fileUrl });
        } else {
          window.open(file.fileUrl, "_blank");
        }
      });

      docProposalsList.appendChild(row);
    });
  } else {
    docProposalsCard.style.display = "none";
  }

  // Render Field Items
  renderFilteredFields();
  updateFillButtonCount();
}

/**
 * Renders fields using a clean, compact single-column layout without horizontal squeeze
 */
function renderFilteredFields() {
  reviewList.innerHTML = "";

  const itemsToRender = currentActions.filter(act => {
    if (currentFilter === "verified") return act.is_verified_fact && !act.review_required;
    if (currentFilter === "review") return act.review_required || !act.is_verified_fact;
    if (currentFilter === "docs") return false;
    return true;
  });

  if (itemsToRender.length === 0) {
    reviewList.innerHTML = '<div class="doc-empty-state">No fields match this filter.</div>';
    return;
  }

  itemsToRender.forEach((act) => {
    const fieldMeta = currentScannedFields.find(f => f.field_id === act.field_id) || {};
    const itemEl = document.createElement("div");

    let statusClass = "approved";
    if (!act.isApproved) statusClass = "skipped";
    else if (act.review_required) statusClass = "needs-review";

    itemEl.className = `review-item ${statusClass}`;
    itemEl.dataset.fieldId = act.field_id;

    // Badges
    let factBadgeHtml = "";
    if (act.profile_source_path === "correction_memory") {
      factBadgeHtml = '<span class="badge-fact badge-correction">🧠 Saved Memory</span>';
    } else if (act.is_verified_fact && !act.review_required) {
      factBadgeHtml = '<span class="badge-fact badge-verified">✓ Verified Fact</span>';
    } else if (!act.is_verified_fact) {
      factBadgeHtml = '<span class="badge-fact badge-ai">✦ AI Draft</span>';
    } else {
      factBadgeHtml = '<span class="badge-fact badge-manual">⚠️ Review Required</span>';
    }

    const confidencePct = Math.round((act.confidence || 0.8) * 100);
    const confidenceHtml = `<span class="confidence-pill" title="Confidence Score">${confidencePct}%</span>`;
    const sourcePath = act.profile_source_path || "Profile Fact";
    const sourceHtml = `<span class="review-source-tag" title="Source: ${escapeHtml(sourcePath)}">${escapeHtml(sourcePath)}</span>`;

    const displayLabel = fieldMeta.display_label || fieldMeta.label;
    let questionText = "";

    // Never display an internal field ID like ai_... as the primary label
    if (displayLabel && !displayLabel.startsWith("ai_") && !displayLabel.startsWith("field_") && !displayLabel.startsWith("f_")) {
      questionText = displayLabel;
    } else if (fieldMeta.nearby_question && !fieldMeta.nearby_question.startsWith("ai_")) {
      questionText = fieldMeta.nearby_question;
    } else if (fieldMeta.placeholder) {
      questionText = `Champ sans libellé (${fieldMeta.placeholder})`;
    } else {
      questionText = "Champ sans libellé";
    }

    // Treat generic section headings purely as secondary context
    const hasDistinctSectionHeading = fieldMeta.section_heading &&
      fieldMeta.section_heading.trim().toLowerCase() !== questionText.trim().toLowerCase();
    const sectionHeadingText = hasDistinctSectionHeading
      ? `<span class="review-section-heading">${escapeHtml(fieldMeta.section_heading)}</span>`
      : "";

    const isTextArea = fieldMeta.tag === "textarea" || (act.proposed_value && act.proposed_value.length > 50);
    const inputHtml = isTextArea
      ? `<textarea class="review-input review-textarea" placeholder="Proposed value (edit here)">${escapeHtml(act.proposed_value || "")}</textarea>`
      : `<input type="text" class="review-input" value="${escapeHtml(act.proposed_value || "")}" placeholder="Proposed value (edit here)">`;

    itemEl.innerHTML = `
      <!-- 1. Question Title & Section Heading -->
      <div class="review-field-meta">
        ${sectionHeadingText}
        <div class="review-field-question">${escapeHtml(questionText)}</div>
      </div>

      <!-- 2. Badges & Source Row -->
      <div class="review-badges-row">
        ${factBadgeHtml}
        ${confidenceHtml}
        ${sourceHtml}
      </div>

      <!-- 3. Full-width Edit Control -->
      <div class="review-edit-row">
        ${inputHtml}
      </div>

      <!-- 4. Approve / Skip Action Row -->
      <div class="review-action-row">
        <label class="approve-toggle" for="chk_${escapeHtml(act.field_id)}">
          <input type="checkbox" class="approve-check" id="chk_${escapeHtml(act.field_id)}" ${act.isApproved ? "checked" : ""}>
          <span class="toggle-text">${act.isApproved ? "Approved to fill" : "Skip this field"}</span>
        </label>
        ${act.review_required ? '<span class="review-hint-tag">Review needed</span>' : ''}
      </div>

      <!-- 5. Correction Memory Option (shown when edited) -->
      <div class="correction-save-wrap" style="display: ${act.saveCorrection ? 'block' : 'none'};">
        <label class="save-corr-label">
          <input type="checkbox" class="save-corr-check" ${act.saveCorrection ? 'checked' : ''}>
          <span>Remember this correction for ${escapeHtml(currentDomain || "this site")}</span>
        </label>
      </div>
    `;

    const jump = document.createElement("button");
    jump.type = "button"; jump.className = "subtle-btn"; jump.textContent = "Show field on page";
    jump.addEventListener("click", async () => {
      try {
        if (currentTabId !== null) {
          const result = await AutofillClient.highlight(currentTabId, fieldMeta);
          if (!result?.success) throw new Error(result?.error || "Field unavailable");
        }
      } catch (error) { jump.textContent = error.message; }
    });
    itemEl.querySelector(".review-field-meta").append(jump);
    // Event listeners
    const inputField = itemEl.querySelector(".review-input");
    const corrWrap = itemEl.querySelector(".correction-save-wrap");
    const saveCorrCheck = itemEl.querySelector(".save-corr-check");
    const approveCheck = itemEl.querySelector(".approve-check");
    const toggleText = itemEl.querySelector(".toggle-text");

    inputField.addEventListener("input", (e) => {
      act.proposed_value = e.target.value;
      act.value = e.target.value;
      act.action = "fill";
      if (["checkbox", "radio"].includes(fieldMeta.type)) act.checked = null;
      act.isApproved = true;
      approveCheck.checked = true;
      toggleText.textContent = "Approved to fill";
      itemEl.className = "review-item approved";
      corrWrap.style.display = "block";
      updateFillButtonCount();
    });

    saveCorrCheck.addEventListener("change", (e) => {
      act.saveCorrection = e.target.checked;
    });

    approveCheck.addEventListener("change", (e) => {
      act.isApproved = e.target.checked;
      if (act.isApproved && AutofillMatching.ready(act, fieldMeta)) act.action = "fill";
      toggleText.textContent = act.isApproved ? "Approved to fill" : "Skip this field";
      itemEl.className = `review-item ${act.isApproved ? (act.review_required ? "needs-review" : "approved") : "skipped"}`;
      updateFillButtonCount();
    });

    reviewList.appendChild(itemEl);
  });
}

function updateFillButtonCount() {
  const readyActions = currentActions.filter(a => AutofillMatching.ready(a, currentScannedFields.find(f => f.field_id === a.field_id)));
  const pending = readyActions.filter(a => !a.isApproved).length;
  const banner = document.getElementById("readyBanner");
  banner.textContent = `${pending} field(s) have answers ready and need your confirmation before filling.`;
  banner.style.display = pending ? "block" : "none";
  document.getElementById("approveReadyBtn").disabled = !readyActions.length;
  if (currentTabId !== null && window.chrome?.tabs?.sendMessage) chrome.tabs.sendMessage(currentTabId, { action: "dock_status", ready: readyActions.length, total: currentScannedFields.length }, { frameId: 0 }).catch(() => {});

  const approvedFieldsCount = currentActions.filter(a => a.isApproved).length;
  const approvedDocsCount = currentDocProposals.filter(d => d.isApproved).length;
  const totalApproved = approvedFieldsCount + approvedDocsCount;

  fillApprovedText.textContent = `Fill Approved Fields (${totalApproved})`;
  fillApprovedBtn.disabled = totalApproved === 0;
}

// Filter Tab Clicks
filterTabs.forEach(tab => {
  tab.addEventListener("click", () => {
    filterTabs.forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentFilter = tab.dataset.filter;
    renderFilteredFields();
  });
});

document.getElementById("approveReadyBtn").addEventListener("click", () => {
  currentActions.forEach(act => {
    if (AutofillMatching.ready(act, currentScannedFields.find(f => f.field_id === act.field_id))) { act.isApproved = true; act.action = "fill"; }
  });
  renderFilteredFields(); updateFillButtonCount(); fillApprovedBtn.click();
});
document.getElementById("openDockBtn").addEventListener("click", async () => {
  try {
    const tab = await targetTab();
    const result = await chrome.runtime.sendMessage({ action: "open_dock", tabId: tab.id });
    if (result?.error) throw new Error(result.error);
    window.close();
  } catch (error) { statusEl.textContent = error.message; }
});
if (dockParams.has("dock")) {
  document.documentElement.classList.add("dock-view");
  document.body.classList.add("dock-view");
  document.getElementById("openDockBtn").hidden = true;
}
// Batch approval actions
approveAllVerifiedBtn.addEventListener("click", () => {
  currentActions.forEach(act => {
    if (act.is_verified_fact && !act.review_required && AutofillMatching.ready(act, currentScannedFields.find(f => f.field_id === act.field_id))) {
      act.isApproved = true;
    }
  });
  renderFilteredFields();
  updateFillButtonCount();
});

deselectAllBtn.addEventListener("click", () => {
  currentActions.forEach(act => {
    act.isApproved = false;
  });
  currentDocProposals.forEach(prop => {
    prop.isApproved = false;
  });
  renderFilteredFields();
  updateFillButtonCount();
});

// ---------------------------------------------------------------------------
// FILL APPROVED FIELDS ACTION
// ---------------------------------------------------------------------------

fillApprovedBtn.addEventListener("click", async () => {
  try {
    fillApprovedBtn.disabled = true;
    fillApprovedText.textContent = "Filling fields...";

    const approvedFields = currentActions.filter(a => a.isApproved);
    const approvedDocs = currentDocProposals.filter(d => d.isApproved);
    const allApprovedActions = [...approvedFields, ...approvedDocs];

    // 1. Save any user corrections to memory
    for (const act of approvedFields) {
      if (act.saveCorrection && act.proposed_value) {
        const fieldMeta = currentScannedFields.find(f => f.field_id === act.field_id);
        const signature = fieldMeta?.name || fieldMeta?.id || fieldMeta?.label || act.field_id;
        try {
          await fetch(CORRECTIONS_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              profileId: profileSelect.value,
              domain: currentDomain,
              fieldSignature: signature,
              fieldLabel: fieldMeta?.label || signature,
              correctionValue: act.proposed_value,
              action: "fill"
            })
          });
          AutofillClient.cache?.clear();
        } catch (corrErr) {
          console.warn("Failed to persist correction:", corrErr);
        }
      }
    }

    let filledCount = 0;
    let diagnostics = [];

    // 2. Dispatch autofill command to content script if in extension context
    if (window.chrome?.tabs?.sendMessage && currentTabId !== null) {
      const allowFileUpload = approvedDocs.length > 0;
      const response = await AutofillClient.fill(currentTabId, allApprovedActions, currentScannedFields, allowFileUpload);
      filledCount = response?.count || 0;
      diagnostics = response?.diagnostics || [];
    } else {
      filledCount = allApprovedActions.length;
      diagnostics = allApprovedActions.map(a => ({
        field_id: a.field_id,
        status: "success",
        value: a.proposed_value
      }));
    }

    // 3. Save multi-step progress in local storage
    const selectedProfileId = profileSelect.value;
    const sessionKey = `session_${currentDomain}_${selectedProfileId}`;
    const previousStored = await safeStorage.get([sessionKey]);
    const previousHistory = previousStored?.[sessionKey]?.filledHistory || [];

    const newHistory = [
      ...previousHistory,
      ...approvedFields.filter(a => diagnostics.some(d => d.field_id === a.field_id && d.status === "success")).map(a => ({ field_id: a.field_id, value: a.proposed_value, date: Date.now() }))
    ];

    await safeStorage.set({
      [sessionKey]: {
        domain: currentDomain,
        profileId: selectedProfileId,
        updatedAt: Date.now(),
        filledHistory: newHistory
      }
    });

    if (filledCount > 0) {
      try {
        const appKey = "applied_jobs_history";
        const storedApps = await safeStorage.get([appKey]);
        const list = Array.isArray(storedApps?.[appKey]) ? storedApps[appKey] : [];
        const entry = {
          id: Date.now(),
          domain: currentDomain,
          title: currentPageContext?.job_title || "Job Application",
          company: currentPageContext?.company_name || currentDomain,
          profileId: selectedProfileId,
          fieldsFilled: filledCount,
          date: new Date().toLocaleDateString()
        };
        const updated = [entry, ...list.filter(item => item.domain !== currentDomain || Date.now() - item.id > 3600000)].slice(0, 50);
        await safeStorage.set({ [appKey]: updated });
        updateAppsBadge();

        // Also log directly to Flask backend
        fetch(`${BACKEND_BASE}/api/autofill/log-application`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(entry)
        }).catch(() => {});
      } catch {}
    }

    // 4. Check for any failures or skipped diagnostics
    const failures = diagnostics.filter(d => d.status === "failed");
    if (failures.length > 0) {
      renderDiagnostics(diagnostics, filledCount);
      showView("diagnostics");
    } else {
      statusEl.textContent = `Autofill complete! Filled ${filledCount} field(s).`;
      showView("setup");
      checkMultiStepSession(selectedProfileId);
    }

  } catch (err) {
    statusEl.textContent = `Autofill error: ${err.message}`;
    showView("setup");
  } finally {
    fillApprovedBtn.disabled = false;
    updateFillButtonCount();
  }
});

// ---------------------------------------------------------------------------
// FAILURE DIAGNOSTICS VIEW
// ---------------------------------------------------------------------------

function renderDiagnostics(diagnostics, filledCount) {
  const failedItems = diagnostics.filter(d => d.status === "failed");

  diagnosticsSummary.innerHTML = `
    <span>⚡ Filled: <strong>${filledCount}</strong> field(s).</span>
    <span>⚠️ Attention: <strong>${failedItems.length}</strong> field(s) rejected.</span>
  `;

  diagnosticsList.innerHTML = "";
  diagnostics.forEach(diag => {
    const fieldMeta = currentScannedFields.find(f => f.field_id === diag.field_id) || {};
    const row = document.createElement("div");
    row.className = `diag-row ${diag.status}`;

    const label = fieldMeta.label || fieldMeta.name || diag.field_id;
    let statusText = "Success";
    if (diag.status === "failed") statusText = `Failed: ${diag.reason || "Validation rejected"}`;
    if (diag.status === "skipped") statusText = `Skipped: ${diag.reason || "Manual review"}`;

    row.innerHTML = `
      <div style="display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1;">
        <span style="font-weight: 600; color: #f8fafc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(label)}</span>
        <span class="diag-reason">${escapeHtml(statusText)}</span>
      </div>
      ${diag.status === "failed" ? '<button class="pill-btn retry-btn" type="button">Edit</button>' : '<span style="color: #34d399;">✓</span>'}
    `;

    if (diag.status === "failed") {
      row.querySelector(".retry-btn").addEventListener("click", () => {
        showView("review");
      });
    }

    diagnosticsList.appendChild(row);
  });
}

// ---------------------------------------------------------------------------
// CORRECTION MEMORY MODAL
// ---------------------------------------------------------------------------

async function openCorrectionsModal() {
  const profileId = profileSelect.value;
  try {
    const res = await fetch(`${CORRECTIONS_URL}?profileId=${encodeURIComponent(profileId)}&domain=${encodeURIComponent(currentDomain)}`);
    const data = await res.json();
    const corrections = data.corrections || [];

    correctionsList.innerHTML = "";
    if (corrections.length === 0) {
      correctionsList.innerHTML = `<div class="doc-empty-state">No saved corrections for ${escapeHtml(currentDomain || "this site")} yet.</div>`;
    } else {
      corrections.forEach(corr => {
        const item = document.createElement("div");
        item.className = "corr-item";
        item.innerHTML = `
          <div class="corr-details">
            <span class="corr-label">${escapeHtml(corr.fieldLabel || corr.fieldSignature)}</span>
            <span class="corr-val">${escapeHtml(corr.correctionValue)}</span>
            <span class="corr-meta">${escapeHtml(corr.domain)} • ${escapeHtml(corr.profileId)}</span>
          </div>
          <button class="icon-btn del-corr-btn" type="button" title="Delete correction">✕</button>
        `;

        item.querySelector(".del-corr-btn").addEventListener("click", async () => {
          await fetch(`${CORRECTIONS_URL}/${corr.id}`, { method: "DELETE" });
          openCorrectionsModal();
          checkCorrectionsBadge(profileId);
        });

        correctionsList.appendChild(item);
      });
    }

    correctionsModal.style.display = "flex";
  } catch (err) {
    console.error("Error loading corrections:", err);
  }
}

openCorrectionsBtn.addEventListener("click", () => {
  openCorrectionsModal();
});

closeCorrectionsBtn.addEventListener("click", () => {
  correctionsModal.style.display = "none";
});

closeCorrectionsBtn2.addEventListener("click", () => {
  correctionsModal.style.display = "none";
});

clearAllCorrectionsBtn.addEventListener("click", async () => {
  const profileId = profileSelect.value;
  try {
    await fetch(`${CORRECTIONS_URL}?profileId=${encodeURIComponent(profileId)}&domain=${encodeURIComponent(currentDomain)}`, {
      method: "DELETE"
    });
    openCorrectionsModal();
    checkCorrectionsBadge(profileId);
  } catch (err) {
    console.error("Error clearing corrections:", err);
  }
});

// ---------------------------------------------------------------------------
// APPLICATION HISTORY MODAL & EXPORT
// ---------------------------------------------------------------------------

async function updateAppsBadge() {
  const appKey = "applied_jobs_history";
  const storedApps = await safeStorage.get([appKey]);
  const list = Array.isArray(storedApps?.[appKey]) ? storedApps[appKey] : [];
  if (appsBadge) {
    if (list.length > 0) {
      appsBadge.textContent = list.length;
      appsBadge.style.display = "inline-flex";
    } else {
      appsBadge.style.display = "none";
    }
  }
}

async function openAppsModal() {
  const appKey = "applied_jobs_history";
  const storedApps = await safeStorage.get([appKey]);
  const list = Array.isArray(storedApps?.[appKey]) ? storedApps[appKey] : [];
  if (!appsList) return;
  appsList.innerHTML = "";
  if (list.length === 0) {
    appsList.innerHTML = '<div class="empty-state">No recorded applications yet.</div>';
  } else {
    list.forEach(app => {
      const item = document.createElement("div");
      item.className = "corr-item";
      item.innerHTML = `
        <div class="corr-details">
          <span class="corr-label">${escapeHtml(app.title || "Position")} • ${escapeHtml(app.company || "Company")}</span>
          <span class="corr-val">⚡ ${app.fieldsFilled} fields filled</span>
          <span class="corr-meta">${escapeHtml(app.domain)} • ${escapeHtml(app.date)}</span>
        </div>
      `;
      appsList.appendChild(item);
    });
  }
  if (appsModal) appsModal.style.display = "flex";
}

async function exportAppsCSV() {
  const appKey = "applied_jobs_history";
  const storedApps = await safeStorage.get([appKey]);
  const list = Array.isArray(storedApps?.[appKey]) ? storedApps[appKey] : [];
  if (!list.length) return;
  const header = ["Date", "Company", "Title", "Domain", "Fields Filled", "Candidate Profile"];
  const rows = list.map(a => [
    `"${a.date}"`,
    `"${(a.company || "").replace(/"/g, '""')}"`,
    `"${(a.title || "").replace(/"/g, '""')}"`,
    `"${a.domain}"`,
    a.fieldsFilled,
    `"${a.profileId}"`
  ]);
  const csvContent = "data:text/csv;charset=utf-8," + [header.join(","), ...rows.map(e => e.join(","))].join("\n");
  const encodedUri = encodeURI(csvContent);
  const link = document.createElement("a");
  link.setAttribute("href", encodedUri);
  link.setAttribute("download", `job_applications_${new Date().toISOString().slice(0, 10)}.csv`);
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function clearAppsHistory() {
  await safeStorage.remove(["applied_jobs_history"]);
  updateAppsBadge();
  openAppsModal();
}

if (openAppsBtn) openAppsBtn.addEventListener("click", openAppsModal);
if (closeAppsBtn) closeAppsBtn.addEventListener("click", () => { appsModal.style.display = "none"; });
if (closeAppsBtn2) closeAppsBtn2.addEventListener("click", () => { appsModal.style.display = "none"; });
if (clearAppsBtn) clearAppsBtn.addEventListener("click", clearAppsHistory);
if (exportAppsBtn) exportAppsBtn.addEventListener("click", exportAppsCSV);

// Dock & Side Panel integration
const openDockBtn = document.getElementById("openDockBtn");
if (openDockBtn) {
  openDockBtn.addEventListener("click", async () => {
    try {
      const tab = await targetTab();
      if (tab?.id) {
        await chrome.runtime.sendMessage({ action: "open_dock", tabId: tab.id });
        window.close();
      }
    } catch (err) {
      statusEl.textContent = `Could not open dock: ${err.message}`;
    }
  });
}

const openSidePanelBtn = document.getElementById("openSidePanelBtn");
if (openSidePanelBtn) {
  openSidePanelBtn.addEventListener("click", async () => {
    try {
      const tab = await targetTab();
      if (tab?.id && window.chrome?.sidePanel?.open) {
        await chrome.sidePanel.open({ tabId: tab.id });
        window.close();
      } else {
        if (openDockBtn) openDockBtn.click();
      }
    } catch (e) {
      if (openDockBtn) openDockBtn.click();
    }
  });
}

// Adapt view when running in in-page dock or iframe
if (window.self !== window.top || dockParams.has("dock")) {
  document.body.classList.add("is-dock");
  if (openDockBtn) openDockBtn.style.display = "none";
  if (openSidePanelBtn) openSidePanelBtn.style.display = "none";
}

// Dynamic form listener
if (window.chrome?.runtime?.onMessage) {
  chrome.runtime.onMessage.addListener((request, sender) => {
    if (request.action === "form_updated" && sender.tab?.id === currentTabId) {
      statusEl.textContent = "Form updated. Ready to re-scan.";
      document.getElementById("readyBanner").textContent = "New form step detected. Go back and scan this step before filling.";
      document.getElementById("readyBanner").style.display = "block";
    }
  });
}

// Initialize on popup launch
(async () => {
  if (window.chrome?.tabs?.query) {
    try {
      const tab = await targetTab();
      if (tab?.url) {
        currentDomain = new URL(tab.url).hostname;
      }
    } catch {}
  }
  await loadProfiles();
  await updateAppsBadge();
  if (dockParams.has("field") && profileSelect.value) scanBtn.click();
})();
