(function () {
    var sections = window.SPASections || {};

    sections.createMoneySection = function createMoneySection() {
        var statusNode      = document.getElementById("money-status");
        var skeleton        = document.getElementById("money-skeleton");
        var dashboard       = document.getElementById("money-dashboard");
        var insightsBox     = document.getElementById("money-insights");
        var topPayers       = document.getElementById("money-top-payers");
        var timeline        = document.getElementById("money-timeline");
        var chartBars       = document.getElementById("money-chart-bars");
        var tableBody       = document.getElementById("money-table-body");
        var emptyNode       = document.getElementById("money-empty");
        var noResults       = document.getElementById("money-no-results");
        var refreshBtn      = document.getElementById("money-refresh");
        var exportBtn       = document.getElementById("money-export");
        var searchInput     = document.getElementById("money-search");
        var sortSelect      = document.getElementById("money-sort");
        var goalInput       = document.getElementById("money-goal-input");

        if (!statusNode || !tableBody) {
            return { show: function () {}, hide: function () {} };
        }

        var allRows = [];
        var hasLoaded = false;
        var isLoading = false;
        var monthlyTarget = 10000;

        function $(id) { return document.getElementById(id); }

        function getSupabaseClient() {
            if (!window.AppSupabase || typeof window.AppSupabase.getClient !== "function") {
                throw new Error("Supabase client helper not available.");
            }
            return window.AppSupabase.getClient();
        }

        function setStatus(message, isError) {
            var v = String(message || "").trim();
            statusNode.hidden = !v;
            statusNode.textContent = v;
            statusNode.classList.toggle("is-error", Boolean(isError));
        }

        function showLoading(loading) {
            isLoading = Boolean(loading);
            skeleton.hidden = !isLoading;
            dashboard.hidden = isLoading;
            emptyNode.hidden = true;
            noResults.hidden = true;
            if (refreshBtn) { refreshBtn.disabled = isLoading; refreshBtn.textContent = isLoading ? "Lade..." : "Refresh"; }
            if (exportBtn) { exportBtn.disabled = isLoading; }
        }

        function fmtMoney(value) {
            return Number(value || 0).toLocaleString("de-DE") + " DH";
        }

        function fmtDate(value) {
            if (!value) return "\u2014";
            var d = new Date(value);
            if (isNaN(d.getTime())) return "\u2014";
            return new Intl.DateTimeFormat("de-DE", { day:"2-digit", month:"2-digit", year:"numeric", hour:"2-digit", minute:"2-digit" }).format(d);
        }

        function fmtDateShort(value) {
            if (!value) return "\u2014";
            var d = new Date(value);
            if (isNaN(d.getTime())) return "\u2014";
            return new Intl.DateTimeFormat("de-DE", { day:"2-digit", month:"2-digit", year:"numeric" }).format(d);
        }

        function fmtDateISO(value) {
            if (!value) return "";
            var d = new Date(value);
            if (isNaN(d.getTime())) return "";
            return d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0") + "-" + String(d.getDate()).padStart(2,"0");
        }

        function escapeHTML(value) {
            return String(value||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
        }

        function changePct(thisVal, lastVal) {
            if (!lastVal || lastVal === 0) return thisVal > 0 ? "+100%" : "0%";
            var pct = Math.round(((thisVal - lastVal) / lastVal) * 100);
            return (pct >= 0 ? "+" : "") + pct + "%";
        }

        function changeClass(pctStr) {
            if (!pctStr || pctStr === "0%" || pctStr === "\u2014") return "";
            return pctStr.startsWith("+") ? "money-change--up" : "money-change--down";
        }

        // ---- Helpers ----
        function getThisMonthRows() {
            var now = new Date();
            var start = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
            return allRows.filter(function(r) { return r.sortTime >= start; });
        }

        function getLastMonthRows() {
            var now = new Date();
            var start = new Date(now.getFullYear(), now.getMonth()-1, 1).getTime();
            var end = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
            return allRows.filter(function(r) { return r.sortTime >= start && r.sortTime < end; });
        }

        function getTodayRows() {
            var today = new Date();
            var start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
            return allRows.filter(function(r) { return r.sortTime >= start; });
        }

        function sumMoney(rows) { return rows.reduce(function(s,r){ return s + r.money; }, 0); }

        function getDateBadge(dateStr) {
            if (!dateStr) return "";
            var d = new Date(dateStr);
            if (isNaN(d.getTime())) return "";
            var today = new Date(); today.setHours(0,0,0,0);
            var rd = new Date(d.getFullYear(), d.getMonth(), d.getDate());
            var diff = Math.floor((today - rd) / 86400000);
            if (diff === 0) return '<span class="money-badge money-badge--today">Today</span>';
            if (diff <= 7) return '<span class="money-badge money-badge--week">This week</span>';
            return "";
        }

        // ---- Render functions ----

        function renderSmartInsights() {
            var thisMonth = getThisMonthRows();
            var lastMonth = getLastMonthRows();
            var thisTotal = sumMoney(thisMonth);
            var lastTotal = sumMoney(lastMonth);
            var thisCount = thisMonth.length;
            var avg = thisCount > 0 ? Math.round(thisTotal / thisCount) : 0;

            var parts = [];
            if (lastTotal > 0) {
                var pct = Math.round(((thisTotal - lastTotal) / lastTotal) * 100);
                var dir = pct >= 0 ? "mehr" : "weniger";
                parts.push("Du hast diesen Monat <strong>" + Math.abs(pct) + "% " + dir + "</strong> erhalten als letzten Monat.");
            }
            if (avg > 0) {
                parts.push("Die durchschnittliche Zahlung betr&auml;gt <strong>" + fmtMoney(avg) + "</strong>.");
            }
            var highest = allRows.length ? allRows.reduce(function(a,b){ return a.money > b.money ? a : b; }) : null;
            if (highest) {
                parts.push("H&ouml;chste Einzelzahlung: <strong>" + fmtMoney(highest.money) + "</strong> von <strong>" + escapeHTML(highest.name) + "</strong>.");
            }

            if (parts.length) {
                insightsBox.innerHTML = parts.join(" ");
                insightsBox.hidden = false;
            } else {
                insightsBox.hidden = true;
            }
        }

        function renderKPI() {
            var thisMonth = getThisMonthRows();
            var today = getTodayRows();
            var highest = allRows.length ? allRows.reduce(function(a,b){ return a.money > b.money ? a : b; }).money : 0;
            var total = sumMoney(allRows);
            var avg = allRows.length ? Math.round(total / allRows.length) : 0;

            $("money-kpi-total").textContent = fmtMoney(total);
            $("money-kpi-avg").textContent = fmtMoney(avg);
            $("money-kpi-highest").textContent = fmtMoney(highest);
            $("money-kpi-today").textContent = fmtMoney(sumMoney(today));
            $("money-kpi-today-count").textContent = today.length + " payments";
        }

        function renderMoM() {
            var thisMonth = getThisMonthRows();
            var lastMonth = getLastMonthRows();
            var thisTotal = sumMoney(thisMonth);
            var lastTotal = sumMoney(lastMonth);
            var thisCount = thisMonth.length;
            var lastCount = lastMonth.length;
            var thisAvg = thisCount > 0 ? Math.round(thisTotal / thisCount) : 0;
            var lastAvg = lastCount > 0 ? Math.round(lastTotal / lastCount) : 0;

            var totalPct = changePct(thisTotal, lastTotal);
            var countPct = changePct(thisCount, lastCount);
            var avgPct = changePct(thisAvg, lastAvg);

            $("money-mom-total").textContent = fmtMoney(thisTotal);
            $("money-mom-total-change").textContent = totalPct;
            $("money-mom-total-change").className = "money-change " + changeClass(totalPct);

            $("money-mom-count").textContent = thisCount;
            $("money-mom-count-change").textContent = countPct;
            $("money-mom-count-change").className = "money-change " + changeClass(countPct);

            $("money-mom-avg").textContent = fmtMoney(thisAvg);
            $("money-mom-avg-change").textContent = avgPct;
            $("money-mom-avg-change").className = "money-change " + changeClass(avgPct);
        }

        function renderChart() {
            var monthly = {};
            allRows.forEach(function(r) {
                if (!r.created_at) return;
                var d = new Date(r.created_at);
                if (isNaN(d.getTime())) return;
                var key = d.getFullYear() + "-" + String(d.getMonth()+1).padStart(2,"0");
                if (!monthly[key]) monthly[key] = { total: 0, label: new Intl.DateTimeFormat("de-DE",{month:"short",year:"2-digit"}).format(d) };
                monthly[key].total += r.money;
            });
            var months = Object.keys(monthly).sort();
            if (!months.length) { chartBars.innerHTML = '<div class="money-chart-empty">Keine Daten.</div>'; return; }
            var maxVal = 0;
            months.forEach(function(m){ if(monthly[m].total>maxVal) maxVal=monthly[m].total; });
            var html = "";
            months.forEach(function(m){
                var d = monthly[m], pct = maxVal>0 ? Math.round((d.total/maxVal)*100) : 0;
                html += '<div class="money-chart-row"><span class="money-chart-label">'+d.label+'</span><div class="money-chart-track"><div class="money-chart-fill" style="width:'+pct+'%"></div></div><span class="money-chart-value">'+fmtMoney(d.total)+'</span></div>';
            });
            chartBars.innerHTML = html;
        }

        function renderTopPayers() {
            var sorted = allRows.slice().sort(function(a,b){ return b.money - a.money; }).slice(0, 5);
            if (!sorted.length) { topPayers.innerHTML = '<div class="money-empty-inline">Noch keine Daten.</div>'; return; }
            var html = "";
            sorted.forEach(function(r, i) {
                html += '<div class="money-top-item"><span class="money-top-rank">#'+(i+1)+'</span><span class="money-top-name">'+escapeHTML(r.name||"\u2014")+'</span><strong class="money-top-amount">'+fmtMoney(r.money)+'</strong></div>';
            });
            topPayers.innerHTML = html;
        }

        function renderTimeline() {
            var latest = allRows.slice().sort(function(a,b){ return b.sortTime - a.sortTime; }).slice(0, 10);
            if (!latest.length) { timeline.innerHTML = '<div class="money-empty-inline">Noch keine Daten.</div>'; return; }
            var html = "";
            latest.forEach(function(r) {
                html += '<div class="money-timeline-item"><div class="money-timeline-dot"></div><div><strong>'+escapeHTML(r.name||"\u2014")+'</strong><small>'+fmtDate(r.created_at)+'</small></div><strong class="money-timeline-amount">'+fmtMoney(r.money)+'</strong></div>';
            });
            timeline.innerHTML = html;
        }

        function renderHealth() {
            var large = allRows.filter(function(r){ return r.money > 5000; });
            $("money-health-large").textContent = large.length;

            var now = Date.now(), day30 = now - 30*86400000;
            var recent = allRows.filter(function(r){ return r.sortTime >= day30; });
            var dailyAvg = recent.length ? Math.round(sumMoney(recent) / 30) : 0;
            $("money-health-daily").textContent = fmtMoney(dailyAvg);

            var dailyMap = {};
            allRows.forEach(function(r){
                var key = fmtDateISO(r.created_at);
                if (!dailyMap[key]) dailyMap[key] = 0;
                dailyMap[key] += r.money;
            });
            var spikeThreshold = dailyAvg * 2;
            var spikes = Object.values(dailyMap).filter(function(v){ return v > spikeThreshold && spikeThreshold > 0; }).length;
            $("money-health-spikes").textContent = spikes;
        }

        function renderGoal() {
            var thisMonth = getThisMonthRows();
            var total = sumMoney(thisMonth);
            var pct = monthlyTarget > 0 ? Math.min(100, Math.round((total / monthlyTarget) * 100)) : 0;
            $("money-goal-fill").style.width = pct + "%";
            $("money-goal-current").textContent = fmtMoney(total);
            $("money-goal-percent").textContent = pct + "%";
            $("money-goal-target").textContent = "/ " + monthlyTarget.toLocaleString("de-DE") + " DH";
        }

        // ---- Table ----
        function getFilteredRows() {
            var term = String(searchInput ? searchInput.value : "").toLowerCase().trim();
            var sort = String(sortSelect ? sortSelect.value : "date-desc");
            var filtered = allRows.slice();
            if (term) filtered = filtered.filter(function(r){ return String(r.name||"").toLowerCase().indexOf(term)>=0; });
            filtered.sort(function(a,b){
                switch(sort){
                    case "date-asc": return a.sortTime - b.sortTime;
                    case "amount-desc": return b.money - a.money;
                    case "amount-asc": return a.money - b.money;
                    default: return b.sortTime - a.sortTime;
                }
            });
            return filtered;
        }

        function renderTable(rows) {
            tableBody.innerHTML = "";
            if (!rows || !rows.length) {
                if (!allRows.length) { emptyNode.hidden = false; noResults.hidden = true; }
                else { emptyNode.hidden = true; noResults.hidden = false; }
                return;
            }
            emptyNode.hidden = true; noResults.hidden = true;
            rows.forEach(function(r){
                var cls = "money-cell" + (r.money >= 5000 ? " money-cell--high" : "");
                var badges = [getDateBadge(r.created_at), r.money >= 5000 ? '<span class="money-badge money-badge--high">High value</span>' : ""].filter(Boolean).join(" ");
                var tr = document.createElement("tr");
                tr.innerHTML = '<td><strong class="money-name">'+escapeHTML(r.name||"\u2014")+'</strong>'+ (badges?'<div class="money-badges">'+badges+'</div>':'') +'</td><td class="'+cls+'">'+fmtMoney(r.money)+'</td><td>'+fmtDate(r.created_at)+'</td>';
                tableBody.appendChild(tr);
            });
        }

        function renderAll() {
            var filtered = getFilteredRows();
            renderSmartInsights();
            renderKPI();
            renderMoM();
                        renderChart();
            renderTopPayers();
            renderTimeline();
            renderHealth();
            renderGoal();
            renderTable(filtered);
        }

        // ---- CSV Export ----
        function exportCSV() {
            var rows = getFilteredRows();
            if (!rows.length) { setStatus("Keine Daten zum Exportieren.", true); return; }
            var lines = ["Name,Amount (DH),Created At"];
            rows.forEach(function(r){ lines.push('"'+String(r.name||"").replace(/"/g,'""')+'",'+r.money+','+(r.created_at||"")); });
            var blob = new Blob([lines.join("\n")], { type:"text/csv;charset=utf-8;" });
            var url = URL.createObjectURL(blob);
            var a = document.createElement("a"); a.href=url; a.download="payments_"+new Date().toISOString().slice(0,10)+".csv";
            document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url);
            setStatus("CSV exportiert ("+rows.length+" Eintr&auml;ge).", false);
        }

        // ---- Load ----
        async function loadPayments(force) {
            if (isLoading || (hasLoaded && !force)) return;
            showLoading(true);
            setStatus("Lade Zahlungen...", false);
            try {
                var client = await getSupabaseClient();
                var resp = await client.from("payed").select("id,name,money,created_at").order("created_at",{ascending:false});
                if (resp.error) throw resp.error;
                allRows = (Array.isArray(resp.data)?resp.data:[]).map(function(r){
                    return { id: String(r.id||"").trim(), name: String(r.name||"").trim(), money: Number(r.money||0), created_at: r.created_at||"", sortTime: r.created_at ? new Date(r.created_at).getTime()||0 : 0 };
                });
                renderAll();
                setStatus("", false);
                hasLoaded = true;
            } catch(e) {
                console.error("Payments load failed.", e);
                showLoading(false);
                emptyNode.hidden = true; noResults.hidden = true;
                setStatus(e.message || "Zahlungen konnten nicht geladen werden.", true);
                return;
            } finally { showLoading(false); }
        }

        // ---- Events ----
        if (refreshBtn) refreshBtn.addEventListener("click", function(){ loadPayments(true); });
        if (exportBtn) exportBtn.addEventListener("click", function(){ exportCSV(); });
        if (searchInput) {
            var t = null;
            searchInput.addEventListener("input", function(){ clearTimeout(t); t=setTimeout(function(){ renderTable(getFilteredRows()); },250); });
        }
        if (sortSelect) sortSelect.addEventListener("change", function(){ renderTable(getFilteredRows()); });
        if (goalInput) {
            goalInput.addEventListener("input", function(){
                monthlyTarget = Number(goalInput.value) || 0;
                renderGoal();
            });
        }

        return {
            show: function () { monthlyTarget = Number(goalInput && goalInput.value) || 10000; loadPayments(false); },
            hide: function () {}
        };
    };

    window.SPASections = sections;
})();
