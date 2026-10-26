// Every scan result is bound to a frame AND document, preventing stale fills after navigation.
globalThis.AutofillClient = {
  async scan(tabId) {
    const injected = (await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["matching.js", "content.js"] })).filter(r => r.result?.scannable);
    const results = await Promise.allSettled(injected.map(async ({ frameId, documentId }) => {
      const result = await chrome.tabs.sendMessage(tabId, { action: "scan" }, { frameId, documentId });
      return { ...result, frameId, documentId };
    }));
    const fields = [], inaccessible_frames = [];
    let page_context, has_captcha = false;
    results.forEach((r, index) => {
      if (r.status !== "fulfilled") { inaccessible_frames.push({ frame_title: `Frame ${injected[index].frameId}`, reason: String(r.reason) }); return; }
      const result = r.value;
      if (result.has_captcha) has_captcha = true;
      if (result.frameId === 0) page_context = result.page_context;
      for (const f of result.fields || []) fields.push({ ...f, local_field_id: f.field_id, field_id: `f${result.frameId}:${f.field_id}`, frame_id: result.frameId, document_id: result.documentId });
    });
    return { fields, inaccessible_frames, page_context, has_captcha };
  },
  async highlight(tabId, field) {
    return chrome.tabs.sendMessage(tabId, { action: "highlight", field_id: field.local_field_id, field_meta: field }, { frameId: field.frame_id, documentId: field.document_id });
  },
  async fill(tabId, actions, fields, allowFileUpload) {
    const groups = new Map();
    const diagnostics = [];
    for (const action of actions) {
      const meta = fields.find(f => f.field_id === action.field_id);
      if (!meta) { diagnostics.push({ field_id: action.field_id, status: "failed", reason: "Field metadata missing; scan again" }); continue; }
      const key = `${meta.frame_id}:${meta.document_id}`;
      if (!groups.has(key)) groups.set(key, { meta, actions: [] });
      groups.get(key).actions.push({ ...action, field_id: meta.local_field_id, field_meta: meta });
    }
    let count = 0;
    for (const { meta, actions: batch } of groups.values()) {
      try {
        const result = await chrome.tabs.sendMessage(tabId, { action: "autofill", actions: batch, allowFileUpload }, { frameId: meta.frame_id, documentId: meta.document_id });
        if (!result?.success) throw new Error(result?.error || "No response from frame");
        count += result.count || 0;
        diagnostics.push(...result.diagnostics.map(d => ({ ...d, field_id: `f${meta.frame_id}:${d.field_id}` })));
      } catch (error) {
        diagnostics.push(...batch.map(a => ({ field_id: a.field_meta.field_id, status: "failed", reason: `Frame unavailable; scan again. ${error.message}` })));
      }
    }
    return { count, diagnostics };
  },
  async getBase() {
    if (globalThis._autofillBackendBase) return globalThis._autofillBackendBase;
    const candidates = ["http://localhost:5000", "http://localhost:8787"];
    for (const base of candidates) {
      try {
        const testRes = await fetch(`${base}/api/profiles`, { method: "HEAD", signal: AbortSignal.timeout(600) });
        if (testRes.ok || testRes.status === 200 || testRes.status === 404) {
          globalThis._autofillBackendBase = base;
          return base;
        }
      } catch (e) {}
    }
    globalThis._autofillBackendBase = "http://localhost:5000";
    return globalThis._autofillBackendBase;
  },
  async map(fields, profileId, domain, pageContext) {
    const base = await this.getBase();
    // Cache only for this review window; refreshing or reopening reloads profile and corrections.
    const key = `${profileId}:${domain}`;
    this.cache ||= new Map();
    let data = this.cache.get(key);
    if (!data || Date.now() - data.loadedAt > 60000) {
      const response = await fetch(`${base}/api/profiles/${encodeURIComponent(profileId)}/matching-data?domain=${encodeURIComponent(domain)}`);
      if (response.ok) { data = { ...await response.json(), loadedAt: Date.now() }; this.cache.set(key, data); }
      else data = null;
    }
    const local = [], unresolved = [];
    for (const f of fields) {
      const signature = f.name || f.id || f.field_id;
      const corrected = data?.corrections?.some(c => c.fieldSignature === signature || c.fieldLabel && AutofillMatching.normalize(c.fieldLabel) === AutofillMatching.normalize(f.label));
      const action = data && !corrected ? AutofillMatching.match(f, data) : null;
      if (action) local.push(action); else unresolved.push(f);
    }
    if (!unresolved.length) return { actions: local };
    const response = await fetch(`${base}/api/map-fields`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fields: unresolved, profileId, domain, pageContext }) });
    if (!response.ok) throw new Error(`Server matching error (${response.status})`);
    const result = await response.json();
    return { ...result, actions: [...local, ...(result.actions || [])] };
  }
};
