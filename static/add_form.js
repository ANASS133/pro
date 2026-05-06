import { initializeApp } from "https://www.gstatic.com/firebasejs/12.7.0/firebase-app.js";
import {
  addDoc,
  collection,
  getFirestore,
  serverTimestamp,
} from "https://www.gstatic.com/firebasejs/12.7.0/firebase-firestore.js";
import {
  getDownloadURL,
  getStorage,
  ref,
  uploadBytes,
} from "https://www.gstatic.com/firebasejs/12.7.0/firebase-storage.js";

const firebaseConfig = {
  apiKey: "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
  authDomain: "clients-9d7fe.firebaseapp.com",
  projectId: "clients-9d7fe",
  storageBucket: "clients-9d7fe.firebasestorage.app",
  messagingSenderId: "489647859812",
  appId: "1:489647859812:web:6f0f06a20beef2ea6a9771",
};

const app = initializeApp(firebaseConfig);
const db = getFirestore(app);
const storage = getStorage(app);

const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_SIZE_BYTES = 25 * 1024 * 1024;
const STORAGE_UPLOAD_TIMEOUT_MS = 120_000;
const STORAGE_DOWNLOAD_URL_TIMEOUT_MS = 30_000;

storage.maxUploadRetryTime = 120_000;
storage.maxOperationRetryTime = 30_000;

const form = document.getElementById("candidate-form");
const fileInput = document.getElementById("documents");
const fileMeta = document.getElementById("file-meta");
const statusMessage = document.getElementById("status-message");
const submitButton = form.querySelector(".submit-button");

function showStatus(message, type) {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${type}`;
}

function clearStatus() {
  statusMessage.textContent = "";
  statusMessage.className = "status-message";
}

function getSelectedLanguageLevel() {
  const selected = form.querySelector('input[name="languageLevel"]:checked');
  return selected ? selected.value : "";
}

function getBereichValue() {
  const select = document.getElementById("bereich");
  if (select) {
    return String(select.value || "").trim();
  }

  const suffixInput = document.getElementById("bereichSuffix");
  const suffix = suffixInput ? String(suffixInput.value || "").trim() : "";
  return suffix ? `ausbildung als ${suffix}` : "";
}

function formatFileSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatFilesSummary(files) {
  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  return `${files.length} file(s), ${formatFileSize(totalSize)} total`;
}

function validateFiles(files) {
  const oversizedFile = files.find((file) => file.size > MAX_FILE_SIZE_BYTES);
  if (oversizedFile) {
    return `${oversizedFile.name} is too large. Max ${formatFileSize(MAX_FILE_SIZE_BYTES)} per file.`;
  }

  const totalSize = files.reduce((sum, file) => sum + file.size, 0);
  if (totalSize > MAX_TOTAL_SIZE_BYTES) {
    return `Selected files are too large. Max ${formatFileSize(MAX_TOTAL_SIZE_BYTES)} total.`;
  }

  return "";
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

function humanizeFirebaseError(error) {
  switch (error?.code) {
    case "permission-denied":
    case "storage/unauthorized":
      return "Firebase permissions are blocking the request.";
    case "storage/canceled":
      return "The file upload was canceled.";
    case "storage/retry-limit-exceeded":
      return "Firebase Storage stopped retrying.";
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

async function uploadFileToFirebase(file, submissionId) {
  const safeName = sanitizeFileName(file.name);
  const storagePath = `applications/${submissionId}/${Date.now()}-${safeName}`;
  const storageRef = ref(storage, storagePath);
  const metadata = file.type ? { contentType: file.type } : undefined;

  await withTimeout(
    uploadBytes(storageRef, file, metadata),
    STORAGE_UPLOAD_TIMEOUT_MS,
    "The file upload stayed pending for too long.",
  );

  const downloadURL = await withTimeout(
    getDownloadURL(storageRef),
    STORAGE_DOWNLOAD_URL_TIMEOUT_MS,
    "The file was uploaded, but no download URL was returned in time.",
  );

  return {
    name: file.name,
    size: file.size,
    contentType: file.type || "",
    storagePath,
    downloadURL,
  };
}

function setSubmitting(isSubmitting) {
  submitButton.disabled = isSubmitting;
  submitButton.textContent = isSubmitting ? "Saving..." : "إرسال الاستمارة";
}

function refreshFileMeta() {
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    fileMeta.textContent = "Keine Datei ausgewählt";
    clearStatus();
    return;
  }

  const validationError = validateFiles(files);
  if (validationError) {
    fileMeta.textContent = validationError;
    showStatus(validationError, "error");
    return;
  }

  fileMeta.textContent = formatFilesSummary(files);
}

async function handleSubmission() {
  if (!form.reportValidity()) {
    showStatus("Please complete all required fields before submitting.", "error");
    return;
  }

  const languageLevel = getSelectedLanguageLevel();
  if (!languageLevel) {
    showStatus("Please select B1 or B2.", "error");
    return;
  }

  const files = Array.from(fileInput.files || []);
  const validationError = validateFiles(files);
  if (validationError) {
    showStatus(validationError, "error");
    return;
  }

  const submissionId = createSubmissionId();
  const payload = {
    submissionId,
    fullName: document.getElementById("fullName").value.trim(),
    email: document.getElementById("email").value.trim(),
    whatsapp: document.getElementById("whatsapp").value.trim(),
    bank: document.getElementById("bank").value.trim(),
    languageLevel,
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

    const docRef = await addDoc(collection(db, "applications"), {
      ...payload,
      documents: uploadedDocuments,
      createdAt: serverTimestamp(),
      uploadStatus: uploadError ? "files-failed" : "completed",
      uploadError,
    });

    form.reset();
    refreshFileMeta();

    if (uploadError) {
      showStatus(
        `Saved form data to Firebase. File upload failed: ${humanizeFirebaseError(uploadError)} Record ID: ${docRef.id}`,
        "error",
      );
      return;
    }

    showStatus("تم الحفظ بنجاح.", "success");
  } catch (error) {
    console.error("Firebase save failed", error);
    showStatus(`Firebase save failed. ${humanizeFirebaseError(error)}`, "error");
  } finally {
    setSubmitting(false);
  }
}

fileInput.addEventListener("change", refreshFileMeta);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  await handleSubmission();
});

refreshFileMeta();
