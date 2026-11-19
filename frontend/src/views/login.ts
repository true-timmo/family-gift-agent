// Anmeldung: Name → Code aus der Mail (oder Knopf in der Mail). Mit Einladungslink: anzeigen und per
// Knopfdruck annehmen. Ein verschickter Code bleibt eingebbar, auch wenn das Fenster zwischendurch zu war.
import type { Api, LoginStep } from "../api.ts";
import { focus, formValues } from "../dom.ts";
import { biometricName, cancelled, credentialJson, passkeyDevice, passkeysAvailable, requestOptions }
  from "../passkey.ts";
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
  private countdown: ReturnType<typeof setInterval> | undefined;
  // Face-ID-Anfrage schon vorab holen: Safari verlangt, dass Face ID direkt auf den Tipp folgt
  private passkeyOptions: Promise<Record<string, unknown> | undefined> | null = null;

  constructor(root: HTMLElement, api: Api, onSignedIn: () => void) {
    super(root, { step: { name: "name" }, loginName: "", busy: false, feedback: null, biometric: biometricName(),
                  deviceUser: null });
    this.api = api;
    this.onSignedIn = onSignedIn;
  }

  /** Wurde vorhin ein Code verschickt, der noch gilt, geht es direkt mit der Code-Eingabe weiter. */
  show(): void {
    void this.offerDevicePasskey();
    const pending = this.pending.load();
    if (!pending) return this.goTo({ name: "name" });
    this.update({ loginName: pending.name });
    this.goTo({ name: "code", email: pending.email, validUntil: pending.validUntil, alreadySent: true,
                resendAt: pending.resendAt ?? 0 });
  }

  /** Einladungslink (#einladung=…): erst zeigen, wer eingeladen ist – angenommen wird per Knopfdruck. */
  async showInvite(token: string): Promise<void> {
    this.inviteToken = token;
    const info = await this.run(() => this.api.inviteInfo(token));
    history.replaceState(null, "", "/"); // Link nicht in Verlauf/Lesezeichen behalten
    if (info) this.goTo({ name: "invite", person: info.name, inviter: info.eingeladen_von });
    else this.goTo({ name: "name" }, false);
  }

  /** Knopf aus der Anmelde-Mail (#anmelden=…): erst zeigen, für wen – angemeldet wird per Knopfdruck
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

  /** Ist auf diesem Gerät Face ID eingerichtet, gibt es oben den großen Knopf „Mit Face ID anmelden“. */
  private async offerDevicePasskey(): Promise<void> {
    const user = passkeyDevice.name();
    const deviceUser = user && await passkeysAvailable() ? user : null;
    this.update({ deviceUser });
    if (!deviceUser) return;
    if (this.state.step.name === "name" && document.activeElement instanceof HTMLElement) document.activeElement.blur();
    this.prefetchPasskey(deviceUser);
  }

  private prefetchPasskey(name: string): void {
    this.passkeyOptions = this.api.passkeyLoginOptions(name).catch(() => undefined);
  }

  /** Face ID: Gerät fragt, unterschreibt, Server prüft – keine Mail, kein Code. */
  private async loginWithPasskey(name: string): Promise<void> {
    const options = (await this.passkeyOptions) ?? await this.run(() => this.api.passkeyLoginOptions(name));
    this.passkeyOptions = null;
    if (!options) {
      if (this.state.step.name === "name") { passkeyDevice.forget(); this.update({ deviceUser: null }); }
      return;
    }
    let credential: PublicKeyCredential | null;
    try {
      credential = await navigator.credentials.get({ publicKey: requestOptions(options) }) as PublicKeyCredential;
    } catch (e) {
      this.say("err", cancelled(e)
        ? `Abgebrochen. Tippe nochmal auf „Mit ${this.state.biometric} anmelden“ – oder lass dir einen Code schicken.`
        : `${this.state.biometric} hat nicht geklappt. Bitte nochmal versuchen.`);
      this.prefetchPasskey(name);
      return;
    }
    const res = credential && await this.run(() => this.api.passkeyLogin(credentialJson(credential)));
    if (res) {
      passkeyDevice.remember(res.name);
      this.signedIn();
    } else {
      this.prefetchPasskey(name);
    }
  }

  private goTo(step: Step, clearFeedback = true): void {
    this.update(clearFeedback ? { step, feedback: null } : { step });
    // Mit Face-ID-Knopf kein Fokus aufs Namensfeld – sonst schiebt sich die Tastatur über den Knopf
    if (!(step.name === "name" && this.state.deviceUser)) focus(this.root);
    this.runCountdown();
  }

  /** Zählt die Wartezeit bis „Neuen Code schicken“ sichtbar herunter. */
  private runCountdown(): void {
    clearInterval(this.countdown);
    const waiting = () => this.state.step.name === "code" && this.state.step.resendAt > Date.now() / 1000;
    if (!waiting()) return;
    this.countdown = setInterval(() => {
      this.update({});
      if (!waiting()) clearInterval(this.countdown);
    }, 1000);
  }

  /** Antwort des Servers → nächster Schritt. */
  private follow(res: LoginStep | undefined): void {
    if (res && "name" in res) this.update({ loginName: res.name }); // Schreibweise vom Server
    switch (res?.step) {
      case "code":
        this.pending.save({ name: res.name, email: res.email, validUntil: res.gueltig_bis,
                            resendAt: res.neuer_code_ab });
        return this.goTo({ name: "code", email: res.email, validUntil: res.gueltig_bis,
                           alreadySent: res.schon_verschickt, resendAt: res.neuer_code_ab });
      case "invited": return this.goTo({ name: "invited", person: res.name, email: res.email });
      case "register": return this.goTo({ name: "register", person: res.name });
      case "passkey":
        this.prefetchPasskey(res.name);
        return this.goTo({ name: "passkey", person: res.name });
    }
  }

  private requestCode(resend = false) {
    const { loginName } = this.state;
    const reg = this.registration;
    return this.run(() => reg ? this.api.register(loginName, reg.email, reg.family_code)
                              : this.api.loginStart(loginName, { resend }));
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
      if (res?.step === "code") this.say("ok", "Neue Mail ist unterwegs. Jeder Code aus den letzten 10 Minuten funktioniert.");
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
    passkeyLogin: () => {
      const name = this.state.step.name === "passkey" ? this.state.step.person : this.state.deviceUser;
      if (name) void this.loginWithPasskey(name);
    },
    codeInstead: async () => {
      this.follow(await this.run(() => this.api.loginStart(this.state.loginName, { code: true })));
    },
    back: () => {
      this.pending.clear();
      this.goTo({ name: "name" });
    },
  };
}
