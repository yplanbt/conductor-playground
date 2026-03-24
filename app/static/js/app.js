const US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming"
];

const stateSelect = document.getElementById("state");
US_STATES.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    stateSelect.appendChild(opt);
});

let currentResults = [];
let sortCol = null;
let sortAsc = true;

document.getElementById("searchForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    await performSearch();
});

async function performSearch() {
    const form = document.getElementById("searchForm");
    const searchBtn = document.getElementById("searchBtn");
    const statusBar = document.getElementById("statusBar");
    const statusText = document.getElementById("statusText");

    const crimeToggle = form.querySelector('input[name="crime_toggle"]:checked')?.value || "both";
    const gender = document.getElementById("gender").value;
    const state = document.getElementById("state").value || null;
    const dateFrom = document.getElementById("dateFrom").value || null;
    const dateTo = document.getElementById("dateTo").value || null;
    const customKw = document.getElementById("customKeywords").value;
    const customKeywords = customKw ? customKw.split(",").map(k => k.trim()).filter(Boolean) : null;

    const deepResearch = form.querySelector('input[name="search_mode"]:checked')?.value === "deep";
    const targetCount = parseInt(document.getElementById("targetCount").value) || 50;

    const body = {
        crime_toggle: crimeToggle,
        gender,
        state,
        date_from: dateFrom,
        date_to: dateTo,
        custom_keywords: customKeywords,
        deep_research: deepResearch,
        target_count: targetCount,
    };

    searchBtn.disabled = true;
    searchBtn.innerHTML = '<span class="spinner"></span>Searching...';
    statusBar.style.display = "flex";
    statusBar.className = "status-bar";
    statusText.textContent = `Searching for ${targetCount} sentencing cases...`;

    try {
        const resp = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });

        if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);

        const data = await resp.json();
        currentResults = data.results;

        statusBar.className = "status-bar success";
        let msg = `Found ${data.total_count} articles.`;
        if (data.duplicates_filtered > 0) {
            msg += ` ${data.duplicates_filtered} duplicates filtered.`;
        }
        if (data.ai_filtered > 0) {
            msg += ` ${data.ai_filtered} non-sentencing filtered by AI.`;
        }
        if (data.source_breakdown) {
            const labels = { google_news: "News", google_web: "Web", facebook: "Facebook", youtube: "YouTube" };
            const parts = Object.entries(data.source_breakdown)
                .map(([k, v]) => `${v} ${labels[k] || k}`)
                .join(", ");
            msg += ` Sources: ${parts}.`;
        }
        statusText.textContent = msg;

        const sheetsLink = document.getElementById("sheetsLink");
        if (data.sheets_url) {
            document.getElementById("sheetsUrl").href = data.sheets_url;
            sheetsLink.style.display = "block";
        } else {
            sheetsLink.style.display = "none";
        }

        document.getElementById("queryUsed").textContent = data.query_used;
        document.getElementById("resultCount").textContent = data.total_count;

        renderResults(data.results);
        document.getElementById("resultsSection").style.display = "block";
        document.getElementById("exportCsvBtn").disabled = false;

    } catch (err) {
        statusBar.className = "status-bar error";
        statusText.textContent = err.message;
    } finally {
        searchBtn.disabled = false;
        searchBtn.textContent = "Search";
    }
}

function renderResults(results) {
    const tbody = document.getElementById("resultsBody");
    tbody.innerHTML = "";

    if (results.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2.5rem;color:var(--text-tertiary);">No articles found. Try broadening your search.</td></tr>';
        return;
    }

    results.forEach(a => {
        const tr = document.createElement("tr");
        const qs = a.quality_score;
        const qClass = qs >= 80 ? "quality-high" : qs >= 60 ? "quality-mid" : "quality-low";
        tr.innerHTML = `
            <td><a href="${escapeHtml(a.url)}" target="_blank" rel="noopener">${escapeHtml(a.title)}</a>${a.case_summary ? `<div class="case-summary">${escapeHtml(a.case_summary)}</div>` : ""}</td>
            <td>${escapeHtml(a.defendant_name || "—")}</td>
            <td style="white-space:nowrap">${escapeHtml(a.published_date || "—")}</td>
            <td>${escapeHtml(a.source || "—")}${a.source_type ? ` <span class="badge badge-source ${a.source_type}">${sourceTypeLabel(a.source_type)}</span>` : ""}</td>
            <td>${a.state ? `<span class="badge badge-state">${escapeHtml(a.state)}</span>` : "—"}</td>
            <td>${a.crime_type ? `<span class="badge badge-crime">${escapeHtml(a.crime_type)}</span>` : "—"}</td>
            <td>${a.sentence_details ? `<span class="badge badge-sentence">${escapeHtml(a.sentence_details)}</span>` : "—"}</td>
            <td>${qs != null ? `<span class="badge badge-quality ${qClass}">${qs}</span>` : "—"}</td>
        `;
        tbody.appendChild(tr);
    });
}

document.querySelectorAll(".results-table th[data-sort]").forEach(th => {
    th.addEventListener("click", () => {
        const col = th.dataset.sort;
        if (sortCol === col) { sortAsc = !sortAsc; } else { sortCol = col; sortAsc = true; }
        currentResults.sort((a, b) => {
            const va = (a[col] || "").toLowerCase();
            const vb = (b[col] || "").toLowerCase();
            return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        });
        renderResults(currentResults);
    });
});

document.getElementById("exportCsvBtn").addEventListener("click", () => {
    window.open("/api/export/csv", "_blank");
});

const saveModal = document.getElementById("saveModal");
document.getElementById("saveSearchBtn").addEventListener("click", () => {
    saveModal.style.display = "flex";
});
document.getElementById("cancelSaveBtn").addEventListener("click", () => {
    saveModal.style.display = "none";
});
document.getElementById("confirmSaveBtn").addEventListener("click", async () => {
    const name = document.getElementById("searchName").value.trim();
    if (!name) return alert("Please enter a name.");

    const form = document.getElementById("searchForm");
    const searchParams = {
        crime_toggle: form.querySelector('input[name="crime_toggle"]:checked')?.value || "both",
        gender: document.getElementById("gender").value,
        state: document.getElementById("state").value || null,
        date_from: document.getElementById("dateFrom").value || null,
        date_to: document.getElementById("dateTo").value || null,
        custom_keywords: document.getElementById("customKeywords").value
            ? document.getElementById("customKeywords").value.split(",").map(k => k.trim()).filter(Boolean)
            : null,
    };

    try {
        await fetch("/api/saved-searches", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, search_params: searchParams }),
        });
        saveModal.style.display = "none";
        document.getElementById("searchName").value = "";
    } catch (err) {
        alert("Save failed: " + err.message);
    }
});

// Load saved search from URL
const urlParams = new URLSearchParams(window.location.search);
const loadId = urlParams.get("load");
if (loadId) {
    fetch("/api/saved-searches")
        .then(r => r.json())
        .then(searches => {
            const s = searches.find(x => x.id == loadId);
            if (!s) return;
            const p = s.search_params;
            if (p.crime_toggle) {
                const radio = document.querySelector(`input[name="crime_toggle"][value="${p.crime_toggle}"]`);
                if (radio) radio.checked = true;
            }
            if (p.gender) document.getElementById("gender").value = p.gender;
            if (p.state) document.getElementById("state").value = p.state;
            if (p.date_from) document.getElementById("dateFrom").value = p.date_from;
            if (p.date_to) document.getElementById("dateTo").value = p.date_to;
            if (p.custom_keywords?.length) {
                document.getElementById("customKeywords").value = p.custom_keywords.join(", ");
            }
        });
}

function sourceTypeLabel(type) {
    const labels = { google_news: "News", google_web: "Web", facebook: "FB", youtube: "YT", rss: "RSS" };
    return labels[type] || type || "";
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}
