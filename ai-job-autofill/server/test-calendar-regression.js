// test-calendar-regression.js
import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";
import { JSDOM } from "jsdom";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function runCalendarRegressionTest() {
  console.log("🧪 Testing Custom Date Picker Automation on French Recruitment Form...\n");

  const htmlPath = path.join(__dirname, "french-form.html");
  const html = await fs.readFile(htmlPath, "utf-8");

  // Load in JSDOM with script execution enabled
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    url: "http://localhost:8787/french-form"
  });

  const { window } = dom;
  const { document } = window;

  const dobInput = document.getElementById("dobInput");
  const calendarPopup = document.getElementById("calendarPopup");
  const calendarYear = document.getElementById("calendarYear");
  const calendarMonth = document.getElementById("calendarMonth");
  const calendarDays = document.getElementById("calendarDays");
  const resultMessage = document.getElementById("resultMessage");

  // 1. Verify initial state matches user problem description
  console.log("Step 1: Inspecting initial calendar DOM state...");
  console.log(`  Initial dobInput.value: "${dobInput.value}"`);
  console.log(`  Initial calendarPopup class: "${calendarPopup.className}"`);
  console.log(`  Initial calendarYear.value: "${calendarYear.value}"`);
  console.log(`  Initial calendarMonth.value: "${calendarMonth.value}"`);

  if (dobInput.value !== "Sélectionner une date") {
    throw new Error(`Expected initial placeholder 'Sélectionner une date', got '${dobInput.value}'`);
  }
  if (calendarPopup.classList.contains("open")) {
    throw new Error("Calendar should initially be closed");
  }
  if (calendarYear.value !== "2026") {
    throw new Error(`Expected initial calendar year 2026, got ${calendarYear.value}`);
  }
  if (calendarMonth.value !== "8") {
    throw new Error(`Expected initial calendar month 8 (Septembre), got ${calendarMonth.value}`);
  }

  // Verify form rejection when unselected
  window.submitForm();
  if (!resultMessage.textContent.includes("Erreur")) {
    throw new Error(`Form should reject initial placeholder, got: ${resultMessage.textContent}`);
  }
  console.log(`  ✅ Verified initial form rejects submission with placeholder: "${resultMessage.textContent}"`);

  // 2. Open the date picker
  console.log("\nStep 2: Opening the date picker...");
  dobInput.dispatchEvent(new window.MouseEvent("click", { bubbles: true, cancelable: true }));
  if (!calendarPopup.classList.contains("open")) {
    throw new Error("Calendar popup should be open after clicking dobInput");
  }
  console.log(`  ✅ Calendar popup opened successfully (class: "${calendarPopup.className}")`);

  // 3. Select Year 2004
  console.log("\nStep 3: Selecting Year 2004 using calendar's actual controls...");
  const yearOpt = Array.from(calendarYear.options).find(o => o.value === "2004");
  if (!yearOpt) {
    throw new Error("Option 2004 not found in calendarYear");
  }
  calendarYear.value = "2004";
  calendarYear.dispatchEvent(new window.Event("change", { bubbles: true }));
  calendarYear.dispatchEvent(new window.Event("input", { bubbles: true }));

  // Wait for view to update
  await new Promise(r => setTimeout(r, 60));
  console.log(`  ✅ Selected year: ${calendarYear.value}`);

  // 4. Select Month August (Août)
  console.log("\nStep 4: Selecting Month August (Août) using calendar's actual controls...");
  const monthOpt = Array.from(calendarMonth.options).find(o => /(ao[uû]t|aug)/i.test(o.textContent.trim()) || o.value === "7");
  if (!monthOpt) {
    throw new Error("August / Août option not found in calendarMonth");
  }
  calendarMonth.value = monthOpt.value;
  calendarMonth.dispatchEvent(new window.Event("change", { bubbles: true }));
  calendarMonth.dispatchEvent(new window.Event("input", { bubbles: true }));

  // Wait for view to update
  await new Promise(r => setTimeout(r, 60));
  console.log(`  ✅ Selected month: ${calendarMonth.options[calendarMonth.selectedIndex].textContent} (value: ${calendarMonth.value})`);

  // 5. Select Day 22
  console.log("\nStep 5: Selecting Day 22 using day grid buttons...");
  const dayButtons = Array.from(calendarDays.querySelectorAll("button, [data-day]")).filter(b => {
    const t = b.textContent.trim();
    const is22 = t === "22" || b.dataset.day === "22";
    const isOther = b.classList.contains("other-month") || b.classList.contains("disabled");
    return is22 && !isOther;
  });

  if (dayButtons.length === 0) {
    throw new Error("Day 22 button not found in August 2004 day grid");
  }

  const day22Btn = dayButtons[0];
  day22Btn.dispatchEvent(new window.MouseEvent("mousedown", { bubbles: true, cancelable: true }));
  day22Btn.dispatchEvent(new window.MouseEvent("mouseup", { bubbles: true, cancelable: true }));
  day22Btn.click();

  // Wait for selection to apply
  await new Promise(r => setTimeout(r, 60));
  console.log(`  ✅ Clicked day 22 button`);

  // 6. Confirm visible date field changed and form state accepted the date
  console.log("\nStep 6: Verifying visible date field and form state...");
  console.log(`  dobInput.value: "${dobInput.value}"`);
  console.log(`  dobInput.dataset.acceptedDate: "${dobInput.dataset.acceptedDate}"`);

  if (dobInput.value === "Sélectionner une date") {
    throw new Error("dobInput still shows placeholder 'Sélectionner une date'!");
  }
  if (dobInput.value !== "22/08/2004") {
    throw new Error(`Expected dobInput.value '22/08/2004', got '${dobInput.value}'`);
  }
  if (dobInput.dataset.acceptedDate !== "22/08/2004") {
    throw new Error(`Expected dataset.acceptedDate '22/08/2004', got '${dobInput.dataset.acceptedDate}'`);
  }
  console.log(`  ✅ Confirmed visible field changed to: "${dobInput.value}"`);
  console.log(`  ✅ Confirmed dataset.acceptedDate: "${dobInput.dataset.acceptedDate}"`);

  // 7. Verify the website's form submission state accepts the date
  console.log("\nStep 7: Verifying website form submission state...");
  window.submitForm();
  console.log(`  resultMessage text: "${resultMessage.textContent}"`);
  if (!resultMessage.textContent.includes("Succès") || !resultMessage.textContent.includes("22/08/2004")) {
    throw new Error(`Form did not accept submission! Message: ${resultMessage.textContent}`);
  }
  console.log(`  ✅ Form successfully accepted and validated: "${resultMessage.textContent}"`);

  // 8. Confirm popup closed after day selection
  if (calendarPopup.classList.contains("open")) {
    throw new Error("Calendar popup should close after selecting a date");
  }
  console.log(`  ✅ Calendar popup closed cleanly after selection`);

  console.log("\n🎉 ALL CUSTOM DATE PICKER REGRESSION CHECKS PASSED!\n");
}

runCalendarRegressionTest().catch(err => {
  console.error("❌ Test Failed:", err);
  process.exit(1);
});
