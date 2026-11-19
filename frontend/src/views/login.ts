// Anmeldung: Name → Code aus der Mail (oder Knopf in der Mail). Mit Einladungslink: anzeigen und per
// Knopfdruck annehmen. Ein verschickter Code bleibt eingebbar, auch wenn das Fenster zwischendurch zu war.
import type { Api, LoginStep } from "../api.ts";
import { focus, formValues } from "../dom.ts";
import { PendingLoginStore } from "../pending-login.ts";
import { FormView } from "../view.ts";
import { type LoginHandlers, type LoginState, loginTemplate, type Step } from "./login.templates.ts";

export class LoginView extends FormView<LoginState> {
  private readonly api: Api;
  private readonly onSignedIn: () => void;
  private registration: { email: string; family_code: string } | null = null; // für „Neuen Code schicken“
  private inviteToken: string | null = null;
  private loginToken: string | null = null;
  private readonly pending = new PendingLoginStore();

  constructor(root: HTMLElement, api: Api, onSignedIn: () => void) {
    super(root, { step: { name: "name" }, loginName: "", busy: false, feedback: null });
    this.api = api;
    this.onSignedIn = onSignedIn;
  }

  /** Wurde vorhin ein Code verschickt, der noch gilt, geht es direkt mit der Code-Eingabe weiter. */
  show(): void {
    const pending = this.pending.load();
    if (!pending) return this.goTo({ name: "name" });
    this.update({ loginName: pending.name });
    this.goTo({ name: "code", email: pending.email, validUntil: pending.validUntil, alreadySent: true });
  }

  /** Einladungslink (?einladung=…): erst zeigen, wer eingeladen ist – angenommen wird per Knopfdruck. */
  async showInvite(token: string): Promise<void> {
    this.inviteToken = token;
    const info = await this.run(() => this.api.inviteInfo(token));
    history.replaceState(null, "", "/"); // Link nicht in Verlauf/Lesezeichen behalten
    if (info) this.goTo({ name: "invite", person: info.name, inviter: info.eingeladen_von });
    else this.goTo({ name: "name" }, false);
  }

  /** Knopf aus der Anmelde-Mail (?anmelden=…): erst zeigen, für wen – angemeldet wird per Knopfdruck
   *  (Mail-Programme öffnen Links teils selbst, das darf den Code nicht verbrauchen). */
  async showLoginLink(token: string): Promise<void> {
    this.loginToken = token;
    const info = await this.run(() => this.api.loginLinkInfo(token));
    history.replaceState(null, "", "/");
    if (info) this.goTo({ name: "link", person: info.name });
    else this.goTo({ name: "name" }, false);
  }

  protected template() {
    return loginTemplate(this.state, this.handlers);
  }

  private goTo(step: Step, clearFeedback = true): void {
    this.update(clearFeedback ? { step, feedback: null } : { step });
    focus(this.root);
  }

  /** Antwort des Servers → nächster Schritt. */
  private follow(res: LoginStep | undefined): void {
    if (res && "name" in res) this.update({ loginName: res.name }); // Schreibweise vom Server
    switch (res?.step) {
      case "code":
        this.pending.save({ name: res.name, email: res.email, validUntil: res.gueltig_bis });
        return this.goTo({ name: "code", email: res.email, validUntil: res.gueltig_bis,
                           alreadySent: res.schon_verschickt });
      case "invited": return this.goTo({ name: "invited", person: res.name, email: res.email });
      case "register": return this.goTo({ name: "register", person: res.name });
    }
  }

  private requestCode(resend = false) {
    const { loginName } = this.state;
    const reg = this.registration;
    return this.run(() => reg ? this.api.register(loginName, reg.email, reg.family_code)
                              : this.api.loginStart(loginName, resend));
  }

  private signedIn(): void {
    this.registration = this.inviteToken = this.loginToken = null;
    this.pending.clear();
    this.update({ loginName: "", step: { name: "name" }, feedback: null });
    this.onSignedIn();
  }

  private readonly handlers: LoginHandlers = {
    submitName: async (e) => {
      this.registration = null;
      this.update({ loginName: formValues(e).name });
      this.follow(await this.requestCode());
    },
    register: async (e) => {
      const { email, family_code } = formValues(e);
      this.registration = { email, family_code };
      this.follow(await this.requestCode());
    },
    verify: async (e) => {
      const code = formValues(e).code.replace(/\s/g, "");
      if (await this.run(() => this.api.verify(this.state.loginName, code))) this.signedIn();
    },
    resendCode: async () => {
      const res = await this.requestCode(true);
      this.follow(res);
      if (res?.step === "code") this.say("ok", "Neuer Code ist unterwegs.");
    },
    resendInvite: async (e) => {
      e.preventDefault();
      const res = await this.run(() => this.api.resendInvite(this.state.loginName));
      if (res) this.say("ok", `Die Einladung ist unterwegs an ${res.email}. Schau in dein Postfach.`);
    },
    acceptInvite: async (e) => {
      e.preventDefault();
      const token = this.inviteToken;
      if (token && await this.run(() => this.api.acceptInvite(token))) this.signedIn();
    },
    acceptLoginLink: async (e) => {
      e.preventDefault();
      const token = this.loginToken;
      if (token && await this.run(() => this.api.acceptLoginLink(token))) this.signedIn();
    },
    back: () => {
      this.pending.clear();
      this.goTo({ name: "name" });
    },
  };
}
