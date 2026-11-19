// Face ID / Touch ID / Fingerabdruck (Passkeys): Übersetzung zwischen Server-JSON und der Browser-Schnittstelle
// (navigator.credentials) – dort sind Binärwerte ArrayBuffer, auf dem Weg zum Server base64url-Texte.

type Json = Record<string, unknown>;

export function toBase64url(buffer: ArrayBuffer): string {
  let text = "";
  for (const byte of new Uint8Array(buffer)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function fromBase64url(value: string): ArrayBuffer {
  const text = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (value.length % 4)) % 4));
  return Uint8Array.from(text, (c) => c.charCodeAt(0)).buffer;
}

interface Descriptor { id: string; type: string; transports?: string[] }

const descriptors = (list: unknown) =>
  ((list as Descriptor[] | undefined) ?? []).map((d) => ({ ...d, id: fromBase64url(d.id) })) as
    PublicKeyCredentialDescriptor[];

export function creationOptions(json: Json): PublicKeyCredentialCreationOptions {
  const user = json.user as { id: string; name: string; displayName: string };
  return {
    ...(json as unknown as PublicKeyCredentialCreationOptions),
    challenge: fromBase64url(json.challenge as string),
    user: { ...user, id: fromBase64url(user.id) },
    excludeCredentials: descriptors(json.excludeCredentials),
  };
}

export function requestOptions(json: Json): PublicKeyCredentialRequestOptions {
  return {
    ...(json as unknown as PublicKeyCredentialRequestOptions),
    challenge: fromBase64url(json.challenge as string),
    allowCredentials: descriptors(json.allowCredentials),
  };
}

/** Antwort des Geräts → JSON für den Server (Einrichten und Anmelden). */
export function credentialJson(credential: PublicKeyCredential): Json {
  const r = credential.response;
  const response: Json = { clientDataJSON: toBase64url(r.clientDataJSON) };
  if ("attestationObject" in r) {
    const attestation = r as AuthenticatorAttestationResponse;
    response.attestationObject = toBase64url(attestation.attestationObject);
    response.transports = attestation.getTransports?.() ?? [];
  } else {
    const assertion = r as AuthenticatorAssertionResponse;
    response.authenticatorData = toBase64url(assertion.authenticatorData);
    response.signature = toBase64url(assertion.signature);
    if (assertion.userHandle) response.userHandle = toBase64url(assertion.userHandle);
  }
  return {
    id: credential.id, rawId: toBase64url(credential.rawId), type: credential.type, response,
    clientExtensionResults: credential.getClientExtensionResults(),
    authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
  };
}

/** Kann dieses Gerät Passkeys mit Face ID / Fingerabdruck? */
export async function passkeysAvailable(): Promise<boolean> {
  try {
    return typeof PublicKeyCredential !== "undefined"
      && await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
  } catch {
    return false;
  }
}

/** So heißt es auf dem Gerät – damit die Beschriftung zu dem passt, was man kennt. */
export function biometricName(userAgent = navigator.userAgent): string {
  if (/iPhone|iPad|iPod/.test(userAgent)) return "Face ID";
  if (/Macintosh/.test(userAgent)) return "Touch ID";
  if (/Android/.test(userAgent)) return "Fingerabdruck";
  return "Windows Hello";
}

export const deviceName = (userAgent = navigator.userAgent): string =>
  /iPhone/.test(userAgent) ? "iPhone" : /iPad/.test(userAgent) ? "iPad" : /Android/.test(userAgent) ? "Android"
    : /Macintosh/.test(userAgent) ? "Mac" : /Windows/.test(userAgent) ? "Windows" : "Gerät";

/** Hat der Nutzer abgebrochen (Face ID weggewischt)? Dann keine Fehlermeldung, sondern einfach zurück. */
export const cancelled = (e: unknown) => e instanceof DOMException && e.name === "NotAllowedError";

// Merkt sich pro Gerät, für wen hier Face ID eingerichtet ist (für den großen Knopf auf der Anmeldeseite)
// und ob das Angebot gerade abgelehnt wurde (dann fragen wir 30 Tage nicht). Der Server prüft trotzdem alles selbst.
const DEVICE_KEY = "geschenke.passkeyFor";
const DECLINED_KEY = "geschenke.passkeyDeclined";
const ASK_AGAIN_MS = 30 * 24 * 3600 * 1000;

export const passkeyDevice = {
  name(): string | null {
    try { return localStorage.getItem(DEVICE_KEY); } catch { return null; }
  },
  remember(name: string): void {
    try { localStorage.setItem(DEVICE_KEY, name); localStorage.removeItem(DECLINED_KEY); } catch { /* egal */ }
  },
  forget(): void {
    try { localStorage.removeItem(DEVICE_KEY); } catch { /* egal */ }
  },
  declined(now = Date.now()): boolean {
    try { return now - Number(localStorage.getItem(DECLINED_KEY) ?? 0) < ASK_AGAIN_MS; } catch { return false; }
  },
  decline(now = Date.now()): void {
    try { localStorage.setItem(DECLINED_KEY, String(now)); } catch { /* egal */ }
  },
};
