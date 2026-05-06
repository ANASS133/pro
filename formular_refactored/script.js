const firebaseConfig = {
  apiKey: "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
  authDomain: "clients-9d7fe.firebaseapp.com",
  projectId: "clients-9d7fe",
  storageBucket: "clients-9d7fe.firebasestorage.app",
  messagingSenderId: "489647859812",
  appId: "1:489647859812:web:6f0f06a20beef2ea6a9771",
};

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_SIZE_BYTES = 25 * 1024 * 1024;
const BEREICH_PREFIX = "ausbildung als";
const STORAGE_UPLOAD_TIMEOUT_MS = 120_000;
const STORAGE_DOWNLOAD_URL_TIMEOUT_MS = 30_000;

const form = document.getElementById("candidate-form");
const fileInput = document.getElementById("documents");
const fileList = document.getElementById("file-list");
const uploadBox = document.getElementById("upload-box");
const uploadCopy = uploadBox.querySelector(".upload-copy");
const uploadTitle = uploadBox.querySelector("strong");
const submitButton = form.querySelector(".submit-button");
const statusMessage = document.getElementById("status-message");
const languageChoiceCards = Array.from(form.querySelectorAll(".choice-card"));
const languageInputs = Array.from(form.querySelectorAll('input[name="languageLevel"]'));
const languageProof = document.getElementById("language-proof");

let selectedFiles = [];
let firebaseInitError = null;
let db = null;
let storageServices = [];

function getStorageBucketCandidates(bucketName) {
  const normalized = String(bucketName || "").trim();
  const candidates = [];

  if (normalized) {
    candidates.push(normalized);
  }

  if (normalized.endsWith(".firebasestorage.app")) {
    candidates.push(normalized.replace(/\.firebasestorage\.app$/i, ".appspot.com"));
  }

  return Array.from(new Set(candidates.filter(Boolean)));
}

try {
  if (!window.firebase) {
    throw new Error("Firebase SDK is not available on this page.");
  }

  if (!window.firebase.apps.length) {
    window.firebase.initializeApp(firebaseConfig);
  }

  db = window.firebase.firestore();
  storageServices = getStorageBucketCandidates(firebaseConfig.storageBucket).map((bucketName) =>
    window.firebase.app().storage(`gs://${bucketName}`),
  );
  if (!storageServices.length) {
    storageServices = [window.firebase.storage()];
  }
  storageServices.forEach((storageService) => {
    storageService.maxUploadRetryTime = 120_000;
    storageService.maxOperationRetryTime = 30_000;
  });
} catch (error) {
  firebaseInitError = error;
  console.error("Firebase initialization failed", error);
}

function setFieldError(element, message) {
  element.setCustomValidity(message);
}

function clearFieldError(element) {
  element.setCustomValidity("");
}

function clearLanguageError() {
  languageInputs.forEach(clearFieldError);
}

function getSelectedLanguageLevel() {
  const selected = form.querySelector('input[name="languageLevel"]:checked');
  return selected ? selected.value : "";
}

function getBereichValue() {
  const suffix = document.getElementById("bereichSuffix").value.trim();
  return suffix ? `${BEREICH_PREFIX} ${suffix}` : "";
}

function updateLanguageProof(value, animate = false) {
  if (!languageProof) {
    return;
  }

  languageProof.textContent = value ? `Selected: ${value}` : "";
  languageProof.classList.toggle("is-visible", Boolean(value));

  if (animate && value) {
    languageProof.classList.remove("is-animating");
    void languageProof.offsetWidth;
    languageProof.classList.add("is-animating");
  }
}

function syncLanguageChoices() {
  languageChoiceCards.forEach((card) => {
    const input = card.querySelector('input[name="languageLevel"]');
    const isSelected = Boolean(input && input.checked);
    card.classList.toggle("is-selected", isSelected);

    if (!isSelected) {
      card.classList.remove("is-animating");
    }
  });

  updateLanguageProof(getSelectedLanguageLevel());
}

function selectLanguageChoice(input) {
  if (!input) {
    return;
  }

  input.checked = true;
  clearLanguageError();
  languageChoiceCards.forEach((card) => {
    card.classList.remove("is-animating");
  });
  syncLanguageChoices();

  const card = input.closest(".choice-card");
  if (card) {
    void card.offsetWidth;
    card.classList.add("is-animating");
  }

  updateLanguageProof(input.value, true);
}

function formatFileSize(size) {
  if (typeof size !== "number" || Number.isNaN(size) || size < 0) {
    return "Unknown size";
  }

  if (size < 1024) {
    return `${size} B`;
  }

  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatFilesSummary(files) {
  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  return `${files.length} file(s), ${formatFileSize(totalSize)} total`;
}

function createSubmissionId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }

  return `submission-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function sanitizeFileName(fileName) {
  return fileName.replace(/[^a-zA-Z0-9._-]+/g, "-");
}

function humanizeFirebaseError(error) {
  switch (error?.code) {
    case "permission-denied":
    case "storage/unauthorized":
      return "Firebase permissions are blocking the request. Check Firestore and Storage rules.";
    case "storage/canceled":
      return "The file upload was canceled.";
    case "storage/retry-limit-exceeded":
      return "Firebase Storage stopped retrying. Check that Storage is enabled, the bucket is correct, and your connection is stable.";
    case "storage/quota-exceeded":
      return "The Firebase Storage quota has been exceeded.";
    case "unavailable":
      return "Firebase is temporarily unavailable.";
    case "upload-timeout":
      return "The upload took too long and timed out.";
    default:
      return error?.message || "An unexpected Firebase error occurred.";
  }
}

function withTimeout(promise, timeoutMs, message) {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      const error = new Error(message);
      error.code = "upload-timeout";
      reject(error);
    }, timeoutMs);

    promise
      .then((value) => {
        window.clearTimeout(timer);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
  });
}

function validateFiles(files) {
  const oversizedFile = files.find((file) => file.size > MAX_FILE_SIZE_BYTES);
  if (oversizedFile) {
    return {
      valid: false,
      message: `${oversizedFile.name} is too large. The max size is ${formatFileSize(MAX_FILE_SIZE_BYTES)} per file.`,
    };
  }

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  if (totalSize > MAX_TOTAL_SIZE_BYTES) {
    return {
      valid: false,
      message: `The selected files are too large. The total max size is ${formatFileSize(MAX_TOTAL_SIZE_BYTES)}.`,
    };
  }

  return { valid: true, message: "" };
}

function syncFileInput(files) {
  try {
    if (typeof window.DataTransfer !== "function") {
      throw new Error("DataTransfer is not supported.");
    }

    const dataTransfer = new window.DataTransfer();
    files.forEach((file) => {
      dataTransfer.items.add(file);
    });
    fileInput.files = dataTransfer.files;
  } catch (_error) {
    if (!files.length) {
      fileInput.value = "";
    }
  }
}

function renderFiles() {
  fileList.innerHTML = "";
  uploadBox.classList.toggle("has-files", selectedFiles.length > 0);

  if (!selectedFiles.length) {
    uploadTitle.textContent = "اختر الملفات";
    uploadCopy.textContent = "اضغط لاختيار الملفات أو اسحبها إلى هذه المساحة.";

    const emptyState = document.createElement("div");
    emptyState.className = "file-empty";
    emptyState.textContent = "No files selected yet.";
    fileList.appendChild(emptyState);
    return;
  }

  uploadTitle.textContent = selectedFiles.length === 1
    ? "تم اختيار ملف واحد"
    : `تم اختيار ${selectedFiles.length} ملفات`;
  uploadCopy.textContent = `Ready to upload: ${formatFilesSummary(selectedFiles)}.`;

  selectedFiles.forEach((file) => {
    const extension = file.name.includes(".")
      ? file.name.split(".").pop().slice(0, 4)
      : "file";

    const item = document.createElement("div");
    const icon = document.createElement("div");
    const meta = document.createElement("div");
    const name = document.createElement("strong");
    const size = document.createElement("span");

    item.className = "file-item";
    icon.className = "file-icon";
    meta.className = "file-meta";
    name.className = "file-name";
    size.className = "file-size";

    icon.textContent = extension;
    name.textContent = file.name;
    size.textContent = formatFileSize(file.size);

    meta.append(name, size);
    item.append(icon, meta);
    fileList.appendChild(item);
  });
}

function showStatus(message, type) {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${type}`;
}

function clearStatus() {
  statusMessage.textContent = "";
  statusMessage.className = "status-message";
}

function validateRequiredFields() {
  const fullName = document.getElementById("fullName");
  const email = document.getElementById("email");
  const whatsapp = document.getElementById("whatsapp");
  const bank = document.getElementById("bank");
  const bereichSuffix = document.getElementById("bereichSuffix");
  const bewerbungen = document.getElementById("bewerbungen");

  [
    fullName,
    email,
    whatsapp,
    bank,
    bereichSuffix,
    bewerbungen,
    ...languageInputs,
  ].forEach(clearFieldError);

  if (!fullName.value.trim()) {
    setFieldError(fullName, "Please enter the full name.");
    fullName.reportValidity();
    return false;
  }

  if (!email.value.trim()) {
    setFieldError(email, "Please enter the email address.");
    email.reportValidity();
    return false;
  }

  if (!whatsapp.value.trim()) {
    setFieldError(whatsapp, "Please enter the WhatsApp number.");
    whatsapp.reportValidity();
    return false;
  }

  if (!bank.value.trim()) {
    setFieldError(bank, "Please select a bank.");
    bank.reportValidity();
    return false;
  }

  if (!getSelectedLanguageLevel()) {
    setFieldError(languageInputs[0], "Please select B1 or B2.");
    languageInputs[0].reportValidity();
    languageInputs[0].focus();
    return false;
  }

  if (!bereichSuffix.value.trim()) {
    setFieldError(bereichSuffix, "Please enter the field after 'ausbildung als'.");
    bereichSuffix.reportValidity();
    return false;
  }

  if (!bewerbungen.value.trim()) {
    setFieldError(bewerbungen, "Please select the package.");
    bewerbungen.reportValidity();
    return false;
  }

  return true;
}

function setSubmitting(isSubmitting) {
  submitButton.disabled = isSubmitting;
  submitButton.textContent = isSubmitting
    ? "sending"
    : "إرسال الاستمارة";
}

function setFiles(files) {
  const normalizedFiles = Array.from(files || []);
  const validation = validateFiles(normalizedFiles);

  if (!validation.valid) {
    fileInput.setCustomValidity(validation.message);
    syncFileInput(selectedFiles);
    renderFiles();
    showStatus(validation.message, "error");
    return false;
  }

  fileInput.setCustomValidity("");
  selectedFiles = normalizedFiles;
  syncFileInput(selectedFiles);
  renderFiles();

  if (selectedFiles.length) {
    showStatus(`Files ready: ${formatFilesSummary(selectedFiles)}.`, "loading");
  } else {
    clearStatus();
  }

  return true;
}

async function uploadFileToFirebase(file, submissionId) {
  if (!storageServices.length) {
    throw firebaseInitError || new Error("Firebase Storage is not available.");
  }

  const safeName = sanitizeFileName(file.name);
  const storagePath = `applications/${submissionId}/${Date.now()}-${safeName}`;
  const metadata = file.type ? { contentType: file.type } : undefined;
  let lastError = null;

  for (const storageService of storageServices) {
    try {
      const storageRef = storageService.ref(storagePath);

      await withTimeout(
        storageRef.put(file, metadata),
        STORAGE_UPLOAD_TIMEOUT_MS,
        "The file upload stayed pending for too long. Check Firebase Storage and your connection.",
      );

      const downloadURL = await withTimeout(
        storageRef.getDownloadURL(),
        STORAGE_DOWNLOAD_URL_TIMEOUT_MS,
        "The file was uploaded, but Firebase did not return a download URL in time.",
      );

      return {
        name: file.name,
        size: file.size,
        contentType: file.type || "",
        storagePath,
        downloadURL,
      };
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error("The file upload failed.");
}

function resetFormState() {
  form.reset();
  selectedFiles = [];
  fileInput.setCustomValidity("");
  syncFileInput(selectedFiles);
  syncLanguageChoices();
  renderFiles();
}

async function handleSubmission() {
  if (firebaseInitError || !db || !storageServices.length) {
    showStatus(
      `Firebase initialization failed. ${humanizeFirebaseError(firebaseInitError)}`,
      "error",
    );
    return;
  }

  if (!validateRequiredFields() || !form.checkValidity()) {
    showStatus("Please complete all required fields before submitting.", "error");
    form.reportValidity();
    return;
  }

  const files = selectedFiles;
  const submissionId = createSubmissionId();
  const payload = {
    submissionId,
    fullName: document.getElementById("fullName").value.trim(),
    email: document.getElementById("email").value.trim(),
    whatsapp: document.getElementById("whatsapp").value.trim(),
    bank: document.getElementById("bank").value.trim(),
    languageLevel: getSelectedLanguageLevel(),
    bereich: getBereichValue(),
    bewerbungen: document.getElementById("bewerbungen").value.trim(),
  };

  setSubmitting(true);

  try {
    const uploadedDocuments = [];
    let uploadError = null;

    for (let index = 0; index < files.length; index += 1) {
      showStatus(`Uploading file ${index + 1} of ${files.length}...`, "loading");

      try {
        uploadedDocuments.push(await uploadFileToFirebase(files[index], submissionId));
      } catch (error) {
        uploadError = {
          code: error?.code || "unknown",
          message: error?.message || "Unknown Firebase upload error",
        };
        break;
      }
    }

    showStatus("Saving...", "loading");

    const docRef = await db.collection("applications").add({
      ...payload,
      documents: uploadedDocuments,
      createdAt: window.firebase.firestore.FieldValue.serverTimestamp(),
      uploadStatus: uploadError ? "files-failed" : "completed",
      uploadError,
    });

    resetFormState();

    if (uploadError) {
      showStatus(
        `Saved form data to Firebase. File upload failed: ${humanizeFirebaseError(uploadError)} Record ID: ${docRef.id}`,
        "error",
      );
      return;
    }

    showStatus(`.تم الحفظ بنجاح`, "success");
  } catch (error) {
    console.error("Firebase save failed", {
      code: error?.code,
      message: error?.message,
      serverResponse: error?.serverResponse,
      stack: error?.stack,
    });

    showStatus(`Firebase save failed. ${humanizeFirebaseError(error)}`, "error");
  } finally {
    setSubmitting(false);
  }
}

form.addEventListener("change", (event) => {
  if (event.target === fileInput) {
    return;
  }

  if (event.target instanceof HTMLInputElement && event.target.name === "languageLevel") {
    clearLanguageError();
    syncLanguageChoices();
    return;
  }

  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
    clearFieldError(event.target);
  }

  syncLanguageChoices();
});

form.addEventListener("input", (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
    clearFieldError(event.target);
  }
});

fileInput.addEventListener("change", () => {
  setFiles(fileInput.files);
});

uploadBox.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }

  event.preventDefault();
  fileInput.click();
});

languageChoiceCards.forEach((card) => {
  card.addEventListener("click", () => {
    selectLanguageChoice(card.querySelector('input[name="languageLevel"]'));
  });
});

languageInputs.forEach((input) => {
  input.addEventListener("change", () => {
    selectLanguageChoice(input);
  });
});

uploadBox.addEventListener("dragover", (event) => {
  event.preventDefault();
  uploadBox.classList.add("is-dragover");
});

uploadBox.addEventListener("dragleave", () => {
  uploadBox.classList.remove("is-dragover");
});

uploadBox.addEventListener("drop", (event) => {
  event.preventDefault();
  uploadBox.classList.remove("is-dragover");

  if (event.dataTransfer?.files?.length) {
    setFiles(event.dataTransfer.files);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await handleSubmission();
});

syncLanguageChoices();
renderFiles();
