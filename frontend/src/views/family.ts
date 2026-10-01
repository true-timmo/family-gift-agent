// Familie: wer ist dabei? Einladen per Mail, als Admin Personen entfernen.
import type { Api, Member } from "../api.ts";
import { focus, formValues } from "../dom.ts";
import { FormView } from "../view.ts";
import { type FamilyHandlers, type FamilyState, familyTemplate } from "./family.templates.ts";

export class FamilyPanel extends FormView<FamilyState> {
  private readonly api: Api;
  private readonly toggle: HTMLButtonElement;
  private readonly onAsk: (question: string) => void;
  private formKey = 0;

  /** onAsk: Frage für den Chat, wenn jemand auf einen Namen tippt. */
  constructor(root: HTMLElement, toggle: HTMLButtonElement, api: Api, onAsk: (question: string) => void) {
    super(root, { members: [], isAdmin: false, invite: null, busy: false, feedback: null });
    this.api = api;
    this.toggle = toggle;
    this.onAsk = onAsk;
    toggle.addEventListener("click", () => (this.root.hidden ? this.open() : this.close()));
  }

  setAdmin(isAdmin: boolean): void {
    this.state = { ...this.state, isAdmin };
  }

  async open(): Promise<void> {
    this.update({ invite: null, feedback: null });
    await this.reload();
    this.setOpen(true);
  }

  close(): void {
    this.setOpen(false);
  }

  protected template() {
    return familyTemplate(this.state, this.handlers);
  }

  private setOpen(open: boolean): void {
    this.root.hidden = !open;
    this.toggle.setAttribute("aria-expanded", String(open));
  }

  private async reload(): Promise<void> {
    const members = await this.run(() => this.api.family());
    if (members) this.update({ members });
  }

  private openInvite(name = ""): void {
    this.update({ invite: { name, key: ++this.formKey }, feedback: null });
    focus(this.root, name ? ".invite-form input[name=email]" : ".invite-form input[name=name]");
  }

  private readonly handlers: FamilyHandlers = {
    ask: (m: Member) => {
      this.close();
      this.onAsk(m.du ? "Zeig mir meine Wunschliste als Tabelle" : `Zeig mir die Wünsche von ${m.name} als Tabelle`);
    },
    openInvite: (name?: string) => this.openInvite(name),
    invite: async (e) => {
      const { name, email } = formValues(e);
      const existing = !!this.state.invite?.name;
      const res = await this.run(() => this.api.invite(name, email, existing));
      if (!res) return;
      this.update({ invite: { name: "", key: ++this.formKey } }); // leeres Formular für die nächste Einladung
      await this.reload();
      this.say("ok", `Einladung an ${res.name} (${res.email}) ist unterwegs.`);
    },
    remove: async (name: string) => {
      const ok = confirm(`${name} wirklich aus der Familienliste entfernen?\n\n` +
        `• Alle Wünsche von ${name} werden gelöscht (wer davon etwas reserviert hat, bekommt eine Mail).\n` +
        `• Geschenke, die ${name} besorgen wollte, sind wieder für alle offen.\n` +
        `• ${name} kann sich nicht mehr anmelden.\n\nDas lässt sich nicht rückgängig machen.`);
      if (!ok) return;
      const res = await this.run(() => this.api.removePerson(name));
      if (!res) return;
      await this.reload();
      this.say("ok", `${res.name} wurde entfernt (${res.wuensche_geloescht} Wünsche gelöscht, ` +
        `${res.reservierungen_freigegeben} Reservierungen freigegeben).`);
    },
  };
}
