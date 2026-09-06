/* File-note copilot front end. No framework, no build step, no inline handlers.
   Small pure functions (rendering, diffing, note bookkeeping) are exposed on window.filenote
   so the browser tests can exercise them directly. */
(function () {
  "use strict";

  // ----- pure helpers -------------------------------------------------------------------------

  const SECTIONS = [
    ["circumstance_changes", "Changes in circumstances"],
    ["goals", "Goals"],
    ["topics_discussed", "Topics discussed"],
    ["advice_discussed", "Advice discussed"],
    ["decisions", "Decisions"],
    ["action_items", "Action items"],
  ];

  function labelOf(item) {
    return item.text !== undefined ? item.text : item.description;
  }

  function isFlagged(item) {
    return Boolean(item.unsupported) && !item.edited;
  }

  function sectionItems(note, section) {
    if (section === "vulnerability_indicators") return note.compliance.vulnerability_indicators || [];
    if (section === "follow_up") return note.follow_up ? [note.follow_up] : [];
    return note[section] || [];
  }

  function unsupportedCount(note) {
    let n = 0;
    const all = SECTIONS.map((s) => s[0]).concat(["vulnerability_indicators", "follow_up"]);
    for (const s of all) for (const item of sectionItems(note, s)) if (isFlagged(item)) n += 1;
    return n;
  }

  function setClaimText(note, section, index, text) {
    const items = sectionItems(note, section);
    const item = items[index];
    if (!item) return note;
    if (item.text !== undefined) item.text = text;
    else item.description = text;
    item.edited = true;
    return note;
  }

  function deleteClaim(note, section, index) {
    if (section === "follow_up") note.follow_up = null;
    else if (section === "vulnerability_indicators") note.compliance.vulnerability_indicators.splice(index, 1);
    else note[section].splice(index, 1);
    return note;
  }

  // Longest-common-subsequence line diff: returns [{type: "same"|"add"|"del", line}].
  function diffLines(a, b) {
    const n = a.length;
    const m = b.length;
    const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    const out = [];
    let i = 0;
    let j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { out.push({ type: "same", line: a[i] }); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push({ type: "del", line: a[i] }); i++; }
      else { out.push({ type: "add", line: b[j] }); j++; }
    }
    while (i < n) out.push({ type: "del", line: a[i++] });
    while (j < m) out.push({ type: "add", line: b[j++] });
    return out;
  }

  function formatTime(seconds) {
    const t = Math.floor(seconds);
    const h = String(Math.floor(t / 3600)).padStart(2, "0");
    const mnt = String(Math.floor((t % 3600) / 60)).padStart(2, "0");
    const s = String(t % 60).padStart(2, "0");
    return `${h}:${mnt}:${s}`;
  }

  // ----- rendering (DOM-producing but side-effect free w.r.t. app state) ----------------------

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    if (attrs) for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v);
    }
    if (children) for (const c of children) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    return node;
  }

  function renderTranscript(transcript, container) {
    container.replaceChildren();
    for (const seg of transcript.segments) {
      const li = el("li", { class: `segment role-${seg.role}`, id: `seg-${seg.id}`, "data-id": seg.id, tabindex: "-1" });
      li.appendChild(el("span", { class: "sid", text: seg.id }));
      li.appendChild(el("span", { class: "time", text: formatTime(seg.t) }));
      const body = el("span", { class: "body" });
      body.appendChild(el("span", { class: "speaker", text: seg.speaker + " " }));
      body.appendChild(el("span", { class: "role", text: `(${seg.role}): ` }));
      body.appendChild(document.createTextNode(seg.text));
      li.appendChild(body);
      container.appendChild(li);
    }
  }

  function renderClaim(item, section, index, template, knownIds) {
    const node = template.content.firstElementChild.cloneNode(true);
    node.dataset.section = section;
    node.dataset.index = String(index);
    node.querySelector(".claim-text").textContent = labelOf(item);
    const meta = [];
    if (item.owner) meta.push(`owner: ${item.owner}`);
    if (item.due) meta.push(`due ${item.due}`);
    node.querySelector(".claim-meta").textContent = meta.join(" · ");
    const flagged = isFlagged(item);
    node.classList.toggle("unsupported", flagged);
    node.classList.toggle("edited", Boolean(item.edited));
    node.querySelector(".flag").hidden = !flagged;
    const reasons = node.querySelector(".reasons");
    reasons.hidden = !(flagged && item.reasons && item.reasons.length);
    if (!reasons.hidden) for (const r of item.reasons) reasons.appendChild(el("li", { text: r }));
    const chips = node.querySelector(".chips");
    for (const sid of item.evidence) {
      const missing = knownIds && !knownIds.has(sid);
      const chip = el("button", { type: "button", class: "chip" + (missing ? " missing" : ""), "data-target": sid, text: sid, "aria-label": `Show segment ${sid}` });
      if (missing) chip.title = "segment not in transcript";
      chips.appendChild(chip);
    }
    if (item.evidence.length === 0) chips.appendChild(el("span", { class: "empty", text: "no evidence" }));
    return node;
  }

  function renderNote(note, container, template, knownIds) {
    container.replaceChildren();
    container.appendChild(el("p", { class: "summary", text: note.summary || "(no summary)" }));
    for (const [section, title] of SECTIONS) {
      container.appendChild(el("h4", { text: title }));
      const items = sectionItems(note, section);
      const list = el("ol", { class: "claims", "data-section": section });
      if (items.length === 0) list.appendChild(el("li", { class: "empty", text: "(none)" }));
      items.forEach((item, i) => list.appendChild(renderClaim(item, section, i, template, knownIds)));
      container.appendChild(list);
    }
    container.appendChild(el("h4", { text: "Compliance" }));
    const c = note.compliance;
    const comp = el("ul", { class: "compliance" });
    comp.appendChild(el("li", { text: `Risk profile confirmed: ${fmtBool(c.risk_profile_confirmed)}${c.risk_profile ? ` (${c.risk_profile})` : ""}` }));
    comp.appendChild(el("li", { text: `Ongoing fee consent discussed: ${fmtBool(c.fee_consent_discussed)}` }));
    comp.appendChild(el("li", { text: `Conflicts / related-party products disclosed: ${fmtBool(c.conflicts_disclosed)}` }));
    container.appendChild(comp);
    const vul = sectionItems(note, "vulnerability_indicators");
    if (vul.length) {
      container.appendChild(el("h4", { text: "Vulnerability indicators" }));
      const list = el("ol", { class: "claims", "data-section": "vulnerability_indicators" });
      vul.forEach((item, i) => list.appendChild(renderClaim(item, "vulnerability_indicators", i, template, knownIds)));
      container.appendChild(list);
    }
    container.appendChild(el("h4", { text: "Follow-up" }));
    const fu = sectionItems(note, "follow_up");
    const fuList = el("ol", { class: "claims", "data-section": "follow_up" });
    if (fu.length === 0) fuList.appendChild(el("li", { class: "empty", text: "(none)" }));
    fu.forEach((item, i) => fuList.appendChild(renderClaim(item, "follow_up", i, template, knownIds)));
    container.appendChild(fuList);
  }

  function fmtBool(v) {
    if (v === true) return "yes";
    if (v === false) return "no";
    return "not recorded";
  }

  function renderDiff(entries, container) {
    container.replaceChildren();
    for (const e of entries) {
      const prefix = e.type === "add" ? "+ " : e.type === "del" ? "- " : "  ";
      container.appendChild(el("span", { class: e.type === "same" ? "same" : e.type, text: prefix + e.line + "\n" }));
    }
  }

  // ----- SSE client with reconnection -------------------------------------------------------

  function subscribe(draftId, handlers) {
    let lastId = 0;
    let source = null;
    let retries = 0;
    let closed = false;

    function open() {
      if (closed) return;
      const url = `/api/drafts/${draftId}/events?last_id=${lastId}`;
      source = new EventSource(url);
      const on = (name) => (ev) => {
        if (ev.lastEventId) lastId = Number(ev.lastEventId);
        retries = 0;
        let data = {};
        try { data = JSON.parse(ev.data); } catch (_) { data = {}; }
        if (handlers[name]) handlers[name](data);
        if (name === "done" || name === "error") close();
      };
      for (const name of ["stage", "partial", "done", "error"]) source.addEventListener(name, on(name));
      source.onerror = () => {
        if (closed) return;
        source.close();
        retries += 1;
        if (retries > 20) { if (handlers.error) handlers.error({ message: "connection lost" }); close(); return; }
        if (handlers.reconnect) handlers.reconnect(retries);
        setTimeout(open, Math.min(500 * retries, 5000));
      };
    }

    function close() {
      closed = true;
      if (source) source.close();
    }

    open();
    return { close };
  }

  // ----- app state and wiring -------------------------------------------------------------

  const state = { draftId: null, note: null, transcript: null, knownIds: null, approved: false, thumbs: null, subscription: null };
  const $ = (id) => document.getElementById(id);

  function setStatus(text, kind) {
    const node = $("status");
    node.textContent = text;
    node.dataset.kind = kind || "info";
  }

  function addProgress(text, cls) {
    const list = $("progress");
    for (const li of list.querySelectorAll(".current")) li.classList.remove("current");
    list.appendChild(el("li", { class: cls || "current", text }));
  }

  function refreshVerdict() {
    const n = state.note ? unsupportedCount(state.note) : 0;
    const v = $("verdict");
    v.replaceChildren();
    if (!state.note) return;
    if (state.approved) {
      v.appendChild(el("span", { class: "pill ok", text: "approved" }));
    } else if (n === 0) {
      v.appendChild(el("span", { class: "pill ok", text: "every claim supported or reviewed" }));
    } else {
      v.appendChild(el("span", { class: "pill bad", text: `${n} unsupported claim${n === 1 ? "" : "s"} to resolve` }));
    }
    $("approve-button").disabled = state.approved || n > 0;
    $("approve-button").dataset.unsupported = String(n);
  }

  function repaint() {
    renderNote(state.note, $("note"), $("claim-template"), state.knownIds);
    refreshVerdict();
    markCited();
  }

  function markCited() {
    const cited = new Set();
    for (const chip of document.querySelectorAll(".chip")) cited.add(chip.dataset.target);
    for (const seg of document.querySelectorAll(".segment")) seg.classList.toggle("cited", cited.has(seg.dataset.id));
  }

  function highlightSegment(sid) {
    for (const seg of document.querySelectorAll(".segment.highlight")) seg.classList.remove("highlight");
    const target = document.getElementById(`seg-${sid}`);
    if (!target) { setStatus(`Segment ${sid} is not in the transcript.`, "warn"); return; }
    target.classList.add("highlight");
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.focus({ preventScroll: true });
  }

  async function api(path, options) {
    const resp = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, options || {}));
    let body = null;
    try { body = await resp.json(); } catch (_) { body = null; }
    if (!resp.ok) {
      const detail = body && body.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : resp.statusText;
      throw new Error(detail);
    }
    return body;
  }

  async function saveNote() {
    const payload = await api(`/api/drafts/${state.draftId}`, { method: "PUT", body: JSON.stringify({ note: state.note, editor: $("approver").value || "adviser" }) });
    state.note = payload.note;
    repaint();
    setStatus(`Saved version ${payload.version}.`, "ok");
  }

  function startEdit(claimNode) {
    const section = claimNode.dataset.section;
    const index = Number(claimNode.dataset.index);
    const item = sectionItems(state.note, section)[index];
    if (!item || claimNode.querySelector(".editor")) return;
    const editor = el("textarea", { class: "editor", rows: "2", "aria-label": "Edit claim text" });
    editor.value = labelOf(item);
    const row = el("editor-row");
    const save = el("button", { type: "button", class: "primary save-edit", text: "Save" });
    const cancel = el("button", { type: "button", class: "cancel-edit", text: "Cancel" });
    row.className = "editor-row";
    row.append(save, cancel);
    claimNode.appendChild(editor);
    claimNode.appendChild(row);
    editor.focus();
    save.addEventListener("click", async () => {
      setClaimText(state.note, section, index, editor.value.trim() || labelOf(item));
      try { await saveNote(); } catch (err) { setStatus(`Could not save: ${err.message}`, "warn"); }
    });
    cancel.addEventListener("click", () => { editor.remove(); row.remove(); });
  }

  async function onNoteClick(ev) {
    const chip = ev.target.closest(".chip");
    if (chip) { highlightSegment(chip.dataset.target); return; }
    const claimNode = ev.target.closest(".claim");
    if (!claimNode) return;
    if (ev.target.closest(".edit-button")) { startEdit(claimNode); return; }
    if (ev.target.closest(".delete-button")) {
      deleteClaim(state.note, claimNode.dataset.section, Number(claimNode.dataset.index));
      try { await saveNote(); } catch (err) { setStatus(`Could not save: ${err.message}`, "warn"); }
    }
  }

  function onNoteKey(ev) {
    if (ev.key !== "Enter" || ev.target.tagName === "TEXTAREA" || ev.target.tagName === "BUTTON" || ev.target.tagName === "INPUT") return;
    const claimNode = ev.target.closest(".claim");
    if (claimNode && ev.target === claimNode) startEdit(claimNode);
  }

  function showDraft(payload) {
    state.transcript = payload.transcript;
    state.knownIds = new Set(payload.transcript.segments.map((s) => s.id));
    state.note = payload.note;
    state.approved = payload.status === "approved";
    $("workspace").hidden = false;
    renderTranscript(state.transcript, $("segments"));
    repaint();
    if (payload.approval) showApproval(payload.approval, payload);
  }

  function showApproval(approval, payload) {
    state.approved = true;
    $("approval").hidden = false;
    $("approval-meta").textContent = `Approved by ${approval.approver} at ${approval.approved_at} (version ${approval.version_n}, ${approval.changed_lines} changed line${approval.changed_lines === 1 ? "" : "s"} vs the AI draft).`;
    const lines = approval.diff ? approval.diff.split("\n") : [];
    const entries = lines.map((line) => ({ type: line.startsWith("+") && !line.startsWith("+++") ? "add" : line.startsWith("-") && !line.startsWith("---") ? "del" : "same", line }));
    renderDiff(entries, $("approval-diff"));
    refreshVerdict();
    if (payload) setStatus("Note approved and saved.", "ok");
  }

  async function startDraft(ev) {
    ev.preventDefault();
    const strategy = $("strategy").value;
    const file = $("file").files[0];
    $("progress").replaceChildren();
    $("workspace").hidden = true;
    $("approval").hidden = true;
    state.approved = false;
    state.thumbs = null;
    $("thumbs-up").setAttribute("aria-pressed", "false");
    $("thumbs-down").setAttribute("aria-pressed", "false");
    try {
      let created;
      if (file) {
        const form = new FormData();
        form.append("file", file);
        form.append("strategy", strategy);
        const resp = await fetch("/api/drafts/upload", { method: "POST", body: form });
        created = await resp.json();
        if (!resp.ok) throw new Error(created.detail || resp.statusText);
      } else {
        created = await api("/api/drafts", { method: "POST", body: JSON.stringify({ transcript: $("transcript").value, strategy }) });
      }
      state.draftId = created.draft_id;
      setStatus(`Draft ${created.draft_id}: ${created.segments} segments queued.`, "info");
      addProgress("queued");
      if (state.subscription) state.subscription.close();
      state.subscription = subscribe(created.draft_id, {
        stage: (d) => { addProgress(`${d.stage}${d.message ? ": " + d.message : ""}`); setStatus(`${d.stage}…`, "info"); },
        partial: (d) => addProgress(`${d.section}: ${d.message}`),
        reconnect: (n) => setStatus(`Connection dropped, reconnecting (${n})…`, "warn"),
        error: (d) => { addProgress(`error: ${d.message}`, "error"); setStatus(`Drafting failed: ${d.message}`, "warn"); },
        done: async () => {
          addProgress("done", "");
          const payload = await api(`/api/drafts/${state.draftId}`);
          showDraft(payload);
          const n = unsupportedCount(payload.note);
          setStatus(n === 0 ? "Draft ready: every claim is supported." : `Draft ready: ${n} unsupported claim${n === 1 ? "" : "s"} need your attention.`, n === 0 ? "ok" : "warn");
        },
      });
    } catch (err) {
      setStatus(`Could not start draft: ${err.message}`, "warn");
    }
  }

  async function approve() {
    try {
      const payload = await api(`/api/drafts/${state.draftId}/approve`, { method: "POST", body: JSON.stringify({ approver: $("approver").value || "adviser" }) });
      state.note = payload.note;
      repaint();
      showApproval(payload.approval, payload);
    } catch (err) {
      setStatus(`Approval refused: ${err.message}`, "warn");
    }
  }

  async function sendFeedback() {
    if (!state.thumbs) { setStatus("Choose thumbs up or down first.", "warn"); return; }
    const wrong = Array.from(document.querySelectorAll(".wrong-box:checked")).map((box) => {
      const claim = box.closest(".claim");
      return `${claim.dataset.section}[${claim.dataset.index}]: ${claim.querySelector(".claim-text").textContent}`;
    });
    try {
      await api(`/api/drafts/${state.draftId}/feedback`, { method: "POST", body: JSON.stringify({ thumbs: state.thumbs, comment: $("feedback-comment").value, wrong_claims: wrong }) });
      setStatus("Feedback recorded, thank you.", "ok");
      $("feedback-comment").value = "";
    } catch (err) {
      setStatus(`Could not send feedback: ${err.message}`, "warn");
    }
  }

  function setThumbs(which) {
    state.thumbs = which;
    $("thumbs-up").setAttribute("aria-pressed", String(which === "up"));
    $("thumbs-down").setAttribute("aria-pressed", String(which === "down"));
  }

  const SAMPLE = [
    "# meeting: sample",
    "# date: 2026-03-12",
    "# type: annual_review",
    "# attendee: Sarah Nguyen | adviser",
    "# attendee: James Chen | client",
    "s001 [00:00:04] Sarah Nguyen (adviser): How was the drive in? The traffic on the bridge was terrible.",
    "s002 [00:00:09] James Chen (client): Not too bad, we came in on the train.",
    "s003 [00:00:14] Sarah Nguyen (adviser): This is your annual review, so let's go through what has changed and then the plan.",
    "s004 [00:00:22] James Chen (client): Big change since we last spoke: I started a new job at Harbourline Logistics in March, as a project manager. Salary is ninety-five thousand now.",
    "s005 [00:00:33] Sarah Nguyen (adviser): Congratulations. So $95k, up from eighty-two thousand?",
    "s006 [00:00:38] James Chen (client): Yes, that's right.",
    "s007 [00:00:45] Sarah Nguyen (adviser): The concessional contribution cap this year is thirty thousand. Your employer contributions come to about $11,000, so there is roughly $19,000 of headroom.",
    "s008 [00:00:58] Sarah Nguyen (adviser): You could salary sacrifice $12,000 a year and stay under the cap. It's taxed at fifteen percent going in rather than your marginal rate.",
    "s009 [00:01:06] James Chen (client): Can I think about it? Cash flow is tight with the renovation.",
    "s010 [00:01:10] Sarah Nguyen (adviser): Of course, we'll park that and revisit at the next review.",
    "s011 [00:01:18] Sarah Nguyen (adviser): Your cover through Northshore Life is $600,000 of life cover and $400,000 TPD. Given the mortgage I'd suggest increasing the life cover to $800,000.",
    "s012 [00:01:29] James Chen (client): Yes, let's go ahead with that.",
    "s013 [00:01:32] Sarah Nguyen (adviser): Great, we'll increase the life cover to eight hundred thousand, subject to underwriting.",
    "s014 [00:01:40] Sarah Nguyen (adviser): On risk profile, last time we had you as Balanced. Are you still comfortable with that?",
    "s015 [00:01:45] James Chen (client): Yes, that still feels right.",
    "s016 [00:01:52] Sarah Nguyen (adviser): I'll prepare the Statement of Advice for the insurance recommendation and get it to you by 26 March.",
    "s017 [00:02:00] Sarah Nguyen (adviser): Could you send me your latest super statement by 20 March?",
    "s018 [00:02:04] James Chen (client): Sure, I'll send it through.",
    "s019 [00:02:10] Sarah Nguyen (adviser): Let's lock in the next review for 12 September 2026.",
    "s020 [00:02:14] James Chen (client): Works for me. Say hi to the kids.",
  ].join("\n");

  function init() {
    $("draft-form").addEventListener("submit", startDraft);
    $("sample-button").addEventListener("click", () => { $("transcript").value = SAMPLE; $("file").value = ""; });
    $("note").addEventListener("click", onNoteClick);
    $("note").addEventListener("keydown", onNoteKey);
    $("approve-button").addEventListener("click", approve);
    $("thumbs-up").addEventListener("click", () => setThumbs("up"));
    $("thumbs-down").addEventListener("click", () => setThumbs("down"));
    $("feedback-button").addEventListener("click", sendFeedback);
    const params = new URLSearchParams(window.location.search);
    if (params.get("draft")) {
      state.draftId = params.get("draft");
      api(`/api/drafts/${state.draftId}`).then(showDraft).catch((err) => setStatus(err.message, "warn"));
    }
  }

  window.filenote = { diffLines, unsupportedCount, setClaimText, deleteClaim, renderNote, renderTranscript, sectionItems, isFlagged, subscribe, state, SAMPLE };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
