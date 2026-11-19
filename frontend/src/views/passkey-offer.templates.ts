import { html, nothing, type TemplateResult } from "lit-html";
import type { Feedback } from "../view.ts";

export interface PasskeyOfferState {
  phase: "hidden" | "offer" | "done";
  biometric: string;
  busy: boolean;
  feedback: Feedback;
}

export interface PasskeyOfferHandlers {
  setUp(): void;
  later(): void;
  close(): void;
}

export const passkeyOfferTemplate = (s: PasskeyOfferState, h: PasskeyOfferHandlers): TemplateResult => {
  if (s.phase === "done") return html`
    <p class="passkey-offer-text">✅ <strong>Fertig!</strong> Beim nächsten Mal tippst du auf der Anmeldeseite einfach
      auf <strong>„Mit ${s.biometric} anmelden“</strong> – ganz ohne E-Mail.</p>
    <div class="passkey-offer-actions"><button type="button" class="passkey-btn small" @click=${h.close}>OK</button></div>`;
  return html`
    <p class="passkey-offer-text">🔐 <strong>Schneller anmelden?</strong> Beim nächsten Mal ohne Code aus der E-Mail –
      einfach mit <strong>${s.biometric}</strong>.</p>
    <div class="passkey-offer-actions">
      <button type="button" class="passkey-btn small" ?disabled=${s.busy} @click=${h.setUp}>${s.biometric} einrichten</button>
      <button type="button" class="link" ?disabled=${s.busy} @click=${h.later}>Nein, danke</button>
    </div>
    ${s.feedback ? html`<p class="error" role="alert">${s.feedback.text}</p>` : nothing}`;
};
