// test-documents.js - Comprehensive test suite for per-applicant document management
import fs from "fs/promises";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const BASE_URL = "http://localhost:8787";

async function setupFixtures() {
  const profilesDir = path.join(__dirname, "profiles");
  await fs.mkdir(profilesDir, { recursive: true });

  // 1. Ensure Chamss.json
  const chamssJsonPath = path.join(profilesDir, "Chamss.json");
  try {
    await fs.access(chamssJsonPath);
  } catch {
    const boumlikPath = path.join(profilesDir, "Boumlik_Chamseddine.json");
    try {
      const data = await fs.readFile(boumlikPath, "utf-8");
      await fs.writeFile(chamssJsonPath, data, "utf-8");
    } catch {
      await fs.writeFile(chamssJsonPath, JSON.stringify({ applicant: { personal: { first_name: "Chamss", last_name: "Boumlik" } } }, null, 2));
    }
  }

  // 2. Ensure anass_sibbi.json
  const anassJsonPath = path.join(profilesDir, "anass_sibbi.json");
  try {
    await fs.access(anassJsonPath);
  } catch {
    await fs.writeFile(anassJsonPath, JSON.stringify({ applicant: { personal: { first_name: "Anass", last_name: "Sibbi" } } }, null, 2));
  }

  // 3. Ensure Chamss folder with test documents
  const chamssDir = path.join(profilesDir, "Chamss");
  await fs.mkdir(chamssDir, { recursive: true });

  const dummyDocs = [
    { name: "CV.pdf", content: "%PDF-1.4 dummy pdf" },
    { name: "les notes.jpeg", content: "dummy image" },
    { name: "certificat de réussit.jpeg", content: "dummy image" },
    { name: "cin recto.jpeg", content: "dummy image" },
    { name: "cin verso.jpeg", content: "dummy image" }
  ];

  for (const doc of dummyDocs) {
    const p = path.join(chamssDir, doc.name);
    try {
      await fs.access(p);
    } catch {
      await fs.writeFile(p, doc.content);
    }
  }
}

async function runTests() {
  console.log("🧪 Starting Automated Document Management & Mapping Tests...\n");
  let passed = 0;
  let failed = 0;

  await setupFixtures();

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
    // 1. Test GET /api/profiles (lists profiles and ensures matching folder creation)
    console.log("▶️ Test 1: Profiles listing and matching folder creation");
    const profilesRes = await fetch(`${BASE_URL}/api/profiles`);
    const profilesData = await profilesRes.json();
    assert(profilesData.success === true, "Profiles endpoint returns success");
    assert(profilesData.profiles.some(p => p.id === "Chamss"), "Profile 'Chamss' is listed");
    assert(profilesData.profiles.some(p => p.id === "anass_sibbi"), "Profile 'anass_sibbi' is listed");

    // 2. Test GET /api/profiles/Chamss/documents (Document detection & types)
    console.log("\n▶️ Test 2: Document detection and categorization for 'Chamss'");
    const chamssDocsRes = await fetch(`${BASE_URL}/api/profiles/Chamss/documents`);
    const chamssDocs = await chamssDocsRes.json();
    assert(chamssDocs.success === true, "Chamss documents endpoint returns success");
    assert(chamssDocs.hasFolder === true, "Chamss has matching document folder");
    assert(chamssDocs.documents.length >= 4, `Chamss has at least 4 documents (found ${chamssDocs.documents.length})`);

    const cvDoc = chamssDocs.documents.find(d => d.type === "cv");
    assert(Boolean(cvDoc && cvDoc.fileName === "CV.pdf"), "CV.pdf is correctly detected as type 'cv'");

    const trDoc = chamssDocs.documents.find(d => d.type === "transcript");
    assert(Boolean(trDoc && trDoc.fileName === "les notes.jpeg"), "'les notes.jpeg' is correctly detected as type 'transcript'");

    const certDoc = chamssDocs.documents.find(d => d.type === "certificate");
    assert(Boolean(certDoc && certDoc.fileName === "certificat de réussit.jpeg"), "'certificat de réussit.jpeg' is correctly detected as type 'certificate'");

    const idFrontDoc = chamssDocs.documents.find(d => d.type === "id_front");
    assert(Boolean(idFrontDoc && idFrontDoc.isSensitive === true), "'cin recto.jpeg' is detected as sensitive id_front");

    const idBackDoc = chamssDocs.documents.find(d => d.type === "id_back");
    assert(Boolean(idBackDoc && idBackDoc.isSensitive === true), "'cin verso.jpeg' is detected as sensitive id_back");

    // 3. Test Non-mixing of documents across profiles
    console.log("\n▶️ Test 3: Document isolation between profiles");
    const anassDocsRes = await fetch(`${BASE_URL}/api/profiles/anass_sibbi/documents`);
    const anassDocs = await anassDocsRes.json();
    assert(anassDocs.success === true, "anass_sibbi documents endpoint returns success");
    const hasChamssFileInAnass = anassDocs.documents.some(d => d.fileName === "CV.pdf");
    assert(!hasChamssFileInAnass, "Chamss documents do NOT bleed or mix into anass_sibbi folder");

    // 4. Test Path Traversal Protection
    console.log("\n▶️ Test 4: Path traversal & unsafe filename security");
    const traversalRes1 = await fetch(`${BASE_URL}/api/profiles/..%2F../documents`);
    assert(traversalRes1.status === 400, "Blocked root traversal attempt with HTTP 400");

    const traversalRes2 = await fetch(`${BASE_URL}/api/profiles/Chamss/documents/..%2F..%2Fserver.js/preview`);
    assert(traversalRes2.status === 400 || traversalRes2.status === 404, "Blocked file traversal attempt with HTTP 400/404");

    // 5. Test Document Preview Header
    console.log("\n▶️ Test 5: Document preview inline headers");
    const previewRes = await fetch(`${BASE_URL}/api/profiles/Chamss/documents/CV.pdf/preview`);
    assert(previewRes.status === 200, "Preview returns status 200");
    assert(previewRes.headers.get("content-type") === "application/pdf", "Preview returns Content-Type application/pdf");
    assert((previewRes.headers.get("content-disposition") || "").includes("inline"), "Preview returns Content-Disposition inline");

    // 6. Test Document Upload Endpoint
    console.log("\n▶️ Test 6: Document upload into applicant folder");
    const testDocContent = Buffer.from("Dummy test diploma content for verification").toString("base64");
    const uploadRes = await fetch(`${BASE_URL}/api/profiles/Chamss/documents`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "test_bachelor_diploma.pdf",
        contentBase64: testDocContent
      })
    });
    const uploadData = await uploadRes.json();
    assert(uploadData.success === true, "Upload endpoint returns success");
    assert(uploadData.uploaded.includes("test_bachelor_diploma.pdf"), "Uploaded file name returned in list");

    // Verify file is now in Chamss documents
    const verifyDocsRes = await fetch(`${BASE_URL}/api/profiles/Chamss/documents`);
    const verifyDocs = await verifyDocsRes.json();
    const uploadedInList = verifyDocs.documents.find(d => d.fileName === "test_bachelor_diploma.pdf");
    assert(Boolean(uploadedInList && uploadedInList.type === "diploma"), "Uploaded file appears in applicant document list with type 'diploma'");

    // 7. Test Field Mapping & File Upload Proposals
    console.log("\n▶️ Test 7: Form field mapping with file upload proposal & sensitive blocking");
    const testFields = [
      { field_id: "f_cv", type: "file", label: "Upload your CV / Resume (PDF)", accept: ".pdf" },
      { field_id: "f_transcript", type: "file", label: "Relevé de notes / Transcripts" },
      { field_id: "f_id", type: "file", label: "National ID Card / CIN / Passport" }
    ];

    const mapRes = await fetch(`${BASE_URL}/api/map-fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        profileId: "Chamss",
        fields: testFields
      })
    });
    const mapData = await mapRes.json();
    assert(mapData.success === true, "Field mapping endpoint returns success");

    const cvAction = mapData.actions.find(a => a.field_id === "f_cv");
    assert(Boolean(cvAction && cvAction.action === "propose_upload" && cvAction.proposed_file?.fileName === "CV.pdf"), "CV field proposed matching CV.pdf with propose_upload action");

    const transcriptAction = mapData.actions.find(a => a.field_id === "f_transcript");
    assert(Boolean(transcriptAction && transcriptAction.action === "propose_upload" && transcriptAction.proposed_file?.fileName === "les notes.jpeg"), "Transcript field proposed matching 'les notes.jpeg'");

    const idAction = mapData.actions.find(a => a.field_id === "f_id");
    assert(Boolean(idAction && idAction.action === "review" && idAction.proposed_file === null), "National ID / CIN field is strictly marked as 'review' with proposed_file: null (NEVER auto-uploaded)");

    // 8. Test JSON Template Endpoint
    console.log("\n▶️ Test 8: JSON Template availability");
    const templateRes = await fetch(`${BASE_URL}/api/template`);
    const templateData = await templateRes.json();
    assert(templateData.success === true && templateData.formattedJson.length > 500, "JSON Template endpoint works and returns clean formatted template");

  } catch (err) {
    console.error("Test execution error:", err);
    failed++;
  }

  console.log("\n==========================================");
  console.log(`🏁 Test Summary: ${passed} PASSED, ${failed} FAILED`);
  console.log("==========================================\n");

  if (failed > 0) {
    process.exit(1);
  }
}

runTests();
