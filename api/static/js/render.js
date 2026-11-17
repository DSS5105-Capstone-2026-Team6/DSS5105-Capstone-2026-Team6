/* ---------------- render root ---------------- */
function render(){
  renderRail(); renderKpis(); renderWorklist(); renderRecords(); renderProvider(); renderChatLog();
  if (!$("cmpA").dataset.filled){ fillCompareSelects(); $("cmpA").dataset.filled = "1"; }
  if (TAB === "dashboard") renderDashboard();
}
function renderAll(){ render(); }

