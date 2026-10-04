// Kleines Markdown für Chat-Antworten: Links, Fett, Listen und Tabellen.
// Liefert eine Struktur statt HTML – die Darstellung (markdown-view.ts) escaped automatisch.

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; children: Inline[] }
  | { kind: "link"; href: string; children: Inline[] };

export interface Cell {
  inlines: Inline[];
  text: string; // ohne Formatierung, z.B. für Spaltennamen und den Status
}

export type Block =
  | { kind: "line"; inlines: Inline[]; breakAfter: boolean }
  | { kind: "list"; items: Inline[][] }
  | { kind: "table"; head: Cell[]; rows: Cell[][] };

export type StatusKind = "open" | "mine" | "taken";

// [Text](https://…) | **fett** | nackte Adresse (am Zeilenanfang, nach Leerzeichen oder Klammer)
const INLINE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*|(^|[\s(])(https?:\/\/[^\s<)|]+)/g;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEP = /^\s*\|?(\s*:?-{2,}:?\s*\|)+\s*(:?-{2,}:?\s*)?\|?\s*$/;
const LIST_ITEM = /^\s*(?:[-*•]|\d+\.)\s+(.*)/;

export function parseInline(source: string): Inline[] {
  const out: Inline[] = [];
  const text = (t: string) => {
    const prev = out.at(-1);
    if (prev?.kind === "text") prev.text += t;
    else if (t) out.push({ kind: "text", text: t });
  };
  let last = 0;
  for (const m of source.matchAll(INLINE)) {
    const [whole, linkText, href, bold, before, url] = m;
    text(source.slice(last, m.index));
    if (href) out.push({ kind: "link", href, children: parseInline(linkText) });
    else if (bold) out.push({ kind: "strong", children: parseInline(bold) });
    else {
      text(before);
      out.push({ kind: "link", href: url, children: [{ kind: "text", text: url }] });
    }
    last = m.index + whole.length;
  }
  text(source.slice(last));
  return out;
}

export function plainText(inlines: Inline[]): string {
  return inlines.map((i) => (i.kind === "text" ? i.text : plainText(i.children))).join("");
}

const cell = (source: string): Cell => {
  const inlines = parseInline(source.trim());
  return { inlines, text: plainText(inlines).trim() };
};
const cells = (row: string): Cell[] => row.trim().replace(/^\||\|$/g, "").split("|").map(cell);

export function parseMarkdown(source: string): Block[] {
  const lines = source.split("\n");
  const blocks: Block[] = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    // Tabelle: Kopfzeile + Trennzeile (|---|---|) + Datenzeilen
    if (TABLE_ROW.test(line) && TABLE_SEP.test(lines[i + 1] ?? "")) {
      const rows: Cell[][] = [];
      for (i += 2; i < lines.length && TABLE_ROW.test(lines[i]); i++) rows.push(cells(lines[i]));
      i--;
      blocks.push({ kind: "table", head: cells(line), rows });
      continue;
    }
    const item = line.match(LIST_ITEM);
    if (item) {
      const prev = blocks.at(-1);
      if (prev?.kind === "list") prev.items.push(parseInline(item[1]));
      else blocks.push({ kind: "list", items: [parseInline(item[1])] });
      continue;
    }
    blocks.push({ kind: "line", inlines: parseInline(line), breakAfter: true });
  }
  return withLineBreaks(blocks);
}

const isEmptyLine = (b: Block | undefined) => b?.kind === "line" && b.inlines.length === 0;

/** Zeilenumbrüche wie im Chat erwartet: keine Leerzeilen am Ende und direkt um Tabellen herum. */
function withLineBreaks(blocks: Block[]): Block[] {
  const result = blocks.filter((b, i) => !(isEmptyLine(b) && blocks[i - 1]?.kind === "table"));
  while (isEmptyLine(result.at(-1))) result.pop();
  result.forEach((b, i) => {
    if (b.kind === "line") b.breakAfter = i < result.length - 1 && result[i + 1].kind !== "table";
  });
  return result;
}

/** Status-Spalte als farbiges Etikett: offen / von dir reserviert / besorgt <Name>. */
export function statusKind(column: string, value: string): StatusKind | null {
  if (column.toLowerCase() !== "status") return null;
  const v = value.toLowerCase();
  if (v.startsWith("offen")) return "open";
  if (v.includes("von dir")) return "mine";
  if (v.startsWith("besorgt")) return "taken";
  return null;
}

export const isEmptyCell = (c: Cell) => ["", "–", "-"].includes(c.text);

/** Spalte mit Details zum Wunsch (Größe, Farbe …) – steht in der Karte ohne Beschriftung unter dem Titel. */
export const isDetailsColumn = (column: string) => /^(details|beschreibung)$/i.test(column.trim());
