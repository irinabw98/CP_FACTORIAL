from __future__ import annotations

import io
import threading
import time
from itertools import combinations
from typing import Any, Dict, List, Tuple
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import BackgroundTasks, Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from statsmodels.formula.api import ols
from statsmodels.stats.anova import anova_lm
from statsmodels.stats.multicomp import pairwise_tukeyhsd

app = FastAPI(title="CP_FACTORIAL · ANOVA factorial + Tukey API")

ALLOWED_ORIGINS = [
    "https://irinabw98.github.io",
    "https://irinabw98.github.io/CP_FACTORIAL",
    "https://irinabw98.github.io/CP_FACTORIAL/",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
    "http://127.0.0.1:5501",
    "http://localhost:5501",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

jobs: Dict[str, Dict[str, Any]] = {}
jobs_lock = threading.Lock()

MAX_ROWS = 100000
MAX_GROUPS = 5000
MAX_LEVELS_FOR_TUKEY = 120
JOB_TTL_SECONDS = 60 * 60 * 6


def _now_ts() -> float:
    return time.time()


def _set_job(job_id: str, **kwargs) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(kwargs)
            jobs[job_id]["updated_at"] = _now_ts()


def _cleanup_old_jobs() -> None:
    cutoff = _now_ts() - JOB_TTL_SECONDS
    with jobs_lock:
        for job_id in [j for j, p in jobs.items() if float(p.get("updated_at", 0)) < cutoff]:
            del jobs[job_id]


def _safe_sheet_name(name: str) -> str:
    bad = ['\\', '/', '*', '?', ':', '[', ']']
    out = str(name)
    for ch in bad:
        out = out.replace(ch, '_')
    return out[:31] or 'sheet'


def _to_numeric_series_strong(s: pd.Series) -> pd.Series:
    s2 = s.astype(str).str.strip()
    s2 = s2.str.replace(r"[^0-9,\.\-]", "", regex=True)

    def _one(x: str):
        x = str(x).strip()
        if x in ("", "-", ".", ","):
            return np.nan
        if "," in x and "." in x:
            if x.rfind(",") > x.rfind("."):
                x = x.replace(".", "").replace(",", ".")
            else:
                x = x.replace(",", "")
        elif "," in x:
            x = x.replace(".", "").replace(",", ".")
        try:
            return float(x)
        except Exception:
            return np.nan

    return s2.apply(_one)


def _make_key(row: pd.Series, cols: List[str]) -> str:
    if not cols:
        return "ALL"
    parts = []
    for c in cols:
        v = row.get(c, "")
        if pd.isna(v):
            v = ""
        parts.append(f"{c}={v}")
    return " | ".join(parts)


def _combo_label(df: pd.DataFrame, factors: List[str], sep: str = " | ") -> pd.Series:
    if not factors:
        return pd.Series(["ALL"] * len(df), index=df.index)
    return df[factors].astype(str).agg(sep.join, axis=1)


def _formula(value_col_num: str, factors: List[str]) -> str:
    rhs = " * ".join([f"C(Q('{c}'))" for c in factors])
    return f"Q('{value_col_num}') ~ {rhs}"


def _compact_letter_display(pairs_df: pd.DataFrame, treatments: List[str]) -> Dict[str, str]:
    tset = list(treatments)
    idx = {t: i for i, t in enumerate(tset)}
    n = len(tset)
    nodiff = np.eye(n, dtype=bool)

    for _, r in pairs_df.iterrows():
        g1, g2 = str(r["group1"]), str(r["group2"])
        rej = bool(r.get("reject", False))
        if g1 in idx and g2 in idx:
            i, j = idx[g1], idx[g2]
            nodiff[i, j] = not rej
            nodiff[j, i] = not rej

    remaining = set(tset)
    letters = [chr(c) for c in range(ord("a"), ord("z") + 1)]
    letter_groups: List[Tuple[str, List[str]]] = []
    letter_i = 0

    while remaining:
        if letter_i < 26:
            letter = letters[letter_i]
        else:
            letter = letters[(letter_i // 26) - 1] + letters[letter_i % 26]
        rem_list = list(remaining)
        seed = max(rem_list, key=lambda t: sum(nodiff[idx[t], idx[x]] for x in rem_list))
        group = [seed]
        for cand in rem_list:
            if cand == seed:
                continue
            if all(nodiff[idx[cand], idx[m]] for m in group):
                group.append(cand)
        letter_groups.append((letter, group))
        for t in group:
            remaining.discard(t)
        letter_i += 1

    out = {t: "" for t in tset}
    for letter, members in letter_groups:
        for t in tset:
            if all(nodiff[idx[t], idx[m]] for m in members):
                out[t] += letter
    return {t: (v or "a") for t, v in out.items()}


def _relabel_letters_by_mean(summary_df: pd.DataFrame, letters_map: Dict[str, str], label_col: str) -> Dict[str, str]:
    if summary_df.empty:
        return letters_map
    df = summary_df[[label_col, "mean"]].copy()
    df[label_col] = df[label_col].astype(str)
    df = df.sort_values("mean", ascending=False)
    seen: List[str] = []
    for _, row in df.iterrows():
        for ch in str(letters_map.get(row[label_col], "")).lower():
            if ch not in seen:
                seen.append(ch)
    symbols = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
    remap = {}
    for i, old in enumerate(seen):
        remap[old] = symbols[i] if i < 26 else symbols[(i // 26) - 1] + symbols[i % 26]
    out = {}
    for trt, raw in letters_map.items():
        rebuilt = []
        for ch in str(raw).lower():
            if ch in remap and remap[ch] not in rebuilt:
                rebuilt.append(remap[ch])
        out[str(trt)] = "".join(rebuilt) or "A"
    return out


def _run_tukey(df: pd.DataFrame, value_col_num: str, label_col: str, alpha: float) -> pd.DataFrame:
    tdf = df[[value_col_num, label_col]].dropna().copy()
    tdf[label_col] = tdf[label_col].astype(str)
    levels = sorted(tdf[label_col].unique().tolist())
    if len(levels) < 2:
        raise ValueError(f"{label_col}: menos de 2 niveles para Tukey.")
    if len(levels) > MAX_LEVELS_FOR_TUKEY:
        raise ValueError(f"{label_col}: demasiados niveles para Tukey ({len(levels)}). Máximo {MAX_LEVELS_FOR_TUKEY}.")
    tuk = pairwise_tukeyhsd(endog=tdf[value_col_num].values, groups=tdf[label_col].values, alpha=alpha)
    out = pd.DataFrame(tuk._results_table.data[1:], columns=tuk._results_table.data[0])
    out["reject"] = out["reject"].astype(bool)
    for c in ["meandiff", "p-adj", "lower", "upper"]:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.rename(columns={"p-adj": "p_adj"})
    out["label_col"] = label_col
    return out


def _summary_for(df: pd.DataFrame, value_col_num: str, by_cols: List[str], label_col: str | None = None) -> pd.DataFrame:
    if label_col:
        by = by_cols + [label_col]
    else:
        by = by_cols
    if not by:
        return pd.DataFrame()
    s = df.groupby(by, dropna=False)[value_col_num].agg(n="count", mean="mean", sd="std", min="min", max="max").reset_index()
    return s


def _interpretation(anova_df: pd.DataFrame, alpha: float) -> pd.DataFrame:
    rows = []
    if anova_df.empty:
        return pd.DataFrame(columns=["analysis_scope", "group_key", "message"])
    for (scope, gkey), sub in anova_df.groupby(["analysis_scope", "group_key"], dropna=False):
        sig = sub[(pd.to_numeric(sub.get("pvalue"), errors="coerce") < alpha) & (sub.get("effect", "Residual") != "Residual")]
        if sig.empty:
            msg = f"No se detectaron efectos significativos con alpha={alpha}."
        else:
            effects = ", ".join(sig.sort_values("pvalue")["effect"].astype(str).tolist())
            msg = f"Efectos significativos con alpha={alpha}: {effects}."
        rows.append({"analysis_scope": scope, "group_key": gkey, "message": msg})
    return pd.DataFrame(rows)


def _run_factorial_one_group(
    gdf: pd.DataFrame,
    value_col_num: str,
    model_factors: List[str],
    alpha: float,
    include_main_tukey: bool,
    include_interaction_tukey: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = gdf[[value_col_num] + model_factors].copy().dropna(subset=[value_col_num])
    for c in model_factors:
        work[c] = work[c].astype(str)
    work = work.dropna(subset=model_factors)

    for c in model_factors:
        if work[c].nunique(dropna=False) < 2:
            raise ValueError(f"El factor '{c}' tiene menos de 2 niveles en este grupo.")

    if len(work) <= len(model_factors) + 1:
        raise ValueError("Datos insuficientes para ajustar el modelo factorial.")

    formula = _formula(value_col_num, model_factors)
    model = ols(formula, data=work).fit()
    an = anova_lm(model, typ=2).reset_index().rename(columns={"index": "effect", "PR(>F)": "pvalue", "sum_sq": "sum_sq"})
    an["effect"] = an["effect"].astype(str).str.replace("C\(Q\('", "", regex=True).str.replace("'\)\)", "", regex=True).str.replace(":", " x ", regex=False)
    if "F" not in an.columns:
        an["F"] = np.nan
    if "pvalue" not in an.columns:
        an["pvalue"] = np.nan
    an["model_formula"] = formula
    an["r2"] = float(model.rsquared) if hasattr(model, "rsquared") else np.nan
    an["adj_r2"] = float(model.rsquared_adj) if hasattr(model, "rsquared_adj") else np.nan
    an["rmse"] = float(np.sqrt(model.mse_resid)) if hasattr(model, "mse_resid") else np.nan

    means = _summary_for(work, value_col_num, model_factors)
    means["factorial_label"] = _combo_label(means, model_factors)

    tukey_rows = []
    letters_rows = []

    if include_main_tukey:
        for f in model_factors:
            try:
                t = _run_tukey(work, value_col_num, f, alpha)
                summ = _summary_for(work, value_col_num, [f])
                levels = summ[f].astype(str).tolist()
                t_letters = _compact_letter_display(t.rename(columns={"p_adj": "p-adj"}), levels)
                t_letters = _relabel_letters_by_mean(summ.rename(columns={f: "label"})[["label", "mean"]], t_letters, "label")
                summ["label_col"] = f
                summ["label"] = summ[f].astype(str)
                summ["tukey_letters"] = summ["label"].map(t_letters).fillna("A")
                letters_rows.append(summ[["label_col", "label", "n", "mean", "sd", "tukey_letters"]])
                tukey_rows.append(t)
            except Exception as e:
                tukey_rows.append(pd.DataFrame([{"label_col": f, "error": str(e)}]))

    if include_interaction_tukey:
        combo_col = "factorial_combination"
        work[combo_col] = _combo_label(work, model_factors)
        try:
            t = _run_tukey(work, value_col_num, combo_col, alpha)
            summ = _summary_for(work, value_col_num, [combo_col])
            levels = summ[combo_col].astype(str).tolist()
            t_letters = _compact_letter_display(t.rename(columns={"p_adj": "p-adj"}), levels)
            t_letters = _relabel_letters_by_mean(summ.rename(columns={combo_col: "label"})[["label", "mean"]], t_letters, "label")
            summ["label_col"] = combo_col
            summ["label"] = summ[combo_col].astype(str)
            summ["tukey_letters"] = summ["label"].map(t_letters).fillna("A")
            letters_rows.append(summ[["label_col", "label", "n", "mean", "sd", "tukey_letters"]])
            t["factor_set"] = " x ".join(model_factors)
            tukey_rows.append(t)
        except Exception as e:
            tukey_rows.append(pd.DataFrame([{"label_col": combo_col, "factor_set": " x ".join(model_factors), "error": str(e)}]))

    tukey_df = pd.concat(tukey_rows, ignore_index=True, sort=False) if tukey_rows else pd.DataFrame()
    letters_df = pd.concat(letters_rows, ignore_index=True, sort=False) if letters_rows else pd.DataFrame()

    diag = pd.DataFrame({
        "row_index": work.index,
        "fitted": model.fittedvalues,
        "residual": model.resid,
    })

    return an, means, tukey_df, letters_df, diag


def _analysis_groups(df: pd.DataFrame, group_cols: List[str]) -> List[Tuple[Dict[str, Any], pd.DataFrame]]:
    if not group_cols:
        return [({}, df)]
    grouped = list(df.groupby(group_cols, dropna=False, sort=False))
    out = []
    for keys, gdf in grouped:
        if not isinstance(keys, tuple):
            keys = (keys,)
        out.append(({c: v for c, v in zip(group_cols, keys)}, gdf))
    return out


def _run_analysis_job(job_id: str, payload: Dict[str, Any]) -> None:
    try:
        rows = payload.get("rows")
        value_col = payload.get("value_col")
        factor_cols = list(payload.get("factor_cols") or [])
        primary_factor = payload.get("primary_factor")
        secondary_factor = payload.get("secondary_factor")
        location_col = payload.get("location_col")
        location_mode = payload.get("location_mode", "separate")
        group_cols = list(payload.get("group_cols") or [])
        alpha = float(payload.get("alpha", 0.05))
        analysis_name = str(payload.get("analysis_name", "CP_FACTORIAL")).strip()
        include_main_tukey = bool(payload.get("include_main_tukey", True))
        include_interaction_tukey = bool(payload.get("include_interaction_tukey", True))

        if not isinstance(rows, list) or not rows:
            raise ValueError("rows vacío o inválido.")
        if len(rows) > MAX_ROWS:
            raise ValueError(f"Dataset demasiado grande. Máximo permitido: {MAX_ROWS} filas.")
        if not value_col:
            raise ValueError("value_col es requerido.")
        if len(factor_cols) < 2:
            raise ValueError("Se requieren al menos 2 factores.")
        if location_mode not in {"separate", "combined", "both"}:
            raise ValueError("location_mode inválido.")

        df = pd.DataFrame(rows)
        needed = [value_col] + factor_cols + group_cols
        if location_col:
            needed.append(location_col)
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise ValueError(f"Faltan columnas requeridas: {missing}")

        _set_job(job_id, progress=2, message="Convirtiendo variable respuesta a numérica...")
        df["response_value_num"] = _to_numeric_series_strong(df[value_col])
        df = df.dropna(subset=["response_value_num"]).copy()
        if df.empty:
            raise ValueError(f"No quedaron filas con valores numéricos en '{value_col}'.")

        df["analysis_name"] = analysis_name
        for c in factor_cols + group_cols + ([location_col] if location_col else []):
            df[c] = df[c].astype(str)

        scopes = []
        if location_mode in {"separate", "both"}:
            if not location_col:
                raise ValueError("Para modo separado o ambos se requiere location_col.")
            scopes.append(("localidades_separadas", group_cols + [location_col], factor_cols))
        if location_mode in {"combined", "both"}:
            combined_factors = list(factor_cols)
            if location_col and location_col not in combined_factors:
                combined_factors = [location_col] + combined_factors
            scopes.append(("localidades_juntas", group_cols, combined_factors))

        planned = []
        for scope_name, grouping, model_factors in scopes:
            for key_dict, gdf in _analysis_groups(df, grouping):
                planned.append((scope_name, grouping, model_factors, key_dict, gdf))
        if len(planned) > MAX_GROUPS:
            raise ValueError(f"Demasiados análisis ({len(planned)}). Máximo permitido: {MAX_GROUPS}.")

        _set_job(job_id, status="running", total=len(planned), current=0, progress=5, message="Iniciando modelos factoriales...")

        anovas, means_list, tukeys, letters, diagnostics, warnings = [], [], [], [], [], []

        for i, (scope_name, grouping, model_factors, key_dict, gdf) in enumerate(planned, start=1):
            group_key = _make_key(pd.Series(key_dict), grouping)
            try:
                an, means, tukey, letter, diag = _run_factorial_one_group(
                    gdf=gdf,
                    value_col_num="response_value_num",
                    model_factors=model_factors,
                    alpha=alpha,
                    include_main_tukey=include_main_tukey,
                    include_interaction_tukey=include_interaction_tukey,
                )
                for frame in [an, means, tukey, letter, diag]:
                    frame["analysis_scope"] = scope_name
                    frame["group_key"] = group_key
                    for col, val in key_dict.items():
                        frame[col] = val
                    frame["model_factors"] = " x ".join(model_factors)
                anovas.append(an)
                means_list.append(means)
                tukeys.append(tukey)
                letters.append(letter)
                diagnostics.append(diag)
            except Exception as e:
                warnings.append({"analysis_scope": scope_name, "group_key": group_key, "error": str(e), "model_factors": " x ".join(model_factors)})

            progress = int(5 + (i / max(len(planned), 1)) * 88)
            _set_job(job_id, current=i, total=len(planned), progress=min(progress, 96), message=f"Procesando {i}/{len(planned)} análisis...")

        anova_df = pd.concat(anovas, ignore_index=True, sort=False) if anovas else pd.DataFrame()
        means_df = pd.concat(means_list, ignore_index=True, sort=False) if means_list else pd.DataFrame()
        tukey_df = pd.concat(tukeys, ignore_index=True, sort=False) if tukeys else pd.DataFrame()
        letters_df = pd.concat(letters, ignore_index=True, sort=False) if letters else pd.DataFrame()
        diag_df = pd.concat(diagnostics, ignore_index=True, sort=False) if diagnostics else pd.DataFrame()
        warnings_df = pd.DataFrame(warnings)
        interp_df = _interpretation(anova_df, alpha)

        _set_job(job_id, progress=97, message="Armando Excel...")
        out = _build_excel(df, anova_df, means_df, tukey_df, letters_df, diag_df, interp_df, warnings_df, payload)

        safe = "".join(ch if ch.isalnum() or ch in (" ", "_", "-") else "_" for ch in analysis_name).strip() or "CP_FACTORIAL"
        _set_job(job_id, status="done", progress=100, message="Análisis finalizado.", result_bytes=out.getvalue(), filename=f"{safe}_factorial_anova_tukey.xlsx")

    except Exception as e:
        _set_job(job_id, status="error", progress=100, message="El análisis terminó con error.", error=str(e))


def _build_excel(
    df: pd.DataFrame,
    anova_df: pd.DataFrame,
    means_df: pd.DataFrame,
    tukey_df: pd.DataFrame,
    letters_df: pd.DataFrame,
    diag_df: pd.DataFrame,
    interp_df: pd.DataFrame,
    warnings_df: pd.DataFrame,
    payload: Dict[str, Any],
) -> io.BytesIO:
    output = io.BytesIO()
    meta = pd.DataFrame([
        {"campo": "analysis_name", "valor": payload.get("analysis_name")},
        {"campo": "value_col", "valor": payload.get("value_col")},
        {"campo": "factor_cols", "valor": ", ".join(payload.get("factor_cols") or [])},
        {"campo": "primary_factor", "valor": payload.get("primary_factor")},
        {"campo": "secondary_factor", "valor": payload.get("secondary_factor")},
        {"campo": "location_col", "valor": payload.get("location_col")},
        {"campo": "location_mode", "valor": payload.get("location_mode")},
        {"campo": "group_cols", "valor": ", ".join(payload.get("group_cols") or [])},
        {"campo": "alpha", "valor": payload.get("alpha")},
    ])

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="input_enriched")
        meta.to_excel(writer, index=False, sheet_name="config")
        if not anova_df.empty:
            anova_df.to_excel(writer, index=False, sheet_name="anova_factorial")
        if not means_df.empty:
            means_df.to_excel(writer, index=False, sheet_name="means_factorial")
        if not letters_df.empty:
            letters_df.to_excel(writer, index=False, sheet_name="tukey_letters")
        if not tukey_df.empty:
            tukey_df.to_excel(writer, index=False, sheet_name="tukey_pairs")
        if not interp_df.empty:
            interp_df.to_excel(writer, index=False, sheet_name="interpretacion")
        if not warnings_df.empty:
            warnings_df.to_excel(writer, index=False, sheet_name="warnings")
        if not diag_df.empty:
            diag_df.to_excel(writer, index=False, sheet_name="diagnostics")
    output.seek(0)
    return output


@app.post("/analyze")
def analyze(background_tasks: BackgroundTasks, payload: Dict[str, Any] = Body(...)):
    _cleanup_old_jobs()
    job_id = str(uuid4())
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "status": "running",
            "progress": 0,
            "current": 0,
            "total": 0,
            "message": "Job creado.",
            "error": None,
            "result_bytes": None,
            "filename": None,
            "created_at": _now_ts(),
            "updated_at": _now_ts(),
        }
    background_tasks.add_task(_run_analysis_job, job_id, payload)
    return {"job_id": job_id}


@app.get("/status/{job_id}")
def status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job no encontrado")
        return {k: job.get(k) for k in ["job_id", "status", "progress", "current", "total", "message", "error", "filename"]}


@app.get("/download/{job_id}")
def download(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job no encontrado")
        if job["status"] != "done":
            raise HTTPException(status_code=400, detail="El archivo todavía no está listo.")
        result_bytes = job.get("result_bytes")
        filename = job.get("filename") or "CP_FACTORIAL_factorial_anova_tukey.xlsx"
    if result_bytes is None:
        raise HTTPException(status_code=500, detail="No se encontró el archivo generado.")
    return StreamingResponse(
        io.BytesIO(result_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version():
    return {"version": "2026-05-20-cp-factorial-v1"}
