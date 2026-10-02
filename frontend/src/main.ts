// Einstieg: verbindet die Views und schaltet zwischen Anmeldung und Chat um.
import { Api } from "./api.ts";
import { AdminSwitch } from "./admin-mode.ts";
import { byId } from "./dom.ts";
import { initHelpDialogs } from "./help.ts";
import { ChatView } from "./views/chat.ts";
import { FamilyPanel } from "./views/family.ts";
import { LoginView } from "./views/login.ts";

class App {
  private readonly api = new Api(() => this.showLogin());
  private readonly loginView = byId("login-view");
  private readonly chatView = byId("chat-view");
  private readonly login = new LoginView(byId("login-steps"), this.api, () => this.showChat());
  private readonly chat = new ChatView({
    messages: byId("messages"),
    form: byId<HTMLFormElement>("chat-form"),
    input: byId<HTMLTextAreaElement>("input"),
    send: byId<HTMLButtonElement>("send"),
  }, this.api);
  private readonly family = new FamilyPanel(byId("family"), byId<HTMLButtonElement>("family-btn"), this.api,
    (question) => this.chat.setDraft(question));
  private readonly adminSwitch = new AdminSwitch(byId<HTMLButtonElement>("admin-toggle"),
    (on) => this.family.setAdminMode(on));

  constructor() {
    initHelpDialogs();
    byId("logout-btn").addEventListener("click", async () => { await this.api.logout(); this.showLogin(); });
    byId("clear-btn").addEventListener("click", () => this.chat.clear());
  }

  start(): void {
    const inviteToken = new URLSearchParams(location.search).get("einladung");
    if (inviteToken) {
      this.switchTo("login");
      void this.login.showInvite(inviteToken);
    } else {
      this.showChat().catch(() => this.showLogin());
    }
  }

  private async showChat(): Promise<void> {
    const me = await this.api.me();
    byId("who").textContent = me.name;
    this.adminSwitch.setAvailable(me.admin);
    this.family.close();
    this.switchTo("chat");
    this.chat.load(me.verlauf);
  }

  private showLogin(): void {
    this.switchTo("login");
    this.login.show();
  }

  private switchTo(view: "login" | "chat"): void {
    this.loginView.hidden = view !== "login";
    this.chatView.hidden = view !== "chat";
  }
}

new App().start();
