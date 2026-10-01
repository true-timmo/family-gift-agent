import { render, type TemplateResult } from "lit-html";
import { ApiError } from "./api.ts";

/** Grundgerüst: Zustand ändern → Vorlage neu rendern (lit-html aktualisiert nur, was sich geändert hat). */
export abstract class View<S extends object> {
  protected readonly root: HTMLElement;
  protected state: S;

  constructor(root: HTMLElement, initial: S) {
    this.root = root;
    this.state = initial;
  }

  protected abstract template(): TemplateResult;

  protected update(patch: Partial<S>): void {
    this.state = { ...this.state, ...patch };
    render(this.template(), this.root);
  }
}

export type Feedback = { kind: "ok" | "err"; text: string } | null;

export interface FormState {
  busy: boolean;
  feedback: Feedback;
}

/** View mit Formularen: sperrt Knöpfe während einer Anfrage und zeigt Fehler als Rückmeldung an. */
export abstract class FormView<S extends FormState> extends View<S> {
  /** Führt eine Server-Aktion aus. Gibt bei Fehlern undefined zurück (die Meldung steht dann in feedback). */
  protected async run<T>(action: () => Promise<T>): Promise<T | undefined> {
    this.update({ busy: true, feedback: null } as Partial<S>);
    try {
      const result = await action();
      this.update({ busy: false } as Partial<S>);
      return result;
    } catch (e) {
      const text = e instanceof ApiError ? e.message : "Das hat nicht geklappt.";
      this.update({ busy: false, feedback: { kind: "err", text } } as Partial<S>);
      return undefined;
    }
  }

  protected say(kind: "ok" | "err", text: string): void {
    this.update({ feedback: { kind, text } } as Partial<S>);
  }
}
