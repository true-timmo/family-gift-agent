// Merkt sich einen verschickten Anmelde-Code (Name, maskierte Adresse, Ablaufzeit – nie den Code selbst),
// damit man ihn eingeben kann, auch wenn das Fenster zwischendurch geschlossen oder neu geladen wurde.

export interface PendingLogin {
  name: string;
  email: string;
  validUntil: number; // Unix-Sekunden
  resendAt?: number; // ab wann „Neuen Code schicken“ wieder geht
}

type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

const STORAGE_KEY = "geschenke.pendingLogin";

export class PendingLoginStore {
  private readonly store: () => KeyValueStore;
  private readonly now: () => number;

  constructor(store: () => KeyValueStore = () => localStorage, now: () => number = () => Date.now() / 1000) {
    this.store = store;
    this.now = now;
  }

  save(login: PendingLogin): void {
    try { this.store().setItem(STORAGE_KEY, JSON.stringify(login)); } catch { /* privates Fenster o.ä. – egal */ }
  }

  /** Der gemerkte Code, solange er noch gilt – sonst null (und vergessen). */
  load(): PendingLogin | null {
    let login: PendingLogin | null = null;
    try {
      const parsed: unknown = JSON.parse(this.store().getItem(STORAGE_KEY) ?? "null");
      if (isPendingLogin(parsed)) login = parsed;
    } catch { /* kaputt oder nicht erlaubt → wie nichts */ }
    if (login && login.validUntil > this.now()) return login;
    this.clear();
    return null;
  }

  clear(): void {
    try { this.store().removeItem(STORAGE_KEY); } catch { /* egal */ }
  }
}

function isPendingLogin(v: unknown): v is PendingLogin {
  const o = v as Partial<PendingLogin> | null;
  return typeof o?.name === "string" && typeof o.email === "string" && typeof o.validUntil === "number";
}
