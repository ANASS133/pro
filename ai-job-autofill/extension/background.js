// Dock activation is per tab and lasts only for the browser session.
async function showDock(tabId, quickField = null, frameId = 0) {
  await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["matching.js", "content.js"] });
  const url = new URL(chrome.runtime.getURL("popup.html"));
  url.searchParams.set("dock", "1");
  url.searchParams.set("tabId", tabId);
  if (quickField) url.searchParams.set("field", `f${frameId}:${quickField}`);
  await chrome.tabs.sendMessage(tabId, { action: "show_dock", url: url.href, quick: Boolean(quickField) }, { frameId: 0 });
}
chrome.runtime.onMessage.addListener((request, sender, respond) => {
  if (request.action === "open_dock") {
    const tabId = sender.tab?.id ?? request.tabId;
    if (!Number.isInteger(tabId)) return;
    (async () => {
      await chrome.storage.session.set({ [`dock_${tabId}`]: true });
      await showDock(tabId, request.field_id, sender.frameId || 0);
    })().then(() => respond({ success: true }), e => respond({ error: e.message }));
    return true;
  }
  if (request.action === "close_dock" && sender.tab) chrome.storage.session.remove(`dock_${sender.tab.id}`);
  if (request.action === "form_updated" && sender.tab) {
    chrome.tabs.sendMessage(sender.tab.id, { action: "step_notice" }, { frameId: 0 }).catch(() => {});
  }
});
chrome.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status !== "complete") return;
  chrome.storage.session.get(`dock_${tabId}`).then(data => {
    if (data[`dock_${tabId}`]) return showDock(tabId);
  }).catch(() => {});
});
chrome.tabs.onRemoved.addListener(tabId => { chrome.storage.session.remove(`dock_${tabId}`); });

chrome.commands?.onCommand?.addListener(async (command) => {
  if (command === "autofill_quick") {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      await chrome.storage.session.set({ [`dock_${tab.id}`]: true });
      await showDock(tab.id);
    }
  }
});
