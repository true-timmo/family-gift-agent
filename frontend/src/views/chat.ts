// Chat: Verlauf anzeigen, Nachricht senden, Antwort live mitlesen.
import type { Api, ChatMessage } from "../api.ts";
import { ApiError } from "../api.ts";
import { View } from "../view.ts";
import { type Message, messagesTemplate } from "./chat.templates.ts";

const TOOL_LABELS: Record<string, string> = {
  wunsch_hinzufuegen: "Wunsch gespeichert", wuensche_anzeigen: "Liste angesehen",
  reservieren: "Reserviert", reservierung_aufheben: "Reservierung aufgehoben",
  meine_reservierungen: "Reservierungen angesehen", wunsch_bearbeiten: "Wunsch geändert",
  wunsch_entfernen: "Wunsch entfernt", personen_auflisten: "Familie angesehen",
};

interface ChatState {
  messages: Message[];
}

export interface ChatElements {
  messages: HTMLElement;
  form: HTMLFormElement;
  input: HTMLTextAreaElement;
  send: HTMLButtonElement;
}

export class ChatView extends View<ChatState> {
  private readonly api: Api;
  private readonly el: ChatElements;

  constructor(el: ChatElements, api: Api) {
    super(el.messages, { messages: [] });
    this.el = el;
    this.api = api;
    el.form.addEventListener("submit", (e) => { e.preventDefault(); this.send(); });
    el.input.addEventListener("input", () => this.fitInput());
    el.input.addEventListener("keydown", (e) => {
      // Enter sendet am Computer; auf dem Handy (Touch) gibt Enter eine neue Zeile
      if (e.key === "Enter" && !e.shiftKey && !matchMedia("(pointer: coarse)").matches) {
        e.preventDefault();
        el.form.requestSubmit();
      }
    });
  }

  load(history: ChatMessage[]): void {
    this.update({ messages: history.map((m) => ({ role: m.role, text: m.content })) });
    this.el.input.focus();
  }

  async clear(): Promise<void> {
    if (!confirm("Chatverlauf leeren? Wünsche und Reservierungen bleiben erhalten.")) return;
    await this.api.clearChat();
    this.update({ messages: [] });
  }

  /** Text ins Eingabefeld legen (z.B. aus der Familienliste oder den Beispielen). */
  setDraft(text: string): void {
    this.el.input.value = text;
    this.fitInput();
    this.el.input.focus();
  }

  protected template() {
    return messagesTemplate(this.state.messages, (example) => this.setDraft(example.replace(" …", " ")));
  }

  protected override update(patch: Partial<ChatState>): void {
    super.update(patch);
    this.root.scrollTop = this.root.scrollHeight;
  }

  private async send(): Promise<void> {
    const text = this.el.input.value.trim();
    if (!text) return;
    this.setDraft("");
    this.el.send.disabled = true;

    const reply: Message = { role: "assistant", text: "", typing: true };
    const tools = new Set<string>();
    let model = "";
    const show = () => this.update({ messages: [...this.state.messages.slice(0, -1), { ...reply }] });
    this.update({ messages: [...this.state.messages, { role: "user", text }, reply] });

    try {
      for await (const ev of this.api.chat(text)) {
        if (ev.type === "text") reply.text += ev.text;
        else if (ev.type === "tool") tools.add(TOOL_LABELS[ev.name] ?? ev.name);
        else if (ev.type === "model") model = ev.model.split("/").pop() ?? "";
        else if (ev.type === "error") Object.assign(reply, { role: "error", text: ev.text });
        show();
      }
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) {
        Object.assign(reply, { role: "error", text: "Verbindung unterbrochen. Bitte nochmal versuchen." });
      }
    }
    Object.assign(reply, {
      typing: false,
      text: reply.text.trim() || "(keine Antwort)",
      meta: [...tools, model].filter(Boolean).join(" · "),
    });
    show();
    this.el.send.disabled = false;
    this.el.input.focus();
  }

  private fitInput(): void {
    const input = this.el.input;
    input.style.height = "auto";
    if (input.value) input.style.height = `${input.scrollHeight}px`;
  }
}
