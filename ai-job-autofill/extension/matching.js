// Shared deterministic helpers. No profile data is stored in the page.
(() => {
  const normalize = value => String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[_-]/g, " ").replace(/\s+/g, " ").trim();
  const clues = f => normalize([f.label, f.name, f.id, f.accessible_name, f.nearby_question].filter(Boolean).join(" "));
  const protectedField = f => /privacy|datenschutz|consent|terms|\bagb\b|bedingungen|richtlinien|einwilligung|accord|confidentialit|criminal|vorstraf|casier|disability|behinder|health|gesundheit|handicap|religion|political|work permit|arbeitserlaubnis|visa|autoris/.test(clues(f));
  const ready = (a, f = {}) => a.action !== "propose_upload" && f.type !== "file" && !protectedField(f) && !String(a.profile_source_path || "").startsWith("legal.") && ((a.proposed_value != null && String(a.proposed_value).trim() !== "") || typeof a.checked === "boolean" && a.action === "fill");

  function datePart(f) {
    const text = clues(f);
    if (!/birth|dob|geburt|naissance/.test(text + " " + normalize(f.section_heading))) return null;
    const own = normalize([f.name, f.id, f.label, f.placeholder].filter(Boolean).join(" ")).replace(/birth|dob|geburts/g, " ");
    if (/\b(day|tag|jour|dd|jj)\b/.test(own)) return "day";
    if (/\b(month|monat|mois|mm)\b/.test(own)) return "month";
    if (/\b(year|jahr|annee|yyyy|aaaa)\b/.test(own)) return "year";
    return null;
  }
  function birthValue(f, iso) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(iso || "")) return null;
    const [year, month, day] = iso.split("-");
    const date = new Date(`${iso}T12:00:00Z`);
    if (Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== iso) return null;
    const part = datePart(f);
    if (!part) return iso;
    const value = { year, month, day }[part];
    const options = f.options || [];
    // Prefer visible numbers/month names over opaque or zero-based option values.
    const names = part === "month" ? ["en", "de", "fr"].flatMap(locale => ["long", "short"].map(style => normalize(new Intl.DateTimeFormat(locale, { month: style, timeZone: "UTC" }).format(date)).replace(/\.$/, ""))) : [];
    const option = options.find(o => Number(o.text) === Number(value) || names.includes(normalize(o.text).replace(/\.$/, ""))) || options.find(o => String(o.value) === value || String(o.value) === String(Number(value)));
    return option ? option.value : String(Number(value));
  }
  function phoneValue(f, variants = {}) {
    let values = [variants.e164, variants.international, variants.national, variants.national_digits, variants.original].filter(Boolean);
    const ph = String(f.placeholder || "").trim();
    if (/^0[^0]/.test(ph)) values = [variants.national_digits, variants.national, ...values].filter(Boolean);
    else if (/^\+.*\s/.test(ph)) values = [variants.international, ...values].filter(Boolean);
    const v = f.validation || {};
    return values.find(value => {
      if (v.maxLength && value.length > v.maxLength || v.minLength && value.length < v.minLength) return false;
      try { return !v.pattern || new RegExp(`^(?:${v.pattern})$`, "v").test(value); } catch { return true; }
    }) || null;
  }
  function salaryValue(f, salaryData) {
    if (!salaryData) return null;
    const amount = typeof salaryData === "object" ? Number(salaryData.amount || salaryData.expected || salaryData.annual) : Number(salaryData);
    if (!Number.isFinite(amount) || amount <= 0) return null;
    const text = clues(f);
    let target = amount;
    if (/\b(months?|monthly|monat(s|lich)?|mensuel(le)?|pro monat|per month)\b/.test(text)) target = Math.round(amount / 12);
    else if (/\b(hours?|hourly|stunde(n)?|pro stunde|per hour|horaire)\b/.test(text)) target = Math.round(amount / 1920);
    else if (/\b(days?|daily|tag(e)?|pro tag|per day|jour)\b/.test(text)) target = Math.round(amount / 220);
    const options = f.options || [];
    if (options.length) {
      const opt = options.find(o => {
        const val = normalize(o.value + " " + o.text).replace(/[,. ]/g, "");
        if (val.includes(String(target))) return true;
        const numbers = (normalize(o.text).match(/\d+/g) || []).map(n => {
          let num = Number(n);
          if (num < 1000 && /k\b/.test(normalize(o.text))) num *= 1000;
          return num;
        });
        return numbers.length >= 2 && target >= Math.min(...numbers) && target <= Math.max(...numbers);
      });
      return opt ? opt.value : String(target);
    }
    return String(target);
  }

  function noticeValue(f, noticeData) {
    if (!noticeData) return null;
    const raw = typeof noticeData === "object" ? String(noticeData.notice_period || noticeData.availability || noticeData.duration || "") : String(noticeData);
    if (!raw.trim()) return null;
    const text = clues(f);
    const monthsMatch = raw.match(/(\d+)\s*(?:month|monat|mois)/i);
    const months = monthsMatch ? Number(monthsMatch[1]) : null;
    if (/\b(weeks?|wochen?|semaines?)\b/.test(text) && months) return String(Math.round(months * 4.33));
    if (/\b(days?|tage?|jours?)\b/.test(text) && months) return String(months * 30);
    if (/\b(months?|monate?|mois)\b/.test(text) && months) return String(months);
    return raw;
  }

  function demographicValue(f, demoData) {
    const text = clues(f);
    const options = f.options || [];
    if (!options.length) return null;
    const declineOpt = options.find(o => /\b(decline|prefer not|choose not|keine angabe|nicht angeben|ne souhaite pas|withhold|neutral)\b/.test(normalize(o.text + " " + o.value)));
    if (!demoData) return declineOpt ? declineOpt.value : null;
    if (/\b(gender|geschlecht|sexe)\b/.test(text)) {
      const g = normalize(demoData.gender_identity || demoData.gender || "");
      if (g) {
        const opt = options.find(o => normalize(o.text + " " + o.value).includes(g));
        if (opt) return opt.value;
      }
    }
    if (/\b(veteran|military|militaer)\b/.test(text)) {
      const v = demoData.veteran_status;
      if (v === "not_a_veteran" || v === false) {
        const opt = options.find(o => /\b(not a (protected )?veteran|kein veteran|i am not)\b/.test(normalize(o.text)));
        if (opt) return opt.value;
      }
    }
    if (/\b(race|ethnicity|ethnie|diversity)\b/.test(text)) {
      const eth = normalize(demoData.ethnicity || "");
      if (eth && eth !== "decline") {
        const opt = options.find(o => normalize(o.text).includes(eth));
        if (opt) return opt.value;
      }
    }
    return declineOpt ? declineOpt.value : null;
  }

  function match(f, data) {
    if (protectedField(f) || ["file", "checkbox", "radio"].includes(f.type)) return null;
    const p = data.applicant || data;
    const text = clues(f);
    let path;
    let value;
    const ac = (f.autocomplete || "").split(" ").pop();
    const rules = [
      ["given-name", /\b(first name|given name|vorname|prenom)\b/, "personal.first_name"],
      ["family-name", /\b(last name|family name|surname|nachname|nom de famille|nom)\b/, "personal.last_name"],
      ["name", /\b(full name|voller name|nom complet)\b/, "personal.full_name"],
      ["email", /\b(email|e mail|courriel)\b/, "contact.email"],
      ["postal-code", /\b(zip|postal code|postcode|plz|postleitzahl|code postal)\b/, "contact.address.postal_code"],
      ["address-level2", /\b(city|stadt|ville|wohnort)\b/, "contact.address.city"],
      ["address-line2", /\b(address line 2|address2|apartment|complement d adresse)\b/, "contact.address.address_line2"],
      [null, /\b(house number|street number|hausnummer|numero de rue)\b/, "contact.address.house_number"],
      [null, /\blinkedin\b/, "contact.linkedin"],
      [null, /\bgithub\b/, "contact.github"],
      [null, /\b(portfolio|website|homepage)\b/, "contact.portfolio"]
    ];
    if (datePart(f)) { path = "personal.date_of_birth"; value = birthValue(f, p.personal?.date_of_birth); }
    else if (ac === "tel" || /phone|telefon|mobile|\btel\b|rufnummer/.test(text)) { path = "contact.phone"; value = phoneValue(f, data.phone_variants); }
    else if (/\b(gehalt|salary|salaire|compensation|remuneration)\b/.test(text) && !/history|currente/i.test(text)) {
      path = "job_application.salary_expectation";
      value = salaryValue(f, p.job_application?.salary_expectation || p.salary_expectation);
    } else if (/\b(notice|kuendigung|k[uü]ndigungsfrist|verfuegbar|availability|disponibilit)\b/.test(text)) {
      path = "job_application.notice_period";
      value = noticeValue(f, p.job_application?.notice_period || p.job_application?.availability || p.availability);
    } else if (/\b(veteran|ethnicity|race\b|ethnie)\b/.test(text)) {
      path = "demographics";
      value = demographicValue(f, p.demographics);
    } else if (["street-address", "address-line1"].includes(ac) || /^(street|street address|address line 1|address1|strasse|rue|adresse)$/.test(normalize(f.label || f.name))) {
      path = "contact.address.street";
      const address = p.contact?.address || {};
      value = address.address_line1 || [address.street, !f.separate_house_number && address.house_number].filter(Boolean).join(" ");
    } else {
      const matches = rules.filter(([token, pattern]) => token && token === ac || pattern.test(text));
      if (matches.length !== 1) return null;
      path = matches[0][2];
      value = path.split(".").reduce((obj, key) => obj?.[key], p);
      if (value && typeof value === "object") value = value.url;
    }
    if (value == null || String(value).trim() === "") return null;
    return { field_id: f.field_id, action: "fill", proposed_value: String(value), value: String(value), checked: null, profile_source_path: `applicant.${path}`, confidence: 0.98, reason: "Matched locally from selected profile", review_required: false, is_verified_fact: true };
  }
  globalThis.AutofillMatching = { normalize, protectedField, ready, datePart, birthValue, phoneValue, salaryValue, noticeValue, demographicValue, match };
})();
