// Darstellung von Markdown-Blöcken mit lit-html (Texte werden dabei automatisch escaped).
import { html, nothing, type TemplateResult } from "lit-html";
import { classMap } from "lit-html/directives/class-map.js";
import { type Block, type Cell, type Inline, isDetailsColumn, isEmptyCell, parseMarkdown, statusKind } from "./markdown.ts";

const inline = (items: Inline[]): TemplateResult[] => items.map((i) => {
  switch (i.kind) {
    case "text": return html`${i.text}`;
    case "strong": return html`<strong>${inline(i.children)}</strong>`;
    case "link": return html`<a href=${i.href} target="_blank" rel="noopener">${inline(i.children)}</a>`;
  }
});

const tableCell = (c: Cell, column: Cell | undefined, index: number) => {
  const label = column?.text ?? "";
  const status = statusKind(label, c.text);
  // data-label: Spaltenname als Beschriftung in der Karte
  const classes = { "cell-title": index === 0, "cell-details": isDetailsColumn(label), "cell-empty": isEmptyCell(c) };
  return html`<td data-label=${label} class=${classMap(classes)}
    >${status ? html`<span class="status status-${status}">${inline(c.inlines)}</span>` : inline(c.inlines)}</td>`;
};

const block = (b: Block): TemplateResult => {
  switch (b.kind) {
    case "line": return html`${inline(b.inlines)}${b.breakAfter ? html`<br>` : nothing}`;
    case "list": return html`<ul>${b.items.map((item) => html`<li>${inline(item)}</li>`)}</ul>`;
    case "table": return html`
      <div class="table-wrap"><table>
        <thead><tr>${b.head.map((h) => html`<th>${inline(h.inlines)}</th>`)}</tr></thead>
        <tbody>${b.rows.map((row) => html`<tr>${row.map((c, k) => tableCell(c, b.head[k], k))}</tr>`)}</tbody>
      </table></div>`;
  }
};

export const markdown = (text: string): TemplateResult => html`${parseMarkdown(text).map(block)}`;
