// Zugriff auf die Server-API – eine Methode je Endpunkt, mit Typen für Anfragen und Antworten.

export type MemberStatus = "registriert" | "eingeladen" | "offen";

export interface Member {
  name: string;
  status: MemberStatus;
  du: boolean;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Me {
  name: string;
  admin: boolean;
  verlauf: ChatMessage[];
}

export type LoginStep =
  | { step: "code"; email: string }
  | { step: "invited"; name: string; email: string }
  | { step: "register"; name: string };

export interface InviteInfo {
  name: string;
  eingeladen_von: string;
}

export interface Removal {
  name: string;
  wuensche_geloescht: number;
  reservierungen_freigegeben: number;
}

export type ChatEvent =
  | { type: "text"; text: string }
  | { type: "tool"; name: string }
  | { type: "model"; model: string }
  | { type: "error"; text: string }
  | { type: "done" };

/** Fehler mit einer Meldung, die man direkt anzeigen kann. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const LOGIN_PATH = "/api/login";

export class Api {
  private readonly onUnauthorized: () => void;

  /** onUnauthorized: Sitzung abgelaufen (401 außerhalb der Anmeldung) → zurück zum Login. */
  constructor(onUnauthorized: () => void) {
    this.onUnauthorized = onUnauthorized;
  }

  // --- Anmeldung ---
  loginStart(name: string) { return this.post<LoginStep>(`${LOGIN_PATH}/start`, { name }); }
  register(name: string, email: string, family_code: string) {
    return this.post<LoginStep>(`${LOGIN_PATH}/register`, { name, email, family_code });
  }
  verify(name: string, code: string) { return this.post<{ name: string }>(`${LOGIN_PATH}/verify`, { name, code }); }
  inviteInfo(token: string) { return this.post<InviteInfo>(`${LOGIN_PATH}/invite`, { token }); }
  acceptInvite(token: string) { return this.post<{ name: string }>(`${LOGIN_PATH}/invite/accept`, { token }); }
  resendInvite(name: string) { return this.post<{ email: string }>(`${LOGIN_PATH}/invite/resend`, { name }); }
  logout() { return this.post<{ ok: boolean }>("/api/logout"); }
  me() { return this.get<Me>("/api/me"); }

  // --- Familie ---
  family() { return this.get<Member[]>("/api/familie"); }
  invite(name: string, email: string, bestehend: boolean) {
    return this.post<{ name: string; email: string }>("/api/einladung", { name, email, bestehend });
  }
  removePerson(name: string) { return this.post<Removal>("/api/admin/person-entfernen", { name }); }

  // --- Chat ---
  clearChat() { return this.post<{ ok: boolean }>("/api/chat/clear"); }

  /** Antwort des Assistenten als Folge von Ereignissen (Server-Sent Events). */
  async *chat(message: string): AsyncGenerator<ChatEvent> {
    const res = await this.request("/api/chat", { message });
    if (!res.body) throw new ApiError(res.status, "Keine Antwort vom Server.");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) return;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        if (part.startsWith("data: ")) yield JSON.parse(part.slice(6)) as ChatEvent;
      }
    }
  }

  // --- Technik ---
  private get<T>(path: string): Promise<T> { return this.json<T>(path); }
  private post<T>(path: string, body: object = {}): Promise<T> { return this.json<T>(path, body); }

  private async json<T>(path: string, body?: object): Promise<T> {
    const res = await this.request(path, body);
    return res.json() as Promise<T>;
  }

  /** GET ohne Body, sonst POST mit JSON. Wirft ApiError mit verständlicher Meldung. */
  private async request(path: string, body?: object): Promise<Response> {
    let res: Response;
    try {
      res = await fetch(path, body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch {
      throw new ApiError(0, "Keine Verbindung zum Server.");
    }
    if (res.ok) return res;
    if (res.status === 401 && !path.startsWith(LOGIN_PATH)) this.onUnauthorized();
    const detail = await res.json().then((d) => d.detail, () => undefined);
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Das hat nicht geklappt.");
  }
}
