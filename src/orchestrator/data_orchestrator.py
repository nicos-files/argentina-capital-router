# src/orchestrator/data_orchestrator.py

import os
import sys
import glob
import json
import argparse
import subprocess
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.execution.curated.daily_consolidator import consolidate_module
import time

# =========================
# Config y rutas
# =========================

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "raw"
PROC_DIR = ROOT_DIR / "data" / "processed"
LOG_DIR = ROOT_DIR / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

STATE_FILE = LOG_DIR / "data_orchestrator_state.json"
EVENT_LOG = LOG_DIR / "data_orchestrator.log.jsonl"
DEFAULT_SUBPROCESS_TIMEOUT_SEC = 300
RAW_VALIDATION_ENV = "ETL_VALIDATE_RAW"
SUBPROCESS_TIMEOUT_ENV = "ETL_SUBPROCESS_TIMEOUT_SEC"

# Guard de variación (desactivado por defecto hasta estabilizar)
ENABLE_PRICE_VARIATION_GUARD = False
PRICE_CHANGE_THRESHOLD_PCT = 0.10

# Globs esperados (Parquet por la refactorización)
EXPECTED_RAW = {
    "alphaV": RAW_DIR / "prices" / "alphaV",
    "prices": RAW_DIR / "prices",
    "fundamentals": RAW_DIR / "fundamentals",
    "sentiment": RAW_DIR / "sentiment"
}

EXPECTED_PROCESSED = {
    "prices": PROC_DIR / "prices",
    "indicators": PROC_DIR / "indicadores", 
    "fundamentals": PROC_DIR / "fundamentals",
    "relevant_sentiment": PROC_DIR / "sentiment"/ "relevant",
    "sentiment": PROC_DIR / "sentiment"
}

# Módulos a ejecutar (usar rutas de módulo, no paths de archivo)
SCRIPTS = {
    # Ingesta
    "alphaV_fetcher": "src.execution.ingest.alphaV_fetcher",
    "fetch_prices": "src.execution.ingest.fetch_prices",
    "ingest_fundamentals": "src.execution.ingest.ingest_fundamentals",
    "ingest_sentiment": "src.execution.ingest.ingest_sentiment",
    # Proceso
    "process_prices": "src.execution.process.process_prices",
    "normalize_prices": "src.execution.process.normalize_prices",
    "process_indicators": "src.execution.process.process_indicators",
    "process_fundamentals": "src.execution.process.process_fundamentals",
    "relevance_filter": "src.execution.process.relevance_filter",
    "process_sentiment": "src.execution.process.process_sentiment",
}

# =========================
# Utils
# =========================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last": {}}

def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def log_event(component: str, level: str, payload: Dict[str, Any]) -> None:
    rec = {"ts": now_iso(), "component": component, "level": level, "payload": payload}
    # a) Consola
    print(f"[{rec['ts']}] {component}: {level} - {json.dumps(payload, ensure_ascii=False)}")
    # b) JSONL
    with open(EVENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

class RawContractError(RuntimeError):
    pass

def _tail_lines(text: str, max_lines: int = 50) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-max_lines:])

def run_script(name: str, module: str, args: Optional[List[str]] = None) -> bool:
    cmd = [sys.executable, "-m", module] + (args or [])
    timeout_sec = int(os.getenv(SUBPROCESS_TIMEOUT_ENV, DEFAULT_SUBPROCESS_TIMEOUT_SEC))
    log_event(name, "STEP_START", {"cmd": " ".join(cmd), "cwd": str(ROOT_DIR), "timeout_sec": timeout_sec})
    start = time.monotonic()
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, cwd=str(ROOT_DIR))
        ok = res.returncode == 0
        elapsed_ms = int((time.monotonic() - start) * 1000)
        details = {"returncode": res.returncode}
        if res.stdout:
            details["stdout_tail"] = _tail_lines(res.stdout)
        if res.stderr:
            details["stderr_tail"] = _tail_lines(res.stderr)
        log_event(name, "STEP_END", {**details, "status": "OK" if ok else "ERROR", "elapsed_ms": elapsed_ms})
        return ok
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log_event(name, "STEP_END", {"status": "ERROR", "reason": "timeout", "elapsed_ms": elapsed_ms})
        raise RuntimeError(f"Step timeout: {name} cmd={' '.join(cmd)}")
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        log_event(name, "STEP_END", {"status": "ERROR", "reason": str(e), "elapsed_ms": elapsed_ms})
        return False

# =========================
# Helpers de archivos y checks
# =========================

def latest_file(base: Path, pattern: str = "*.parquet") -> Optional[Path]:
    if not base.exists():
        print(f" Path base no existe: {base}")
        return None

    files = list(base.rglob(pattern))
    files = [f for f in files if f.exists() and f.stat().st_size > 0]

    if not files:
        print(f" No se encontraron archivos válidos en: {base}")
        return None

    return max(files, key=lambda f: f.stat().st_mtime)


def file_mtime(path: Optional[Path]) -> Optional[float]:
    return path.stat().st_mtime if path and path.exists() else None


def any_new_file_since(base: Path, pattern: str = "*.parquet", last_ts: Optional[float] = None) -> bool:
    files = list(base.rglob(pattern))
    files = [f for f in files if f.stat().st_size > 0]
    if not files:
        return False
    if last_ts is None:
        return True
    return any(f.stat().st_mtime > last_ts for f in files)

def _validate_raw_outputs(step_name: str, expected_bases: List[Path], pattern: str = "*.parquet") -> None:
    if os.getenv(RAW_VALIDATION_ENV) != "1":
        return
    missing: List[str] = []
    found: List[str] = []
    for base in expected_bases:
        if not base.exists():
            missing.append(str(base))
            continue
        matches = [p for p in base.rglob(pattern) if p.is_file()]
        if not matches:
            missing.append(str(base))
            continue
        found.extend([str(p) for p in matches[:5]])
    if missing:
        log_event(step_name, "RAW_CONTRACT_FAIL", {"missing": missing, "found_samples": found})
        raise RawContractError(f"RawContractError: step={step_name} missing={missing}")
    log_event(step_name, "RAW_CONTRACT_OK", {"found_samples": found})

def compare_latest_raw_vs_processed_parquet(raw_base: Path, proc_base: Path) -> Optional[float]:
    raw_file = latest_file(raw_base)
    proc_file = latest_file(proc_base)
    if not raw_file or not proc_file:
        return None
    try:
        df_raw = pd.read_parquet(raw_file)
        df_proc = pd.read_parquet(proc_file)
        if "ticker" not in df_raw.columns or "close" not in df_raw.columns:
            return None
        if "ticker" not in df_proc.columns or "close" not in df_proc.columns:
            return None
        raw_close = df_raw.groupby("ticker")["close"].last()
        proc_close = df_proc.groupby("ticker")["close"].last()
        common = raw_close.index.intersection(proc_close.index)
        if len(common) == 0:
            return None
        base = proc_close[common].mean()
        if base == 0:
            return None
        pct = (raw_close[common].mean() - base) / base * 100.0
        return float(pct)
    except Exception as e:
        log_event("compare_raw_vs_processed", "ERROR", {"error": str(e)})
        return None

# =========================
# Orquestación
# =========================



def orchestrate(forwarded_args: List[str], args,execution_date, execution_hour) -> None:
    state = load_state()

    # ==============
    # INGESTA (siempre se intenta; el proceso decide si hay novedades)
    # ==============
    ingest_steps = [
        ("alphaV_fetcher", SCRIPTS["alphaV_fetcher"], EXPECTED_RAW["alphaV"]),
        ("fetch_prices", SCRIPTS["fetch_prices"], EXPECTED_RAW["prices"]),
        ("ingest_fundamentals", SCRIPTS["ingest_fundamentals"], EXPECTED_RAW["fundamentals"]),
        ("ingest_sentiment", SCRIPTS["ingest_sentiment"], EXPECTED_RAW["sentiment"]),
    ]

    def _run_ingest_step(step_name: str, module: str, expected: List[Path], skip: bool) -> None:
        if skip:
            log_event(step_name, "SKIPPED", {"reason": "flag"})
            return
        if not run_script(step_name, module, forwarded_args):
            log_event(step_name, "WARN", {"reason": "ingest failed; continuing"})
            return
        _validate_raw_outputs(step_name, expected)

    _run_ingest_step("alphaV_fetcher", SCRIPTS["alphaV_fetcher"], [EXPECTED_RAW["alphaV"]], args.skip_alpha)
    _run_ingest_step("fetch_prices", SCRIPTS["fetch_prices"], [EXPECTED_RAW["prices"]], args.skip_fetch_prices)
    _run_ingest_step("ingest_fundamentals", SCRIPTS["ingest_fundamentals"], [EXPECTED_RAW["fundamentals"]], args.skip_fundamentals)
    _run_ingest_step("ingest_sentiment", SCRIPTS["ingest_sentiment"], [EXPECTED_RAW["sentiment"]], args.skip_sentiment)

    # Registrar mtimes de ingesta (no confundir con los de proceso)
    for step_name, _, expect_glob in ingest_steps:
        latest = latest_file(expect_glob)
        state["last"][f"{step_name}_raw_mtime"] = file_mtime(latest) if latest else None
    save_state(state)

    # ==============
    # PROCESO (incremental)
    # ==============
    # 1) Precios e indicadores
    new_prices = any_new_file_since(
        base=EXPECTED_RAW["prices"],
        pattern="*.parquet",
        last_ts=state["last"].get("process_prices_raw_mtime")
    )
    
    market_change_pct = compare_latest_raw_vs_processed_parquet(
        EXPECTED_RAW["prices"],
        EXPECTED_PROCESSED["prices"]
    )
    
    should_process_prices = new_prices or args.force_process_prices
    reason_prices = (
        "forced by flag"
        if args.force_process_prices
        else ("new raw prices detected" if new_prices else "no new raw prices")
    )
    
    if ENABLE_PRICE_VARIATION_GUARD and market_change_pct is not None and not args.force_prices:
        if abs(market_change_pct) < PRICE_CHANGE_THRESHOLD_PCT:
            should_process_prices = False
            reason_prices = f"market change {market_change_pct:.2f}% < threshold {PRICE_CHANGE_THRESHOLD_PCT:.2f}%"
        else:
            reason_prices = f"market change {market_change_pct:.2f}% >= threshold {PRICE_CHANGE_THRESHOLD_PCT:.2f}%"
    
    log_event("process_prices_guard", "DECISION", {"should_process": should_process_prices, "reason": reason_prices})
    
    if should_process_prices:
        if not run_script("process_prices", SCRIPTS["process_prices"], forwarded_args):
            log_event("process_prices", "ABORT", {"reason": "processing failed"})
            sys.exit(1)
        last_raw_prices = latest_file(EXPECTED_RAW["prices"])
        state["last"]["process_prices_raw_mtime"] = file_mtime(last_raw_prices)
        save_state(state)
    
        if not run_script("normalize_prices", SCRIPTS["normalize_prices"], forwarded_args):
            log_event("normalize_prices", "ABORT", {"reason": "processing failed"})
            sys.exit(1)

        if not run_script("process_indicators", SCRIPTS["process_indicators"], forwarded_args):
            log_event("process_indicators", "ABORT", {"reason": "processing failed"})
            sys.exit(1)
    else:
        log_event("process_prices", "SKIPPED", {"reason": reason_prices})
        log_event("process_indicators", "SKIPPED", {"reason": "dependent on prices"})
    
    # 2) Fundamentos
    new_fund = any_new_file_since(
        base=EXPECTED_RAW["fundamentals"],
        pattern="*.parquet",
        last_ts=state["last"].get("process_fundamentals_raw_mtime")
    )
    should_process_fund = new_fund or args.force_fundamentals
    
    if should_process_fund:
        if not run_script("process_fundamentals", SCRIPTS["process_fundamentals"], forwarded_args):
            log_event("process_fundamentals", "ABORT", {"reason": "processing failed"})
            sys.exit(1)
        last_raw_fund = latest_file(EXPECTED_RAW["fundamentals"])
        state["last"]["process_fundamentals_raw_mtime"] = file_mtime(last_raw_fund)
        save_state(state)
    else:
        log_event("process_fundamentals", "SKIPPED", {"reason": "no new fundamentals raw files"})
    
    # 3) Sentimiento (relevance_filter siempre antes de process_sentiment)
    
    # Paso 1: decidir si correr relevance_filter
    new_senti = any_new_file_since(
        base=EXPECTED_RAW["sentiment"],
        pattern="*.parquet",
        last_ts=state["last"].get("relevance_filter_raw_mtime")
    )
    should_run_filter = new_senti or args.force_relevance
    if args.skip_relevance:
        should_run_filter = False

    if should_run_filter:
        if not run_script("relevance_filter", SCRIPTS["relevance_filter"], forwarded_args):
            log_event("relevance_filter", "ABORT", {"reason": "processing failed"})
            sys.exit(1)
        last_raw_senti = latest_file(EXPECTED_RAW["sentiment"])
        state["last"]["relevance_filter_raw_mtime"] = file_mtime(last_raw_senti)
        save_state(state)
    else:
        reason = "flag" if args.skip_relevance else "no new sentiment raw files"
        log_event("relevance_filter", "SKIPPED", {"reason": reason})
    
    # Paso 2: decidir si correr process_sentiment (basado en archivos relevantes)
    new_relevant = any_new_file_since(
        base=EXPECTED_PROCESSED["sentiment"],
        pattern="*.parquet",
        last_ts=state["last"].get("process_sentiment_raw_mtime")
    )
    should_process_senti = new_relevant or args.force_sentiment
    if args.skip_sentiment:
        should_process_senti = False
    reason_senti = (
        "forced by flag"
        if args.force_sentiment
        else ("new relevant sentiment detected" if new_relevant else "no new relevant sentiment")
    )
    
    log_event("process_sentiment_guard", "DECISION", {"should_process": should_process_senti, "reason": reason_senti})
    
    if should_process_senti:
        if not run_script("process_sentiment", SCRIPTS["process_sentiment"], forwarded_args):
            log_event("process_sentiment", "ABORT", {"reason": "processing failed"})
            sys.exit(1)
        last_relevant_file = latest_file(EXPECTED_PROCESSED["sentiment"])
        state["last"]["process_sentiment_raw_mtime"] = file_mtime(last_relevant_file)
        save_state(state)
    else:
        log_event("process_sentiment", "SKIPPED", {"reason": reason_senti})



    # Resumen data_ready
    data_ready = {
        "timestamp": now_iso(),
        "prices_updated": bool(should_process_prices),
        "execution_date": execution_date.strftime("%Y-%m-%d"),
        "execution_hour": str(execution_hour),
        "fundamentals_updated": bool(should_process_fund),
        "sentiment_updated": bool(should_process_senti),
    }
    with open(os.path.join(LOG_DIR, "data_ready.json"), "w", encoding="utf-8") as f:
        json.dump(data_ready, f, indent=2)

    log_event("data_orchestrator", "DONE", {"note": "ingest + process completed incrementally"})
    
    MODULOS = ["prices", "fundamentals", "sentiment", "indicadores", "features"]
    print("\nIniciando consolidación diaria por módulo...")
    for modulo in MODULOS:
        try:
            consolidate_module(modulo, execution_date,execution_hour)
        except Exception as e:
            print(f" Error consolidando módulo {modulo}: {e}")


# =========================
# Llamados desde otros modulos
# # =========================

def run_etl_pipeline(
    date: str = None,
    hour: str = None,
    skip_flags: Dict[str, bool] = None,
    force_flags: Dict[str, bool] = None
    ):
    from src.utils.execution_context import get_execution_date, get_execution_hour

    execution_date = get_execution_date(date)
    execution_hour = get_execution_hour(hour)

    forwarded_args = [f"--date={execution_date.strftime('%Y-%m-%d')}", f"--hour={execution_hour}"]

    class Args:
        pass

    args = Args()
    args.date = date
    args.hour = hour
    args.skip_alpha = skip_flags.get("alpha", False) if skip_flags else False
    args.skip_fetch_prices = skip_flags.get("fetch_prices", False)
    args.skip_fundamentals = skip_flags.get("fundamentals", False) if skip_flags else False
    args.skip_relevance = skip_flags.get("relevance", False) if skip_flags else False
    args.skip_sentiment = skip_flags.get("sentiment", False) if skip_flags else False

    args.force_fetch_prices = force_flags.get("fetch_prices", False)
    args.force_process_prices = force_flags.get("process_prices", False)
    args.force_fundamentals = force_flags.get("fundamentals", False) if force_flags else False
    args.force_relevance = force_flags.get("relevance", False) if force_flags else False
    args.force_sentiment = force_flags.get("sentiment", False) if force_flags else False

    orchestrate(forwarded_args, args, execution_date, execution_hour)



# =========================
# Entry point
# =========================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="HHMM")
    parser.add_argument("--skip-alpha", action="store_true")
    parser.add_argument("--skip-fetch_prices", action="store_true", help="Saltear ingesta de precios") 
    parser.add_argument("--skip-fundamentals", action="store_true")
    parser.add_argument("--skip-relevance", action="store_true")
    parser.add_argument("--skip-sentiment", action="store_true")
    parser.add_argument("--force-process_prices", action="store_true", help="Forzar procesamiento de precios incluso sin nuevos datos")
    parser.add_argument("--skip-process_prices", action="store_true", help="Saltear procesamiento de precios")            
    parser.add_argument("--force-fundamentals", action="store_true")
    parser.add_argument("--force-relevance", action="store_true")
    parser.add_argument("--force-sentiment", action="store_true")
    args = parser.parse_args()

    from src.utils.execution_context import get_execution_date, get_execution_hour
    execution_date = get_execution_date(args.date)
    execution_hour = get_execution_hour(args.hour)

    forwarded_args = [f"--date={execution_date.strftime('%Y-%m-%d')}", f"--hour={execution_hour}"]

    orchestrate(forwarded_args, args, execution_date, execution_hour)



if __name__ == "__main__":
    main()
