import os
import json
from typing import Dict, Any
from autogen import AssistantAgent
import pandas as pd
from datetime import datetime

class IntradayDecisionAgent:
    def __init__(self):
        self.agent = AssistantAgent(
            name="intraday_agent",
            system_message=(
                "Sos un trader táctico especializado en oportunidades intradía. "
                "Buscás activos con momentum, alta liquidez, sentimiento positivo inmediato y señales fuertes. "
                "Tu objetivo es seleccionar activos para operar hoy con alto potencial de retorno ajustado por riesgo."
            ),
            llm_config={
                "model": "gpt-4o",
                "temperature": 0.4,
                "api_key": os.getenv("OPENAI_API_KEY"),
                "max_tokens": 2048
            }
        )

    # Este método es el punto de entrada principal cuando el agente es invocado por el orquestador
    def decide(self, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self._build_prompt(context)
        messages = [{"role": "user", "content": prompt}]
        response = self.agent.generate_reply(messages)
        return self._parse_response(response)

    def _build_prompt(self, context: Dict[str, Any]) -> str:
        raw_signals = context.get("signals", [])
        sentiment = context.get("sentiment", {})
        max_positions = context.get("max_positions", 10)

        # Filtrar señales relevantes y completas
        required_keys = ["ticker", "score", "expected_return_pct"]
        signals = [s for s in raw_signals if s.get("investment_type") == "intraday"]
        signals = [s for s in signals if all(k in s for k in required_keys)]
        signals = sorted(signals, key=lambda x: x.get("score", 0), reverse=True)[:30]

        # Construcción del prompt compacto
        prompt = (
            f"Seleccioná hasta {max_positions} activos para operar intradía hoy.\n"
            f"Priorizá momentum, liquidez alta, sentimiento positivo y señales fuertes.\n"
            f"Formato de respuesta: {{ \"intraday\": [ {{\"ticker\": \"...\", \"justificacion\": \"...\"}}, ... ] }}\n\n"
            f"Señales:\n"
        )

        for s in signals:
            ticker = s["ticker"]
            score = round(s["score"], 2)
            ret_val = s.get("expected_return_pct")
            ret = round(ret_val, 2) if isinstance(ret_val, (int, float)) else "N/A"
            sent = sentiment.get(ticker, [{}])[0].get("combined_score", "N/A")
            prompt += f"{ticker}: score={score}, ret={ret}, sent={sent}\n"

        return prompt


    def _parse_response(self, response: str) -> Dict[str, Any]:
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            json_str = response[start:end]
            parsed = json.loads(json_str)
            if "intraday" not in parsed or not isinstance(parsed["intraday"], list):
                return {"intraday": []}
            return parsed
        except Exception as e:
            print(f" Error al parsear respuesta del agente intradía: {e}")
            return {"intraday": []}
        
    def save_decision(self, decision: Dict[str, Any], path: str = "data/results/intraday_decision.json"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(decision, f, indent=2, ensure_ascii=False)
        print(f"Decisión intradía guardada en: {path}")

        print("\nResumen de activos seleccionados (intradía):")
        for item in decision.get("intraday", []):
            t = item.get("ticker", "")
            just = item.get("justificacion", "")
            print(f" - {t}: motivo: {just}")

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
