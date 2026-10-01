// Hilfe-Fenster: Knöpfe mit data-help="<dialog-id>" öffnen sie – auch Knöpfe, die erst später gerendert werden.

export function initHelpDialogs(): void {
  document.addEventListener("click", (e) => {
    const button = (e.target as Element).closest<HTMLElement>("[data-help]");
    const dialog = button && document.getElementById(button.dataset.help ?? "");
    if (dialog instanceof HTMLDialogElement) {
      dialog.showModal();
      dialog.scrollTop = 0;
    }
  });

  for (const dialog of document.querySelectorAll<HTMLDialogElement>("dialog.help")) {
    dialog.querySelectorAll(".help-x, .help-close").forEach((b) => b.addEventListener("click", () => dialog.close()));
    // Nur ein Tipp wirklich NEBEN das Fenster schließt es (nicht auf den Rand/Innenabstand)
    dialog.addEventListener("click", (e) => {
      if (e.target !== dialog) return;
      const r = dialog.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) dialog.close();
    });
  }
}
