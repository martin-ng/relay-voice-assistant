const $ = (s) => document.querySelector(s);
const state = {
  session: null,
  snapshot: null,
  dashboard: null,
  filter: "confirmed",
  view: "overview",
  busy: false,
  operatorToken: "",
  retry: null,
};
const titles = {
  overview: [
    "A little less busywork.",
    "Your front desk, with room to breathe.",
  ],
  appointments: [
    "Every appointment, in place.",
    "Availability and bookings for your service bay.",
  ],
  sessions: [
    "Conversations with context.",
    "A durable record of each scheduling session.",
  ],
  handoffs: [
    "A human touch, when it counts.",
    "Pick up where the assistant left off.",
  ],
  activity: [
    "Nothing behind the curtain.",
    "Inspect booking actions, outcomes, and failures.",
  ],
};
const dateFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});
function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}
function notice(message, retry) {
  const n = $("#notice");
  n.replaceChildren();
  n.hidden = !message;
  if (!message) return;
  n.append(document.createTextNode(message));
  if (retry) {
    const b = el("button", "Retry");
    b.onclick = retry;
    n.append(b);
  }
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  try {
    const r = await fetch(path, {
      ...options,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    let data;
    try {
      data = await r.json();
    } catch {
      throw new Error("The server returned an unreadable response.");
    }
    if (!r.ok)
      throw new Error(
        data.message || data.error || `Request failed (${r.status})`,
      );
    return data;
  } finally {
    clearTimeout(timeout);
  }
}
function sessionHeaders() {
  return { "X-Session-Token": state.session.token };
}
function operatorHeaders() {
  return state.operatorToken
    ? { Authorization: `Bearer ${state.operatorToken}` }
    : {};
}
function saveSession() {
  try {
    sessionStorage.setItem("relay-session", JSON.stringify(state.session));
  } catch {
    notice(
      "Session storage is unavailable. Keep this tab open to retain access to your bookings.",
    );
  }
}
async function newSession() {
  if (state.busy) return;
  state.busy = true;
  setBusy();
  try {
    state.session = await api("/api/sessions", { method: "POST", body: "{}" });
    saveSession();
    state.retry = null;
    state.snapshot = await api(`/api/sessions/${state.session.id}`, {
      headers: sessionHeaders(),
    });
    renderChat();
    await refresh();
    notice("");
  } catch (e) {
    notice(e.message);
  } finally {
    state.busy = false;
    setBusy();
  }
}
function setBusy() {
  document
    .querySelectorAll(
      "#chat-form button,#choices button,.quick-actions button,#new-session,#reset-chat,#demo-book",
    )
    .forEach(
      (b) =>
        (b.disabled = state.busy || (b.id === "mic" && !SpeechRecognition)),
    );
  $("#message").disabled = state.busy;
}
async function send(text, requestId) {
  if (state.busy || !state.session) return;
  const message = (text || "").trim();
  if (!message) return;
  state.busy = true;
  setBusy();
  const id = requestId || crypto.randomUUID();
  try {
    const snapshot = await api(`/api/sessions/${state.session.id}/messages`, {
      method: "POST",
      headers: sessionHeaders(),
      body: JSON.stringify({ text: message, request_id: id }),
    });
    state.snapshot = snapshot;
    state.retry = null;
    $("#message").value = "";
    notice("");
    renderChat();
    speak(snapshot.messages.at(-1).content);
    await refresh();
  } catch (e) {
    state.retry = { text: message, id };
    notice(
      `Message not acknowledged: ${e.message} Retry safely with the same request ID.`,
      () => send(message, id),
    );
  } finally {
    state.busy = false;
    setBusy();
    $("#message").focus();
  }
}
function renderChat() {
  const box = $("#messages");
  box.replaceChildren();
  for (const m of state.snapshot.messages) {
    const b = el("div", undefined, `bubble ${m.role}`);
    b.append(
      el("span", m.role === "user" ? "YOU" : "RELAY", "bubble-label"),
      document.createTextNode(m.content),
    );
    box.append(b);
  }
  box.scrollTop = box.scrollHeight;
  const choices = $("#choices");
  choices.replaceChildren();
  const s = state.snapshot.state;
  const add = (label, message) => {
    const b = el("button", label, "choice");
    b.onclick = () => send(message);
    choices.append(b);
  };
  if (s.pending) {
    add("Confirm", "confirm");
    add("No, go back", "no");
  } else if (s.slots?.length) {
    s.slots.forEach((slot, i) =>
      add(
        `${i + 1}. ${dateFmt.format(new Date(slot.starts_at))}`,
        String(i + 1),
      ),
    );
  } else if (state.snapshot.messages.length === 1) {
    add("Book an inspection", "book an inspection");
    add("Consultation", "book a consultation");
    add("Maintenance", "book maintenance");
  }
}
async function refresh() {
  try {
    state.dashboard = await api("/api/operator/dashboard", {
      headers: operatorHeaders(),
    });
    $("#connection").textContent = "Workspace connected";
    renderDashboard();
  } catch (e) {
    $("#connection").textContent = "Dashboard unavailable";
    notice(e.message);
  }
}
function renderDashboard() {
  const d = state.dashboard;
  if (!d) return;
  $("#metric-bookings").textContent = d.metrics.confirmed;
  $("#metric-sessions").textContent = d.metrics.sessions;
  $("#metric-latency").textContent =
    d.metrics.p95_ms === null ? "—" : `${Math.round(d.metrics.p95_ms)} ms`;
  const open = d.handoffs.filter((h) => h.status === "open");
  $("#metric-handoffs").textContent = open.length;
  $("#handoff-badge").textContent = open.length;
  renderAppointments();
  renderSessions();
  renderHandoffs();
  renderEvents();
}
function renderAppointments() {
  const query = $("#search").value.toLowerCase();
  const rows = state.dashboard.appointments
    .filter(
      (a) =>
        (state.filter === "all" ||
          (a.status === "confirmed" && new Date(a.starts_at) > new Date())) &&
        `${a.service} ${a.id}`.includes(query),
    )
    .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
  const body = $("#appointment-rows");
  body.replaceChildren();
  for (const a of rows) {
    const tr = el("tr");
    const service = el("td");
    service.append(
      el("strong", a.service.charAt(0).toUpperCase() + a.service.slice(1)),
      el(
        "small",
        `${Math.round((new Date(a.ends_at) - new Date(a.starts_at)) / 60000)} min · Service bay 01`,
      ),
    );
    const when = el("td", dateFmt.format(new Date(a.starts_at)));
    const status = el("td");
    status.append(el("span", a.status, "status " + a.status));
    tr.append(service, when, status, el("td", a.id.slice(0, 8), "reference"));
    body.append(tr);
  }
  $("#appointment-empty").hidden = !!rows.length;
  $("#appointment-count").textContent =
    `${rows.length} appointment${rows.length === 1 ? "" : "s"} shown · latest 200 records`;
}
function listEmpty(parent, message) {
  parent.append(el("p", message, "list-empty"));
}
function renderSessions() {
  const box = $("#session-list");
  box.replaceChildren();
  if (!state.dashboard.sessions.length)
    listEmpty(box, "No conversations yet. Start one with the assistant.");
  for (const s of state.dashboard.sessions) {
    const row = el("div", undefined, "list-row");
    const info = el("div", s.id.slice(0, 8));
    info.append(
      el("small", `${s.status} · ${dateFmt.format(new Date(s.updated_at))} ET`),
    );
    const b = el("button", "Inspect →");
    b.onclick = async () => {
      try {
        const data = await api(`/api/operator/sessions/${s.id}`, {
          headers: operatorHeaders(),
        });
        const t = $("#transcript");
        t.replaceChildren(el("h3", `Session ${s.id.slice(0, 8)}`));
        for (const m of data.messages)
          t.append(el("p", `${m.role.toUpperCase()} · ${m.content}`));
        t.hidden = false;
      } catch (e) {
        notice(e.message);
      }
    };
    row.append(info, b);
    box.append(row);
  }
}
function renderHandoffs() {
  const box = $("#handoff-list");
  box.replaceChildren();
  if (!state.dashboard.handoffs.length)
    listEmpty(
      box,
      "All clear. Requests to speak to a person will appear here.",
    );
  for (const h of state.dashboard.handoffs) {
    const row = el("div", undefined, "list-row");
    const info = el("div", `Session ${h.session_id.slice(0, 8)}`);
    info.append(
      el("small", `${h.status} · ${dateFmt.format(new Date(h.created_at))} ET`),
    );
    row.append(info);
    if (h.status === "open") {
      const b = el("button", "Mark resolved");
      b.onclick = async () => {
        b.disabled = true;
        try {
          await api(`/api/operator/handoffs/${h.id}/resolve`, {
            method: "POST",
            headers: operatorHeaders(),
            body: "{}",
          });
          await refresh();
        } catch (e) {
          notice(e.message);
          b.disabled = false;
        }
      };
      row.append(b);
    }
    box.append(row);
  }
}
function renderEvents() {
  const box = $("#event-list");
  box.replaceChildren();
  if (!state.dashboard.events.length)
    listEmpty(box, "Activity will appear as you use the assistant.");
  for (const e of state.dashboard.events) {
    const row = el("div", undefined, "list-row");
    const info = el("div", e.kind);
    const detail = JSON.parse(e.detail);
    info.append(
      el(
        "small",
        `Session ${e.session_id.slice(0, 8)}${detail.latency_ms !== undefined ? " · " + detail.latency_ms + " ms" : ""}${detail.code ? " · " + detail.code : ""}`,
      ),
    );
    row.append(info, el("small", dateFmt.format(new Date(e.created_at))));
    box.append(row);
  }
}
function view(name) {
  state.view = name;
  document
    .querySelectorAll(".nav")
    .forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $("#breadcrumb").textContent = name.charAt(0).toUpperCase() + name.slice(1);
  $("#page-title").textContent = titles[name][0];
  $("#page-subtitle").textContent = titles[name][1];
  $("#overview-panel").hidden = !["overview", "appointments"].includes(name);
  $("#overview-extras").hidden = name !== "overview";
  for (const p of ["sessions", "handoffs", "activity"])
    $(`#${p}-panel`).hidden = p !== name;
}
function speak(text) {
  if (!$("#speak").checked || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1;
  window.speechSynthesis.speak(utterance);
}
$("#chat-form").onsubmit = (e) => {
  e.preventDefault();
  const text = $("#message").value;
  send(text, state.retry?.text === text.trim() ? state.retry.id : undefined);
};
document
  .querySelectorAll("[data-message]")
  .forEach((b) => (b.onclick = () => send(b.dataset.message)));
document
  .querySelectorAll("[data-view]")
  .forEach((b) => (b.onclick = () => view(b.dataset.view)));
document.querySelectorAll("[data-filter]").forEach(
  (b) =>
    (b.onclick = () => {
      state.filter = b.dataset.filter;
      document
        .querySelectorAll("[data-filter]")
        .forEach((x) => x.classList.toggle("active", x === b));
      if (state.dashboard) renderAppointments();
    }),
);
$("#search").oninput = () => {
  if (state.dashboard) renderAppointments();
};
$("#new-session").onclick = $("#reset-chat").onclick = () => {
  if (
    !state.snapshot ||
    state.snapshot.messages.length < 2 ||
    confirm(
      "Start a new session? Existing bookings stay saved, but this tab will switch to a new session.",
    )
  )
    newSession();
};
$("#demo-book").onclick = () => send("book an inspection");
$("#view-activity").onclick = () => view("activity");
$("#operator-auth").onclick = () => $("#auth-dialog").showModal();
$("#save-token").onclick = () => {
  state.operatorToken = $("#auth-token").value;
  $("#auth-token").value = "";
  refresh();
};
$("#speak").onchange = () => {
  if (!$("#speak").checked) window.speechSynthesis?.cancel();
};
const SpeechRecognition =
  window.SpeechRecognition || window.webkitSpeechRecognition;
if (SpeechRecognition) {
  const recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.continuous = false;
  let listening = false;
  $("#mic").onclick = () => {
    if (listening) {
      recognition.stop();
      return;
    }
    if (
      !confirm(
        "Your browser may send microphone audio to its speech provider. Start dictation?",
      )
    )
      return;
    window.speechSynthesis?.cancel();
    try {
      recognition.start();
    } catch {
      notice("Microphone could not start. Try typing instead.");
    }
  };
  recognition.onstart = () => {
    listening = true;
    $("#voice-status").textContent = "Listening…";
    $("#mic").setAttribute("aria-label", "Stop dictation");
  };
  recognition.onend = () => {
    listening = false;
    $("#voice-status").textContent = "Microphone off";
    $("#mic").setAttribute("aria-label", "Dictate a message");
  };
  recognition.onresult = (e) => {
    $("#message").value = e.results[0][0].transcript;
    $("#message").focus();
    $("#voice-status").textContent = "Review, then send";
  };
  recognition.onerror = (e) => {
    notice(`Speech recognition: ${e.error}. You can still type your message.`);
  };
} else {
  $("#mic").disabled = true;
  $("#mic").title = "Speech recognition unavailable in this browser";
  $("#voice-status").textContent = "Text mode · speech unavailable";
}
async function boot() {
  try {
    const config = await api("/api/config");
    $(".engine-label").textContent =
      config.engine === "openai"
        ? "OpenAI language · Browser speech"
        : "Guided demo · Text + browser speech";
    if (config.engine === "openai")
      $(".assistant-note").textContent =
        "Requests may be sent to OpenAI for interpretation. Booking changes still require explicit confirmation. Use demo data only.";
  } catch (e) {
    notice(e.message);
  }
  try {
    const saved = sessionStorage.getItem("relay-session");
    if (saved) state.session = JSON.parse(saved);
  } catch {}
  if (state.session) {
    try {
      state.snapshot = await api(`/api/sessions/${state.session.id}`, {
        headers: sessionHeaders(),
      });
      renderChat();
    } catch (e) {
      notice(
        "Could not restore the saved session. Retry or start a new conversation.",
      );
      await refresh();
      return;
    }
  } else await newSession();
  await refresh();
}
boot();
setInterval(() => {
  if (!document.hidden && !state.busy) refresh();
}, 15000);
