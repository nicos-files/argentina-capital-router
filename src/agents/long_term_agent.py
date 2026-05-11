import os
import json
import pandas as pd
from typing import Dict, Any, List
from autogen import AssistantAgent
from datetime import datetime

SIGNALS_PATH = "data/results/strategy_signals.csv"
DECISIONS_PATH = "data/results/long_term_decision.json"

class LongTermDecisionAgent:
    def __init__(self):
        self.agent = AssistantAgent(
            name="long_term_agent",
            system_message=(
                "Sos un inversor institucional de largo plazo. "
                "Priorizás calidad, estabilidad, crecimiento y riesgo controlado. "
                "Usás señales cuantitativas (score y retorno esperado), volatilidad, liquidez, sector y sentimiento. "
                "Buscás diversificar por sector y evitar concentraciones de riesgo. "
                "Preferís señales con score alto, retorno esperado positivo, volatilidad moderada y buena liquidez."
            ),
            llm_config={
                "model": "gpt-4o",
                "temperature": 0.2,
                "api_key": os.getenv("OPENAI_API_KEY"),
                "max_tokens": 2048
            }
        )

    # Este método se usa para ejecutar el agente de forma autónoma, fuera del orquestador
    def run(self, context: Dict[str, Any]):
        decision = self.decide(context)
        self.save_decision(decision)
        return decision


    def load_signals(self) -> List[Dict[str, Any]]:
        df = pd.read_csv(SIGNALS_PATH)
        return df.to_dict(orient="records")

    def prepare_context(
        self,
        signals: List[Dict[str, Any]],
        max_positions: int,
        min_score: float,
        min_ret_pct: float,
        max_vol_pct: float,
        min_liquidez: int
    ) -> Dict[str, Any]:
        return {
            "signals": signals,
            "max_positions": max_positions,
            "min_score": min_score,
            "min_ret_pct": min_ret_pct,
            "max_vol_pct": max_vol_pct,
            "min_liquidez": min_liquidez
        }

    # Este método es el punto de entrada principal cuando el agente es invocado por el orquestador
    def decide(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_prompt(context)
        messages = [{"role": "user", "content": prompt}]
        response = self.agent.generate_reply(messages)
        return self._parse_response(response)

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        raw_signals = context.get("signals", [])
        max_positions = context.get("max_positions", 10)
        min_score = context.get("min_score", 0.7)
        min_ret_pct = context.get("min_ret_pct", 0.5)
        max_vol_pct = context.get("max_vol_pct", 5.0)
        min_liquidez = context.get("min_liquidez", 1_000_000)
    
        # Filtrar señales relevantes y completas
        required_keys = ["ticker", "score", "expected_return_pct", "volatilidad_pct", "sector", "liquidez"]
        signals = [s for s in raw_signals if s.get("investment_type") == "long_term"]
        signals = [s for s in signals if all(k in s for k in required_keys)]
        signals = [s for s in signals if s.get("score", 0) >= min_score]
        signals = sorted(signals, key=lambda x: x.get("score", 0), reverse=True)[:30]
    
        # Si no hay señales válidas, devolver mensaje de terminación
        if not signals:
            print("⚠️ No hay señales válidas para largo plazo. El agente no puede tomar decisiones.")
            return "TERMINATE"
    
        # Construcción del prompt compacto
        prompt = (
            f"Seleccioná hasta {max_positions} activos para una cartera de largo plazo.\n"
            f"Priorizá score alto, retorno esperado positivo (>{min_ret_pct}%), volatilidad baja (<{max_vol_pct}%), "
            f"buena liquidez (>{min_liquidez}) y diversificación sectorial.\n"
            f"Formato de respuesta: {{ \"long_term\": [ {{\"ticker\": \"...\", \"peso_pct\": 0-100, \"justificacion\": \"...\"}}, ... ] }}\n\n"
            f"Señales:\n"
        )
    
        for s in signals:
            t = s.get("ticker", "")
            sc = round(s.get("score", 0), 2)
            ret = round(s.get("expected_return_pct", 0), 2)
            vol = round(s.get("volatilidad_pct", 0), 2)
            sec = s.get("sector", "N/A")
            liq = int(s.get("liquidez", 0)) // 1000  # en miles
    
            prompt += f"{t}: score={sc}, ret%={ret}, vol%={vol}, liq={liq}k, sector={sec}\n"
    
        return prompt



    def _parse_response(self, response: str) -> Dict[str, Any]:
        try:
            if not response or not response.strip().startswith("{"):
                print("⚠️ Respuesta vacía o inválida del agente largo plazo.")
                return {"long_term": []}
            start = response.find("{")
            end = response.rfind("}") + 1
            json_str = response[start:end]
            parsed = json.loads(json_str)
            if "long_term" not in parsed or not isinstance(parsed["long_term"], list):
                return {"long_term": []}
            return parsed
        except Exception as e:
            print(f"Error al parsear respuesta del agente largo plazo: {e}")
            return {"long_term": []}

    def save_decision(self, decision: Dict[str, Any]):
        os.makedirs(os.path.dirname(DECISIONS_PATH), exist_ok=True)
        with open(DECISIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(decision, f, indent=2, ensure_ascii=False)
        print(f"Decisión guardada en: {DECISIONS_PATH}")

        # Log adicional en consola
        print("\nResumen de activos seleccionados (largo plazo):")
        for item in decision.get("long_term", []):
            t = item.get("ticker", "")
            peso = item.get("peso_pct", "")
            just = item.get("justificacion", "")
            print(f" - {t}: peso={peso}%, motivo: {just}")


    def export_decision(self, decision: Dict[str, Any], tipo: str, export_dir: str = "data/exports", accumulate: bool = True):
        """
        Exporta las decisiones a CSV y Parquet.
        
        Args:
            decision (dict): Diccionario con claves "intraday" o "long_term".
            tipo (str): "intraday" o "long_term".
            export_dir (str): Carpeta donde guardar los archivos.
            accumulate (bool): Si True acumula datos, si False sobrescribe.
        """
        os.makedirs(export_dir, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
        # Convertir a DataFrame
        df = pd.DataFrame(decision.get(tipo, []))
        if df.empty:
            print(f"⚠️ No hay datos para exportar en {tipo}.")
            return
        df["fecha"] = date_str
    
        # Rutas de exportación
        csv_path = os.path.join(export_dir, f"{tipo}_decision.csv")
        parquet_path = os.path.join(export_dir, f"{tipo}_decision.parquet")
    
        # Si acumula y ya existe, concatenar
        if accumulate and os.path.exists(csv_path):
            try:
                existing = pd.read_csv(csv_path)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception as e:
                print(f"⚠️ Error al leer CSV existente: {e}")
    
        # Guardar en CSV y Parquet
        df.to_csv(csv_path, index=False)
        df.to_parquet(parquet_path, index=False)
    
        print(f"✅ Exportación {tipo} guardada en:\n - CSV: {csv_path}\n - Parquet: {parquet_path}")
