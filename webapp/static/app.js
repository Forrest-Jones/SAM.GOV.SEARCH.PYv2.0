(function () {
  "use strict";

  const state = {
    activeProfile: null,
    settings: null,
    certOptions: [],
    naicsCodes: [],
    lastOpportunities: [],
  };

  const COMPANY_FIELDS = [
    "legal_name", "uei", "cage", "address", "phone", "email",
    "signatory_name", "signatory_title", "capability_statement",
  ];

  function $(id) { return document.getElementById(id); }

  function withProfile(path) {
    if (!state.activeProfile) return path;
    return path + (path.includes("?") ? "&" : "?") + "profile=" + encodeURIComponent(state.activeProfile);
  }

  async function api(path, options) {
    const resp = await fetch(withProfile(path), Object.assign({
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
        if (btn.dataset.tab === "packets") loadPackets();
      });
    });
  }

  // ---------------- Bid Desk ----------------

  const desk = { folder: null, blanks: [], rows: [], solicitation: "" };

  function money(n) {
    return "$" + (Math.round(n * 100) / 100).toLocaleString(undefined, {
      minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function urgency(days) {
    if (days === null || days === undefined) return { cls: "badge-low", text: "no deadline listed" };
    if (days < 0) return { cls: "badge-low", text: "closed" };
    if (days <= 3) return { cls: "badge-great", text: days + " days left" };
    if (days <= 10) return { cls: "badge-good", text: days + " days left" };
    return { cls: "badge-maybe", text: days + " days left" };
  }

  async function loadPackets() {
    $("packet-detail-view").hidden = true;
    $("packet-list-view").hidden = false;

    const fb = await api("/api/factbank");
    const banner = $("factbank-banner");
    if (fb.required_missing && fb.required_missing.length) {
      banner.hidden = false;
      banner.className = "notice notice-warn";
      banner.innerHTML = "<strong>Your business details aren't complete yet.</strong> " +
        "Until they are, every packet repeats the same blanks: " +
        fb.required_missing.map(escapeHtml).join(", ") +
        ". Fill them once in <code>company.toml</code> and they fill themselves forever after.";
    } else if (fb.leverage_missing && fb.leverage_missing.length) {
      banner.hidden = false;
      banner.className = "notice notice-info";
      banner.innerHTML = "<strong>Ready to submit.</strong> These would still save you work on " +
        "every packet: " + fb.leverage_missing.map(escapeHtml).join(", ") + ".";
    } else {
      banner.hidden = true;
    }

    const data = await api("/api/packets");
    const list = $("packets-list");
    list.innerHTML = "";
    const packets = data.packets || [];
    $("packets-empty").hidden = packets.length > 0;

    packets.forEach((p) => {
      const u = urgency(p.days);
      const card = document.createElement("div");
      card.className = "opp-card";
      card.innerHTML =
        '<div class="opp-head"><span class="opp-title">' + escapeHtml(p.title) + "</span>" +
        '<span class="badge ' + u.cls + '">' + u.text + "</span></div>" +
        '<div class="opp-meta">Due ' + escapeHtml(p.deadline || "—") +
        " &middot; " + (p.blanks === null ? "—" : p.blanks) + " blanks left" +
        " &middot; " + p.attachments + " document" + (p.attachments === 1 ? "" : "s") +
        "</div>";
      card.addEventListener("click", () => openPacket(p.folder));
      list.appendChild(card);
    });
  }

  async function openPacket(folder) {
    const d = await api("/api/packets/" + encodeURIComponent(folder));
    if (!d.ok) { alert("Could not open that packet."); return; }

    desk.folder = folder;
    desk.blanks = d.blanks || [];
    desk.rows = d.price_rows || [];

    $("packet-list-view").hidden = true;
    $("packet-detail-view").hidden = false;
    $("packet-title").textContent = d.summary.title;

    // The facts table comes straight out of the checklist the tool wrote,
    // so the page and the file can never tell different stories.
    const facts = [];
    (d.start_here || "").split("\n").forEach((line) => {
      const m = line.match(/^\|\s*(?:\*\*)?([^|*]+?)(?:\*\*)?\s*\|\s*(?:\*\*)?(.+?)(?:\*\*)?\s*\|$/);
      if (m && m[1].trim() !== "" && !/^-+$/.test(m[2])) facts.push([m[1].trim(), m[2].trim()]);
    });
    $("packet-facts").innerHTML = facts.map(([k, v]) =>
      '<div class="fact"><span class="fact-k">' + escapeHtml(k) + "</span>" +
      '<span class="fact-v">' + linkifyPlain(v) + "</span></div>").join("");

    const sol = facts.find(([k]) => /solicitation/i.test(k));
    desk.solicitation = sol ? sol[1] : "";

    $("packet-attachments").innerHTML = (d.attachments || []).length
      ? d.attachments.map((a) =>
          '<a class="attachment" target="_blank" rel="noopener" href="' +
          withProfile("/api/packets/" + encodeURIComponent(folder) + "/file/attachments/" + encodeURIComponent(a.name)) +
          '">' + escapeHtml(a.name) + ' <span class="muted">' +
          (a.size > 1048576 ? (a.size / 1048576).toFixed(1) + " MB" : Math.round(a.size / 1024) + " KB") +
          "</span></a>").join("")
      : '<p class="muted">No attachments came back for this notice — open the listing itself, some agencies post documents only in the notice body.</p>';

    $("packet-email").value = d.email || "";
    $("proposal-download").href = withProfile(
      "/api/packets/" + encodeURIComponent(folder) + "/file/01-proposal.md");

    renderPrice();
    renderBlanks();
  }

  function renderPrice() {
    const body = $("price-table").querySelector("tbody");
    body.innerHTML = "";
    desk.rows.forEach((row, i) => {
      const tr = document.createElement("tr");
      tr.innerHTML =
        '<td><input data-i="' + i + '" data-f="category" value="' + escapeHtml(row.category || "") + '" /></td>' +
        '<td><input class="narrow" data-i="' + i + '" data-f="unit" value="' + escapeHtml(row.unit || "hr") + '" /></td>' +
        '<td><input class="narrow" data-i="' + i + '" data-f="rate" value="' + escapeHtml(row.rate || "") + '" /></td>' +
        '<td><input class="narrow" data-i="' + i + '" data-f="hours" value="' + escapeHtml(row.hours || "") + '" /></td>' +
        '<td class="ext">—</td>';
      body.appendChild(tr);
    });
    body.querySelectorAll("input").forEach((input) => {
      input.addEventListener("input", () => {
        const row = desk.rows[Number(input.dataset.i)];
        row[input.dataset.f] = input.value;
        recalc();
      });
    });
    recalc();
  }

  function recalc() {
    const body = $("price-table").querySelector("tbody");
    let total = 0, any = false;
    desk.rows.forEach((row, i) => {
      const rate = parseFloat(String(row.rate || "").replace(/[^0-9.\-]/g, ""));
      const qty = parseFloat(String(row.hours || "").replace(/[^0-9.\-]/g, ""));
      const cell = body.children[i] && body.children[i].querySelector(".ext");
      if (!cell) return;
      if (isFinite(rate) && isFinite(qty)) {
        const ext = rate * qty;
        total += ext; any = true;
        cell.textContent = money(ext);
      } else {
        cell.textContent = "—";
      }
    });
    $("price-total").textContent = any ? money(total) : "—";
  }

  function renderBlanks() {
    const form = $("blanks-form");
    form.innerHTML = "";
    $("blanks-count").textContent = desk.blanks.length
      ? desk.blanks.length + " blank" + (desk.blanks.length === 1 ? "" : "s") + " left to fill."
      : "Nothing left to fill. Every blank in this proposal has an answer.";

    let section = null;
    desk.blanks.forEach((b) => {
      if (b.section !== section) {
        section = b.section;
        const h = document.createElement("h3");
        h.className = "blank-section";
        h.textContent = section || "Elsewhere in the document";
        form.appendChild(h);
        // These sections repeat the same facts on every bid, so filling
        // them here is work you will redo forever. Say so once, here,
        // where someone is about to do exactly that.
        const hint = {
          "6. Past performance": "These three references are the same on every bid. " +
            "Put them in company.toml once and they fill themselves in from then on.",
          "9. Insurance and bonding": "Also a company.toml fact — enter it once.",
          "7. Price proposal": "Use the price table in step 3 above; saving it fills these.",
        }[section];
        if (hint) {
          const note = document.createElement("p");
          note.className = "blank-hint";
          note.textContent = hint;
          form.appendChild(note);
        }
      }
      const wrap = document.createElement("div");
      wrap.className = "blank-field";
      const input = b.multiline
        ? '<textarea rows="4" data-index="' + b.index + '"></textarea>'
        : '<input type="text" data-index="' + b.index + '" />';
      wrap.innerHTML =
        '<label>' + escapeHtml(b.label) + "</label>" +
        (b.context ? '<p class="blank-context">' + escapeHtml(b.context) + "</p>" : "") +
        input;
      form.appendChild(wrap);
    });
  }

  async function saveBlanks() {
    const answers = {};
    $("blanks-form").querySelectorAll("[data-index]").forEach((el) => {
      if (!el.value.trim()) return;
      const b = desk.blanks.find((x) => x.index === Number(el.dataset.index));
      answers[el.dataset.index] = { label: b ? b.label : "", value: el.value };
    });
    if (!Object.keys(answers).length) {
      $("blanks-saved").textContent = "Nothing to save yet.";
      return;
    }
    const res = await api("/api/packets/" + encodeURIComponent(desk.folder) + "/fill", {
      method: "POST", body: JSON.stringify({ answers: answers }),
    });
    if (!res.ok) {
      // A stale page is refused rather than writing an answer into the
      // wrong blank, so say exactly that and reload the real state.
      $("blanks-saved").textContent = res.error === "stale"
        ? "This page was out of date, so nothing was written. Reloading."
        : "Could not save.";
      if (res.error === "stale") openPacket(desk.folder);
      return;
    }
    desk.blanks = res.blanks || [];
    renderBlanks();
    $("blanks-saved").textContent = "Saved. " + res.remaining + " left.";
  }

  function wireBidDesk() {
    $("packet-back").addEventListener("click", loadPackets);
    $("blanks-save").addEventListener("click", saveBlanks);
    $("price-add-row").addEventListener("click", () => {
      desk.rows.push({ category: "", unit: "hr", rate: "", hours: "" });
      renderPrice();
    });
    $("price-save").addEventListener("click", async () => {
      const res = await api("/api/packets/" + encodeURIComponent(desk.folder) + "/price", {
        method: "POST",
        body: JSON.stringify({ rows: desk.rows, solicitation: desk.solicitation }),
      });
      if (!res.ok) { $("price-saved").textContent = "Could not save."; return; }
      // Saving the price answers the proposal's whole price section, so the
      // fill-in form below has to be redrawn or it shows blanks that are
      // already answered.
      $("price-saved").textContent = "Saved — and it filled the price section of your proposal.";
      if (res.blanks) { desk.blanks = res.blanks; renderBlanks(); }
    });
    $("email-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText($("packet-email").value);
        $("email-copied").textContent = "Copied.";
      } catch (e) {
        $("packet-email").select();
        $("email-copied").textContent = "Press Cmd/Ctrl+C to copy.";
      }
    });
    $("packet-go").addEventListener("click", () => {
      $("packet-go-state").textContent = "Bidding. Price it, fill the blanks, send it.";
      $("step-price").scrollIntoView({ behavior: "smooth", block: "start" });
    });
    $("packet-nogo").addEventListener("click", () => {
      $("packet-go-state").textContent =
        "Not bidding. Add a word from the title to skip_keywords in company.toml and work like it stops reaching you.";
    });
  }

  function linkifyPlain(text) {
    const safe = escapeHtml(text);
    return safe.replace(/(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">open</a>')
      .replace(/([\w.+-]+@[\w.-]+\.\w+)/g, '<a href="mailto:$1">$1</a>');
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
      card.addEventListener("click", () => openDraftModal(draft.filename, draft.notice_id));
      container.appendChild(card);
    });
  }

  async function openDraftModal(filename, noticeId) {
    const result = await api("/api/drafts/" + encodeURIComponent(filename));
    if (!result.ok) return;
    renderDraftContent(filename, result.content, noticeId);
    showModal();
  }

  const isTableRow = (line) => line.trim().startsWith("|") && line.trim().endsWith("|");
  const isTableDivider = (line) => /^\|[\s:|-]+\|$/.test(line.trim());
  const tableCells = (line) => line.trim().slice(1, -1).split("|").map((c) => c.trim());

  function renderDraftContent(filename, content, noticeId) {
    const lines = content.split("\n");
    const html = [];
    let inList = false;
    let inQuote = false;

    const closeList = () => { if (inList) { html.push("</ul>"); inList = false; } };
    const closeQuote = () => { if (inQuote) { html.push("</blockquote>"); inQuote = false; } };

    for (let idx = 0; idx < lines.length; idx++) {
      const line = lines[idx];

      const checklistMatch = line.match(/^- \[( |x|X)\] (.*)$/);
      if (checklistMatch) {
        closeQuote();
        if (!inList) { html.push("<ul>"); inList = true; }
        const checked = checklistMatch[1].toLowerCase() === "x";
        html.push(`<li class="checklist-item"><label><input type="checkbox" data-line="${idx}" ${checked ? "checked" : ""}/> <span>${escapeHtml(checklistMatch[2])}</span></label></li>`);
        continue;
      }
      closeList();

      // Markdown table: a run of | rows, with an optional |---| divider
      // after the first, which marks that first row as the header.
      if (isTableRow(line) && !isTableDivider(line)) {
        closeQuote();
        const headerRow = tableCells(line);
        let cursor = idx + 1;
        const hasHeader = cursor < lines.length && isTableDivider(lines[cursor]);
        if (hasHeader) cursor++;
        const bodyRows = [];
        while (cursor < lines.length && isTableRow(lines[cursor]) && !isTableDivider(lines[cursor])) {
          bodyRows.push(tableCells(lines[cursor]));
          cursor++;
        }
        const cell = (c, tag) => `<${tag}>${inlineMd(c)}</${tag}>`;
        html.push('<div class="table-scroll"><table>');
        if (hasHeader) {
          html.push("<thead><tr>" + headerRow.map((c) => cell(c, "th")).join("") + "</tr></thead>");
        } else {
          bodyRows.unshift(headerRow);
        }
        html.push("<tbody>" + bodyRows.map((r) => "<tr>" + r.map((c) => cell(c, "td")).join("") + "</tr>").join("") + "</tbody>");
        html.push("</table></div>");
        idx = cursor - 1;
        continue;
      }

      if (line.startsWith(">")) {
        if (!inQuote) { html.push("<blockquote>"); inQuote = true; }
        html.push(`<p>${inlineMd(line.replace(/^>\s?/, ""))}</p>`);
        continue;
      }
      closeQuote();

      if (line.startsWith("### ")) { html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`); continue; }
      if (line.startsWith("## ")) { html.push(`<h2>${escapeHtml(line.slice(3))}</h2>`); continue; }
      if (line.startsWith("# ")) { html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`); continue; }
      if (line.trim() === "---") { html.push("<hr />"); continue; }
      if (line.startsWith("- ")) {
        const boldMatch = line.match(/^- \*\*(.+?):\*\* (.*)$/);
        if (boldMatch) {
          html.push(`<p><strong>${escapeHtml(boldMatch[1])}:</strong> ${inlineMd(boldMatch[2])}</p>`);
        } else {
          html.push(`<p>${inlineMd(line.slice(2))}</p>`);
        }
        continue;
      }
      if (line.trim() === "") { continue; }
      html.push(`<p>${inlineMd(line)}</p>`);
    }
    closeList();
    closeQuote();

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

    if (noticeId) {
      const btn = document.createElement("button");
      btn.className = "btn btn-primary";
      btn.textContent = "📝 Build proposal draft";
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "Building...";
        const res = await api("/api/proposals/" + encodeURIComponent(noticeId), { method: "POST" });
        btn.disabled = false;
        btn.textContent = "📝 Build proposal draft";
        if (res.ok) {
          renderProposal(res);
        } else {
          const note = document.createElement("p");
          note.className = "muted";
          note.textContent = res.error === "notice_not_cached"
            ? "This packet is from an older search, so the full notice isn't saved. Run a new search and proposal drafts will be available for anything new."
            : "Couldn't build the draft.";
          btn.after(note);
        }
      });
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent = "Builds a cover letter, technical-approach outline matching this solicitation's own sections, a requirements table, and blank price/past-performance worksheets for you to fill in. Never submits anything.";
      $("modal-body").append(hint, btn);
    }
  }

  function renderProposal(res) {
    renderDraftContent(res.filename, res.content, null);
    const banner = document.createElement("p");
    banner.className = "muted";
    banner.textContent = `Saved as ${res.filename} — ${res.blanks} blanks marked [[FILL: ...]] for you to complete. Nothing has been submitted.`;
    $("modal-body").prepend(banner);
    $("modal-backdrop").scrollTop = 0;
  }

  function inlineMd(text) {
    // Escape first, then apply inline markers. Draft lines like
    // "- **NAICS:** 541213  **PSC:** R710" carry a second bold marker after
    // the label renderDraftContent already peeled off, and proposal drafts
    // use `code` spans and [[FILL: ...]] blanks that should stand out.
    let out = escapeHtml(text);
    out = out.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\[\[FILL:([^\]]*)\]\]/g, '<span class="fill-blank">$1</span>');
    return out.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  }

  // Kept as an alias: older call sites still say linkify().
  const linkify = inlineMd;

  // ---------------- Settings ----------------

  async function loadSettings() {
    const data = await api("/api/settings");
    state.settings = data.settings;
    state.activeProfile = data.active_profile;
    state.profiles = data.profiles || [];
    state.certOptions = data.certification_options;
    state.naicsCodes = data.settings.naics_codes.slice();
    renderProfileSwitch();
    renderSettingsForm();
    renderCredentialStatus();
  }

  function renderProfileSwitch() {
    const sel = $("profile-switch");
    if (!sel || !state.profiles.length) return;
    sel.innerHTML = state.profiles
      .map((p) => `<option value="${escapeAttr(p.key)}"${p.key === state.activeProfile ? " selected" : ""}>${escapeHtml(p.label)}</option>`)
      .join("");
    if (!sel.dataset.wired) {
      sel.dataset.wired = "1";
      sel.addEventListener("change", async () => {
        // Persist the choice, then reload everything: results, packets and
        // settings are all per-business.
        await api("/api/settings", {
          method: "POST",
          body: JSON.stringify({ switch_to: sel.value }),
        });
        state.activeProfile = sel.value;
        $("summary-cards").hidden = true;
        $("dashboard-preview").innerHTML = "";
        $("opportunities-list").innerHTML = "";
        $("drafts-list").innerHTML = "";
        $("search-status").textContent = "";
        await loadSettings();
        await loadLastOpportunities();
        loadDrafts();
      });
    }
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

    const profile = s.company_profile || {};
    COMPANY_FIELDS.forEach((key) => {
      const el = $("cp-" + key);
      if (el) el.value = profile[key] || "";
    });
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

    const companyProfile = {};
    COMPANY_FIELDS.forEach((key) => {
      const el = $("cp-" + key);
      if (el) companyProfile[key] = el.value;
    });

    await api("/api/settings", {
      method: "POST",
      body: JSON.stringify({
        company_profile: companyProfile,
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
    wireBidDesk();
    loadSettings();
    loadLastOpportunities();
  }

  checkSetup();
})();
