import {
  getApp,
  getApps,
  initializeApp,
} from "https://www.gstatic.com/firebasejs/12.7.0/firebase-app.js";
import {
  collection,
  deleteDoc,
  doc,
  getDocs,
  getFirestore,
} from "https://www.gstatic.com/firebasejs/12.7.0/firebase-firestore.js";

const firebaseConfig = {
  apiKey: "AIzaSyD3xQalpdCJZK2GNCYRP8noiY5ei6oOtFw",
  authDomain: "clients-9d7fe.firebaseapp.com",
  projectId: "clients-9d7fe",
  storageBucket: "clients-9d7fe.firebasestorage.app",
  messagingSenderId: "489647859812",
  appId: "1:489647859812:web:6f0f06a20beef2ea6a9771",
};

const section = document.getElementById("firebase-section");
const cardsRoot = document.getElementById("firebase-cards");

if (!section || !cardsRoot) {
  throw new Error("Firebase dashboard container not found.");
}

const firebaseAppName = "dashboard-firebase";
const firebaseApp = getApps().some((entry) => entry.name === firebaseAppName)
  ? getApp(firebaseAppName)
  : initializeApp(firebaseConfig, firebaseAppName);
const db = getFirestore(firebaseApp);

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toMillis(value) {
  if (!value) {
    return 0;
  }

  if (typeof value.toMillis === "function") {
    try {
      return value.toMillis();
    } catch (error) {
      console.error("Failed to read Firestore timestamp with toMillis().", error);
    }
  }

  if (typeof value.toDate === "function") {
    try {
      return value.toDate().getTime();
    } catch (error) {
      console.error("Failed to read Firestore timestamp with toDate().", error);
    }
  }

  if (typeof value.seconds === "number") {
    const nanos = typeof value.nanoseconds === "number" ? value.nanoseconds : 0;
    return (value.seconds * 1000) + Math.round(nanos / 1_000_000);
  }

  if (typeof value === "string") {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  return 0;
}

function formatCreatedAt(value) {
  const millis = toMillis(value);
  if (!millis) {
    return "k. A.";
  }

  return new Intl.DateTimeFormat("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(millis));
}

function normalizeApplication(snapshot) {
  const data = snapshot.data() || {};
  const documents = Array.isArray(data.documents) ? data.documents : [];

  return {
    id: snapshot.id,
    sourceLabel: "Firebase",
    fullName: String(data.fullName || "").trim() || "Unnamed applicant",
    email: String(data.email || "").trim() || "k. A.",
    whatsapp: String(data.whatsapp || "").trim() || "k. A.",
    bewerbungen: String(data.bewerbungen || "").trim() || "k. A.",
    bereich: String(data.bereich || "").trim() || "k. A.",
    documentCount: documents.length,
    createdAt: data.createdAt || null,
    createdAtDisplay: formatCreatedAt(data.createdAt),
    sortTime: toMillis(data.createdAt),
  };
}

function renderFirebaseCard(application) {
  return `
    <div class="card firebase-card" data-firebase-id="${escapeHtml(application.id)}" data-source="firebase">
      <h3>
        ${escapeHtml(application.fullName)}
        <span class="firebase-badge">${escapeHtml(application.sourceLabel)}</span>
      </h3>
      <div class="meta">
        Quelle: <strong>${escapeHtml(application.sourceLabel)}</strong><br>
        E-Mail: <strong>${escapeHtml(application.email)}</strong><br>
        WhatsApp: <span>${escapeHtml(application.whatsapp)}</span><br>
        Paket: <span>${escapeHtml(application.bewerbungen)}</span><br>
        Bereich: <span>${escapeHtml(application.bereich)}</span><br>
        Dokumente: <span>${escapeHtml(application.documentCount)}</span><br>
        Eingereicht: <span>${escapeHtml(application.createdAtDisplay)}</span>
      </div>
      <div class="actions">
        <button
          type="button"
          class="firebase-delete-btn"
          data-firebase-delete="${escapeHtml(application.id)}"
        >
          Löschen
        </button>
      </div>
    </div>
  `;
}

function updateSectionVisibility() {
  const cardCount = cardsRoot.querySelectorAll("[data-firebase-id]").length;
  cardsRoot.dataset.initialCount = String(cardCount);
  section.hidden = cardCount === 0;
}

function bindDeleteButtons() {
  const buttons = cardsRoot.querySelectorAll("[data-firebase-delete]");
  buttons.forEach((button) => {
    if (button.dataset.bound === "true") {
      return;
    }

    button.dataset.bound = "true";
    button.addEventListener("click", async () => {
      const applicationId = String(button.dataset.firebaseDelete || "").trim();
      const card = button.closest("[data-firebase-id]");
      if (!applicationId || !card) {
        return;
      }

      const confirmed = window.confirm(
        "Diese Firebase-Bewerbung löschen? Das kann nicht rückgängig gemacht werden.",
      );
      if (!confirmed) {
        return;
      }

      const originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Loesche...";

      try {
        await deleteDoc(doc(db, "applications", applicationId));
        card.remove();
        updateSectionVisibility();
      } catch (error) {
        console.error("Failed to delete Firebase application.", error);
        button.disabled = false;
        button.textContent = originalLabel;
        window.alert("Firebase-Bewerbung konnte nicht gelöscht werden.");
      }
    });
  });
}

async function loadFirebaseApplications() {
  try {
    const snapshot = await getDocs(collection(db, "applications"));
    const applications = snapshot.docs
      .map(normalizeApplication)
      .sort((left, right) => right.sortTime - left.sortTime);

    if (!applications.length) {
      updateSectionVisibility();
      return;
    }

    cardsRoot.innerHTML = applications.map(renderFirebaseCard).join("");
    section.hidden = false;
    bindDeleteButtons();
    updateSectionVisibility();
  } catch (error) {
    console.error("Failed to load Firebase applications for the dashboard.", error);
  }
}

bindDeleteButtons();

if (Number(cardsRoot.dataset.initialCount || 0) === 0) {
  loadFirebaseApplications();
} else {
  updateSectionVisibility();
}
