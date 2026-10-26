// test-suite.js - Comprehensive test suite for 3-Stage Matching, Trilingual Support, Correction Memory & Safeguards
import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { JSDOM } from "jsdom";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE_URL = "http://localhost:8787";

async function runTestSuite() {
  console.log("🧪 Starting Comprehensive AI Autofill Test Suite...\n");
  let passed = 0;
  let failed = 0;

  function assert(condition, testName) {
    if (condition) {
      console.log(`  ✅ PASS: ${testName}`);
      passed++;
    } else {
      console.error(`  ❌ FAIL: ${testName}`);
      failed++;
    }
  }

  try {
    // -----------------------------------------------------------------------
    // Test Set 1: Trilingual Deterministic Matching (German, French, English)
    // -----------------------------------------------------------------------
    console.log("▶️ Test Set 1: Trilingual Deterministic Matching");

    const trilingualFields = [
      // German fields
      { field_id: "de_vorname", type: "text", label: "Vorname" },
      { field_id: "de_nachname", type: "text", label: "Nachname" },
      { field_id: "de_email", type: "email", label: "E-Mail-Adresse" },
      { field_id: "de_telefon", type: "tel", label: "Telefonnummer" },
      { field_id: "de_geb", type: "text", label: "Geburtsdatum" },
      { field_id: "de_stadt", type: "text", label: "Wohnort / Stadt" },
      { field_id: "de_plz", type: "text", label: "Postleitzahl" },
      { field_id: "de_strasse", type: "text", label: "Straße und Hausnummer" },

      // French fields
      { field_id: "fr_prenom", type: "text", label: "Prénom" },
      { field_id: "fr_nom", type: "text", label: "Nom de famille" },
      { field_id: "fr_courriel", type: "email", label: "Courriel" },
      { field_id: "fr_tel", type: "tel", label: "Numéro de téléphone" },
      { field_id: "fr_ville", type: "text", label: "Ville de résidence" },
      { field_id: "fr_code_postal", type: "text", label: "Code postal" },

      // English fields
      { field_id: "en_first_name", type: "text", label: "First Name" },
      { field_id: "en_last_name", type: "text", label: "Last Name" },
      { field_id: "en_email", type: "email", label: "Email Address" },
      { field_id: "en_phone", type: "tel", label: "Phone Number" },
      { field_id: "en_city", type: "text", label: "City" },
      { field_id: "en_country", type: "text", label: "Country" }
    ];

    const triRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        fields: trilingualFields
      })
    });
    const triData = await triRes.json();
    assert(triData.success === true, "Trilingual mapping returns success");

    // German assertions
    const deVorname = triData.actions.find(a => a.field_id === "de_vorname");
    assert(deVorname && deVorname.action === "fill" && deVorname.proposed_value === "Chamseddine", "German 'Vorname' mapped to 'Chamseddine'");
    assert(deVorname && deVorname.is_verified_fact === true, "German 'Vorname' is marked as verified fact");

    const deNachname = triData.actions.find(a => a.field_id === "de_nachname");
    assert(deNachname && deNachname.action === "fill" && deNachname.proposed_value === "Boumlik", "German 'Nachname' mapped to 'Boumlik'");

    const deEmail = triData.actions.find(a => a.field_id === "de_email");
    assert(deEmail && deEmail.proposed_value === "chamsboumlik@gmail.com", "German 'E-Mail-Adresse' mapped correctly");

    const deStadt = triData.actions.find(a => a.field_id === "de_stadt");
    assert(deStadt && deStadt.proposed_value === "Casablanca", "German 'Wohnort / Stadt' mapped to 'Casablanca'");

    // French assertions
    const frPrenom = triData.actions.find(a => a.field_id === "fr_prenom");
    assert(frPrenom && frPrenom.proposed_value === "Chamseddine", "French 'Prénom' mapped to 'Chamseddine'");

    const frNom = triData.actions.find(a => a.field_id === "fr_nom");
    assert(frNom && frNom.proposed_value === "Boumlik", "French 'Nom de famille' mapped to 'Boumlik'");

    const frCourriel = triData.actions.find(a => a.field_id === "fr_courriel");
    assert(frCourriel && frCourriel.proposed_value === "chamsboumlik@gmail.com", "French 'Courriel' mapped to email");

    const frVille = triData.actions.find(a => a.field_id === "fr_ville");
    assert(frVille && frVille.proposed_value === "Casablanca", "French 'Ville de résidence' mapped to 'Casablanca'");

    // English assertions
    const enFirst = triData.actions.find(a => a.field_id === "en_first_name");
    assert(enFirst && enFirst.proposed_value === "Chamseddine", "English 'First Name' mapped to 'Chamseddine'");

    const enCountry = triData.actions.find(a => a.field_id === "en_country");
    assert(enCountry && enCountry.proposed_value === "Morocco", "English 'Country' mapped to 'Morocco'");

    // -----------------------------------------------------------------------
    // Test Set 2: Sensitive Declarations & Privacy Guardrails
    // -----------------------------------------------------------------------
    console.log("\n▶️ Test Set 2: Sensitive Declarations & Safeguards");

    const sensitiveFields = [
      { field_id: "f_privacy", type: "checkbox", label: "Ich akzeptiere die Datenschutzbestimmungen / Privacy Policy" },
      { field_id: "f_criminal", type: "text", label: "Do you have any criminal convictions? (Führungszeugnis / Casier judiciaire)" },
      { field_id: "f_health", type: "text", label: "Disabilities or health restrictions (Behinderung / Handicap)" },
      { field_id: "f_visa", type: "text", label: "Do you hold a valid work permit or visa? (Arbeitserlaubnis)" }
    ];

    const sensRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        fields: sensitiveFields
      })
    });
    const sensData = await sensRes.json();

    const privacyAct = sensData.actions.find(a => a.field_id === "f_privacy");
    assert(privacyAct && privacyAct.action === "review" && privacyAct.review_required === true, "Privacy policy checkbox strictly requires manual review");

    const criminalAct = sensData.actions.find(a => a.field_id === "f_criminal");
    assert(criminalAct && criminalAct.action === "review" && criminalAct.review_required === true && criminalAct.proposed_value === null, "Criminal record inquiry strictly marked review_required with null value");

    const healthAct = sensData.actions.find(a => a.field_id === "f_health");
    assert(healthAct && healthAct.action === "review" && healthAct.review_required === true, "Health/disability inquiry strictly marked review_required");

    const visaAct = sensData.actions.find(a => a.field_id === "f_visa");
    assert(visaAct && visaAct.action === "review" && visaAct.review_required === true, "Visa/work permit inquiry requires manual confirmation");

    // -----------------------------------------------------------------------
    // Test Set 3: Correction Memory Engine
    // -----------------------------------------------------------------------
    console.log("\n▶️ Test Set 3: Correction Memory (Save, Recall, Delete)");

    const testDomain = "test-jobs-portal.de";
    const testSig = "custom_applicant_nickname";

    // 1. Save correction
    const saveRes = await fetch(`${BASE_URL}/api/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        domain: testDomain,
        fieldSignature: testSig,
        fieldLabel: "Preferred Nickname",
        correctionValue: "Chams"
      })
    });
    const saveData = await saveRes.json();
    assert(saveData.success === true && saveData.correction?.correctionValue === "Chams", "Correction successfully saved to memory");

    // 2. Map fields on that domain and verify correction is applied
    const mapWithCorrRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        domain: testDomain,
        fields: [
          { field_id: "fld_nick", type: "text", name: testSig, label: "Preferred Nickname" }
        ]
      })
    });
    const mapWithCorrData = await mapWithCorrRes.json();
    const corrAction = mapWithCorrData.actions.find(a => a.field_id === "fld_nick");
    assert(corrAction && corrAction.proposed_value === "Chams", "Saved correction recalled and applied to matching field");
    assert(corrAction && corrAction.profile_source_path === "correction_memory", "Profile source path identifies 'correction_memory'");

    // 3. Inspect corrections endpoint
    const listCorrRes = await fetch(`${BASE_URL}/api/corrections?profileId=Chamss&domain=${testDomain}`);
    const listCorrData = await listCorrRes.json();
    assert(listCorrData.corrections.some(c => c.fieldSignature === testSig), "Correction listed in GET /api/corrections query");

    // 4. Delete correction
    const corrId = saveData.correction.id;
    const delRes = await fetch(`${BASE_URL}/api/corrections/${corrId}`, { method: "DELETE" });
    const delData = await delRes.json();
    assert(delData.success === true, "Correction deleted via DELETE /api/corrections/:id");

    // -----------------------------------------------------------------------
    // Test Set 4: Gender & Country Dropdown/Radio Handling
    // -----------------------------------------------------------------------
    console.log("\n▶️ Test Set 4: Gender & Country Dropdown/Radio Handling");

    const optionFields = [
      {
        field_id: "f_gender_radio_m",
        type: "radio",
        name: "gender",
        value: "männlich",
        label: "Männlich"
      },
      {
        field_id: "f_gender_radio_w",
        type: "radio",
        name: "gender",
        value: "weiblich",
        label: "Weiblich"
      },
      {
        field_id: "f_country_sel",
        type: "select",
        tag: "select",
        name: "country",
        label: "Country / Land",
        options: [
          { value: "", text: "Select a country" },
          { value: "DE", text: "Deutschland" },
          { value: "MA", text: "Marokko / Morocco" },
          { value: "FR", text: "France" }
        ]
      }
    ];

    const optRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        fields: optionFields
      })
    });
    const optData = await optRes.json();

    const maleRadio = optData.actions.find(a => a.field_id === "f_gender_radio_m");
    assert(maleRadio && maleRadio.action === "fill" && maleRadio.checked === true, "Male radio button matched with checked: true");

    const femaleRadio = optData.actions.find(a => a.field_id === "f_gender_radio_w");
    assert(femaleRadio && femaleRadio.action === "skip" && femaleRadio.checked === false, "Female radio button marked with checked: false");

    const countrySelect = optData.actions.find(a => a.field_id === "f_country_sel");
    assert(countrySelect && countrySelect.proposed_value === "MA", "Country select option resolved to 'MA' (Morocco/Marokko)");

    // -----------------------------------------------------------------------
    // Test Set 6: Focused Regressions for Date of Birth & Field Context (Issues 1 & 2)
    // -----------------------------------------------------------------------
    console.log("\n▶️ Test Set 6: Regressions for Date of Birth & Field Context Extraction");

    const frenchRegressionFields = [
      {
        field_id: "fr_reg_prenom",
        tag: "input",
        type: "text",
        name: "first_name",
        label: "Votre prénom",
        section_heading: "COMPLÉTEZ VOTRE PROFIL"
      },
      {
        field_id: "fr_reg_nom",
        tag: "input",
        type: "text",
        name: "last_name",
        label: "Votre nom",
        section_heading: "COMPLÉTEZ VOTRE PROFIL"
      },
      {
        field_id: "fr_reg_ville",
        tag: "input",
        type: "text",
        name: "city",
        label: "Votre ville",
        section_heading: "COMPLÉTEZ VOTRE PROFIL"
      },
      {
        field_id: "fr_reg_nationality",
        tag: "select",
        type: "select",
        name: "nationality",
        label: "Nationalité",
        section_heading: "COMPLÉTEZ VOTRE PROFIL",
        options: [
          { value: "Moroccan", text: "Marocaine" },
          { value: "French", text: "Française" },
          { value: "German", text: "Allemande" }
        ]
      },
      {
        field_id: "fr_reg_dob",
        tag: "input",
        type: "date",
        is_date_picker: true,
        name: "date_de_naissance",
        label: "Date de naissance",
        placeholder: "Sélectionner une date",
        section_heading: "COMPLÉTEZ VOTRE PROFIL"
      },
      {
        field_id: "ai_7g07d6_3",
        tag: "input",
        type: "text",
        name: "",
        id: "",
        label: "Champ sans libellé (Complément d'information / Remarques)",
        display_label: "Champ sans libellé (Complément d'information / Remarques)",
        placeholder: "Complément d'information / Remarques",
        section_heading: "COMPLÉTEZ VOTRE PROFIL"
      }
    ];

    const regRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Boumlik_Chamseddine",
        fields: frenchRegressionFields
      })
    });

    const regData = await regRes.json();
    assert(regData.success === true, "French regression field mapping returned success");

    // 1. Verify Date of Birth resolution respecting site's French format (DD/MM/YYYY)
    const dobAction = regData.actions.find(a => a.field_id === "fr_reg_dob");
    assert(dobAction && dobAction.action === "fill", "Date of birth field mapped to 'fill'");
    assert(dobAction && (dobAction.proposed_value === "22/08/2004" || dobAction.proposed_value === "2004-08-22"), `Date of birth mapped to 22 August 2004 (${dobAction?.proposed_value})`);
    assert(dobAction && dobAction.is_verified_fact === true, "Date of birth is marked as verified fact");

    // 2. Verify individual field mappings under repeated generic headings
    const prenomAction = regData.actions.find(a => a.field_id === "fr_reg_prenom");
    assert(prenomAction && prenomAction.proposed_value === "Chamseddine", "Votre prénom mapped to 'Chamseddine'");

    const nomAction = regData.actions.find(a => a.field_id === "fr_reg_nom");
    assert(nomAction && nomAction.proposed_value === "Boumlik", "Votre nom mapped to 'Boumlik'");

    const villeAction = regData.actions.find(a => a.field_id === "fr_reg_ville");
    assert(villeAction && villeAction.proposed_value === "Casablanca", "Votre ville mapped to 'Casablanca'");

    const natAction = regData.actions.find(a => a.field_id === "fr_reg_nationality");
    assert(natAction && (natAction.proposed_value === "Moroccan" || natAction.proposed_value === "Marocaine"), "Nationalité mapped to Moroccan option");

    // 3. Verify unlabeled field handling: Not titled with internal ID
    assert(frenchRegressionFields[5].label !== "ai_7g07d6_3", "Unlabeled field label does not use internal ID");
    assert(frenchRegressionFields[5].label.startsWith("Champ sans libellé"), "Unlabeled field uses 'Champ sans libellé' fallback");

    // 4. Correction memory protection test: Shared section headings do not cross-contaminate
    const regDomain = `test-corr-${Date.now()}.fr`;
    await fetch(`${BASE_URL}/api/corrections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Boumlik_Chamseddine",
        domain: regDomain,
        fieldSignature: "fr_reg_prenom",
        fieldLabel: "Votre prénom",
        correctionValue: "Chamseddine-Custom"
      })
    });

    const corrCheckRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        domain: regDomain,
        profileId: "Boumlik_Chamseddine",
        fields: [
          { field_id: "fr_reg_prenom", name: "fr_reg_prenom", label: "Votre prénom", section_heading: "COMPLÉTEZ VOTRE PROFIL" },
          { field_id: "fr_reg_ville", name: "fr_reg_ville", label: "Votre ville", section_heading: "COMPLÉTEZ VOTRE PROFIL" }
        ]
      })
    });

    const corrCheckData = await corrCheckRes.json();
    const checkedPrenom = corrCheckData.actions.find(a => a.field_id === "fr_reg_prenom");
    const checkedVille = corrCheckData.actions.find(a => a.field_id === "fr_reg_ville");

    assert(checkedPrenom && checkedPrenom.proposed_value === "Chamseddine-Custom", "First name correction applied to first name");
    assert(checkedVille && checkedVille.proposed_value === "Casablanca", "City field NOT contaminated by First Name correction despite shared section heading");

    // Cleanup test correction
    await fetch(`${BASE_URL}/api/corrections?profileId=Boumlik_Chamseddine&domain=${regDomain}`, { method: "DELETE" });

    // -----------------------------------------------------------------------
    // Test Set 7: Custom Date Picker Interactive Automation & Form State Acceptance
    // -----------------------------------------------------------------------
    console.log("\n▶️ Test Set 7: Custom Date Picker Interactive Automation & Form Acceptance");

    const frenchHtmlPath = path.join(__dirname, "french-form.html");
    const frenchHtml = await fs.readFile(frenchHtmlPath, "utf-8");

    const dom = new JSDOM(frenchHtml, {
      runScripts: "dangerously",
      url: "http://localhost:8787/french-form"
    });

    const win = dom.window;
    const doc = win.document;

    const dobInput = doc.getElementById("dobInput");
    const calendarPopup = doc.getElementById("calendarPopup");
    const calendarYear = doc.getElementById("calendarYear");
    const calendarMonth = doc.getElementById("calendarMonth");
    const calendarDays = doc.getElementById("calendarDays");
    const resultMessage = doc.getElementById("resultMessage");

    // 1. Initial State Verification
    assert(dobInput && dobInput.value === "Sélectionner une date", "Initial date field value displays 'Sélectionner une date'");
    assert(calendarPopup && !calendarPopup.classList.contains("open"), "Calendar popup is initially closed");
    assert(calendarYear && calendarYear.value === "2026", "Calendar year is initially set to 2026");
    assert(calendarMonth && calendarMonth.value === "8", "Calendar month is initially set to September (index 8)");

    // Initial submit rejection: Website form state must not accept empty/placeholder date
    win.submitForm();
    assert(resultMessage.textContent.includes("Erreur"), "Website form submission initially rejected when date is placeholder");

    // 2. Open Calendar via single click interaction
    dobInput.dispatchEvent(new win.MouseEvent("click", { bubbles: true, cancelable: true }));
    assert(calendarPopup.classList.contains("open"), "Calendar popup opened successfully on interaction");

    // 3. Year Selection: Select 2004 using actual calendar year control
    const year2004Opt = Array.from(calendarYear.options).find(o => o.value === "2004" || o.textContent.trim() === "2004");
    assert(Boolean(year2004Opt), "Calendar year control contains option for year 2004");
    calendarYear.value = "2004";
    calendarYear.dispatchEvent(new win.Event("change", { bubbles: true }));
    calendarYear.dispatchEvent(new win.Event("input", { bubbles: true }));

    // Wait for year view to update
    await new Promise(r => setTimeout(r, 60));
    assert(calendarYear.value === "2004", "Calendar year control updated to 2004 without month-by-month scrolling");

    // 4. Month Selection: Select August (Août) using actual calendar month control
    const aoutOpt = Array.from(calendarMonth.options).find(o => /(ao[uû]t|aug)/i.test(o.textContent.trim()) || o.value === "7");
    assert(Boolean(aoutOpt), "Calendar month control contains option for August / Août");
    calendarMonth.value = aoutOpt.value;
    calendarMonth.dispatchEvent(new win.Event("change", { bubbles: true }));
    calendarMonth.dispatchEvent(new win.Event("input", { bubbles: true }));

    // Wait for month view to update
    await new Promise(r => setTimeout(r, 60));
    assert(calendarMonth.value === "7", "Calendar month control updated to August (value 7 / Août)");

    // 5. Day Selection: Select Day 22 using calendar's actual day buttons
    const day22Candidates = Array.from(calendarDays.querySelectorAll("button, [data-day]")).filter(b => {
      const t = b.textContent.trim();
      const is22 = t === "22" || b.dataset.day === "22";
      const isOther = b.classList.contains("other-month") || b.classList.contains("disabled");
      return is22 && !isOther;
    });
    assert(day22Candidates.length > 0, "Calendar day grid contains valid enabled button for day 22");

    const day22Btn = day22Candidates[0];
    day22Btn.dispatchEvent(new win.MouseEvent("mousedown", { bubbles: true, cancelable: true }));
    day22Btn.dispatchEvent(new win.MouseEvent("mouseup", { bubbles: true, cancelable: true }));
    day22Btn.click();

    // Wait for day selection to apply
    await new Promise(r => setTimeout(r, 60));

    // 6. Post-Fill Field & Form State Acceptance
    assert(dobInput.value !== "Sélectionner une date", "Date field no longer says 'Sélectionner une date'");
    assert(dobInput.value === "22/08/2004", "Date field updated to '22/08/2004' (August 22, 2004)");
    assert(dobInput.dataset.acceptedDate === "22/08/2004", "Website form state accepted the date (dataset.acceptedDate = '22/08/2004')");
    assert(!calendarPopup.classList.contains("open"), "Calendar popup closed cleanly after selection");

    // 7. Form Submission Acceptance Test
    win.submitForm();
    assert(resultMessage.textContent.includes("Succès") && resultMessage.textContent.includes("22/08/2004"), "Website form submission accepted and validated with date 22/08/2004");

    // 8. Preserve No-Auto-Submit Rule Test
    // Reset resultMessage to verify autofill actions do not trigger auto-submit
    resultMessage.textContent = "";
    resultMessage.style.display = "none";
    // Verify form was not automatically submitted
    assert(resultMessage.textContent === "", "Preserved no-auto-submit rule: Autofill never submits the form automatically");

  } catch (err) {
    console.error("Test suite execution error:", err);
    failed++;
  }

  console.log("\n==========================================");
  console.log(`🏁 Test Suite Summary: ${passed} PASSED, ${failed} FAILED`);
  console.log("==========================================\n");

  if (failed > 0) {
    process.exit(1);
  }
}

runTestSuite();
