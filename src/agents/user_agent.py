class UserAgent:
    def __init__(self, name="UserAgent"):
        self.name = name

    def present_sentiment(self, resultado_sentimiento):
        return (
            f"🧠 Sentimiento del mercado:\n"
            f"{resultado_sentimiento}\n"
            f"Interpretación: Este análisis puede influir en decisiones de corto plazo."
        )

    def present_strategy(self, estrategia):
        return (
            f"📈 Estrategia recomendada:\n"
            f"{estrategia}\n"
            f"Acción sugerida: Evaluá esta recomendación junto con tu perfil de riesgo."
        )

    def present_summary(self, sentimiento, estrategia):
        return (
            f"🧾 Resumen de análisis:\n\n"
            f"{self.present_sentiment(sentimiento)}\n\n"
            f"{self.present_strategy(estrategia)}"
        )
