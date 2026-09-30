const $ = (s) => document.querySelector(s);
const messages = $("#messages");
const input = $("#input");

const TOOL_LABELS = {
  wunsch_hinzufuegen: "Wunsch gespeichert", wuensche_anzeigen: "Liste angesehen",
  reservieren: "Reserviert", reservierung_aufheben: "Reservierung aufgehoben",
  meine_reservierungen: "Reservierungen angesehen", wunsch_bearbeiten: "Wunsch geändert",
  wunsch_entfernen: "Wunsch entfernt", personen_auflisten: "Familie angesehen",
};

// Minimales, sicheres Markdown: erst alles escapen, dann Links, Fett, Listen und Tabellen
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*(:?-{2,}:?\s*)?\|?\s*$/;
const cells = (row) => row.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());

function render(text) {
  const esc = text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let html = esc
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)|]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  const lines = html.split("\n");
  const out = []; let inList = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Tabelle: Kopfzeile + Trennzeile (|---|---|) + Datenzeilen
    if (TABLE_ROW.test(line) && TABLE_SEP.test(lines[i + 1] || "")) {
      if (inList) { out.push("</ul>"); inList = false; }
      const head = cells(line).map((c) => `<th>${c}</th>`).join("");
      const body = [];
      for (i += 2; i < lines.length && TABLE_ROW.test(lines[i]); i++) {
        body.push("<tr>" + cells(lines[i]).map((c) => `<td>${c}</td>`).join("") + "</tr>");
      }
      i--;
      out.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body.join("")}</tbody></table></div>`);
      continue;
    }
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (m) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${m[1]}</li>`); continue; }
    if (inList) { out.push("</ul>"); inList = false; }
    out.push(line + "<br>");
  }
  if (inList) out.push("</ul>");
  return out.join("").replace(/(<br>)+$/, "").replace(/<br>(<div class="table-wrap">)/g, "$1");
}

function addMessage(role, text = "") {
  $(".hint")?.remove();
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = render(text);
  messages.append(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && !path.startsWith("/api/login")) { showLogin(); throw new Error("401"); }
  return res;
}

function showLogin() { $("#chat-view").hidden = true; $("#login-view").hidden = false; step("step-name"); }

async function showChat() {
  const res = await api("/api/me");
  const me = await res.json();
  $("#who").textContent = me.name;
  messages.querySelectorAll(".msg").forEach((m) => m.remove());
  me.verlauf.forEach((m) => addMessage(m.role, m.content));
  $("#login-view").hidden = true; $("#chat-view").hidden = false;
  input.focus();
}

// --- Login: Name → (Registrierung) → Code ---
let loginName = "";
function step(id) {
  document.querySelectorAll(".step").forEach((f) => (f.hidden = f.id !== id));
  $("#login-back").hidden = id === "step-name";
  $(`#${id} input`)?.focus();
}
async function loginCall(path, body) {
  $("#login-error").textContent = "";
  document.querySelectorAll(".step button").forEach((b) => (b.disabled = true));
  try {
    const res = await api(path, body);
    const data = await res.json();
    if (!res.ok) { $("#login-error").textContent = data.detail || "Das hat nicht geklappt."; return null; }
    return data;
  } catch { $("#login-error").textContent = "Keine Verbindung zum Server."; return null; }
  finally { document.querySelectorAll(".step button").forEach((b) => (b.disabled = false)); }
}
function handleStep(data) {
  if (!data) return;
  if (data.step === "register") { loginName = data.name; $("#step-register .name").textContent = data.name; step("step-register"); }
  else if (data.step === "code") { $("#step-code .email").textContent = data.email; step("step-code"); }
}
$("#step-name").addEventListener("submit", async (e) => {
  e.preventDefault();
  loginName = new FormData(e.target).get("name").trim();
  handleStep(await loginCall("/api/login/start", { name: loginName }));
});
$("#step-register").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  handleStep(await loginCall("/api/login/register", { name: loginName, email: f.get("email"), family_code: f.get("family_code") }));
});
$("#step-code").addEventListener("submit", async (e) => {
  e.preventDefault();
  const code = new FormData(e.target).get("code").replace(/\s/g, "");
  const data = await loginCall("/api/login/verify", { name: loginName, code });
  if (data) { document.querySelectorAll(".step").forEach((f) => f.reset()); step("step-name"); showChat(); }
});
$("#step-code .resend").addEventListener("click", async () => {
  const reg = $("#step-register");
  // Kam man über die Registrierung, dieselben Angaben nochmal schicken
  if (reg.email.value) handleStep(await loginCall("/api/login/register", { name: loginName, email: reg.email.value, family_code: reg.family_code.value }));
  else handleStep(await loginCall("/api/login/start", { name: loginName }));
  if (!$("#login-error").textContent) $("#login-error").textContent = "Neuer Code ist unterwegs.";
});
$("#login-back").addEventListener("click", () => { $("#login-error").textContent = ""; step("step-name"); });

// --- Hilfe-Fenster ---
document.querySelectorAll("[data-help]").forEach((btn) =>
  btn.addEventListener("click", () => { const d = $("#" + btn.dataset.help); d.showModal(); d.scrollTop = 0; }));
document.querySelectorAll("dialog.help").forEach((d) => {
  d.querySelectorAll(".help-x, .help-close").forEach((b) => b.addEventListener("click", () => d.close()));
  // Nur ein Tipp wirklich NEBEN das Fenster schließt es (nicht auf den Rand/Innenabstand)
  d.addEventListener("click", (e) => {
    if (e.target !== d) return;
    const r = d.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
  });
});

// --- Familie: wer ist registriert? ---
$("#family-btn").addEventListener("click", async () => {
  const panel = $("#family"), btn = $("#family-btn");
  if (!panel.hidden) { panel.hidden = true; btn.setAttribute("aria-expanded", "false"); return; }
  const res = await api("/api/familie");
  const list = $("#family-list"); list.replaceChildren();
  for (const p of await res.json()) {
    const li = document.createElement("li"), b = document.createElement("button");
    const name = document.createElement("span"), badge = document.createElement("span");
    name.textContent = p.du ? `${p.name} (du)` : p.name;
    badge.className = `badge ${p.registriert ? "yes" : "no"}`;
    badge.textContent = p.registriert ? "registriert" : "noch nicht registriert";
    b.append(name, badge);
    b.addEventListener("click", () => {
      panel.hidden = true; btn.setAttribute("aria-expanded", "false");
      input.value = p.du ? "Zeig mir meine Wunschliste als Tabelle" : `Zeig mir die Wünsche von ${p.name} als Tabelle`;
      input.focus();
    });
    li.append(b); list.append(li);
  }
  panel.hidden = false; btn.setAttribute("aria-expanded", "true");
});

$("#logout-btn").addEventListener("click", async () => { await api("/api/logout", {}); showLogin(); });
$("#clear-btn").addEventListener("click", async () => {
  if (!confirm("Chatverlauf leeren? Wünsche und Reservierungen bleiben erhalten.")) return;
  await api("/api/chat/clear", {}); messages.querySelectorAll(".msg").forEach((m) => m.remove());
});

messages.addEventListener("click", (e) => {
  if (e.target.classList.contains("chip")) { input.value = e.target.textContent.replace(" …", " "); input.focus(); }
});

input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = input.scrollHeight + "px"; });
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) { e.preventDefault(); $("#chat-form").requestSubmit(); }
});

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = ""; input.style.height = "auto";
  $("#send").disabled = true;
  addMessage("user", text);
  const el = addMessage("assistant"); el.classList.add("typing");
  let answer = "", model = "", tools = [];

  try {
    const res = await api("/api/chat", { message: text });
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split("\n\n"); buf = parts.pop();
      for (const p of parts) {
        if (!p.startsWith("data: ")) continue;
        const ev = JSON.parse(p.slice(6));
        if (ev.type === "text") answer += ev.text;
        else if (ev.type === "tool") tools.push(TOOL_LABELS[ev.name] || ev.name);
        else if (ev.type === "model") model = ev.model;
        else if (ev.type === "error") { el.className = "msg error"; answer = ev.text; }
        el.innerHTML = render(answer.trim());
        messages.scrollTop = messages.scrollHeight;
      }
    }
  } catch (err) {
    if (err.message !== "401") { el.className = "msg error"; answer = "Verbindung unterbrochen. Bitte nochmal versuchen."; }
  }
  el.classList.remove("typing");
  el.innerHTML = render(answer.trim() || "(keine Antwort)");
  const meta = [...new Set(tools)].join(" · ") + (model ? `${tools.length ? " · " : ""}${model.split("/").pop()}` : "");
  if (meta) el.insertAdjacentHTML("beforeend", `<div class="meta">${render(meta)}</div>`);
  $("#send").disabled = false; input.focus();
});

showChat().catch(() => showLogin());
