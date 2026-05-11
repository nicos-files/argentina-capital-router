
    # src/agents/orchestrator_agent.py
from pathlib import Path
import json
import time
import traceback
import pandas as pd
from typing import Dict, Any, Optional, List
import sys
import subprocess
from pathlib import Path
from src.orchestrator.data_orchestrator import run_etl_pipeline
from src.utils.llm_logger import log_llm_interaction

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
PROC_DIR = DATA_DIR / "processed"
RESULTS_DIR = DATA_DIR / "results"
SIMULATIONS_DIR = ROOT / "simulations"

PATHS = {
    "signals": RESULTS_DIR / "strategy_signals.csv",
    "equity": SIMULATIONS_DIR / "equity_curve.csv",
    "sentiment": PROC_DIR / "sentiment" / "sentiment_summary.json",
    "final_decision": RESULTS_DIR / "final_decision.json",
}

MIN_SIGNALS = 3
RETRY_N = 1
RETRY_SLEEP = 5


class OrchestratorDecisionAgent:
    def __init__(self, args):
        self.args = args
        self.threshold = args.threshold
        self.max_positions = args.max_positions
        self.lt_agent = None
        self.intra_agent = None
        self.manager = None
        self.agents = None
        self.user_proxy = None


    # ---------- Entry point ----------
    def run_day(
            self,
            run_etl: bool = True,
            date: Optional[str] = None,
            hour: Optional[str] = None,
            skip_flags: Optional[Dict[str, bool]] = None,
            force_flags: Optional[Dict[str, bool]] = None,
            only_agent: bool = False,
            accumulate: bool = True
        ) -> Dict[str, Any]:

        try:
            
            self._log_info("start", {"msg": "iniciando orquestación diaria", "run_etl": run_etl})
            skip_flags = skip_flags or {}
            force_flags = force_flags or {}
            # 1) ETL opcional
            if run_etl:
                self._log_info("etl", "Ejecutando ETL completo")
                self._run_etl_with_retries(date=date, hour=hour, skip_flags=skip_flags, force_flags=force_flags)
            elif only_agent:
                self._log_info("etl", "ETL/modelado salteado (modo only_agent)")
            else:
                self._log_info("etl", "ETL salteado por configuración")

            # 2) Pipeline de modelado
            if not only_agent:
                self._log_info("pipeline", "Ejecutando feature engineering, entrenamiento y generación de señales")
                self._run_modeling_pipeline()

            # 3) Construcción y validación del contexto
            context = self._build_context()
            self._validate_context(context)

            # 4) Decisión de agentes
            self._ensure_agents()
            self._log_info("decision", "Ejecutando lógica de decisión de agentes")
            lt_decision = self.lt_agent.decide(context)
            self.lt_agent.save_decision(lt_decision)
            self.lt_agent.export_decision(lt_decision, tipo="long_term", accumulate=accumulate)


            intra_decision = self.intra_agent.decide(context)
            self.intra_agent.save_decision(intra_decision)
            self.intra_agent.export_decision(intra_decision, tipo="intraday", accumulate=accumulate)

            decision = {
                "long_term": lt_decision.get("long_term", []),
                "intraday": intra_decision.get("intraday", []),
            }
            
            # 5) Post-procesamiento y persistencia
            decision = self._sanitize_decision(decision)
            self._save_decision(decision)
            self._log_day_summary(decision, context)

            self._log_info("end", "orquestación diaria finalizada")
            return decision
            
        except Exception as e:
            err = {"error": str(e), "trace": traceback.format_exc()}
            self._log_info("error", err)
            raise
    # ---------- Pipeline de modelado ----------
    def _run_modeling_pipeline(self):
        def run_script(name: str, module: str):
            print(f"[PIPELINE] → Iniciando módulo: {name}")
            cmd = [sys.executable, "-m", module]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[ERROR] → {name} falló:\n{res.stderr}")
                raise RuntimeError(f"{name} falló con código {res.returncode}")
            else:
                print(f"[OK] → {name} completado:\n{res.stdout[-300:]}")

        run_script("feature_engineering", "src.pipeline.feature_engineering")
        run_script("train_model", "src.pipeline.train_model")
        run_script("generate_signals", "src.pipeline.generate_signals")
        run_script("backtest_strategy", "src.backtest.backtest_strategy")


    # ---------- Helpers ----------
    def _run_etl_with_retries(
        self,
        date: Optional[str],
        hour: Optional[str],
        skip_flags: Optional[Dict[str, bool]],
        force_flags: Optional[Dict[str, bool]],
    ):
        for i in range(RETRY_N + 1):
            try:
                run_etl_pipeline(date=date, hour=hour, skip_flags=skip_flags, force_flags=force_flags)
                return
            except Exception as e:
                self._log_info("warning", f"ETL intento {i+1} falló: {e}")
                if i < RETRY_N:
                    time.sleep(RETRY_SLEEP)
                else:
                    raise

    def _ensure_agents(self):
        if self.lt_agent is None or self.intra_agent is None or self.manager is None:
            from src.autogen.orchestrator import create_orchestrator
            from src.agents.long_term_agent import LongTermDecisionAgent
            from src.agents.intraday_agent import IntradayDecisionAgent

            self.lt_agent = LongTermDecisionAgent()
            self.intra_agent = IntradayDecisionAgent()
            self.manager, self.agents, self.user_proxy = create_orchestrator()

    def _build_context(self) -> Dict[str, Any]:
        signals = self._load_signals(PATHS["signals"])
        backtest = self._load_backtest(PATHS["equity"])
        sentiment = self._load_sentiment(PATHS["sentiment"])

        params = {
            "threshold": self.threshold,
            "max_positions": self.max_positions,
            "min_ret_pct": self.args.min_ret_pct,
            "max_vol_pct": self.args.max_vol_pct,
            "min_liquidez": self.args.min_liquidez,
            "costs": {"commission_side": 0.0005, "slippage_side": 0.0003},
            "risk": {"stop_loss": 0.05, "take_profit": 0.07},
        }
        return {"signals": signals, "backtest": backtest, "sentiment": sentiment, **params}


    def _validate_context(self, ctx: Dict[str, Any]):
        if not ctx["signals"]:
            raise ValueError("No hay señales generadas (strategy_signals.csv vacío o inexistente)")
        if len(ctx["signals"]) < MIN_SIGNALS:
            self._log_info("warning", f"pocas señales: {len(ctx['signals'])} < {MIN_SIGNALS}")
        if not ctx["backtest"]:
            self._log_info("warning", "no se encontró equity_curve.csv, se continuará con métricas vacías")

    def _sanitize_decision(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        def clean_list(items: List[Dict[str, Any]], tipo: str) -> List[Dict[str, Any]]:
            out = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                t = it.get("ticker")
                j = it.get("justificacion")
                if t and isinstance(t, str):
                    out.append({
                        "ticker": t.upper().strip(),
                        "justificacion": str(j).strip() if j is not None else ""
                    })
            if not out:
                print(f"No se seleccionaron activos válidos en la decisión {tipo}.")
            return out

        decision["intraday"] = clean_list(decision.get("intraday", []), "intradía")
        decision["long_term"] = clean_list(decision.get("long_term", []), "largo plazo")
        return decision


    def _save_decision(self, decision: Dict[str, Any]):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        with PATHS["final_decision"].open("w", encoding="utf-8") as f:
            json.dump(decision, f, ensure_ascii=False, indent=2)

    # ---------- Loaders ----------
    def _load_signals(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        df = pd.read_csv(path)
        keep = [
            "ticker", "score", "expected_return_pct", "investment_type",
            "volatilidad_pct", "sector", "liquidez", "sentimiento"
        ]
        for col in keep:
            if col not in df.columns:
                df[col] = None
        df["ticker"] = df["ticker"].astype(str).str.upper()
        return df[keep].to_dict(orient="records")

    def _load_backtest(self, path: Path) -> Dict[str, float]:
        if not path.exists():
            return {}
        df = pd.read_csv(path)
        if "capital" not in df.columns:
            return {}
        df["ret"] = df["capital"].pct_change().fillna(0)
        return {
            "ret_total": float(df["capital"].iloc[-1] - 1),
            "ret_daily_mean": float(df["ret"].mean()),
            "max_drawdown": float((df["capital"].cummax() - df["capital"]).max() / df["capital"].cummax().max()),
        }

    def _load_sentiment(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # ---------- Logging ----------
    def _log_day_summary(self, decision: Dict[str, Any], ctx: Dict[str, Any]):
        payload = {
            "module": "orchestrator_agent",
            "status": "ok",
            "n_signals": len(ctx.get("signals", [])),
            "ret_total_bt": ctx.get("backtest", {}).get("ret_total"),
            "sentiment_general": (
                ctx.get("sentiment", {}).get("GENERAL", [{}])[0].get("combined_score", 0.0)
                if isinstance(ctx.get("sentiment", {}).get("GENERAL", [{}]), list)
                else 0.0
            ),
            "n_intra": len(decision.get("intraday", [])),
            "n_long": len(decision.get("long_term", [])),

        }
        log_llm_interaction(payload, log_name="orchestrator_agent")

    def _log_info(self, stage: str, msg: Any):
        log_llm_interaction({"module": "orchestrator_agent", "stage": stage, "msg": msg}, log_name="orchestrator_agent")


    def _load_backtest(self, path: Path) -> Dict[str, float]:
        if not path.exists():
            return {}
        df = pd.read_csv(path)
        if "capital" not in df.columns:
            return {}
        df["ret"] = df["capital"].pct_change().fillna(0)
        return {
            "ret_total": float(df["capital"].iloc[-1] - 1),
            "ret_daily_mean": float(df["ret"].mean()),
            "max_drawdown": float((df["capital"].cummax() - df["capital"]).max() / df["capital"].cummax().max()),
        }

    def _load_sentiment(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
