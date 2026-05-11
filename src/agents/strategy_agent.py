import os
from openai import OpenAI

class StrategyAgent:
    def __init__(self, model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY")):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate_strategy(self, contexto):
        prompt = (
            "Sos un estratega financiero con razonamiento avanzado. "
            "Tu tarea es combinar señales de modelos predictivos, sentimiento del mercado, "
            "y análisis fundamental para recomendar acciones concretas: comprar, vender, mantener o ajustar riesgo. "
            f"Contexto: {contexto}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
