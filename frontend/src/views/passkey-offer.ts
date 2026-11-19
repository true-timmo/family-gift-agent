// Angebot im Chat: „Beim nächsten Mal mit Face ID anmelden?“ – einmal einrichten, danach keine Codes mehr.
// Erscheint nur, wenn das Gerät es kann und hier noch nicht eingerichtet bzw. nicht kürzlich abgelehnt wurde.
import type { Api } from "../api.ts";
import { biometricName, cancelled, credentialJson, creationOptions, deviceName, passkeyDevice, passkeysAvailable }
  from "../passkey.ts";
import { FormView } from "../view.ts";
import { type PasskeyOfferHandlers, type PasskeyOfferState, passkeyOfferTemplate } from "./passkey-offer.templates.ts";

export class PasskeyOffer extends FormView<PasskeyOfferState> {
  private readonly api: Api;
  private name = "";
  // Vorab geholt: Safari verlangt, dass Face ID direkt auf den Tipp folgt
  private options: Promise<Record<string, unknown> | undefined> | null = null;

  constructor(root: HTMLElement, api: Api) {
    super(root, { phase: "hidden", biometric: biometricName(), busy: false, feedback: null });
    this.api = api;
  }

  async maybeShow(name: string): Promise<void> {
    this.name = name;
    const show = passkeyDevice.name() !== name && !passkeyDevice.declined() && await passkeysAvailable();
    if (show) this.options = this.api.passkeySetupOptions().catch(() => undefined);
    this.setPhase(show ? "offer" : "hidden");
  }

  hide(): void {
    this.setPhase("hidden");
  }

  protected template() {
    return passkeyOfferTemplate(this.state, this.handlers);
  }

  private setPhase(phase: PasskeyOfferState["phase"]): void {
    this.root.hidden = phase === "hidden";
    this.update({ phase, feedback: null });
  }

  private async setUp(): Promise<void> {
    const options = (await this.options) ?? await this.run(() => this.api.passkeySetupOptions());
    this.options = null;
    if (!options) return;
    let credential: PublicKeyCredential;
    try {
      credential = await navigator.credentials.create({ publicKey: creationOptions(options) }) as PublicKeyCredential;
    } catch (e) {
      if (e instanceof DOMException && e.name === "InvalidStateError") return this.finished(); // gibt es hier schon
      this.say("err", cancelled(e) ? "Abgebrochen – du kannst es jederzeit nochmal versuchen."
        : `${this.state.biometric} konnte nicht eingerichtet werden.`);
      this.options = this.api.passkeySetupOptions().catch(() => undefined);
      return;
    }
    if (await this.run(() => this.api.passkeySetup(credentialJson(credential), deviceName()))) this.finished();
  }

  private finished(): void {
    passkeyDevice.remember(this.name);
    this.setPhase("done");
  }

  private readonly handlers: PasskeyOfferHandlers = {
    setUp: () => void this.setUp(),
    later: () => { passkeyDevice.decline(); this.hide(); },
    close: () => this.hide(),
  };
}
