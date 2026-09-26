/* Start. Last on the page, so everything it calls is declared. */

document.getElementById("newtab").onclick = () => newTab();
document.addEventListener("keydown", (e) => {
  const tab = current();
  if (e.key === "Escape" && tab?.ui?.zoom) { closeZoom(tab); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === "t") { e.preventDefault(); newTab(); }
  if ((e.ctrlKey || e.metaKey) && e.key === "w") { e.preventDefault(); if (state.active) closeTab(state.active, e); }
  if (e.key === "r" && !e.ctrlKey && !e.metaKey && document.activeElement?.tagName !== "INPUT") {
    if (tab?.status === "ready") refreshLive(tab, true);
  }
});

startClock();
newTab();
