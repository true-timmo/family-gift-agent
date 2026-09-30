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

// Status-Spalte als farbiges Etikett: offen / von dir reserviert / besorgt <Name>
function statusBadge(label, cell) {
  if (!/^status$/i.test(label.replace(/<[^>]*>/g, "").trim()) || !cell) return cell;
  const t = cell.replace(/<[^>]*>/g, "").toLowerCase();
  const kind = t.startsWith("offen") ? "open" : t.includes("von dir") ? "mine" : t.startsWith("besorgt") ? "taken" : "";
  return kind ? `<span class="status status-${kind}">${cell}</span>` : cell;
}

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
      const heads = cells(line);
      const body = [];
      for (i += 2; i < lines.length && TABLE_ROW.test(lines[i]); i++) {
        const tds = cells(lines[i]).map((c, k) => {
          const label = heads[k] || "";
          const empty = c === "" || c === "–" || c === "-";
          const cls = [k === 0 ? "cell-title" : "", empty ? "cell-empty" : ""].filter(Boolean).join(" ");
          // data-label: Spaltenname für die Karten-Ansicht auf dem Handy
          return `<td data-label="${label.replace(/<[^>]*>/g, "")}"${cls ? ` class="${cls}"` : ""}>${statusBadge(label, c)}</td>`;
        });
        body.push("<tr>" + tds.join("") + "</tr>");
      }
      i--;
      const head = heads.map((h) => `<th>${h}</th>`).join("");
      out.push(`<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body.join("")}</tbody></table></div>`);
      continue;
    }
    const m = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/);
    if (m) { if (!inList) { out.push("<ul>"); inList = true; } out.push(`<li>${m[1]}</li>`); continue; }
    if (inList) { out.push("</ul>"); inList = false; }
    out.push(line + "<br>");
  }
  if (inList) out.push("</ul>");
  return out.join("").replace(/(<br>)+$/, "")
    .replace(/<br>(<div class="table-wrap">)/g, "$1")     // keine Leerzeile vor …
    .replace(/(<\/table><\/div>)<br>/g, "$1");            // … und nach Tabellen
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

let isAdmin = false;

async function showChat() {
  const res = await api("/api/me");
  const me = await res.json();
  isAdmin = !!me.admin;
  $("#who").textContent = me.name + (isAdmin ? " · Admin" : "");
  messages.querySelectorAll(".msg").forEach((m) => m.remove());
  me.verlauf.forEach((m) => addMessage(m.role, m.content));
  $("#login-view").hidden = true; $("#chat-view").hidden = false;
  input.focus();
}

// --- Login: Name → (Registrierung) → Code ---
let loginName = "";
function step(id) {
  document.querySelectorAll(".step").forEach((f) => (f.hidden = f.id !== id));
  $("#login-back").hidden = id === "step-name" || id === "step-invite";
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
  else if (data.step === "invited") {
    loginName = data.name;
    $("#step-invited .name").textContent = data.name; $("#step-invited .email").textContent = data.email;
    step("step-invited");
  }
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
$("#step-invited").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = await loginCall("/api/login/invite/resend", { name: loginName });
  if (data) $("#login-error").textContent = `Die Einladung ist unterwegs an ${data.email}. Schau in dein Postfach.`;
});

// --- Einladungslink (?einladung=…): erst anzeigen, per Knopfdruck annehmen ---
let inviteToken = new URLSearchParams(location.search).get("einladung");
async function showInvite() {
  $("#chat-view").hidden = true; $("#login-view").hidden = false;
  const data = await loginCall("/api/login/invite", { token: inviteToken });
  history.replaceState(null, "", "/");            // Link nicht in Verlauf/Lesezeichen behalten
  if (!data) { inviteToken = null; step("step-name"); return; }
  $("#step-invite .name").textContent = data.name;
  $("#step-invite .inviter").textContent = data.eingeladen_von;
  step("step-invite");
}
$("#step-invite").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = await loginCall("/api/login/invite/accept", { token: inviteToken });
  if (data) { inviteToken = null; step("step-name"); showChat(); }
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

// --- Familie: wer ist dabei? Einladen per Mail ---
const STATUS = { registriert: ["yes", "registriert"], eingeladen: ["wait", "eingeladen"], offen: ["no", "noch nicht dabei"] };

function closeFamily() { $("#family").hidden = true; $("#family-btn").setAttribute("aria-expanded", "false"); }

// Mit Name = vorhandene Person aus der Liste (Name fest), ohne = neue Person
function openInviteForm(name = "") {
  const f = $("#invite-form");
  f.hidden = false; $("#invite-open").hidden = true;
  f.name.value = name; f.name.readOnly = !!name; f.dataset.bestehend = name ? "1" : "";
  f.email.value = ""; $("#invite-msg").textContent = "";
  (name ? f.email : f.name).focus();
}

async function loadFamily() {
  const res = await api("/api/familie");
  const list = $("#family-list"); list.replaceChildren();
  for (const p of await res.json()) {
    const li = document.createElement("li"), b = document.createElement("button");
    const name = document.createElement("span"), badge = document.createElement("span");
    const [cls, label] = STATUS[p.status];
    name.textContent = p.du ? `${p.name} (du)` : p.name;
    badge.className = `badge ${cls}`; badge.textContent = label;
    b.append(name, badge);
    b.addEventListener("click", () => {
      closeFamily();
      input.value = p.du ? "Zeig mir meine Wunschliste als Tabelle" : `Zeig mir die Wünsche von ${p.name} als Tabelle`;
      input.focus();
    });
    li.append(b);
    if (p.status !== "registriert") {   // offen: einladen / eingeladen: nochmal (z.B. andere Adresse)
      const act = document.createElement("button");
      act.className = "family-action"; act.type = "button";
      act.textContent = p.status === "eingeladen" ? "Erneut" : "Einladen";
      act.title = p.status === "eingeladen" ? "Einladung nochmal senden (auch an eine andere Adresse)" : "Per E-Mail einladen";
      act.addEventListener("click", () => openInviteForm(p.name));
      li.append(act);
    }
    if (isAdmin && !p.du) {   // nur Admin: Person endgültig entfernen
      const del = document.createElement("button");
      del.className = "family-action family-delete"; del.type = "button";
      del.textContent = "Entfernen"; del.title = `${p.name} aus der Familienliste entfernen`;
      del.addEventListener("click", () => removePerson(p.name));
      li.append(del);
    }
    list.append(li);
  }
}

async function removePerson(name) {
  const ok = confirm(`${name} wirklich aus der Familienliste entfernen?\n\n` +
    `• Alle Wünsche von ${name} werden gelöscht (wer davon etwas reserviert hat, bekommt eine Mail).\n` +
    `• Geschenke, die ${name} besorgen wollte, sind wieder für alle offen.\n` +
    `• ${name} kann sich nicht mehr anmelden.\n\nDas lässt sich nicht rückgängig machen.`);
  if (!ok) return;
  const res = await api("/api/admin/person-entfernen", { name });
  const data = await res.json();
  const msg = $("#family-msg");
  if (!res.ok) { msg.className = "invite-msg err"; msg.textContent = data.detail || "Das hat nicht geklappt."; return; }
  msg.className = "invite-msg ok";
  msg.textContent = `${data.name} wurde entfernt (${data.wuensche_geloescht} Wünsche gelöscht, ` +
                    `${data.reservierungen_freigegeben} Reservierungen freigegeben).`;
  await loadFamily();
}

$("#family-btn").addEventListener("click", async () => {
  const panel = $("#family");
  if (!panel.hidden) return closeFamily();
  $("#invite-form").hidden = true; $("#invite-open").hidden = false; $("#family-msg").textContent = "";
  await loadFamily();
  panel.hidden = false; $("#family-btn").setAttribute("aria-expanded", "true");
});
$("#invite-open").addEventListener("click", () => openInviteForm());
$("#invite-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#invite-msg"), btn = f.querySelector("button");
  btn.disabled = true; msg.className = "invite-msg"; msg.textContent = "Wird gesendet …";
  try {
    const res = await api("/api/einladung", { name: f.name.value.trim(), email: f.email.value.trim(),
                                              bestehend: !!f.dataset.bestehend });
    const data = await res.json();
    if (!res.ok) { msg.className = "invite-msg err"; msg.textContent = data.detail || "Das hat nicht geklappt."; return; }
    msg.className = "invite-msg ok";
    msg.textContent = `Einladung an ${data.name} (${data.email}) ist unterwegs.`;
    f.name.value = ""; f.email.value = ""; f.name.readOnly = false; f.dataset.bestehend = "";
    await loadFamily();
  } catch { msg.className = "invite-msg err"; msg.textContent = "Keine Verbindung zum Server."; }
  finally { btn.disabled = false; }
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

if (inviteToken) showInvite(); else showChat().catch(() => showLogin());
