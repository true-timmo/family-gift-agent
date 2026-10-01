import { html, nothing, type TemplateResult } from "lit-html";
import { keyed } from "lit-html/directives/keyed.js";
import type { Member, MemberStatus } from "../api.ts";
import type { Feedback, FormState } from "../view.ts";

export interface InviteForm {
  name: string; // vorhandene Person aus der Liste (Name fest) – leer = neue Person
  key: number; // neuer Schlüssel = frisches, leeres Formular
}

export interface FamilyState extends FormState {
  members: Member[];
  isAdmin: boolean;
  invite: InviteForm | null;
}

export interface FamilyHandlers {
  ask(member: Member): void;
  openInvite(name?: string): void;
  invite(e: SubmitEvent): void;
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
  const invited = m.status === "eingeladen";
  return html`<li>
    <button @click=${() => h.ask(m)}>
      <span>${m.du ? `${m.name} (du)` : m.name}${m.beziehung ? html` <span class="relation">· ${m.beziehung}</span>` : nothing
        }</span><span class="badge ${cls}">${label}</span>
    </button>
    ${m.status === "registriert" ? nothing : html`
      <button type="button" class="family-action" @click=${() => h.openInvite(m.name)}
        title=${invited ? "Einladung nochmal senden (auch an eine andere Adresse)" : "Per E-Mail einladen"}
        >${invited ? "Erneut" : "Einladen"}</button>`}
    ${s.isAdmin && !m.du ? html`
      <button type="button" class="family-action family-delete" @click=${() => h.remove(m.name)}
        title="${m.name} aus der Familienliste entfernen">Entfernen</button>` : nothing}
  </li>`;
}

const inviteForm = (form: InviteForm, s: FamilyState, h: FamilyHandlers) => keyed(form.key, html`
  <form class="invite-form" @submit=${h.invite}>
    <label>Name <input name="name" placeholder="z.B. Gisela" required value=${form.name} ?readonly=${!!form.name}></label>
    <p class="family-note">Am besten den Vornamen – so, wie ihn alle in der Familie kennen.</p>
    <label>E-Mail-Adresse <input name="email" type="email" autocomplete="off" required></label>
    ${message(s.feedback)}
    <button type="submit" ?disabled=${s.busy}>Einladung per E-Mail senden</button>
  </form>`);

export const familyTemplate = (s: FamilyState, h: FamilyHandlers): TemplateResult => html`
  <ul id="family-list">${s.members.map((m) => member(m, s, h))}</ul>
  ${s.invite ? nothing : message(s.feedback)}
  <p class="family-note">Tippe auf einen Namen, um nach den Wünschen zu fragen.</p>
  ${s.invite ? inviteForm(s.invite, s, h)
    : html`<button type="button" class="invite-open" @click=${() => h.openInvite()}>＋ Jemanden einladen</button>`}`;
