import { html, nothing, type TemplateResult } from "lit-html";
import type { Feedback } from "../view.ts";

export type Step =
  | { name: "name" }
  | { name: "invite"; person: string; inviter: string } // Link aus der Einladung geöffnet
  | { name: "invited"; person: string; email: string } // Einladung liegt im Postfach
  | { name: "register"; person: string } // erstes Mal, ohne Einladung
  | { name: "code"; email: string };

export interface LoginState {
  step: Step;
  loginName: string;
  busy: boolean;
  feedback: Feedback;
}

export interface LoginHandlers {
  submitName(e: SubmitEvent): void;
  acceptInvite(e: SubmitEvent): void;
  resendInvite(e: SubmitEvent): void;
  register(e: SubmitEvent): void;
  verify(e: SubmitEvent): void;
  resendCode(): void;
  back(): void;
}

const submit = (label: string, busy: boolean) => html`<button type="submit" ?disabled=${busy}>${label}</button>`;

function step(s: LoginState, h: LoginHandlers): TemplateResult {
  switch (s.step.name) {
    case "name": return html`
      <form class="step" @submit=${h.submitName}>
        <label>Dein Name
          <input name="name" autocomplete="username" placeholder="z.B. Mama" required value=${s.loginName}></label>
        ${submit("Weiter", s.busy)}
      </form>`;

    case "invite": return html`
      <form class="step" @submit=${h.acceptInvite}>
        <p class="info big">Hallo <strong>${s.step.person}</strong>! 👋</p>
        <p class="info"><strong>${s.step.inviter}</strong> hat dich zur Geschenke-Liste der Familie eingeladen.</p>
        ${submit("Los geht's", s.busy)}
      </form>`;

    case "invited": return html`
      <form class="step" @submit=${h.resendInvite}>
        <p class="info">Hallo <strong>${s.step.person}</strong>! Für dich liegt eine <strong>Einladung</strong>
          in deinem E-Mail-Postfach (${s.step.email}).</p>
        <p class="info">Öffne die E-Mail und tippe darin auf <strong>„Einladung annehmen“</strong>.</p>
        ${submit("Einladung nochmal schicken", s.busy)}
      </form>`;

    case "register": return html`
      <form class="step" @submit=${h.register}>
        <p class="info">Hallo <strong>${s.step.person}</strong>, du bist zum ersten Mal hier.
          Am einfachsten: Bitte jemanden aus der Familie, dich einzuladen.
          Wenn du den Familien-Code kennst, geht es auch hier:</p>
        <label>Mail-Adresse <input name="email" type="email" autocomplete="email" required></label>
        <label>Familien-Code <input name="family_code" autocomplete="off" required></label>
        ${submit("Code schicken", s.busy)}
      </form>`;

    case "code": return html`
      <form class="step" @submit=${h.verify}>
        <p class="info">Wir haben einen Code an <strong>${s.step.email}</strong> geschickt.</p>
        <label>Code aus der Mail
          <input name="code" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9 ]{6,7}" maxlength="7"
            required></label>
        ${submit("Anmelden", s.busy)}
        <button type="button" class="link" ?disabled=${s.busy} @click=${h.resendCode}>Neuen Code schicken</button>
      </form>`;
  }
}

export const loginTemplate = (s: LoginState, h: LoginHandlers): TemplateResult => html`
  ${step(s, h)}
  <p class="error" role="alert">${s.feedback?.text ?? ""}</p>
  ${s.step.name === "name" || s.step.name === "invite" ? nothing
    : html`<button type="button" class="link" @click=${h.back}>← Anderer Name</button>`}`;
