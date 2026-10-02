// Schalter im Kopf: blendet die Admin-Funktionen ein oder aus, damit die Oberfläche im Alltag aufgeräumt bleibt.
// Die Wahl merkt sich der Browser; die Rechte selbst prüft immer der Server.

const STORAGE_KEY = "geschenke.adminMode";

function load(): boolean {
  try { return localStorage.getItem(STORAGE_KEY) === "1"; } catch { return false; }
}

function save(on: boolean): void {
  try { localStorage.setItem(STORAGE_KEY, on ? "1" : "0"); } catch { /* privates Fenster o.ä. – egal */ }
}

export class AdminSwitch {
  private readonly button: HTMLButtonElement;
  private readonly onChange: (on: boolean) => void;
  private available = false;
  private on = load();

  constructor(button: HTMLButtonElement, onChange: (on: boolean) => void) {
    this.button = button;
    this.onChange = onChange;
    button.addEventListener("click", () => { this.on = !this.on; save(this.on); this.apply(); });
  }

  /** Nur Admins sehen den Schalter. */
  setAvailable(isAdmin: boolean): void {
    this.available = isAdmin;
    this.button.hidden = !isAdmin;
    this.apply();
  }

  private apply(): void {
    const active = this.available && this.on;
    this.button.setAttribute("aria-checked", String(active));
    this.button.title = active ? "Admin-Funktionen ausblenden" : "Admin-Funktionen einblenden";
    this.onChange(active);
  }
}
