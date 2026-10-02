import { html, nothing, type TemplateResult } from "lit-html";
import { keyed } from "lit-html/directives/keyed.js";
import type { Member, MemberStatus } from "../api.ts";
import type { Feedback, FormState } from "../view.ts";

export interface PersonForm {
  mode: "invite" | "add"; // per Mail einladen (nur Admin) / ohne Login hinzufügen (z.B. Kinder)
  key: number; // neuer Schlüssel = frisches, leeres Formular
}

export interface FamilyState extends FormState {
  members: Member[];
  adminMode: boolean; // Admin-Funktionen eingeblendet (Schalter im Kopf)
  form: PersonForm | null;
}

export interface FamilyHandlers {
  ask(member: Member): void;
  openForm(mode: PersonForm["mode"]): void;
  submit(e: SubmitEvent): void;
  remove(name: string): void;
}

const BADGE: Record<MemberStatus, [cls: string, label: string]> = {
  registriert: ["yes", "registriert"],
  eingeladen: ["wait", "eingeladen"],
  offen: ["no", "noch nicht dabei"],
};

const message = (feedback: Feedback) =>
  html`<p class="invite-msg ${feedback?.kind ?? ""}" role="status">${feedback?.text ?? ""}</p>`;

function member(m: Member, s: FamilyState, h: FamilyHandlers): TemplateResult {
  const [cls, label] = BADGE[m.status];
  return html`<li>
    <button @click=${() => h.ask(m)}>
      <span>${m.du ? `${m.name} (du)` : m.name}${m.beziehung ? html` <span class="relation">· ${m.beziehung}</span>` : nothing
        }</span><span class="badge ${cls}">${label}</span>
    </button>
    ${s.adminMode && !m.du ? html`
      <button type="button" class="family-action family-delete" @click=${() => h.remove(m.name)}
        title="${m.name} aus der Familienliste entfernen">Entfernen</button>` : nothing}
  </li>`;
}

const personForm = (form: PersonForm, s: FamilyState, h: FamilyHandlers) => keyed(form.key, html`
  <form class="invite-form" @submit=${h.submit}>
    <label>Name <input name="name" placeholder="z.B. Gisela" required></label>
    <p class="family-note">Am besten den Vornamen – so, wie ihn alle in der Familie kennen.</p>
    ${form.mode === "invite"
      ? html`<label>E-Mail-Adresse <input name="email" type="email" autocomplete="off" required></label>
        <p class="family-note">Steht die Person schon in der Liste (z.B. ohne E-Mail), genau diesen Namen nehmen –
          sie übernimmt dann ihre Wunschliste.</p>`
      : html`<p class="family-note">Für Kinder oder alle ohne E-Mail-Adresse: Wünsche tragen dann andere im Chat
          ein.</p>`}
    ${message(s.feedback)}
    <button type="submit" ?disabled=${s.busy}>
      ${form.mode === "invite" ? "Einladung per E-Mail senden" : "Zur Familienliste hinzufügen"}</button>
  </form>`);

export const familyTemplate = (s: FamilyState, h: FamilyHandlers): TemplateResult => html`
  <ul id="family-list">${s.members.map((m) => member(m, s, h))}</ul>
  ${s.form ? nothing : message(s.feedback)}
  <p class="family-note">Tippe auf einen Namen, um nach den Wünschen zu fragen.</p>
  ${s.form ? personForm(s.form, s, h) : html`
    <button type="button" class="invite-open" @click=${() => h.openForm("add")}>＋ Jemanden hinzufügen</button>
    ${s.adminMode ? html`<button type="button" class="invite-open admin-only" @click=${() => h.openForm("invite")}
      >＋ Jemanden einladen (E-Mail)</button>` : nothing}`}`;
