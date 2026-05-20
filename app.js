const API_BASE = "https://cp-factorial.onrender.com";

const $ = (id) => document.getElementById(id);

const paste = $("paste");
const btnParse = $("btnParse");
const btnAnalyze = $("btnAnalyze");
const btnClear = $("btnClear");
const statusEl = $("status");
const preview = $("preview");

const valueColSel = $("valueCol");
const locationColSel = $("locationCol");
const factorColsBox = $("factorCols");
const groupColsBox = $("groupCols");
const primaryFactorSel = $("primaryFactor");
const secondaryFactorSel = $("secondaryFactor");
const alphaInput = $("alpha");
const progressWrap = $("progressWrap");
const progressBar = $("progressBar");
const progressText = $("progressText");
const includeMainTukey = $("includeMainTukey");
const includeInteractionTukey = $("includeInteractionTukey");

let currentRows = [];
let currentCols = [];
let selectedFactors = new Set();
let selectedGroupCols = new Set();

function resetProgress(){
  progressBar.style.width = "0%";
  progressText.textContent = "";
  progressWrap.style.display = "none";
}

function showProgress(){ progressWrap.style.display = "block"; }

function updateProgress(progress, current, total){
  const p = Number.isFinite(progress) ? progress : 0;
  progressBar.style.width = `${p}%`;
  progressText.textContent = total > 0
    ? `Procesando ${current}/${total} análisis (${p}%)`
    : `Preparando análisis... (${p}%)`;
}

function parseLine(line, delim){
  if (delim !== "," && delim !== ";") return line.split(delim);
  const out = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++){
    const ch = line[i];
    if (ch === '"'){
      if (inQuotes && line[i+1] === '"') { cur += '"'; i++; }
      else inQuotes = !inQuotes;
    } else if (ch === delim && !inQuotes){
      out.push(cur); cur = "";
    } else cur += ch;
  }
  out.push(cur);
  return out;
}

function parseTable(text){
  const raw = text.trim();
  if (!raw) return {cols:[], rows:[]};
  const firstLine = raw.split(/\r?\n/)[0];
  let delim = "\t";
  if (!firstLine.includes("\t")) delim = firstLine.includes(";") ? ";" : firstLine.includes(",") ? "," : "\t";
  const lines = raw.split(/\r?\n/).filter(l => l.trim().length > 0);
  const cols = parseLine(lines[0], delim).map(h => h.trim());
  const rows = [];
  for (let i=1;i<lines.length;i++){
    const parts = parseLine(lines[i], delim);
    const obj = {};
    cols.forEach((c, idx) => obj[c] = (parts[idx] ?? "").trim());
    rows.push(obj);
  }
  return {cols, rows};
}

function renderPreview(cols, rows, maxRows=30){
  preview.innerHTML = "";
  if (!cols.length) return;
  const thead = document.createElement("thead");
  const trh = document.createElement("tr");
  cols.forEach(c => { const th = document.createElement("th"); th.textContent = c; trh.appendChild(th); });
  thead.appendChild(trh); preview.appendChild(thead);
  const tbody = document.createElement("tbody");
  rows.slice(0, maxRows).forEach(r => {
    const tr = document.createElement("tr");
    cols.forEach(c => { const td = document.createElement("td"); td.textContent = r[c] ?? ""; tr.appendChild(td); });
    tbody.appendChild(tr);
  });
  preview.appendChild(tbody);
}

function fillSelect(selectEl, cols, preferredName, allowNone=false){
  selectEl.innerHTML = "";
  if (allowNone){
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Sin localidad / ambiente";
    selectEl.appendChild(opt);
  }
  cols.forEach(c => { const opt = document.createElement("option"); opt.value = c; opt.textContent = c; selectEl.appendChild(opt); });
  if (preferredName && cols.includes(preferredName)) selectEl.value = preferredName;
}

function guessValueColumn(cols){
  const preferred = ["assessment_value", "rendimiento", "yield", "fitotoxicidad", "fito", "value"];
  return preferred.find(p => cols.includes(p)) || cols[0] || "";
}

function guessLocationColumn(cols){
  const preferred = ["trial_mod", "localidad", "location", "ambiente", "trial"];
  return preferred.find(p => cols.includes(p)) || "";
}

function syncFactorOrderSelects(){
  const factors = Array.from(selectedFactors);
  [primaryFactorSel, secondaryFactorSel].forEach(sel => {
    const previous = sel.value;
    sel.innerHTML = "";
    factors.forEach(f => { const opt = document.createElement("option"); opt.value = f; opt.textContent = f; sel.appendChild(opt); });
    if (factors.includes(previous)) sel.value = previous;
  });
  if (factors.length >= 1 && !primaryFactorSel.value) primaryFactorSel.value = factors[0];
  if (factors.length >= 2 && (!secondaryFactorSel.value || secondaryFactorSel.value === primaryFactorSel.value)) secondaryFactorSel.value = factors.find(f => f !== primaryFactorSel.value) || factors[1];
}

function renderChips(){
  factorColsBox.innerHTML = "";
  groupColsBox.innerHTML = "";
  const excludedBase = new Set([valueColSel.value]);
  if (locationColSel.value) excludedBase.add(locationColSel.value);

  currentCols.forEach(c => {
    if (c === valueColSel.value) return;
    const chip = document.createElement("div");
    chip.className = "chip" + (selectedFactors.has(c) ? " on" : "");
    chip.textContent = c;
    chip.addEventListener("click", () => {
      if (selectedFactors.has(c)) selectedFactors.delete(c);
      else {
        selectedFactors.add(c);
        selectedGroupCols.delete(c);
      }
      renderChips();
      syncFactorOrderSelects();
    });
    factorColsBox.appendChild(chip);
  });

  currentCols.forEach(c => {
    if (excludedBase.has(c) || selectedFactors.has(c)) return;
    const chip = document.createElement("div");
    chip.className = "chip" + (selectedGroupCols.has(c) ? " on" : "");
    chip.textContent = c;
    chip.addEventListener("click", () => {
      if (selectedGroupCols.has(c)) selectedGroupCols.delete(c);
      else selectedGroupCols.add(c);
      renderChips();
    });
    groupColsBox.appendChild(chip);
  });
}

function resetAll(){
  paste.value = ""; currentRows = []; currentCols = [];
  selectedFactors = new Set(); selectedGroupCols = new Set();
  preview.innerHTML = ""; valueColSel.innerHTML = ""; locationColSel.innerHTML = "";
  factorColsBox.innerHTML = ""; groupColsBox.innerHTML = ""; primaryFactorSel.innerHTML = ""; secondaryFactorSel.innerHTML = "";
  btnAnalyze.disabled = true; statusEl.textContent = "Tabla limpiada."; resetProgress();
}

btnClear.addEventListener("click", resetAll);

btnParse.addEventListener("click", () => {
  try{
    const {cols, rows} = parseTable(paste.value);
    currentCols = cols; currentRows = rows;
    if (!cols.length || !rows.length){
      statusEl.textContent = "No se detectaron datos. Revisá encabezados y filas.";
      btnAnalyze.disabled = true; renderPreview([], []); resetProgress(); return;
    }
    fillSelect(valueColSel, cols, guessValueColumn(cols));
    fillSelect(locationColSel, cols, guessLocationColumn(cols), true);
    selectedFactors = new Set(); selectedGroupCols = new Set();
    const autoFactors = ["hibrido", "hybrid", "dosis", "dose", "treatment", "tratamiento"].filter(c => cols.includes(c));
    autoFactors.slice(0, 4).forEach(c => { if (c !== valueColSel.value && c !== locationColSel.value) selectedFactors.add(c); });
    renderChips(); syncFactorOrderSelects(); renderPreview(cols, rows);
    statusEl.textContent = `Tabla cargada: ${rows.length} filas, ${cols.length} columnas.`;
    btnAnalyze.disabled = false; resetProgress();
  } catch(e){
    console.error(e); statusEl.textContent = "Error al parsear la tabla. Probá pegar desde Excel o CSV."; btnAnalyze.disabled = true; resetProgress();
  }
});

[valueColSel, locationColSel].forEach(sel => sel.addEventListener("change", () => {
  selectedFactors.delete(valueColSel.value);
  if (locationColSel.value) selectedFactors.delete(locationColSel.value);
  selectedGroupCols.delete(valueColSel.value);
  if (locationColSel.value) selectedGroupCols.delete(locationColSel.value);
  renderChips(); syncFactorOrderSelects();
}));

primaryFactorSel.addEventListener("change", () => {
  if (secondaryFactorSel.value === primaryFactorSel.value){
    const other = Array.from(selectedFactors).find(f => f !== primaryFactorSel.value);
    if (other) secondaryFactorSel.value = other;
  }
});

btnAnalyze.addEventListener("click", async () => {
  if (!currentRows.length) return;
  const factors = Array.from(selectedFactors);
  if (factors.length < 2){ statusEl.textContent = "Seleccioná al menos 2 factores para un análisis factorial."; return; }
  const locationMode = document.querySelector('input[name="locationMode"]:checked').value;
  if ((locationMode === "separate" || locationMode === "both") && !locationColSel.value){
    statusEl.textContent = "Para analizar localidades separadas o ambas, elegí una columna de localidad/ambiente."; return;
  }
  const analysisName = prompt("Nombre del análisis:", "CP_FACTORIAL");
  if (!analysisName || !analysisName.trim()){ statusEl.textContent = "Cancelado: se requiere un nombre de análisis."; return; }

  btnAnalyze.disabled = true; btnParse.disabled = true; btnClear.disabled = true;
  resetProgress(); showProgress(); updateProgress(0,0,0); statusEl.textContent = "Iniciando análisis factorial...";

  const payload = {
    rows: currentRows,
    value_col: valueColSel.value,
    factor_cols: factors,
    primary_factor: primaryFactorSel.value || factors[0],
    secondary_factor: secondaryFactorSel.value || factors[1],
    location_col: locationColSel.value || null,
    location_mode: locationMode,
    group_cols: Array.from(selectedGroupCols),
    alpha: Number(alphaInput.value || 0.05),
    analysis_name: analysisName.trim(),
    include_main_tukey: includeMainTukey.checked,
    include_interaction_tukey: includeInteractionTukey.checked
  };

  try{
    const res = await fetch(`${API_BASE}/analyze`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload) });
    if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
    const {job_id} = await res.json();
    const poll = setInterval(async () => {
      try{
        const s = await fetch(`${API_BASE}/status/${job_id}`);
        if (!s.ok) throw new Error(`No se pudo consultar estado. HTTP ${s.status}`);
        const data = await s.json();
        updateProgress(Number(data.progress || 0), Number(data.current || 0), Number(data.total || 0));
        if (data.status === "done"){
          clearInterval(poll); progressBar.style.width = "100%"; progressText.textContent = "Análisis finalizado. Descargando archivo...";
          const file = await fetch(`${API_BASE}/download/${job_id}`);
          if (!file.ok) throw new Error(`No se pudo descargar. HTTP ${file.status}`);
          const blob = await file.blob(); const url = URL.createObjectURL(blob);
          const safe = analysisName.trim().replace(/[^\w \-]/g,"_").trim() || "CP_FACTORIAL";
          const a = document.createElement("a"); a.href = url; a.download = `${safe}_factorial_anova_tukey.xlsx`; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
          statusEl.textContent = "Listo. Se descargó el Excel factorial.";
          btnAnalyze.disabled = false; btnParse.disabled = false; btnClear.disabled = false;
        }
        if (data.status === "error"){
          clearInterval(poll); statusEl.textContent = `Error: ${data.error || "falló el análisis."}`; progressText.textContent = "El análisis terminó con error.";
          btnAnalyze.disabled = false; btnParse.disabled = false; btnClear.disabled = false;
        }
      } catch(err){
        clearInterval(poll); console.error(err); statusEl.textContent = "Error consultando el progreso."; progressText.textContent = "No se pudo continuar el seguimiento.";
        btnAnalyze.disabled = false; btnParse.disabled = false; btnClear.disabled = false;
      }
    }, 1000);
  } catch(e){
    console.error(e); statusEl.textContent = "Error al iniciar el análisis en el backend."; progressText.textContent = "No se pudo crear el job.";
    btnAnalyze.disabled = false; btnParse.disabled = false; btnClear.disabled = false;
  }
});

resetProgress();
