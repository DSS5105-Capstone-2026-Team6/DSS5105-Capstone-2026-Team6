/* ---------------- compare models ----------------
   Four-phase animated run, all client-side pacing:
   1. open the three request pools, slide to each picked message and star it
   2. run both models per request (cells fill as answers arrive)
   3. show the labelled ground truth next to each answer for checking
   4. accuracy bars for both models — done
   The endpoint classifies one request per call, so the main desk stays
   fully usable while a comparison runs. */
const CMP_FILES = ["dispatch_requests.txt", "dispatch_requests_full120.txt",
                   "dispatch_requests_heldout.txt"];

function fillCompareSelects(){
  const opts = [];
  for (const [prov, spec] of Object.entries(STATE.providers))
    for (const m of spec.models) opts.push(`${prov}:${m[0]}|${spec.label} · ${m[1]}`);
  const html = opts.map(o => {
    const [v, label] = o.split("|");
    return `<option value="${v}">${esc(label)}</option>`;
  }).join("");
  $("cmpA").innerHTML = html; $("cmpB").innerHTML = html;
  if (opts.length > 1) $("cmpB").selectedIndex = 1;
}

const _sleep = ms => new Promise(r => setTimeout(r, ms));

/* interrupt: closing the overlay or pressing Stop invalidates the run —
   in-flight requests finish but the loop never touches the UI again */
window._cmpRunId = 0;
function abortCompare(){
  window._cmpRunId++;
  $("compareOverlay").style.display = "none";
  $("cmpBtn").disabled = false;
}

function _cmpHeader(step, text){
  return `<div class="cmp-step"><span class="cmp-step-n">${step}</span>${esc(text)}</div>`;
}
function _chip(b){
  const [label, color] = BADGE[b] || [b, "#dee2e6"];
  return `<span class="chip ${b}" style="background:${color}">${label}</span>`;
}

async function compareModels(){
  const a = $("cmpA").value, b = $("cmpB").value;
  if (a === b){ status("Pick two different models to compare."); return; }
  const run = ++window._cmpRunId;          // closing/Stop invalidates this run
  const alive = () => run === window._cmpRunId;
  const stage = $("cmpStage");
  $("compareOverlay").style.display = "block";
  $("cmpBtn").disabled = true;
  stage.innerHTML = "";

  try {
    /* ---- phase 1: open the pools, slide to each pick, star it ---- */
    stage.innerHTML = _cmpHeader(1, "Opening the request pools…");
    const filesRow = document.createElement("div");
    filesRow.className = "cmp-files";
    stage.appendChild(filesRow);
    for (const f of CMP_FILES){
      const chip = document.createElement("span");
      chip.className = "cmp-file";
      chip.textContent = f.replace("dispatch_requests", "…").replace(".txt", "");
      chip.title = f;
      filesRow.appendChild(chip);
      await _sleep(260);
      if (!alive()) return;
      chip.classList.add("open");
    }
    const pick = await post("/api/compare_pick", {n: 8});
    if (!alive()) return;
    stage.insertAdjacentHTML("beforeend",
      _cmpHeader(1, `Picked ${pick.requests.length} of ${pick.pool} requests — locating each message…`));
    const list = document.createElement("div");
    stage.appendChild(list);
    for (const r of pick.requests){
      const row = document.createElement("div");
      row.className = "cmp-row";
      row.id = "cmp-" + r.rid;
      row.innerHTML = `
        <div class="one-line"><span class="cmp-star"></span><b>${esc(r.rid)}</b>
          <span class="muted">${esc(r.source.replace("dispatch_requests_", "").replace("dispatch_requests", "dev").replace(".txt", ""))} · line ${r.line_no}</span></div>
        <div class="cmp-text">${esc(r.text.slice(0, 120))}${r.text.length > 120 ? "…" : ""}</div>
        <div class="cmp-cells">
          <div class="cmp-cell" data-model="a"></div>
          <div class="cmp-cell" data-model="b"></div>
        </div>
        <div class="cmp-label"></div>`;
      list.appendChild(row);
      row.scrollIntoView({behavior: "smooth", block: "nearest"});
      await _sleep(340);
      if (!alive()) return;
      row.querySelector(".cmp-star").innerHTML = icon("star");
      row.classList.add("starred");
      await _sleep(120);
      if (!alive()) return;
    }

    /* ---- phase 2: classify with both models, cells fill progressively ---- */
    stage.insertAdjacentHTML("beforeend",
      _cmpHeader(2, `Comparing — each request through both models…`));
    const results = {a: [], b: []};
    for (const r of pick.requests){
      const row = $("cmp-" + r.rid);
      for (const key of ["a", "b"])
        row.querySelector(`[data-model="${key}"]`).innerHTML =
          '<span class="cmp-spin"></span>';
      row.scrollIntoView({behavior: "smooth", block: "nearest"});
      const [ra, rb] = await Promise.all([
        post("/api/compare_run", {model: a, text: r.text, rid: r.rid}),
        post("/api/compare_run", {model: b, text: r.text, rid: r.rid}),
      ]);
      if (!alive()) return;
      for (const [key, res] of [["a", ra], ["b", rb]]){
        const cell = row.querySelector(`[data-model="${key}"]`);
        if (res.error){
          cell.innerHTML = `<span class="warn">error</span>`;
          cell.title = res.error;
          results[key].push({ok: false, labeled: !!r.expected});
        } else {
          cell.innerHTML = _chip(res.got);
          cell.title = res.explanation || "";
          results[key].push({got: res.got, expected: r.expected,
                             ok: r.expected ? res.got === r.expected : null,
                             labeled: !!r.expected});
        }
      }
      /* ---- phase 3 (per row): reveal the labelled ground truth ---- */
      const lab = row.querySelector(".cmp-label");
      if (r.expected){
        lab.innerHTML = `label: ${_chip(r.expected)}` +
          (r.note ? ` <span class="muted" title="${esc(r.note)}">ⓘ</span>` : "");
      } else {
        lab.innerHTML = '<span class="muted">no label on file</span>';
      }
    }

    /* ---- phase 4: accuracy bars ---- */
    stage.insertAdjacentHTML("beforeend", _cmpHeader(3, "Result"));
    const sum = document.createElement("div");
    sum.className = "cmp-summary";
    for (const [key, spec] of [["a", a], ["b", b]]){
      const labeled = results[key].filter(x => x.labeled);
      const ok = labeled.filter(x => x.ok).length;
      const acc = labeled.length ? Math.round(100 * ok / labeled.length) : null;
      const unlabeled = results[key].length - labeled.length;
      sum.innerHTML += `
        <div class="cmp-model">
          <div class="one-line"><b>${esc(spec)}</b>
            <span class="muted">${acc == null ? "no labeled picks" : `${ok}/${labeled.length} correct`}${unlabeled ? ` · ${unlabeled} unlabeled` : ""}</span></div>
          <div class="cmp-bar"><div class="cmp-fill" style="width:0%"></div></div>
        </div>`;
    }
    stage.appendChild(sum);
    sum.scrollIntoView({behavior: "smooth", block: "nearest"});
    await _sleep(150);
    for (const [i, key] of ["a", "b"].entries()){
      const labeled = results[key].filter(x => x.labeled);
      const acc = labeled.length
        ? Math.round(100 * labeled.filter(x => x.ok).length / labeled.length) : 0;
      sum.children[i].querySelector(".cmp-fill").style.width = acc + "%";
    }
  } catch(e){
    if (alive())
      stage.insertAdjacentHTML("beforeend",
        `<div class="warn">Compare failed: ${esc(e)}</div>`);
  }
  if (alive()) $("cmpBtn").disabled = false;
}
