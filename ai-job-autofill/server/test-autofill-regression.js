import assert from "node:assert/strict";
import fs from "node:fs/promises";
import vm from "node:vm";
import { JSDOM } from "jsdom";
import "../extension/matching.js";

const matching = AutofillMatching;
const profile = { applicant: { personal: { first_name: "Ada", date_of_birth: "1992-08-22" }, contact: { email: "ada@example.test" } } };
assert.equal(matching.match({ field_id: "x", name: "first_name", type: "text" }, profile).proposed_value, "Ada");
assert.equal(matching.match({ name: "privacy_email", type: "text" }, profile), null);
assert.equal(matching.ready({ action: "review", proposed_value: "Yes" }, { label: "Privacy consent" }), false);
assert.equal(matching.ready({ action: "review", proposed_value: "My draft" }, { label: "Motivation" }), true);
assert.equal(matching.ready({ action: "fill", proposed_value: "" }, {}), false);
assert.equal(matching.birthValue({ name: "birth_month", options: [{ value: "7", text: "Août" }] }, "1992-08-22"), "7");
assert.equal(matching.birthValue({ label: "Année", nearby_question: "Date de naissance" }, "1992-08-22"), "1992");
assert.equal(matching.birthValue({}, "1992-02-31"), null);
assert.equal(matching.birthValue({}, undefined), null);
assert.equal(matching.phoneValue({ validation: { pattern: "0[0-9]{10}" } }, { e164: "+4917612345678", national_digits: "01761234567" }), "01761234567");

// Salary unit conversions
assert.equal(matching.salaryValue({ label: "Expected annual salary" }, 65000), "65000");
assert.equal(matching.salaryValue({ label: "Monthly salary expectation" }, 65000), "5417");
assert.equal(matching.salaryValue({ label: "Salary range", options: [{ value: "range_1", text: "50k-70k" }, { value: "range_2", text: "70k-90k" }] }, 65000), "range_1");

// Notice period conversions
assert.equal(matching.noticeValue({ label: "Notice period in weeks" }, "3 months"), "13");
assert.equal(matching.noticeValue({ label: "Notice period in days" }, "3 months"), "90");

// Demographics auto-matching (EEOC)
assert.equal(matching.demographicValue({ label: "Gender identity", options: [{ value: "m", text: "Male" }, { value: "f", text: "Female" }] }, { gender_identity: "male" }), "m");
assert.equal(matching.demographicValue({ label: "Race / Ethnicity", options: [{ value: "white", text: "White" }, { value: "decline", text: "Decline to self-identify" }] }, null), "decline");

const dom = new JSDOM(`<!doctype html><body><form id="application">
<label for="name">First name</label><input id="name" name="first_name">
<input id="focus" name="focus_test"><input id="masked" name="phone" type="tel">
<input id="reject" name="reject"><input id="cancel" name="cancel">
<label><input id="yes" type="radio" name="choice" value="opt_yes">Oui</label>
<label><input id="no" type="radio" name="choice" value="0">Non</label>
<label><input id="terms" type="checkbox">Privacy consent</label>
<fieldset><legend>Date de naissance</legend><input name="birth_day" id="day"><select name="birth_month" id="month"><option value="7">Août</option></select></fieldset>
<label for="combo">Country</label><input id="combo" role="combobox" readonly aria-controls="countries" aria-expanded="false">
<div id="countries" role="listbox" hidden><div role="option">France</div><div role="option">Germany</div></div>
<label for="loc">Location</label><input id="loc" name="location" class="pac-target" placeholder="City, State">
</form></body>`, { runScripts: "outside-only", url: "https://jobs.example.test/apply" });
const w = dom.window;
w.CSS ||= {};
w.CSS.escape ||= value => String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
w.HTMLElement.prototype.getBoundingClientRect = function () { return { top: 10, right: 210, width: 200, height: 30 }; };
const listeners = [];
w.chrome = { runtime: { onMessage: { addListener: fn => listeners.push(fn) }, sendMessage: async () => ({}), getURL: path => `chrome-extension://test/${path}` } };
w.eval(await fs.readFile(new URL("../extension/matching.js", import.meta.url), "utf8"));
const content = await fs.readFile(new URL("../extension/content.js", import.meta.url), "utf8");
w.eval(content); w.eval(content);
assert.equal(listeners.length, 1, "Reinjection must not duplicate message listeners");
const message = request => new Promise(resolve => listeners[0](request, {}, resolve));
const scan = await message({ action: "scan" });
const fields = scan.fields;
const field = id => fields.find(f => f.id === id);
assert.equal(field("combo").type, "combobox");
assert.equal(field("day").is_date_picker, false);
assert.equal(field("month").is_date_picker, false);
const byId = id => w.document.getElementById(id);
const replace = id => { const old = byId(id); const next = old.cloneNode(true); next.removeAttribute("data-ai-field-id"); old.replaceWith(next); return next; };
replace("name");
byId("focus").addEventListener("focus", () => replace("focus"), { once: true });
const events = [];
byId("name").addEventListener("beforeinput", e => events.push(e.inputType));
byId("masked").addEventListener("input", () => w.setTimeout(() => { byId("masked").value = "123 456"; }, 20));
byId("reject").addEventListener("input", () => w.setTimeout(() => { byId("reject").value = "unrelated old value"; }, 20));
byId("cancel").addEventListener("beforeinput", e => e.preventDefault());
byId("combo").addEventListener("click", () => { byId("countries").hidden = false; byId("combo").setAttribute("aria-expanded", "true"); });
byId("countries").addEventListener("click", e => { byId("combo").value = e.target.textContent; e.target.setAttribute("aria-selected", "true"); byId("combo").setAttribute("aria-expanded", "false"); byId("countries").hidden = true; });
const action = (id, value, extras = {}) => ({ field_id: field(id).field_id, field_meta: field(id), action: "fill", proposed_value: value, ...extras });
assert.equal(scan.has_captcha, false);
const result = await message({ action: "autofill", actions: [action("name", "Ada"), action("focus", "focused"), action("masked", "123456"), action("reject", "wanted"), action("cancel", "blocked"), action("yes", "Oui"), action("no", "Oui"), action("terms", "Yes", { checked: true }), action("day", "22", { profile_source_path: "applicant.personal.date_of_birth" }), action("month", "7"), action("combo", "France"), action("loc", "Paris, France")] });
assert.equal(byId("name").value, "Ada");
assert.deepEqual(events, ["insertText"]);
assert.equal(byId("focus").value, "focused");
assert.equal(byId("yes").checked, true);
assert.equal(byId("no").checked, false);
assert.equal(byId("terms").checked, false);
assert.equal(byId("day").value, "22");
assert.equal(byId("month").value, "7");
assert.equal(byId("combo").value, "France");
assert.equal(byId("loc").value, "Paris, France");
for (const id of ["reject", "cancel"]) assert.equal(result.diagnostics.find(d => d.field_id === field(id).field_id).status, "failed");
assert.equal(result.count, 8);
dom.window.close();

// Two frames deliberately return identical local IDs. Fill must target their original documents.
const calls = [];
const sandbox = { console, AutofillMatching, chrome: { scripting: { executeScript: async () => [0, 4].map(frameId => ({ frameId, documentId: `doc${frameId}`, result: { scannable: true } })) }, tabs: { sendMessage: async (tab, request, options) => {
  calls.push({ tab, request, options });
  if (request.action === "scan") return { fields: [{ field_id: "same", name: "email" }], page_context: { title: "job" } };
  if (options.documentId === "doc4") throw new Error("Document navigated");
  return { success: true, count: 1, diagnostics: [{ field_id: "same", status: "success" }] };
} } } };
vm.createContext(sandbox);
vm.runInContext(await fs.readFile(new URL("../extension/client.js", import.meta.url), "utf8"), sandbox);
const scanned = await sandbox.AutofillClient.scan(10);
assert.deepEqual(Array.from(scanned.fields, f => f.field_id), ["f0:same", "f4:same"]);
const filled = await sandbox.AutofillClient.fill(10, scanned.fields.map(f => ({ field_id: f.field_id, action: "fill", proposed_value: "Ada" })), scanned.fields, false);
assert.equal(filled.count, 1);
assert.equal(filled.diagnostics.find(d => d.field_id === "f4:same").status, "failed");
assert.equal(calls.at(-1).options.frameId, 4);
assert.equal(calls.at(-1).options.documentId, "doc4");
console.log("PASS: local matching, approval safeguards, rerenders, events, masked/rejected values, radio labels, split dates, comboboxes, reinjection and frame routing");
