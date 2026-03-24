let currentPage = 1;
let totalPages = 1;
let searchTimeout = null;
let searchQuery = "";

async function loadArticles(page = 1, q = "") {
    const params = new URLSearchParams({ page, per_page: 100, q });
    const resp = await fetch(`/api/articles?${params}`);
    const data = await resp.json();

    currentPage = data.page;
    totalPages = data.total_pages;

    document.getElementById("articleCount").textContent =
        `${data.total} article${data.total !== 1 ? "s" : ""}`;

    renderSpreadsheet(data.articles);
    renderPagination();
}

function renderSpreadsheet(articles) {
    const tbody = document.getElementById("spreadsheetBody");
    tbody.innerHTML = "";

    if (articles.length === 0) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:3rem;color:var(--text-tertiary);">
            No articles yet. Run a search or add one manually.
        </td></tr>`;
        return;
    }

    articles.forEach((a, i) => {
        const tr = document.createElement("tr");
        tr.dataset.id = a.id;
        const qs = a.quality_score;
        const qClass = qs >= 80 ? "quality-high" : qs >= 60 ? "quality-mid" : "quality-low";
        tr.innerHTML = `
            <td class="cell-row-num">${(currentPage - 1) * 100 + i + 1}</td>
            <td class="cell-editable" data-field="title">${esc(a.title)}</td>
            <td class="cell-editable" data-field="defendant_name">${esc(a.defendant_name || "")}</td>
            <td class="cell-editable cell-url" data-field="url"><a href="${esc(a.url)}" target="_blank" rel="noopener">${truncUrl(a.url)}</a></td>
            <td class="cell-editable" data-field="published_date">${esc(a.published_date || "")}</td>
            <td class="cell-editable" data-field="source">${esc(a.source || "")}${a.source_type ? ` <span class="badge badge-source ${a.source_type}">${sourceLabel(a.source_type)}</span>` : ""}</td>
            <td class="cell-editable" data-field="state">${esc(a.state || "")}</td>
            <td class="cell-editable" data-field="crime_type">${esc(a.crime_type || "")}</td>
            <td class="cell-editable" data-field="sentence_details">${esc(a.sentence_details || "")}</td>
            <td>${qs != null ? `<span class="badge badge-quality ${qClass}">${qs}</span>` : ""}</td>
            <td class="cell-actions">
                <button class="btn-icon btn-delete" title="Delete row" data-id="${a.id}">
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path d="M2 4h10M5 4V3a1 1 0 011-1h2a1 1 0 011 1v1M9 4v7a1 1 0 01-1 1H6a1 1 0 01-1-1V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    // Attach click handlers for inline editing
    tbody.querySelectorAll(".cell-editable").forEach(cell => {
        cell.addEventListener("dblclick", () => startEdit(cell));
    });

    // Attach delete handlers
    tbody.querySelectorAll(".btn-delete").forEach(btn => {
        btn.addEventListener("click", () => deleteRow(btn.dataset.id));
    });
}

function startEdit(cell) {
    if (cell.querySelector("input, textarea")) return; // already editing

    const field = cell.dataset.field;
    const tr = cell.closest("tr");
    const articleId = tr.dataset.id;

    // Get current text value
    let currentValue = "";
    if (field === "url") {
        const link = cell.querySelector("a");
        currentValue = link ? link.href : cell.textContent.trim();
    } else {
        currentValue = cell.textContent.trim();
    }

    // Create input
    const isTitle = field === "title" || field === "snippet";
    const input = document.createElement(isTitle ? "textarea" : "input");
    input.className = "cell-input";
    input.value = currentValue;
    if (!isTitle) input.type = "text";
    else input.rows = 2;

    cell.textContent = "";
    cell.appendChild(input);
    input.focus();
    input.select();

    // Save on blur or Enter
    const save = async () => {
        const newValue = input.value.trim();
        input.removeEventListener("blur", save);

        // Update the cell display
        if (field === "url") {
            cell.innerHTML = `<a href="${esc(newValue)}" target="_blank" rel="noopener">${truncUrl(newValue)}</a>`;
        } else {
            cell.textContent = newValue;
        }

        // Save to server
        try {
            await fetch(`/api/articles/${articleId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ [field]: newValue }),
            });
            cell.classList.add("cell-saved");
            setTimeout(() => cell.classList.remove("cell-saved"), 800);
        } catch (err) {
            cell.classList.add("cell-error");
            setTimeout(() => cell.classList.remove("cell-error"), 1500);
        }
    };

    input.addEventListener("blur", save);
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            input.blur();
        }
        if (e.key === "Escape") {
            input.removeEventListener("blur", save);
            if (field === "url") {
                cell.innerHTML = `<a href="${esc(currentValue)}" target="_blank" rel="noopener">${truncUrl(currentValue)}</a>`;
            } else {
                cell.textContent = currentValue;
            }
        }
    });
}

async function deleteRow(articleId) {
    if (!confirm("Delete this article?")) return;

    try {
        await fetch(`/api/articles/${articleId}`, { method: "DELETE" });
        const row = document.querySelector(`tr[data-id="${articleId}"]`);
        if (row) {
            row.style.opacity = "0";
            row.style.transform = "translateX(-20px)";
            setTimeout(() => {
                row.remove();
                // Update count
                const count = document.getElementById("articleCount");
                const n = parseInt(count.textContent) - 1;
                count.textContent = `${n} article${n !== 1 ? "s" : ""}`;
            }, 200);
        }
    } catch (err) {
        alert("Delete failed: " + err.message);
    }
}

document.getElementById("addRowBtn").addEventListener("click", async () => {
    try {
        const resp = await fetch("/api/articles", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: "New Article" }),
        });
        const data = await resp.json();
        await loadArticles(1, searchQuery);

        // Highlight the new row and auto-edit the title
        setTimeout(() => {
            const row = document.querySelector(`tr[data-id="${data.id}"]`);
            if (row) {
                row.classList.add("row-new");
                setTimeout(() => row.classList.remove("row-new"), 1500);
                const titleCell = row.querySelector('[data-field="title"]');
                if (titleCell) startEdit(titleCell);
            }
        }, 100);
    } catch (err) {
        alert("Failed to add row: " + err.message);
    }
});

// Delete all articles
document.getElementById("deleteAllBtn").addEventListener("click", async () => {
    const count = document.getElementById("articleCount").textContent;
    if (!confirm(`Are you sure? This will permanently delete ALL articles (${count}). This cannot be undone.`)) return;

    try {
        const resp = await fetch("/api/articles", { method: "DELETE" });
        if (!resp.ok) throw new Error("Delete failed");
        await loadArticles(1, searchQuery);
    } catch (err) {
        alert("Delete all failed: " + err.message);
    }
});

// Search with debounce
document.getElementById("searchInput").addEventListener("input", (e) => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        searchQuery = e.target.value;
        loadArticles(1, searchQuery);
    }, 300);
});

function renderPagination() {
    const container = document.getElementById("pagination");
    if (totalPages <= 1) {
        container.innerHTML = "";
        return;
    }

    let html = "";
    html += `<button class="btn btn-sm btn-secondary" ${currentPage === 1 ? "disabled" : ""} onclick="goPage(${currentPage - 1})">Prev</button>`;

    for (let p = 1; p <= totalPages; p++) {
        if (p === currentPage) {
            html += `<span class="page-current">${p}</span>`;
        } else if (Math.abs(p - currentPage) <= 2 || p === 1 || p === totalPages) {
            html += `<button class="btn btn-sm btn-secondary" onclick="goPage(${p})">${p}</button>`;
        } else if (Math.abs(p - currentPage) === 3) {
            html += `<span class="page-ellipsis">...</span>`;
        }
    }

    html += `<button class="btn btn-sm btn-secondary" ${currentPage === totalPages ? "disabled" : ""} onclick="goPage(${currentPage + 1})">Next</button>`;
    container.innerHTML = html;
}

window.goPage = (p) => {
    if (p >= 1 && p <= totalPages) loadArticles(p, searchQuery);
};

function esc(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function sourceLabel(type) {
    const labels = { google_news: "News", google_web: "Web", facebook: "FB", youtube: "YT", rss: "RSS" };
    return labels[type] || type || "";
}

function truncUrl(url) {
    if (!url) return "";
    try {
        const u = new URL(url);
        let display = u.hostname.replace("www.", "");
        if (u.pathname.length > 1) display += u.pathname.slice(0, 30);
        if (u.pathname.length > 30) display += "...";
        return display;
    } catch {
        return url.slice(0, 40);
    }
}

// Initial load
loadArticles();
