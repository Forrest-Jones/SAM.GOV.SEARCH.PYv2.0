(function () {
  "use strict";

  const state = {
    settings: null,
    certOptions: [],
    naicsCodes: [],
    lastOpportunities: [],
  };

  function $(id) { return document.getElementById(id); }

  async function api(path, options) {
    const resp = await fetch(path, Object.assign({
      headers: { "Content-Type": "application/json" },
    }, options));
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok && !("ok" in data)) {
      data.ok = false;
    }
    return data;
  }

  // ---------------- Setup screen ----------------

  async function checkSetup() {
    const status = await api("/api/status");
    if (!status.sam_api_key_set) {
      $("setup-screen").hidden = false;
      $("app").hidden = true;
    } else {
      $("setup-screen").hidden = true;
      $("app").hidden = false;
      initApp();
    }
  }

  $("setup-save").addEventListener("click", async () => {
    const key = $("setup-api-key").value.trim();
    if (!key) {
      $("setup-error").textContent = "Please paste your API key first.";
      $("setup-error").hidden = false;
      return;
    }
    $("setup-save").disabled = true;
    await api("/api/credentials", { method: "POST", body: JSON.stringify({ sam_api_key: key }) });
    $("setup-save").disabled = false;
    checkSetup();
  });

  // ---------------- Tabs ----------------

  function wireTabs() {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
        btn.classList.add("active");
        $("tab-" + btn.dataset.tab).classList.add("active");
        if (btn.dataset.tab === "drafts") loadDrafts();
      });
    });
  }

  // ---------------- Scoring labels ----------------

  function matchBadge(score) {
    if (score >= 6) return { cls: "badge-great", text: "🔥 Great Match" };
    if (score >= 4) return { cls: "badge-good", text: "👍 Worth a Look" };
    if (score >= 1) return { cls: "badge-maybe", text: "🤔 Maybe" };
    return { cls: "badge-low", text: "Low Match" };
  }

  function daysUntil(dateStr) {
    if (!dateStr) return null;
    const d = new Date(dateStr + "T00:00:00");
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((d - today) / 86400000);
  }

  // ---------------- Dashboard / search ----------------

  $("search-btn").addEventListener("click", runSearch);

  async function runSearch() {
    $("search-btn").disabled = true;
    $("search-status").textContent = "Searching SAM.gov... this can take a minute.";
    const result = await api("/api/search", { method: "POST" });
    $("search-btn").disabled = false;

    if (!result.ok) {
      $("search-status").textContent = friendlyError(result.error);
      return;
    }
    $("search-status").textContent = "Done!";
    renderSearchResult(result);
  }

  function friendlyError(code) {
    if (code === "no_api_key") return "Your SAM.gov API key isn't set up yet — refresh the page to add it.";
    if (code === "no_naics_codes") return "Add at least one business category in Settings first.";
    return "Something went wrong. Try again in a moment.";
  }

  function renderSearchResult(result) {
    state.lastOpportunities = result.ranked;
    $("summary-cards").hidden = false;
    $("summary-total").textContent = result.ranked.length;
    $("summary-new").textContent = result.new_notice_ids.length;
    $("summary-drafts").textContent = result.draft_count;
    renderDashboardPreview(result);
    renderOpportunities(result.ranked, result.new_notice_ids);
  }

  function renderDashboardPreview(result) {
    const top = result.ranked.slice(0, 3);
    const container = $("dashboard-preview");
    if (!top.length) {
      container.innerHTML = "<p class='muted'>No matches this time. Try widening your deadline window in Settings.</p>";
      return;
    }
    container.innerHTML = "<h2>Top matches</h2>";
    const list = document.createElement("div");
    list.className = "card-list";
    top.forEach((opp) => list.appendChild(buildOppCard(opp, result.new_notice_ids.includes(opp.notice_id))));
    container.appendChild(list);
  }

  // ---------------- Opportunities tab ----------------

  function buildOppCard(opp, isNew) {
    const badge = matchBadge(opp.score);
    const card = document.createElement("div");
    card.className = "opp-card";
    const days = daysUntil(opp.deadline);
    const deadlineText = opp.deadline
      ? (days !== null && days >= 0 ? `Due in ${days} day${days === 1 ? "" : "s"}` : `Deadline ${opp.deadline}`)
      : "No deadline listed";

    card.innerHTML = `
      <div class="opp-card-top">
        <div>
          <p class="opp-title">${escapeHtml(opp.title || "Untitled opportunity")}</p>
          <div class="opp-meta">${escapeHtml(opp.city || "-")}, ${escapeHtml(opp.state || "-")} &middot; ${escapeHtml(deadlineText)}</div>
        </div>
        <div>
          <span class="badge ${badge.cls}">${badge.text}</span>
          ${isNew ? '<span class="badge badge-new">NEW</span>' : ""}
        </div>
      </div>
      ${opp.eligibility === "unknown_set_aside" ? '<div class="opp-meta"><span class="badge badge-warn">⚠️ Double-check you can bid on this one</span></div>' : ""}
    `;
    card.addEventListener("click", () => openOppModal(opp, isNew));
    return card;
  }

  function renderOpportunities(ranked, newIds) {
    newIds = newIds || [];
    const container = $("opportunities-list");
    container.innerHTML = "";
    if (!ranked.length) {
      $("opportunities-empty").hidden = false;
      return;
    }
    $("opportunities-empty").hidden = true;
    ranked.forEach((opp) => container.appendChild(buildOppCard(opp, newIds.includes(opp.notice_id))));
  }

  function openOppModal(opp, isNew) {
    const badge = matchBadge(opp.score);
    $("modal-body").innerHTML = `
      <h1>${escapeHtml(opp.title || "Untitled opportunity")}</h1>
      <p><span class="badge ${badge.cls}">${badge.text}</span> ${isNew ? '<span class="badge badge-new">NEW</span>' : ""}</p>
      <p class="muted">${escapeHtml(opp.city || "-")}, ${escapeHtml(opp.state || "-")} &middot; Deadline: ${escapeHtml(opp.deadline || "not listed")}</p>
      <p><strong>Business category (NAICS):</strong> ${escapeHtml(opp.naics || "-")}</p>
      <p><strong>Special program:</strong> ${escapeHtml(opp.set_aside || "None (open to everyone)")}</p>
      <p><strong>Why this matched:</strong> ${escapeHtml(opp.reasons || "No particular reason — showing anyway")}</p>
      ${opp.link ? `<p><a href="${escapeAttr(opp.link)}" target="_blank" rel="noopener">View full listing on SAM.gov →</a></p>` : ""}
    `;
    showModal();
  }

  async function loadLastOpportunities() {
    const result = await api("/api/opportunities");
    if (result.ranked && result.ranked.length) {
      $("summary-cards").hidden = false;
      $("summary-total").textContent = result.ranked.length;
      $("summary-new").textContent = (result.new_notice_ids || []).length;
      $("summary-drafts").textContent = result.draft_count || 0;
      renderDashboardPreview(result);
      renderOpportunities(result.ranked, result.new_notice_ids);
    } else {
      $("opportunities-empty").hidden = false;
    }
  }

  // ---------------- Drafts / review packets ----------------

  async function loadDrafts() {
    const { drafts } = await api("/api/drafts");
    const container = $("drafts-list");
    container.innerHTML = "";
    if (!drafts.length) {
      $("drafts-empty").hidden = false;
      return;
    }
    $("drafts-empty").hidden = true;
    drafts.forEach((draft) => {
      const card = document.createElement("div");
      card.className = "draft-card";
      const pct = draft.checklist_total ? Math.round((100 * draft.checklist_done) / draft.checklist_total) : 0;
      card.innerHTML = `
        <p class="opp-title">${escapeHtml(draft.title)}</p>
        <div class="opp-meta">${escapeHtml(draft.score_line || "")}</div>
        <div class="opp-meta">${draft.checklist_done}/${draft.checklist_total} steps done</div>
        <div class="progress-track"><div class="progress-fill" style="width:${pct}%"></div></div>
      `;
      card.addEventListener("click", () => openDraftModal(draft.filename));
      container.appendChild(card);
    });
  }

  async function openDraftModal(filename) {
    const result = await api("/api/drafts/" + encodeURIComponent(filename));
    if (!result.ok) return;
    renderDraftContent(filename, result.content);
    showModal();
  }

  function renderDraftContent(filename, content) {
    const lines = content.split("\n");
    const html = [];
    let inList = false;
    lines.forEach((line, idx) => {
      const checklistMatch = line.match(/^- \[( |x|X)\] (.*)$/);
      if (checklistMatch) {
        if (!inList) { html.push("<ul>"); inList = true; }
        const checked = checklistMatch[1].toLowerCase() === "x";
        html.push(`<li class="checklist-item"><label><input type="checkbox" data-line="${idx}" ${checked ? "checked" : ""}/> <span>${escapeHtml(checklistMatch[2])}</span></label></li>`);
        return;
      }
      if (inList) { html.push("</ul>"); inList = false; }

      if (line.startsWith("# ")) { html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`); return; }
      if (line.startsWith("## ")) { html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`); return; }
      if (line.startsWith("- ")) {
        const boldMatch = line.match(/^- \*\*(.+?):\*\* (.*)$/);
        if (boldMatch) {
          html.push(`<p><strong>${escapeHtml(boldMatch[1])}:</strong> ${linkify(boldMatch[2])}</p>`);
        } else {
          html.push(`<p>${linkify(line.slice(2))}</p>`);
        }
        return;
      }
      if (line.trim() === "") { return; }
      html.push(`<p>${linkify(line)}</p>`);
    });
    if (inList) html.push("</ul>");

    $("modal-body").innerHTML = html.join("\n");
    $("modal-body").querySelectorAll('input[type="checkbox"]').forEach((box) => {
      box.addEventListener("change", async () => {
        box.disabled = true;
        const res = await api(`/api/drafts/${encodeURIComponent(filename)}/toggle`, {
          method: "POST",
          body: JSON.stringify({ line_index: parseInt(box.dataset.line, 10) }),
        });
        box.disabled = false;
        if (res.ok) loadDrafts();
      });
    });
  }

  function linkify(text) {
    // draft lines like "- **NAICS:** 541213  **PSC:** R710" have a second
    // bold marker after the one renderDraftContent already peeled off as
    // the label, so this still needs to catch **...** in the remainder.
    const bolded = escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    return bolded.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }

  // ---------------- Settings ----------------

  async function loadSettings() {
    const data = await api("/api/settings");
    state.settings = data.settings;
    state.certOptions = data.certification_options;
    state.naicsCodes = data.settings.naics_codes.slice();
    renderSettingsForm();
    renderCredentialStatus();
  }

  function renderSettingsForm() {
    const s = state.settings;
    renderNaicsChips();
    $("cert-checkboxes").innerHTML = state.certOptions.map((opt) => `
      <label class="checkbox-row">
        <input type="checkbox" value="${escapeAttr(opt.key)}" ${s.certifications.includes(opt.key) ? "checked" : ""} />
        ${escapeHtml(opt.label)}
      </label>
    `).join("");

    $("show-ineligible").checked = !!s.show_ineligible;
    $("deadline-max").value = s.deadline_max_days;
    $("deadline-min").value = s.deadline_min_days;
    $("posted-days").value = s.posted_days;
    $("generate-drafts").checked = !!s.generate_drafts;
    $("draft-min-score").value = s.draft_min_score;
    $("send-email").checked = !!s.send_email;
    $("notify-email").value = s.notify_email;
  }

  function renderNaicsChips() {
    $("naics-chips").innerHTML = state.naicsCodes.map((code, i) => `
      <span class="chip">${escapeHtml(code)}<button data-idx="${i}" aria-label="Remove">×</button></span>
    `).join("");
    $("naics-chips").querySelectorAll("button").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.naicsCodes.splice(parseInt(btn.dataset.idx, 10), 1);
        renderNaicsChips();
      });
    });
  }

  $("naics-add").addEventListener("click", () => {
    const val = $("naics-input").value.replace(/[^0-9]/g, "");
    if (val && !state.naicsCodes.includes(val)) {
      state.naicsCodes.push(val);
      renderNaicsChips();
    }
    $("naics-input").value = "";
  });
  $("naics-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); $("naics-add").click(); }
  });

  function renderCredentialStatus() {
    api("/api/status").then((status) => {
      $("sam-status").textContent = status.sam_api_key_set ? "✓ Connected" : "Not set";
      $("sam-status").className = "status-badge " + (status.sam_api_key_set ? "ok" : "missing");
      $("gmail-status").textContent = status.gmail_configured ? "✓ Connected" : "Not set";
      $("gmail-status").className = "status-badge " + (status.gmail_configured ? "ok" : "missing");
    });
  }

  $("settings-save").addEventListener("click", async () => {
    $("settings-save").disabled = true;
    $("settings-status").textContent = "Saving...";

    const checkedCerts = Array.from($("cert-checkboxes").querySelectorAll("input:checked")).map((i) => i.value);

    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        naics_codes: state.naicsCodes,
        certifications: checkedCerts,
        show_ineligible: $("show-ineligible").checked,
        deadline_max_days: $("deadline-max").value,
        deadline_min_days: $("deadline-min").value,
        posted_days: $("posted-days").value,
        generate_drafts: $("generate-drafts").checked,
        draft_min_score: $("draft-min-score").value,
        send_email: $("send-email").checked,
        notify_email: $("notify-email").value,
      }),
    });

    const credUpdates = {};
    if ($("sam-api-key").value.trim()) credUpdates.sam_api_key = $("sam-api-key").value.trim();
    if ($("gmail-user").value.trim()) credUpdates.gmail_user = $("gmail-user").value.trim();
    if ($("gmail-app-password").value.trim()) credUpdates.gmail_app_password = $("gmail-app-password").value.trim();
    if (Object.keys(credUpdates).length) {
      await api("/api/credentials", { method: "POST", body: JSON.stringify(credUpdates) });
      $("sam-api-key").value = "";
      $("gmail-user").value = "";
      $("gmail-app-password").value = "";
    }

    renderCredentialStatus();
    $("settings-save").disabled = false;
    $("settings-status").textContent = "Saved!";
    setTimeout(() => { $("settings-status").textContent = ""; }, 2500);
  });

  // ---------------- Modal ----------------

  function showModal() { $("modal-backdrop").hidden = false; }
  function hideModal() { $("modal-backdrop").hidden = true; }
  $("modal-close").addEventListener("click", hideModal);
  $("modal-backdrop").addEventListener("click", (e) => { if (e.target.id === "modal-backdrop") hideModal(); });

  // ---------------- Helpers ----------------

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
  }
  function escapeAttr(str) { return escapeHtml(str).replace(/"/g, "&quot;"); }

  // ---------------- Init ----------------

  function initApp() {
    wireTabs();
    loadSettings();
    loadLastOpportunities();
  }

  checkSetup();
})();
