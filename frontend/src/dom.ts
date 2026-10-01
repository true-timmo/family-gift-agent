/** Element per id – wirft sofort, wenn es fehlt (statt später mit „null“ zu scheitern). */
export function byId<T extends HTMLElement = HTMLElement>(id: string): T {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} fehlt in index.html`);
  return el as T;
}

/** Werte eines abgeschickten Formulars als Texte (ohne Leerraum an den Rändern). */
export function formValues(e: SubmitEvent): Record<string, string> {
  e.preventDefault();
  const data = new FormData(e.currentTarget as HTMLFormElement);
  return Object.fromEntries([...data].map(([key, value]) => [key, String(value).trim()]));
}

/** Setzt den Fokus auf das erste passende Eingabefeld im Container. */
export function focus(root: ParentNode, selector = "input:not([readonly]), textarea"): void {
  root.querySelector<HTMLElement>(selector)?.focus();
}
