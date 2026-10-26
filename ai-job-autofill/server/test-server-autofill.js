// Isolated fixture; never replace a user's profile or invoke paid AI matching.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { randomUUID } from "node:crypto";
const base = "http://localhost:8787";
const id = `autofill_test_${randomUUID()}`;
const fixture = new URL(`./profiles/${id}.json`, import.meta.url);
const profile = { applicant: { personal: { first_name: "Ada", date_of_birth: "1992-08-22" }, contact: { phone: "+4917612345678", address: { country_code: "DE", street: "Teststrasse", house_number: "12" } } } };
let correctionId;
const map = async fields => {
  const response = await fetch(`${base}/api/map-fields`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profileId: id, domain: "autofill.test", fields }) });
  assert.equal(response.status, 200);
  return (await response.json()).actions;
};
await fs.writeFile(fixture, JSON.stringify(profile), { flag: "wx" });
try {
  const cache = await fetch(`${base}/api/profiles/${id}/matching-data?domain=autofill.test`);
  assert.equal(cache.status, 200);
  const data = await cache.json();
  assert.equal(data.applicant.personal.first_name, "Ada");
  assert.equal(data.phone_variants.national_digits, "017612345678");
  assert.equal((await fetch(`${base}/api/profiles/missing_${id}/matching-data`)).status, 404);
  const actions = await map([
    { field_id: "day", label: "Jour", name: "birth_day", type: "text" },
    { field_id: "month", label: "Mois", name: "birth_month", tag: "select", options: [{ value: "7", text: "Août" }] },
    { field_id: "year", label: "Année", nearby_question: "Date de naissance", type: "text" },
    { field_id: "phone", label: "Telefon", validation: { pattern: "0[0-9]{11}" } },
    { field_id: "street", label: "Street", separate_house_number: true },
    { field_id: "number", label: "House number" }
  ]);
  assert.deepEqual(actions.map(a => a.proposed_value), ["22", "7", "1992", "017612345678", "Teststrasse", "12"]);
  const saved = await fetch(`${base}/api/corrections`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profileId: id, domain: "autofill.test", fieldSignature: "consent", fieldLabel: "Privacy consent", correctionValue: "Yes" }) });
  const savedData = await saved.json();
  correctionId = savedData.correction?.id;
  assert.ok(correctionId);
  const [consent] = await map([{ field_id: "consent", name: "consent", label: "Privacy consent", type: "checkbox" }]);
  assert.equal(consent.action, "review");
  assert.equal(consent.proposed_value, null);
  delete profile.applicant.personal.date_of_birth;
  await fs.writeFile(fixture, JSON.stringify(profile));
  const [missing] = await map([{ field_id: "dob", label: "Date of birth", type: "date" }]);
  assert.equal(missing.action, "skip");
  assert.equal(missing.proposed_value, null);
  console.log("PASS: isolated server split dates, phone formats, separate address fields, cache isolation, consent correction protection and missing birth dates");
} finally {
  if (correctionId) await fetch(`${base}/api/corrections/${correctionId}`, { method: "DELETE" });
  await fs.unlink(fixture);
  // Only our unique, empty test directory; never recursively delete profile data.
  await fs.rmdir(new URL(`./profiles/${id}/`, import.meta.url)).catch(error => { if (error.code !== "ENOENT") throw error; });
}
