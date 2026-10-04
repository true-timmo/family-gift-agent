import { html, nothing, type TemplateResult } from "lit-html";
import type { TableLayout } from "../markdown.ts";
import { markdown } from "../markdown-view.ts";

export interface Message {
  role: "user" | "assistant" | "error";
  text: string;
  typing?: boolean;
  meta?: string; // benutzte Tools und Modell, klein unter der Antwort
  tables?: TableLayout; // Übersichten als Karten oder – auf Nachfrage – als Tabelle
}

const EXAMPLES = ["Ich wünsche mir …", "Wer ist in der Familie dabei?", "Was besorge ich gerade?"];

const hint = (onExample: (text: string) => void) => html`
  <div class="hint">
    <p>Zum Beispiel:</p>
    ${EXAMPLES.map((text) => html`<button class="chip" @click=${() => onExample(text)}>${text}</button>`)}
  </div>`;

const message = (m: Message) => html`
  <div class="msg ${m.role} ${m.typing ? "typing" : ""}">
    ${markdown(m.text, m.tables)}${m.meta ? html`<div class="meta">${m.meta}</div>` : nothing}
  </div>`;

export const messagesTemplate = (messages: Message[], onExample: (text: string) => void): TemplateResult =>
  messages.length ? html`${messages.map(message)}` : hint(onExample);
