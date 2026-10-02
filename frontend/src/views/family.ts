// Familie: wer ist dabei? Jemanden hinzufügen; als Admin per Mail einladen und Personen entfernen.
import type { Api, Member } from "../api.ts";
import { focus, formValues } from "../dom.ts";
import { FormView } from "../view.ts";
import { type FamilyHandlers, type FamilyState, familyTemplate, type PersonForm } from "./family.templates.ts";

export class FamilyPanel extends FormView<FamilyState> {
  private readonly api: Api;
  private readonly toggle: HTMLButtonElement;
  private readonly onAsk: (question: string) => void;
  private formKey = 0;

  /** onAsk: Frage für den Chat, wenn jemand auf einen Namen tippt. */
  constructor(root: HTMLElement, toggle: HTMLButtonElement, api: Api, onAsk: (question: string) => void) {
    super(root, { members: [], adminMode: false, form: null, busy: false, feedback: null });
    this.api = api;
    this.toggle = toggle;
    this.onAsk = onAsk;
    toggle.addEventListener("click", () => (this.root.hidden ? this.open() : this.close()));
  }

  /** Admin-Funktionen ein-/ausblenden (Schalter im Kopf). */
  setAdminMode(adminMode: boolean): void {
    const form = adminMode || this.state.form?.mode !== "invite" ? this.state.form : null;
    this.update({ adminMode, form });
  }

  async open(): Promise<void> {
    this.update({ form: null, feedback: null });
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

  private openForm(mode: PersonForm["mode"]): void {
    this.update({ form: { mode, key: ++this.formKey }, feedback: null });
    focus(this.root, ".invite-form input[name=name]");
  }

  /** Nach Erfolg: Liste neu laden, leeres Formular derselben Art für die nächste Person. */
  private async done(mode: PersonForm["mode"], text: string): Promise<void> {
    this.update({ form: { mode, key: ++this.formKey } });
    await this.reload();
    this.say("ok", text);
  }

  private readonly handlers: FamilyHandlers = {
    ask: (m: Member) => {
      this.close();
      this.onAsk(m.du ? "Zeig mir meine Wunschliste als Tabelle" : `Zeig mir die Wünsche von ${m.name} als Tabelle`);
    },
    openForm: (mode) => this.openForm(mode),
    submit: async (e) => {
      const { name, email } = formValues(e);
      const form = this.state.form;
      if (form?.mode === "invite") {
        const res = await this.run(() => this.api.invite(name, email));
        if (res) await this.done("invite", `Einladung an ${res.name} (${res.email}) ist unterwegs.`);
      } else {
        const res = await this.run(() => this.api.addPerson(name));
        if (res) await this.done("add", `${res.name} steht jetzt in der Familienliste. Wünsche für ${res.name} ` +
          `kannst du im Chat eintragen.`);
      }
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
