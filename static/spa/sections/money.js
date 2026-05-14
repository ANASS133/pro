(function () {
    const sections = window.SPASections || {};

    sections.createMoneySection = function createMoneySection() {
        const dashboard = document.getElementById("money-dashboard");
        const statusNode = document.getElementById("money-status");
        const refreshBtn = document.getElementById("money-refresh");
        const packageBars = document.getElementById("money-package-bars");
        const monthlyBars = document.getElementById("money-monthly-bars");
        const latestList = document.getElementById("money-latest-list");

        if (!dashboard || !statusNode || !packageBars || !monthlyBars || !latestList) {
            return { show() {}, hide() {} };
        }

        const utils = window.SPAUtils || {};
        const escapeHtml = typeof utils.escapeHtml === "function"
            ? utils.escapeHtml
            : function fallbackEscapeHtml(value) {
                return String(value ?? "")
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#39;");
            };

        let hasLoaded = false;
        let isLoading = false;

        function getSupabaseClient() {
            if (!window.AppSupabase || typeof window.AppSupabase.getClient !== "function") {
                throw new Error("Supabase client helper is not available.");
            }
            return window.AppSupabase.getClient();
        }

        function setStatus(message, isError) {
            const value = String(message || "").trim();
            statusNode.hidden = !value;
            statusNode.textContent = value;
            statusNode.classList.toggle("is-error", Boolean(isError));
        }

        function setLoading(loading) {
            isLoading = Boolean(loading);
            if (refreshBtn) {
                refreshBtn.disabled = isLoading;
                refreshBtn.textContent = isLoading ? "Lade..." : "Refresh";
            }
        }

        function getPriceForPack(pack) {
            const normalizedPack = String(pack || "").toLowerCase();
            if (normalizedPack.includes("1000")) {
                return 400;
            }
            if (normalizedPack.includes("500")) {
                return 200;
            }
            return 0;
        }

        function formatMoney(value) {
            const amount = Number(value || 0);
            return `${amount.toLocaleString("de-DE")} dh`;
        }

        function formatDate(value) {
            if (!value) {
                return "k. A.";
            }

            const date = new Date(value);
            if (Number.isNaN(date.getTime())) {
                return "k. A.";
            }

            return new Intl.DateTimeFormat("de-DE", {
                day: "2-digit",
                month: "2-digit",
                year: "numeric",
            }).format(date);
        }

        function getStartOfToday() {
            const date = new Date();
            date.setHours(0, 0, 0, 0);
            return date;
        }

        function getStartOfWeek() {
            const date = getStartOfToday();
            const day = date.getDay();
            const diff = day === 0 ? -6 : 1 - day;
            date.setDate(date.getDate() + diff);
            return date;
        }

        function getStartOfMonth() {
            const date = getStartOfToday();
            date.setDate(1);
            return date;
        }

        function normalizeApplication(row) {
            const pack = String(row.pack || "").trim();
            const price = getPriceForPack(pack);
            const createdAt = row.created_at || "";
            const createdDate = createdAt ? new Date(createdAt) : null;

            return {
                id: String(row.id || "").trim(),
                name: String(row.full_name || "").trim() || "Unnamed applicant",
                email: String(row.email || "").trim(),
                pack: pack || "k. A.",
                price,
                created_at: createdAt,
                createdDate: createdDate && !Number.isNaN(createdDate.getTime()) ? createdDate : null,
            };
        }

        function getPaidApplications(applications) {
            return applications.filter(function (application) {
                return application.price > 0;
            });
        }

        function sumPrices(applications) {
            return applications.reduce(function (total, application) {
                return total + application.price;
            }, 0);
        }

        function byDateFrom(startDate) {
            return function (application) {
                return application.createdDate && application.createdDate >= startDate;
            };
        }

        function getMonthKey(date) {
            return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
        }

        function getMonthLabel(date) {
            return new Intl.DateTimeFormat("de-DE", {
                month: "short",
                year: "2-digit",
            }).format(date);
        }

        function getLastSixMonthBuckets(applications) {
            const now = new Date();
            const buckets = [];

            for (let index = 5; index >= 0; index -= 1) {
                const date = new Date(now.getFullYear(), now.getMonth() - index, 1);
                buckets.push({
                    key: getMonthKey(date),
                    label: getMonthLabel(date),
                    total: 0,
                    count: 0,
                });
            }

            const byKey = new Map(buckets.map(function (bucket) {
                return [bucket.key, bucket];
            }));

            applications.forEach(function (application) {
                if (!application.createdDate) {
                    return;
                }
                const key = getMonthKey(application.createdDate);
                const bucket = byKey.get(key);
                if (!bucket) {
                    return;
                }
                bucket.total += application.price;
                bucket.count += 1;
            });

            return buckets;
        }

        function renderBarRows(rows) {
            const maxTotal = Math.max.apply(null, rows.map(function (row) {
                return row.total;
            }).concat([1]));

            return rows.map(function (row) {
                const percent = Math.max(4, Math.round((row.total / maxTotal) * 100));
                return (
                    '<div class="money-bar-row">' +
                    '<div class="money-bar-label">' +
                    '<span>' + escapeHtml(row.label) + '</span>' +
                    '<strong>' + escapeHtml(formatMoney(row.total)) + '</strong>' +
                    '</div>' +
                    '<div class="money-bar-track">' +
                    '<div class="money-bar-fill" style="width:' + percent + '%"></div>' +
                    '</div>' +
                    '<small>' + escapeHtml(row.count) + ' Bewerbungen</small>' +
                    '</div>'
                );
            }).join("");
        }

        function renderLatest(applications) {
            const latest = applications
                .slice()
                .sort(function (left, right) {
                    const leftTime = left.createdDate ? left.createdDate.getTime() : 0;
                    const rightTime = right.createdDate ? right.createdDate.getTime() : 0;
                    return rightTime - leftTime;
                })
                .slice(0, 6);

            if (!latest.length) {
                latestList.innerHTML = '<div class="money-empty">Noch keine bezahlten Supabase-Bewerbungen gefunden.</div>';
                return;
            }

            latestList.innerHTML = latest.map(function (application) {
                return (
                    '<div class="money-latest-item">' +
                    '<div>' +
                    '<strong>' + escapeHtml(application.name) + '</strong>' +
                    '<span>' + escapeHtml(application.pack) + ' | ' + escapeHtml(formatDate(application.created_at)) + '</span>' +
                    '</div>' +
                    '<b>' + escapeHtml(formatMoney(application.price)) + '</b>' +
                    '</div>'
                );
            }).join("");
        }

        function setText(id, value) {
            const node = document.getElementById(id);
            if (node) {
                node.textContent = value;
            }
        }

        function renderDashboard(applications) {
            const paidApplications = getPaidApplications(applications);
            const startOfToday = getStartOfToday();
            const startOfWeek = getStartOfWeek();
            const startOfMonth = getStartOfMonth();

            const todayApplications = paidApplications.filter(byDateFrom(startOfToday));
            const weekApplications = paidApplications.filter(byDateFrom(startOfWeek));
            const monthApplications = paidApplications.filter(byDateFrom(startOfMonth));

            const total = sumPrices(paidApplications);
            const average = paidApplications.length ? Math.round(total / paidApplications.length) : 0;

            const pack500 = paidApplications.filter(function (application) {
                return application.price === 200;
            });
            const pack1000 = paidApplications.filter(function (application) {
                return application.price === 400;
            });

            setText("money-total", formatMoney(total));
            setText("money-total-note", `${paidApplications.length} bezahlte Bewerbungen aus Supabase`);
            setText("money-week", formatMoney(sumPrices(weekApplications)));
            setText("money-week-count", `${weekApplications.length} Bewerbungen`);
            setText("money-month", formatMoney(sumPrices(monthApplications)));
            setText("money-month-count", `${monthApplications.length} Bewerbungen`);
            setText("money-today", formatMoney(sumPrices(todayApplications)));
            setText("money-today-count", `${todayApplications.length} Bewerbungen`);
            setText("money-average", formatMoney(average));

            packageBars.innerHTML = renderBarRows([
                { label: "500 Bewerbung", total: sumPrices(pack500), count: pack500.length },
                { label: "1000 Bewerbung", total: sumPrices(pack1000), count: pack1000.length },
            ]);
            monthlyBars.innerHTML = renderBarRows(getLastSixMonthBuckets(paidApplications));
            renderLatest(paidApplications);

            dashboard.hidden = false;
        }

        async function loadMoneyDashboard(force) {
            if (isLoading || (hasLoaded && !force)) {
                return;
            }

            setLoading(true);
            setStatus("Lade Money-Daten aus Supabase...", false);

            try {
                const client = await getSupabaseClient();
                const response = await client
                    .from("applications")
                    .select("id,created_at,pack,full_name,email")
                    .order("created_at", { ascending: false });

                if (response.error) {
                    throw response.error;
                }

                const applications = Array.isArray(response.data)
                    ? response.data.map(normalizeApplication)
                    : [];

                renderDashboard(applications);
                setStatus("", false);
                hasLoaded = true;
            } catch (error) {
                console.error("Money dashboard load failed.", error);
                dashboard.hidden = true;
                setStatus(error.message || "Money-Daten konnten nicht geladen werden.", true);
            } finally {
                setLoading(false);
            }
        }

        if (refreshBtn) {
            refreshBtn.addEventListener("click", function () {
                loadMoneyDashboard(true);
            });
        }

        return {
            show() {
                loadMoneyDashboard(false);
            },
            hide() {},
        };
    };

    window.SPASections = sections;
})();
