import assert from "node:assert/strict";
import { test } from "node:test";
import { type Block, isDetailsColumn, parseInline, parseMarkdown, statusKind, tableLayoutFor } from "../src/markdown.ts";

const text = (t: string) => ({ kind: "text", text: t });
const line = (b: Block) => (b.kind === "line" ? b : assert.fail(`erwartet Zeile, nicht ${b.kind}`));

test("Links, fett und nackte Adressen", () => {
  assert.deepEqual(parseInline("bei [Thalia](https://thalia.de/x) für **25 €**"), [
    text("bei "),
    { kind: "link", href: "https://thalia.de/x", children: [text("Thalia")] },
    text(" für "),
    { kind: "strong", children: [text("25 €")] },
  ]);
  assert.deepEqual(parseInline("siehe https://a.de/b)"), [
    text("siehe "),
    { kind: "link", href: "https://a.de/b", children: [text("https://a.de/b")] },
    text(")"),
  ]);
});

test("HTML bleibt Text (escaped wird beim Rendern)", () => {
  assert.deepEqual(parseInline("<img src=x onerror=alert(1)>"), [text("<img src=x onerror=alert(1)>")]);
  assert.deepEqual(parseInline("[x](javascript:alert(1))"), [text("[x](javascript:alert(1))")]);
});

test("Listen fassen aufeinanderfolgende Punkte zusammen", () => {
  const blocks = parseMarkdown("Wünsche:\n- Pfanne\n* Buch\n1. Rad\nEnde");
  assert.deepEqual(blocks.map((b) => b.kind), ["line", "list", "line"]);
  assert.equal(blocks[1].kind === "list" && blocks[1].items.length, 3);
});

test("Tabelle mit Spaltennamen und ohne Leerzeilen drumherum", () => {
  const blocks = parseMarkdown("Hier:\n\n| Wunsch | Status |\n|---|---|\n| Pfanne | offen |\n| Buch | – |\n\nFertig\n\n");
  assert.deepEqual(blocks.map((b) => b.kind), ["line", "line", "table", "line"]);
  assert.equal(line(blocks[0]).breakAfter, true);
  assert.equal(line(blocks[1]).breakAfter, false); // keine Leerzeile direkt vor der Tabelle
  assert.equal(line(blocks[3]).breakAfter, false); // letzte Zeile, Leerzeilen am Ende entfernt
  const table = blocks[2];
  assert.ok(table.kind === "table");
  assert.deepEqual(table.head.map((c) => c.text), ["Wunsch", "Status"]);
  assert.deepEqual(table.rows.map((r) => r.map((c) => c.text)), [["Pfanne", "offen"], ["Buch", "–"]]);
});

test("Status-Etiketten nur in der Status-Spalte", () => {
  assert.equal(statusKind("Status", "offen"), "open");
  assert.equal(statusKind("status", "von dir reserviert"), "mine");
  assert.equal(statusKind("Status", "besorgt Mama"), "taken");
  assert.equal(statusKind("Shop", "offen"), null);
  assert.equal(statusKind("Status", "?"), null);
});

test("Details-Spalte wird erkannt", () => {
  assert.ok(isDetailsColumn("Details") && isDetailsColumn(" beschreibung "));
  assert.ok(!isDetailsColumn("Shop") && !isDetailsColumn("Details zum Shop"));
});

test("Tabelle nur auf ausdrücklichen Wunsch", () => {
  assert.equal(tableLayoutFor("Zeig mir Timmos Wünsche als Tabelle"), "table");
  assert.equal(tableLayoutFor("tabellarisch bitte"), "table");
  assert.equal(tableLayoutFor("Was wünscht sich Mama?"), "cards");
});
