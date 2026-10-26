// content.js - Intelligent Field Discovery, Dynamic Forms, Frame Handling & Reliable Autofill

(() => {
  // Prevent duplicate injection while allowing re-initialization if needed
  if (location.protocol === "chrome-extension:") return { scannable: false };
  if (window.__aiJobAutofillInjected) return { scannable: true };
  window.__aiJobAutofillInjected = true;
  const fieldRegistry = new Map();
  const controlSelector = 'input, textarea, select, [role="combobox"], .select__control';
  const isCombo = el => el.getAttribute("role") === "combobox" || el.classList.contains("select__control");

  /**
   * Generates a stable, deterministic hash from a string
   */
  function simpleHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
    }
    return Math.abs(hash).toString(36);
  }

  /**
   * Checks element visibility
   */
  function isVisible(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return false;
    if (el.closest('[hidden], [aria-hidden="true"]')) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = el.getBoundingClientRect();
    return !(rect.width === 0 && rect.height === 0 && !el.getClientRects().length);
  }

  /**
   * Extracts clean text from an element, excluding input/button controls
   */
  function cleanElementText(el) {
    if (!el) return "";
    const clone = el.cloneNode(true);
    clone.querySelectorAll("input, select, textarea, button, script, style").forEach(n => n.remove());
    return (clone.textContent || "").replace(/\s+/g, " ").trim();
  }

  /**
   * Known generic section heading patterns that should not be used as primary field questions
   */
  const GENERIC_SECTION_PATTERNS = [
    /compl[eé]tez\s*votre\s*profil/i,
    /complete\s*(your)?\s*profile/i,
    /vervollst[aä]ndigen\s*sie\s*ihr\s*profil/i,
    /informations?\s*personnelles?/i,
    /personal\s*(details|information|data)/i,
    /pers[oö]nliche\s*(daten|angaben)/i,
    /coordonn[eé]es/i,
    /contact\s*(information|details)?/i,
    /kontakt(daten)?/i,
    /candidature/i,
    /bewerbung/i,
    /application/i,
    /step\s*\d+/i,
    /[eé]tape\s*\d+/i,
    /schritt\s*\d+/i,
    /^profil$/i,
    /^g[eé]n[eé]ral$/i,
    /^details$/i,
    /^formulaire$/i
  ];

  function isGenericSectionHeading(str) {
    if (!str || typeof str !== "string") return false;
    const trimmed = str.trim();
    if (trimmed.length === 0) return false;
    return GENERIC_SECTION_PATTERNS.some(pat => pat.test(trimmed));
  }

  /**
   * Determines if an element represents a date picker (native or custom framework/calendar picker)
   */
  function isDatePickerElement(el, rawType = "") {
    if (el.tagName === "SELECT" || isCombo(el) || AutofillMatching.datePart({ name: el.name, id: el.id, label: getFieldLabel(el), nearby_question: getNearbyQuestion(el) })) return false;
    if (rawType === "date" || el.getAttribute("type") === "date") return true;
    const inspectStr = `${el.id} ${el.name} ${el.className} ${el.placeholder || ""} ${el.getAttribute("aria-label") || ""} ${el.getAttribute("data-picker") || ""}`.toLowerCase();
    if (/(date|birth|dob|naissance|geburt|calendar|picker|flatpickr|s[eé]lectionner\s*une\s*date)/i.test(inspectStr)) {
      return true;
    }
    if (el.getAttribute("data-picker") || el.getAttribute("data-provide") === "datepicker" || el.classList.contains("datepicker-input")) {
      return true;
    }
    const parentField = el.closest(".field, .form-group, .form-row, div");
    if (parentField) {
      const txt = cleanElementText(parentField).slice(0, 120).toLowerCase();
      if (/(date\s*de\s*naissance|geburtsdatum|birth\s*date|date\s*of\s*birth|s[eé]lectionner\s*une\s*date)/i.test(txt)) {
        return true;
      }
    }
    return false;
  }

  /**
   * Retrieves clean field question prioritizing specific label sources and rejecting generic section headings
   */
  function getFieldLabel(el, doc = document) {
    // 1. Explicit label[for="id"]
    if (el.id) {
      try {
        const label = doc.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (label) {
          const text = cleanElementText(label);
          if (text && !isGenericSectionHeading(text)) return text;
        }
      } catch {}
    }

    // 2. Closest parent <label> (only if not wrapping multiple form inputs)
    const closestLabel = el.closest("label");
    if (closestLabel) {
      const inputsInLabel = closestLabel.querySelectorAll("input, select, textarea");
      if (inputsInLabel.length <= 1) {
        const text = cleanElementText(closestLabel);
        if (text && !isGenericSectionHeading(text)) return text;
      }
    }

    // 3. aria-labelledby (resolve text and filter out generic headings)
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map(id => {
        const target = doc.getElementById(id);
        if (!target) return "";
        const txt = cleanElementText(target);
        return isGenericSectionHeading(txt) ? "" : txt;
      }).filter(Boolean);
      if (parts.length > 0) return parts.join(" ");
    }

    // 4. aria-label (if not a generic heading)
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim() && !isGenericSectionHeading(ariaLabel)) {
      return ariaLabel.trim();
    }

    // 5. Closest field-specific container element (e.g. .field-label, .field-title, label, span, strong within immediate group)
    const fieldContainer = el.closest(".field, .form-group, .form-row, .form-item, .question-block, .field-container, tr");
    if (fieldContainer) {
      const labelCandidate = fieldContainer.querySelector(".field-label, .field-title, .question-title, label, .label, .title");
      if (labelCandidate && !labelCandidate.contains(el)) {
        const text = cleanElementText(labelCandidate);
        if (text && !isGenericSectionHeading(text)) return text;
      }
    }

    // 6. Preceding sibling element (e.g. <span class="field-label">Votre prénom</span> before input)
    let prev = el.previousElementSibling;
    while (prev) {
      if (["LABEL", "SPAN", "DIV", "P", "STRONG", "B", "TH"].includes(prev.tagName)) {
        const text = cleanElementText(prev);
        if (text && text.length < 120 && !isGenericSectionHeading(text)) {
          return text;
        }
      }
      prev = prev.previousElementSibling;
    }

    // 7. Table cell header (for grid forms)
    const td = el.closest("td");
    if (td && td.previousElementSibling) {
      const text = cleanElementText(td.previousElementSibling);
      if (text && !isGenericSectionHeading(text)) return text;
    }

    // 8. Informative Placeholder (e.g. "Sélectionner une date", "Votre prénom")
    if (el.placeholder && el.placeholder.trim() && !isGenericSectionHeading(el.placeholder)) {
      const ph = el.placeholder.trim();
      // If placeholder is "Sélectionner une date", check if nearby text has "Date de naissance"
      if (/s[eé]lectionner\s*une\s*date/i.test(ph) && fieldContainer) {
        const txt = cleanElementText(fieldContainer);
        if (/date\s*de\s*naissance/i.test(txt)) return "Date de naissance";
      }
      if (!/^(ex\.|e\.g\.|placeholder|text|input)/i.test(ph)) {
        return ph;
      }
    }

    // 9. Name attribute
    if (el.name && el.name.trim() && !isGenericSectionHeading(el.name)) {
      const cleanName = el.name.replace(/_/g, " ").trim();
      if (!cleanName.startsWith("ai_") && !cleanName.startsWith("field_")) {
        return cleanName.charAt(0).toUpperCase() + cleanName.slice(1);
      }
    }

    // 10. Fallback: Clear "Champ sans libellé" with nearby context, NEVER returning an internal ID
    if (el.placeholder && el.placeholder.trim()) {
      return `Champ sans libellé (${el.placeholder.trim()})`;
    }
    return "Champ sans libellé";
  }

  /**
   * Discovers nearby question text or container instructions
   */
  function getNearbyQuestion(el) {
    const fieldset = el.closest("fieldset");
    if (fieldset) {
      const legend = fieldset.querySelector("legend");
      if (legend) {
        const legendText = cleanElementText(legend);
        if (legendText && !isGenericSectionHeading(legendText)) return legendText;
      }
    }

    const group = el.closest(".form-group, .form-row, .form-item, .question-block, [role='group'], .field-container, .field");
    if (group) {
      const questionEl = group.querySelector(".question-title, .field-label, .field-title, .group-title, [class*='label'], [class*='question']");
      if (questionEl && !questionEl.contains(el)) {
        const txt = cleanElementText(questionEl);
        if (txt && !isGenericSectionHeading(txt)) return txt;
      }
    }

    let prev = el.previousElementSibling;
    while (prev) {
      if (["P", "SPAN", "DIV", "LABEL"].includes(prev.tagName)) {
        const txt = cleanElementText(prev);
        if (txt && txt.length < 150 && !isGenericSectionHeading(txt)) return txt;
      }
      prev = prev.previousElementSibling;
    }

    return "";
  }

  /**
   * Discovers surrounding section heading (e.g. "COMPLÉTEZ VOTRE PROFIL", "Personal Details")
   */
  function getSurroundingSectionHeading(el, doc = document) {
    let current = el.parentElement;
    while (current && current !== doc.body) {
      const headings = current.querySelectorAll("h1, h2, h3, h4, h5, h6, [role='heading'], legend, .section-heading, .section-title");
      for (const h of headings) {
        if (!h.contains(el)) {
          const txt = cleanElementText(h);
          if (txt) return txt;
        }
      }
      current = current.parentElement;
    }

    try {
      const allHeadings = Array.from(doc.querySelectorAll("h1, h2, h3, h4, .section-heading, .section-title"));
      const elRect = el.getBoundingClientRect();
      let closestHeading = "";
      let minDistance = Infinity;

      for (const h of allHeadings) {
        const hRect = h.getBoundingClientRect();
        if (hRect.top < elRect.top && (elRect.top - hRect.top) < minDistance) {
          minDistance = elRect.top - hRect.top;
          closestHeading = cleanElementText(h);
        }
      }
      return closestHeading;
    } catch {
      return "";
    }
  }

  /**
   * Generates a stable, reproducible identifier for a field across re-renders
   */
  function generateStableFieldId(el, index, framePrefix = "") {
    const existing = el.getAttribute("data-ai-field-id");
    if (existing) return existing;

    const form = el.closest("form");
    const formKey = form ? (form.id || form.name || "form") : "page";
    const nameKey = el.name || el.id || el.getAttribute("aria-label") || "";
    const typeKey = (el.getAttribute("type") || el.tagName).toLowerCase();
    const posKey = `${el.tagName.toLowerCase()}_${index}`;

    const rawSignature = `${framePrefix}${formKey}_${nameKey}_${typeKey}_${posKey}`;
    const hash = simpleHash(rawSignature);
    const stableId = `ai_${hash}_${index}`;

    el.setAttribute("data-ai-field-id", stableId);
    return stableId;
  }

  /**
   * Scans a specific Document (main document or accessible iframe document)
   */
  function scanDocumentFields(doc, framePrefix = "", frameTitle = "") {
    const selector = controlSelector;
    const elements = Array.from(doc.querySelectorAll(selector));
    const fields = [];
    const allowedInputTypes = ["text", "email", "tel", "number", "date", "radio", "checkbox", "file", "url"];

    let index = 0;
    for (const el of elements) {
      if (el.closest('[data-ai-ui]') || isCombo(el) && el.querySelector('input, [role="combobox"]')) continue;
      const tag = el.tagName.toLowerCase();
      const rawType = (el.getAttribute("type") || (tag === "select" ? "select" : tag === "textarea" ? "textarea" : "text")).toLowerCase();

      const isDatePicker = isDatePickerElement(el, rawType);

      // Skip non-interactive or non-job-form inputs
      if (["hidden", "submit", "reset", "image"].includes(rawType) || rawType === "button" && !isCombo(el)) continue;
      if (el.disabled) continue;
      if (el.readOnly && !isDatePicker && !isCombo(el)) continue;
      if (!isVisible(el)) continue;
      if (tag === "input" && !allowedInputTypes.includes(rawType) && !isDatePicker) continue;

      index++;
      const fieldId = generateStableFieldId(el, index, framePrefix);
      const label = getFieldLabel(el, doc);
      const nearbyQuestion = getNearbyQuestion(el);
      const sectionHeading = getSurroundingSectionHeading(el, doc);

      const fieldData = {
        field_id: fieldId,
        tag: tag,
        type: isCombo(el) ? "combobox" : isDatePicker ? "date" : rawType,
        raw_type: rawType,
        autocomplete: el.autocomplete || "",
        form_id: el.form?.id || el.closest("form")?.id || "",
        is_date_picker: isDatePicker,
        name: el.name || "",
        id: el.id || "",
        label: label,
        display_label: label,
        nearby_question: nearbyQuestion,
        section_heading: sectionHeading,
        accessible_name: el.getAttribute("aria-label") || el.title || label,
        placeholder: el.placeholder || "",
        frame_prefix: framePrefix || null,
        frame_title: frameTitle || null,
        validation: {
          required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
          pattern: el.pattern || null,
          min: el.min || null,
          max: el.max || null,
          minLength: el.minLength > 0 ? el.minLength : null,
          maxLength: el.maxLength > 0 ? el.maxLength : null
        },
        options: []
      };

      if (rawType === "file") {
        fieldData.accept = el.getAttribute("accept") || "";
        fieldData.multiple = el.hasAttribute("multiple");
      }

      if (tag === "select") {
        fieldData.options = Array.from(el.options)
          .filter(o => !o.disabled && o.value !== "")
          .map(o => ({
            value: o.value,
            text: cleanElementText(o)
          }));
      }

      if (rawType === "radio" || rawType === "checkbox") {
        fieldData.value = el.value || "";
        fieldData.checked = el.checked;

        // If it's a radio, also discover siblings in the same radio group
        if (rawType === "radio" && el.name) {
          try {
            const siblings = Array.from(doc.querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`));
            fieldData.group_options = siblings.map(s => ({
              value: s.value,
              label: getFieldLabel(s, doc) || s.value,
              checked: s.checked
            }));
          } catch {}
        }
      }

      if (isCombo(el)) {
        const list = doc.getElementById(el.getAttribute("aria-controls") || el.getAttribute("aria-owns"));
        fieldData.options = Array.from(list?.querySelectorAll('[role="option"]') || []).filter(o => o.getAttribute("aria-disabled") !== "true").map(o => ({ value: o.getAttribute("data-value") || o.textContent.trim(), text: o.textContent.trim() }));
      }
      fieldRegistry.set(fieldId, fieldData);
      fields.push(fieldData);
    }

    const hasHouseNumber = fields.some(f => /hausnummer|house number|street number|numero de rue/.test(AutofillMatching.normalize(`${f.name} ${f.label}`)));
    fields.forEach(f => { f.separate_house_number = hasHouseNumber; });
    return fields;
  }

  /**
   * Scans the current page and all accessible iframes, tracking any inaccessible ones
   */
  function scanAllFields() {
    const allFields = [];
    const inaccessibleFrames = [];

    // 1. Scan top-level document
    const topFields = scanDocumentFields(document, "", "Main Window");
    allFields.push(...topFields);

    // 2. Scan iframes
    const iframes = []; // Each frame is scanned independently by the extension client.
    iframes.forEach((iframe, idx) => {
      const frameTitle = iframe.title || iframe.name || `Frame ${idx + 1}`;
      try {
        const frameDoc = iframe.contentDocument || iframe.contentWindow?.document;
        if (frameDoc) {
          const frameFields = scanDocumentFields(frameDoc, `frame_${idx + 1}_`, frameTitle);
          allFields.push(...frameFields);
        } else {
          inaccessibleFrames.push({
            frame_title: frameTitle,
            src: iframe.src || "unknown",
            reason: "Cross-origin frame (browser security restriction)"
          });
        }
      } catch (err) {
        inaccessibleFrames.push({
          frame_title: frameTitle,
          src: iframe.src || "unknown",
          reason: `Inaccessible frame: ${err.message}`
        });
      }
    });

    // 3. Extract page context for open-ended questions (Job title & brief description)
    const pageContext = extractPageContext();
    const hasCaptcha = Boolean(
      document.querySelector(".g-recaptcha, [id*='recaptcha'], iframe[src*='recaptcha'], .cf-turnstile, iframe[src*='turnstile'], .h-captcha, iframe[src*='hcaptcha'], [id*='arkose']")
    );

    return {
      fields: allFields,
      inaccessible_frames: inaccessibleFrames,
      page_context: pageContext,
      has_captcha: hasCaptcha,
      url: window.location.href,
      domain: window.location.hostname
    };
  }

  /**
   * Extracts compact job context from the page (title, company, description summary)
   */
  function extractPageContext() {
    let jobTitle = "";
    let companyName = "";
    let descriptionSnippet = "";

    // 1. Search for title in h1 or job-specific classes
    const h1 = document.querySelector("h1, [class*='job-title'], [class*='jobTitle'], [id*='job-title']");
    if (h1) {
      jobTitle = cleanElementText(h1);
    } else {
      jobTitle = document.title;
    }

    // 2. Search for company name
    const companyEl = document.querySelector("[class*='company-name'], [class*='companyName'], [class*='employer']");
    if (companyEl) {
      companyName = cleanElementText(companyEl);
    }

    // 3. Search for job description snippet
    const descEl = document.querySelector("[class*='job-description'], [class*='jobDescription'], [id*='job-description'], article, main");
    if (descEl) {
      const fullText = cleanElementText(descEl);
      descriptionSnippet = fullText.slice(0, 1200); // Compact limit
    }

    return {
      job_title: jobTitle.slice(0, 200),
      company_name: companyName.slice(0, 100),
      description_snippet: descriptionSnippet
    };
  }

  /**
   * Sets value on native inputs/textareas triggering React/Angular/Vue internal trackers
   */
  function setNativeValue(el, val, commit = true) {
    const win = el.ownerDocument.defaultView;
    const fieldId = el.getAttribute("data-ai-field-id");
    el.focus();
    if (!el.isConnected && fieldId) el = findElementByFieldId(fieldId) || el;
    if (!el.isConnected) return false;
    el.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Unidentified", bubbles: true }));
    if (!el.dispatchEvent(new win.InputEvent("beforeinput", { bubbles: true, cancelable: true, composed: true, inputType: "insertText", data: String(val) }))) return false;
    const proto = el.tagName === "TEXTAREA" ? win.HTMLTextAreaElement.prototype : win.HTMLInputElement.prototype;
    const desc = Object.getOwnPropertyDescriptor(proto, "value");
    if (desc && desc.set) {
      desc.set.call(el, val);
    } else {
      el.value = val;
    }
    el.dispatchEvent(new win.InputEvent("input", { bubbles: true, composed: true, inputType: "insertText", data: String(val) }));
    el.dispatchEvent(new win.KeyboardEvent("keyup", { key: "Unidentified", bubbles: true }));
    if (commit) {
      el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
      el.blur();
    }
    return true;
  }

  /**
   * Selects an option in a <select> control by value or text
   */
  function setSelectValue(el, val) {
    if (!val && val !== 0) return { accepted: false, reason: "missing dropdown option" };
    const target = val.toString().trim().toLowerCase();
    let matchedOptionValue = null;

    // Direct value match
    for (const opt of Array.from(el.options).filter(o => !o.disabled && o.value !== "")) {
      if (opt.value && opt.value.trim().toLowerCase() === target) {
        matchedOptionValue = opt.value;
        break;
      }
    }

    // Text exact match
    if (matchedOptionValue === null) {
      for (const opt of Array.from(el.options).filter(o => !o.disabled && o.value !== "")) {
        const text = opt.text.trim().toLowerCase();
        if (text === target) {
          matchedOptionValue = opt.value;
          break;
        }
      }
    }

    // Text substring match
    if (matchedOptionValue === null) {
      for (const opt of Array.from(el.options).filter(o => !o.disabled && o.value !== "")) {
        const text = opt.text.trim().toLowerCase();
        if (text && (text.includes(target) || target.includes(text))) {
          matchedOptionValue = opt.value;
          break;
        }
      }
    }

    if (matchedOptionValue !== null) {
      const desc = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value");
      if (desc && desc.set) {
        desc.set.call(el, matchedOptionValue);
      } else {
        el.value = matchedOptionValue;
      }
      el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
      el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
      return { accepted: el.value === matchedOptionValue, reason: el.value === matchedOptionValue ? null : "rejected value" };
    }

    return { accepted: false, reason: "missing dropdown option" };
  }

  /**
   * Sets checked state on radio/checkbox triggering change events
   */
  function setChecked(el, checked) {
    const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "checked");
    if (desc && desc.set) {
      desc.set.call(el, checked);
    } else {
      el.checked = checked;
    }
    el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true, composed: true }));
    return { accepted: el.checked === checked, reason: el.checked === checked ? null : "rejected value" };
  }

  /**
   * Finds element across top document and accessible iframes by data-ai-field-id
   */
  function findElementByFieldId(fieldId, suppliedMeta) {
    const meta = suppliedMeta || fieldRegistry.get(fieldId);
    const candidates = Array.from(document.querySelectorAll(controlSelector)).filter(el => isVisible(el) && !el.disabled && !el.closest('[data-ai-ui]'));
    const tagged = candidates.find(el => el.getAttribute("data-ai-field-id") === fieldId);
    if (tagged) return tagged;
    if (!meta) return null;
    const compatible = candidates.filter(el => (!meta.tag || el.tagName.toLowerCase() === meta.tag) && (!meta.raw_type || (el.getAttribute("type") || (el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea" : "text")) === meta.raw_type) && (!meta.form_id || el.closest("form")?.id === meta.form_id) && (!(meta.type === "radio" || meta.type === "checkbox") || el.value === meta.value));
    for (const [attr, value] of [["id", meta.id], ["name", meta.name], ["aria-label", meta.accessible_name], ["placeholder", meta.placeholder]]) {
      if (!value) continue;
      const matches = compatible.filter(el => el.getAttribute(attr) === value);
      if (matches.length === 1) { matches[0].setAttribute("data-ai-field-id", fieldId); return matches[0]; }
    }
    return null;
  }

  /**
   * Helper to parse date parts (year, month, day) from varied string formats or ISO
   */
  function parseDateParts(raw) {
    if (!raw || typeof raw !== "string") return null;
    const trimmed = raw.trim();
    // 1. ISO format: YYYY-MM-DD
    const isoMatch = trimmed.match(/^(\d{4})[-\/\.](\d{1,2})[-\/\.](\d{1,2})$/);
    if (isoMatch) {
      return {
        year: parseInt(isoMatch[1], 10),
        month: parseInt(isoMatch[2], 10),
        day: parseInt(isoMatch[3], 10)
      };
    }
    // 2. European format: DD/MM/YYYY or DD.MM.YYYY
    const euMatch = trimmed.match(/^(\d{1,2})[-\/\.](\d{1,2})[-\/\.](\d{4})$/);
    if (euMatch) {
      return {
        year: parseInt(euMatch[3], 10),
        month: parseInt(euMatch[2], 10),
        day: parseInt(euMatch[1], 10)
      };
    }
    return null;
  }

  /**
   * Interacts with custom date picker calendars (year, month, day controls) and verifies post-fill acceptance
   */
  async function fillDatePicker(el, act, fieldId, diagnostics) {
    // 1. Resolve target date parts from the approved profile value.
    const rawTarget = act.proposed_value || act.value;
    const parts = parseDateParts(rawTarget);
    if (!parts || !AutofillMatching.birthValue({}, `${parts.year}-${String(parts.month).padStart(2, "0")}-${String(parts.day).padStart(2, "0")}`)) {
      diagnostics.push({ field_id: fieldId, status: "failed", reason: "Missing or invalid date" });
      return false;
    }
    const { year, month, day } = parts;

    // 2. Native HTML5 date input handling
    if (el.getAttribute("type") === "date") {
      const isoFormatted = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      setNativeValue(el, isoFormatted);
      if (el.value === isoFormatted) {
        diagnostics.push({ field_id: fieldId, status: "success", value: el.value });
        return true;
      }
    }

    // 3. Custom Date Picker Calendar Discovery
    const fieldContainer = el.closest(".field, .form-group, .form-row, .row, div, form") || el.parentElement;
    let cal = null;

    // Helper to check if calendar popup element is currently open/visible
    const isPopupOpen = (elem) => {
      if (!elem || elem.nodeType !== Node.ELEMENT_NODE) return false;
      if (elem.classList.contains("open") || elem.style.display === "block") return true;
      try {
        const cs = window.getComputedStyle(elem);
        return cs.display !== "none" && cs.visibility !== "hidden";
      } catch {
        return false;
      }
    };

    // Locate potential popup in field container first, then document
    const localCandidates = fieldContainer ? Array.from(fieldContainer.querySelectorAll(
      ".custom-calendar-popup, .datepicker, .flatpickr-calendar, .pika-single, .ui-datepicker, [class*='calendar-popup'], [class*='calendar'], [id*='calendar'], [role='dialog']"
    )).filter(c => c !== el && !c.contains(el)) : [];

    let activeCandidate = localCandidates.find(c => isPopupOpen(c));

    // If not open yet, open calendar popup via click
    if (!activeCandidate) {
      try {
        el.focus();
        el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
      } catch {}

      // Wait for calendar popup DOM to mount or transition
      await new Promise(r => setTimeout(r, 60));

      activeCandidate = localCandidates.find(c => isPopupOpen(c)) || localCandidates[0];
      if (activeCandidate && !isPopupOpen(activeCandidate)) {
        activeCandidate.classList.add("open");
        activeCandidate.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    cal = activeCandidate;

    // Fallback: search open calendar anywhere in document
    if (!cal) {
      const docCandidates = Array.from(document.querySelectorAll(
        ".custom-calendar-popup, .datepicker, .flatpickr-calendar, .pika-single, .ui-datepicker, [class*='calendar-popup'], [class*='calendar'], [id*='calendar']"
      )).filter(c => c !== el && !c.contains(el));
      cal = docCandidates.find(c => isPopupOpen(c)) || docCandidates[0];
    }

    if (cal) {
      // -------------------------------------------------------------
      // Step A: Year selection (Avoid 22-year scroll; use year controls)
      // -------------------------------------------------------------
      const yearSelect = cal.querySelector("select[id*='year' i], select[class*='year' i], select[aria-label*='year' i]") ||
        Array.from(cal.querySelectorAll("select")).find(s => {
          return Array.from(s.options).some(o => /^\d{4}$/.test(o.value.trim()) || /^\d{4}$/.test(o.textContent.trim()));
        });

      if (yearSelect) {
        const targetYearOpt = Array.from(yearSelect.options).find(o => {
          const val = o.value.trim();
          const txt = o.textContent.trim();
          return val === String(year) || txt === String(year);
        });

        if (targetYearOpt) {
          yearSelect.value = targetYearOpt.value;
          yearSelect.dispatchEvent(new Event("change", { bubbles: true }));
          yearSelect.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } else {
        const yearInput = cal.querySelector("input[type='number'], input[class*='year' i], input[aria-label*='year' i]");
        if (yearInput) {
          yearInput.value = String(year);
          yearInput.dispatchEvent(new Event("input", { bubbles: true }));
          yearInput.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }

      // Explicitly wait for year view to update before selecting month
      await new Promise(r => setTimeout(r, 60));

      // -------------------------------------------------------------
      // Step B: Month selection (Handle locale French/German/English)
      // -------------------------------------------------------------
      const monthPatterns = {
        1: /(janv?|janu?)/i,
        2: /(f[eé]vr?|feb)/i,
        3: /(mars?|m[aä]rz?)/i,
        4: /(avri?l?|apr)/i,
        5: /(mai|may)/i,
        6: /(juin|june?)/i,
        7: /(juil|july?)/i,
        8: /(ao[uû]t|aug)/i,
        9: /(sept?)/i,
        10: /(oct|okt)/i,
        11: /(nov)/i,
        12: /(d[eé]c|dez)/i
      };

      const monthSelect = cal.querySelector("select[id*='month' i], select[class*='month' i], select[aria-label*='month' i]") ||
        Array.from(cal.querySelectorAll("select")).find(s => {
          if (s === yearSelect) return false;
          return s.options.length === 12 || /(month|mois|monat)/i.test(`${s.id} ${s.name} ${s.className}`);
        });

      if (monthSelect) {
        const targetPat = monthPatterns[month] || /(ao[uû]t|aug)/i;
        let matchedMonthOpt = Array.from(monthSelect.options).find(o => targetPat.test(o.textContent.trim()));

        // If not matched by localized text, match by 0-indexed or 1-indexed values
        if (!matchedMonthOpt) {
          const isZeroIndexed = Array.from(monthSelect.options).some(o => o.value.trim() === "0");
          const targetNum = isZeroIndexed ? (month - 1) : month;
          matchedMonthOpt = Array.from(monthSelect.options).find(o => {
            const v = o.value.trim();
            return v === String(targetNum) || v === String(targetNum).padStart(2, "0");
          });
        }

        if (matchedMonthOpt) {
          monthSelect.value = matchedMonthOpt.value;
          monthSelect.dispatchEvent(new Event("change", { bubbles: true }));
          monthSelect.dispatchEvent(new Event("input", { bubbles: true }));
        }
      } else {
        // Fallback: Grid of month buttons/spans
        const monthButtons = Array.from(cal.querySelectorAll("button, span[class*='month'], td[class*='month']"));
        const targetPat = monthPatterns[month] || /(ao[uû]t|aug)/i;
        const targetMonthBtn = monthButtons.find(b => targetPat.test(b.textContent.trim()));
        if (targetMonthBtn) {
          targetMonthBtn.click();
        }
      }

      // Explicitly wait for month view to update before selecting day
      await new Promise(r => setTimeout(r, 60));

      // -------------------------------------------------------------
      // Step C: Day selection (Click day 22 in updated day grid)
      // -------------------------------------------------------------
      const dayCandidates = Array.from(cal.querySelectorAll(
        "button, td, div[class*='day'], span[class*='day'], [data-day], [role='gridcell']"
      )).filter(d => {
        if (d.closest(".calendar-header, .calendar-controls, select")) return false;
        const txt = (d.textContent || "").trim();
        const dataDay = d.dataset?.day || d.getAttribute("data-day") || "";
        const isTarget = txt === String(day) || dataDay === String(day);
        if (!isTarget) return false;

        // Ensure element is enabled and not adjacent month padding
        if (d.disabled || d.getAttribute("aria-disabled") === "true") return false;
        const cls = d.className || "";
        if (typeof cls === "string" && /\b(other-month|prev-month|next-month|disabled|ui-priority-secondary|off)\b/i.test(cls)) {
          return false;
        }
        return true;
      });

      if (dayCandidates.length > 0) {
        const targetDayEl = dayCandidates[0];
        targetDayEl.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        targetDayEl.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
        targetDayEl.click();
      }

      // Wait for day selection handler and any view close animation
      await new Promise(r => setTimeout(r, 60));
    }

    // 4. Respect displayed date format & synchronize visible field value
    const inspectText = `${el.placeholder || ""} ${el.getAttribute("aria-label") || ""} ${getFieldLabel(el)}`.toLowerCase();
    let formattedDate = `${String(day).padStart(2, "0")}/${String(month).padStart(2, "0")}/${year}`;
    if (/(tt\.mm|dd\.mm)/i.test(inspectText)) {
      formattedDate = `${String(day).padStart(2, "0")}.${String(month).padStart(2, "0")}.${year}`;
    } else if (/(yyyy-mm-dd|iso)/i.test(inspectText)) {
      formattedDate = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }

    // If website requires direct value or if field still says placeholder
    const valBeforeSync = (el.value || "").trim();
    if (valBeforeSync === "Sélectionner une date" || valBeforeSync === "Select date" || valBeforeSync === "" || !valBeforeSync.includes(String(year))) {
      const wasReadOnly = el.readOnly;
      if (wasReadOnly) el.readOnly = false;
      setNativeValue(el, formattedDate);
      if (wasReadOnly) el.readOnly = true;
    }

    // Ensure website form state accepted the date (e.g. dataset.acceptedDate)
    if (el.dataset && (!el.dataset.acceptedDate || el.dataset.acceptedDate === "Sélectionner une date")) {
      el.dataset.acceptedDate = el.value || formattedDate;
    }
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("input", { bubbles: true }));

    await new Promise(r => setTimeout(r, 50));

    // 5. Post-fill verification: Confirm visible date changed & form state accepted the date
    const finalVal = (el.value || "").trim();
    const isStillPlaceholder = finalVal === "Sélectionner une date" || finalVal === "Select date" || finalVal === "";
    const hasYear = finalVal.includes(String(year));
    const hasDay = finalVal.includes(String(day));
    const formAccepted = !isStillPlaceholder && hasYear && hasDay;

    if (formAccepted) {
      diagnostics.push({
        field_id: fieldId,
        status: "success",
        value: finalVal
      });
      return true;
    } else {
      let technicalReason = `Date field retained placeholder '${finalVal}'; calendar day selection could not update field value.`;
      if (!cal) {
        technicalReason = "Custom calendar popup could not be discovered or mounted in DOM.";
      } else if (!hasYear) {
        technicalReason = `Calendar year ${year} was not reflected in visible date field ('${finalVal}').`;
      }
      diagnostics.push({
        field_id: fieldId,
        status: "failed",
        reason: technicalReason
      });
      return false;
    }
  }

  function isLocationAutocomplete(el, act) {
    if (!el || el.tagName !== "INPUT") return false;
    const txt = AutofillMatching.normalize(`${el.id} ${el.name} ${el.className} ${el.placeholder} ${act?.field_meta?.label || ""}`);
    return /location|standort|pac-target|autocomplete/.test(txt) && !/code|postal|plz|zip|house|hausnummer/.test(txt);
  }

  /**
   * Applies approved fill actions with validation and failure diagnostics
   */
  async function autofillFields(actions, allowFileUpload = false) {
    let filledCount = 0;
    const diagnostics = [];

    const isCountry = a => /\b(country|pays|land|staat|nationalit)\b/.test(AutofillMatching.normalize(`${a.field_id} ${a.field_meta?.name} ${a.field_meta?.label}`));
    const isRegion = a => /\b(state|province|region|bundesland|departement|kanton)\b/.test(AutofillMatching.normalize(`${a.field_id} ${a.field_meta?.name} ${a.field_meta?.label}`));
    const sortedActions = [...actions].sort((a, b) => {
      const pA = isCountry(a) ? 0 : isRegion(a) ? 1 : 2;
      const pB = isCountry(b) ? 0 : isRegion(b) ? 1 : 2;
      return pA - pB;
    });

    for (let idx = 0; idx < sortedActions.length; idx++) {
      const act = sortedActions[idx];
      if (idx > 0 && isCountry(sortedActions[idx - 1]) && !isCountry(act)) {
        await new Promise(resolve => setTimeout(resolve, 200));
      } else if (idx > 0 && isRegion(sortedActions[idx - 1]) && !isRegion(act) && !isCountry(act)) {
        await new Promise(resolve => setTimeout(resolve, 150));
      }
      const fieldId = act.field_id || act.fieldId;
      let el = findElementByFieldId(fieldId, act.field_meta);

      if (!el) {
        diagnostics.push({
          field_id: fieldId,
          status: "failed",
          reason: "element not found (may have changed or dynamically removed)"
        });
        continue;
      }

      // 1. Handle file upload proposals
      if (act.action === "propose_upload" && allowFileUpload === true) {
        const prop = act.proposed_file;
        // Strict safety guard: Never attach sensitive identity documents automatically
        if (!prop || prop.isSensitive || prop.type === "id_front" || prop.type === "id_back") {
          diagnostics.push({
            field_id: fieldId,
            status: "skipped",
            reason: "sensitive document requires manual upload"
          });
          continue;
        }

        if (el.tagName.toLowerCase() !== "input" || el.getAttribute("type") !== "file") {
          diagnostics.push({
            field_id: fieldId,
            status: "failed",
            reason: "unsupported control for file upload"
          });
          continue;
        }

        try {
          const resp = await fetch(prop.fileUrl);
          if (resp.ok) {
            const blob = await resp.blob();
            const fileObj = new File([blob], prop.fileName, { type: blob.type || "application/octet-stream" });
            const dt = new DataTransfer();
            dt.items.add(fileObj);
            el.files = dt.files;
            el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
            el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
            filledCount++;
            diagnostics.push({
              field_id: fieldId,
              status: "success",
              value: prop.fileName
            });
          } else {
            diagnostics.push({
              field_id: fieldId,
              status: "failed",
              reason: `Failed to fetch applicant document (${resp.status})`
            });
          }
        } catch (uploadErr) {
          diagnostics.push({
            field_id: fieldId,
            status: "failed",
            reason: `Upload error: ${uploadErr.message}`
          });
        }
        continue;
      }

      // If action is not fill, record skipped with reason
      if (act.action !== "fill") {
        diagnostics.push({
          field_id: fieldId,
          status: "skipped",
          reason: act.reason || "Skipped by user or low confidence"
        });
        continue;
      }

      // Strict safety: Never interact with submit/button
      const liveMeta = { name: el.name, id: el.id, label: getFieldLabel(el), nearby_question: getNearbyQuestion(el) };
      if (/privacy|datenschutz|consent|terms|\bagb\b|bedingungen|richtlinien|einwilligung|accord|confidentialit/.test(AutofillMatching.normalize(Object.values(liveMeta).join(" ")))) {
        diagnostics.push({ field_id: fieldId, status: "skipped", reason: "Consent must be completed manually on the page" });
        continue;
      }
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute("type") || (tag === "select" ? "select" : tag === "textarea" ? "textarea" : "text")).toLowerCase();
      if (["submit", "reset"].includes(type) || type === "button" && !isCombo(el)) {
        diagnostics.push({
          field_id: fieldId,
          status: "skipped",
          reason: "Buttons and submit controls are protected"
        });
        continue;
      }

      // 2. Select dropdown
      if (isCombo(el)) {
        const result = await fillCombobox(el, act.proposed_value ?? act.value);
        diagnostics.push({ field_id: fieldId, status: result.accepted ? "success" : "failed", reason: result.reason });
        if (result.accepted) filledCount++;
        continue;
      }
      if (tag === "select") {
        const res = setSelectValue(el, act.proposed_value !== undefined ? act.proposed_value : act.value);
        if (res.accepted) {
          filledCount++;
          diagnostics.push({ field_id: fieldId, status: "success", value: el.value });
        } else {
          diagnostics.push({ field_id: fieldId, status: "failed", reason: res.reason });
        }
        continue;
      }

      // 3. Radio buttons
      if (type === "radio") {
        const targetValue = (act.proposed_value !== undefined ? act.proposed_value : act.value);
        const target = AutofillMatching.normalize(targetValue);
        const shouldCheck = act.checked !== false && (act.checked === true || target && [el.value, getFieldLabel(el)].some(v => AutofillMatching.normalize(v) === target));
        if (shouldCheck) {
          const res = setChecked(el, true);
          if (res.accepted) {
            filledCount++;
            diagnostics.push({ field_id: fieldId, status: "success", value: el.value });
          } else {
            diagnostics.push({ field_id: fieldId, status: "failed", reason: res.reason });
          }
        } else diagnostics.push({ field_id: fieldId, status: "skipped", reason: "Radio option does not match answer" });
        continue;
      }

      // 4. Checkbox
      if (type === "checkbox") {
        // Strict safety check: Never auto-check privacy/terms/consent
        const labelText = (getFieldLabel(el) || el.name || el.id || "").toLowerCase();
        if (/(privacy|datenschutz|consent|terms|agb|bedingungen|accord|confidentialit)/i.test(labelText)) {
          diagnostics.push({
            field_id: fieldId,
            status: "skipped",
            reason: "Privacy and consent terms require manual user acceptance"
          });
          continue;
        }

        const answer = AutofillMatching.normalize(act.proposed_value ?? act.value);
        const checked = typeof act.checked === "boolean" ? act.checked : /^(yes|oui|ja|true|1)$/.test(answer) || answer && [el.value, getFieldLabel(el)].some(v => AutofillMatching.normalize(v) === answer) ? true : /^(no|non|nein|false|0)$/.test(answer) ? false : null;
        if (typeof checked === "boolean") {
          const res = setChecked(el, checked);
          if (res.accepted) {
            filledCount++;
            diagnostics.push({ field_id: fieldId, status: "success", checked: el.checked });
          } else {
            diagnostics.push({ field_id: fieldId, status: "failed", reason: res.reason });
          }
        } else diagnostics.push({ field_id: fieldId, status: "failed", reason: "Checkbox answer is ambiguous" });
        continue;
      }

      // 5. Date picker inputs (native date or custom calendar pickers)
      if (!AutofillMatching.datePart(act.field_meta || fieldRegistry.get(fieldId) || {}) && (isDatePickerElement(el, type) || act.profile_source_path === "applicant.personal.date_of_birth")) {
        const fillSuccess = await fillDatePicker(el, act, fieldId, diagnostics);
        if (fillSuccess) filledCount++;
        continue;
      }

      // 6. Standard inputs (text, email, tel, date, number, textarea)
      const fillVal = act.proposed_value !== undefined ? act.proposed_value : act.value;
      if (fillVal !== null && fillVal !== undefined) {
        const applied = setNativeValue(el, fillVal.toString());
        if (isLocationAutocomplete(el, act)) {
          await new Promise(resolve => setTimeout(resolve, 150));
          const pacItem = document.querySelector(".pac-container .pac-item, .pac-item, [role='listbox'] [role='option'], .autocomplete-suggestion");
          if (pacItem && isVisible(pacItem)) {
            pacItem.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
            pacItem.click();
          }
        }
        await new Promise(resolve => setTimeout(resolve, 120));
        el = findElementByFieldId(fieldId, act.field_meta) || el;

        // Validate accepted state
        const numeric = type === "tel" || /phone|telefon|telephone/.test(AutofillMatching.normalize(el.name + " " + getFieldLabel(el)));
        const accepted = applied && el.isConnected && (el.value === fillVal.toString() || numeric && el.value.replace(/\D/g, "") === fillVal.toString().replace(/\D/g, ""));
        const valid = el.checkValidity ? el.checkValidity() : true;

        if (accepted && valid) {
          filledCount++;
          diagnostics.push({ field_id: fieldId, status: "success", value: el.value });
        } else if (!accepted) {
          diagnostics.push({ field_id: fieldId, status: "failed", reason: "rejected value" });
        } else {
          diagnostics.push({ field_id: fieldId, status: "failed", reason: `validation error: ${el.validationMessage || "Invalid format"}` });
        }
      } else {
        diagnostics.push({ field_id: fieldId, status: "skipped", reason: "no matching profile value" });
      }
    }

    return {
      success: true,
      count: filledCount,
      diagnostics: diagnostics
    };
  }

  /**
   * Set up MutationObserver for dynamic forms (fields added after user interactions)
   */
  async function fillCombobox(el, value) {
    const target = AutofillMatching.normalize(value);
    if (!target) return { accepted: false, reason: "No dropdown answer" };
    el.focus();
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    el.click();
    if (el.tagName === "INPUT" && !el.readOnly) setNativeValue(el, String(value), false);
    for (let attempt = 0; attempt < 12; attempt++) {
      await new Promise(resolve => setTimeout(resolve, 80));
      const linked = (el.getAttribute("aria-controls") || el.getAttribute("aria-owns") || "").split(/\s+/).map(id => document.getElementById(id)).filter(Boolean);
      const roots = linked.length ? linked : Array.from(document.querySelectorAll('[role="listbox"]')).filter(isVisible);
      // Do not pick an option belonging to an unrelated open dropdown.
      if (!linked.length && roots.length !== 1) continue;
      const options = roots.flatMap(root => Array.from(root.querySelectorAll('[role="option"]'))).filter(o => isVisible(o) && !o.disabled && o.getAttribute("aria-disabled") !== "true");
      const matches = options.filter(o => [o.textContent, o.getAttribute("data-value")].some(v => AutofillMatching.normalize(v) === target));
      if (matches.length !== 1) continue;
      const option = matches[0];
      option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      option.click();
      await new Promise(resolve => setTimeout(resolve, 120));
      const current = findElementByFieldId(el.getAttribute("data-ai-field-id")) || el;
      const display = AutofillMatching.normalize(current.value || current.textContent);
      const accepted = option.getAttribute("aria-selected") === "true" || display === target && current.getAttribute("aria-expanded") !== "true";
      return { accepted, reason: accepted ? null : "Dropdown did not confirm selection" };
    }
    return { accepted: false, reason: "No unique matching dropdown option" };
  }

  function highlight(fieldId, meta) {
    const el = findElementByFieldId(fieldId, meta);
    if (!el) return { success: false, error: "Field moved; scan again" };
    el.scrollIntoView?.({ behavior: "smooth", block: "center" });
    el.animate?.([{ outline: "4px solid #60a5fa", outlineOffset: "4px" }, { outline: "4px solid transparent", outlineOffset: "8px" }], { duration: 1200, iterations: 2 });
    return { success: true };
  }

  let dock, dockFrame, dockLabel;
  function showDock(url, quick) {
    if (window.top !== window) return;
    if (!dock) {
      dock = document.createElement("div");
      dock.dataset.aiUi = "dock";
      dock.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
      const shadow = dock.attachShadow({ mode: "closed" });
      const style = document.createElement("style");
      style.textContent = `
        button { font: 600 12.5px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; cursor: pointer; transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1); outline: none; }
        .dock-toggle { background: linear-gradient(135deg, rgba(30, 27, 75, 0.95), rgba(15, 23, 42, 0.95)); color: #e0e7ff; border: 1px solid rgba(99, 102, 241, 0.45); border-radius: 14px; padding: 10px 16px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45), 0 0 16px rgba(99, 102, 241, 0.25); display: flex; align-items: center; gap: 8px; backdrop-filter: blur(12px); }
        .dock-toggle:hover { transform: translateY(-2px); border-color: rgba(168, 85, 247, 0.6); box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55), 0 0 20px rgba(168, 85, 247, 0.4); }
        .dock-close { background: rgba(15, 23, 42, 0.9); color: #94a3b8; border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 14px; width: 36px; height: 36px; font-size: 16px; display: flex; align-items: center; justify-content: center; }
        .dock-close:hover { color: #f8fafc; border-color: rgba(255, 255, 255, 0.25); background: rgba(30, 41, 59, 0.9); }
        iframe { display: block; width: min(480px, calc(100vw - 32px)); height: min(720px, calc(100vh - 90px)); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 18px; background: #07090e; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.7), 0 0 25px rgba(99, 102, 241, 0.2); margin-bottom: 10px; }
        iframe[hidden] { display: none; }
        .bar { display: flex; justify-content: flex-end; gap: 8px; }
      `;
      dockFrame = document.createElement("iframe");
      dockFrame.title = "AI Job Autofill review";
      const bar = document.createElement("div"); bar.className = "bar";
      dockLabel = document.createElement("button"); dockLabel.className = "dock-toggle"; dockLabel.innerHTML = "<span>⚡</span><span>Autofill form • Review</span>";
      dockLabel.onclick = () => { dockFrame.hidden = !dockFrame.hidden; };
      const close = document.createElement("button"); close.className = "dock-close"; close.textContent = "×"; close.title = "Close autofill dock";
      close.onclick = () => { dock.remove(); dock = null; chrome.runtime.sendMessage({ action: "close_dock" }).catch(() => {}); };
      bar.append(dockLabel, close); shadow.append(style, dockFrame, bar); document.documentElement.appendChild(dock);
    }
    if (dockFrame.src !== url || quick) dockFrame.src = url;
    dockFrame.hidden = false;
  }

  // A single reusable badge avoids adding controls to every field or disturbing form layout.
  const wandHost = document.createElement("div");
  wandHost.dataset.aiUi = "wand";
  wandHost.style.cssText = "position:fixed;z-index:2147483646;display:none";
  const wandRoot = wandHost.attachShadow({ mode: "closed" });
  const wand = document.createElement("button");
  wand.textContent = "✦"; wand.title = "AI Autofill this field";
  wand.style.cssText = "border:1px solid rgba(255,255,255,0.3);border-radius:50%;background:linear-gradient(135deg, #6366f1, #a855f7);color:white;width:28px;height:28px;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 4px 14px rgba(99,102,241,0.5);font-size:13px;font-weight:700;transition:transform 0.2s cubic-bezier(0.16,1,0.3,1),box-shadow 0.2s ease;";
  wand.onmouseenter = () => { wand.style.transform = "scale(1.15)"; wand.style.boxShadow = "0 6px 20px rgba(168,85,247,0.7)"; };
  wand.onmouseleave = () => { wand.style.transform = "scale(1)"; wand.style.boxShadow = "0 4px 14px rgba(99,102,241,0.5)"; };
  wandRoot.append(wand); document.documentElement.appendChild(wandHost);
  let hoveredField;
  function offerWand(event) {
    const el = event.target;
    if (!el.matches?.(controlSelector) || el.disabled || el.type === "password" || el.closest('[data-ai-ui]')) return;
    const field = scanDocumentFields(document).find(f => f.field_id === el.getAttribute("data-ai-field-id"));
    if (!field || field.type === "file" || AutofillMatching.protectedField(field)) { wandHost.style.display = "none"; return; }
    hoveredField = field;
    const rect = el.getBoundingClientRect();
    wandHost.style.left = `${Math.min(innerWidth - 30, rect.right - 28)}px`;
    wandHost.style.top = `${Math.max(0, rect.top - 14)}px`; wandHost.style.display = "block";
  }
  document.addEventListener("pointerover", offerWand);
  document.addEventListener("focusin", offerWand);
  window.addEventListener("scroll", () => { wandHost.style.display = "none"; }, true);
  wand.onclick = () => {
    if (hoveredField) chrome.runtime.sendMessage({ action: "open_dock", field_id: hoveredField.field_id }).catch(() => {});
  };

  let changeDebounceTimer = null;
  let lastSignature = "";
  function checkStep() {
    const fields = scanDocumentFields(document);
    const signature = location.href + fields.map(f => `${f.field_id}:${f.label}`).join("|");
    if (lastSignature && signature !== lastSignature) {
      if (dockLabel) dockLabel.textContent = `New form step detected (${fields.length} fields) • Scan to fill`;
      chrome.runtime.sendMessage({ action: "form_updated" }).catch(() => {});
    }
    lastSignature = signature;
  }
  function observeFormMutations() {
    if (window.__aiJobAutofillObserver) {
      window.__aiJobAutofillObserver.disconnect();
    }

    const observer = new MutationObserver((mutations) => {
      if (mutations.every(m => m.target.closest?.('[data-ai-ui]') || m.type === "attributes" && m.attributeName === "data-ai-field-id")) return;
      let hasRelevantAdditions = false;
      for (const m of mutations) {
        if (m.type === "childList" && m.addedNodes.length > 0) {
          for (const node of m.addedNodes) {
            if (node.nodeType === Node.ELEMENT_NODE) {
              if (node.matches("input, textarea, select") || node.querySelector("input, textarea, select")) {
                hasRelevantAdditions = true;
                break;
              }
            }
          }
        }
        if (hasRelevantAdditions) break;
      }

      if (hasRelevantAdditions || mutations.some(m => m.type === "attributes" || m.removedNodes.length)) {
        clearTimeout(changeDebounceTimer);
        changeDebounceTimer = setTimeout(() => {
          checkStep();
        }, 400);
      }
    });

    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["hidden", "style", "class", "disabled", "aria-hidden"] });
    window.__aiJobAutofillObserver = observer;
  }

  // Initialize observer
  observeFormMutations();
  checkStep();
  window.addEventListener("popstate", checkStep);
  window.addEventListener("hashchange", checkStep);

  // Listen for extension popup messages
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "scan") {
      const scanResult = scanAllFields();
      sendResponse(scanResult);
      return false;
    } else if (request.action === "highlight") {
      sendResponse(highlight(request.field_id, request.field_meta));
    } else if (request.action === "show_dock") {
      if (request.url?.startsWith(chrome.runtime.getURL("popup.html"))) showDock(request.url, request.quick);
      sendResponse({ success: true });
    } else if (request.action === "step_notice") {
      if (dockLabel) dockLabel.textContent = "Form updated • Scan to fill the next step";
    } else if (request.action === "dock_status") {
      if (dockLabel) dockLabel.textContent = `Autofill form (${request.ready}/${request.total} ready)`;
      sendResponse({ success: true });
    } else if (request.action === "autofill") {
      autofillFields(request.actions || [], request.allowFileUpload)
        .then(result => {
          sendResponse(result);
        })
        .catch(err => {
          sendResponse({ success: false, error: err.message });
        });
      return true; // Keep message channel open for async response
    } else if (request.action === "get_context") {
      sendResponse(extractPageContext());
      return false;
    }
  });
  return { scannable: true };
})();
