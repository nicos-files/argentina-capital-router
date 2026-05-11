import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class SentimentAgent:
    def __init__(self,
                 relevance_model="gpt-4o",
                 sentiment_model="gpt-4o",
                 api_key=os.getenv("OPENAI_API_KEY")):
        self.client = OpenAI(api_key=api_key)
        self.relevance_model = relevance_model
        self.sentiment_model = sentiment_model

    def relevance_filter(self, texto):
        #print(f" Usando modelo: {self.relevance_model}") 
        prompt = (
            "Respondé únicamente con 'Sí' o 'No'. No agregues explicaciones ni comentarios. "
            "Considerá como relevantes los textos que puedan tener implicancia económica, financiera o de mercado, directa o indirecta. "
            "Esto incluye noticias, rumores, opiniones, lenguaje informal o técnico que puedan influir en precios de activos financieros, decisiones de inversión, percepción de riesgo o comportamiento del mercado. "
            "Incluí también textos que mencionen empresas, productos tecnológicos, lanzamientos, cambios estratégicos, reputación corporativa o críticas institucionales, siempre que puedan afectar la valoración de una compañía o su posición competitiva. "
            "No incluyas textos que solo mencionen marcas, productos, celebridades o eventos sin conexión clara con el ámbito económico o financiero.\n\n"
            f"Texto: '{texto}'")
        #print(f"\n Prompt enviado:\n{prompt}\n")


        response = self.client.chat.completions.create(
            model=self.relevance_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        response_text = response.choices[0].message.content.strip()
        print(f"Respuesta del modelo: {response_text}\n")
        return response_text


    def process_sentiment(self, texto):
        prompt = (
            "Actuá como un analista financiero con experiencia en trading y gestión de carteras. "
            "Analizá el siguiente texto desde una perspectiva de impacto en mercados financieros. "
            "Evaluá el sentimiento en dos horizontes temporales:\n"
            "- Corto plazo (trading): ¿El texto sugiere una reacción inmediata del mercado, volatilidad, euforia o miedo?\n"
            "- Mediano-largo plazo (inversión): ¿El texto implica cambios en fundamentos, reputación corporativa, estrategia, regulación o contexto macroeconómico?\n\n"
            "Indicá el sentimiento en cada horizonte como 'positivo', 'negativo' o 'neutral'. Luego, asigná un puntaje numérico entre -1 y 1 para cada uno:\n"
            "- Sentimiento de corto plazo (trading)\n"
            "- Sentimiento de mediano-largo plazo (inversión)\n"
            "- Sentimiento combinado (promedio ponderado de ambos, considerando que el largo plazo tiene mayor peso)\n\n"
            "Respondé en el siguiente formato:\n"
            "Sentimiento corto: [positivo/negativo/neutral]\n"
            "Score corto: [número entre -1 y 1]\n"
            "Sentimiento largo: [positivo/negativo/neutral]\n"
            "Score largo: [número entre -1 y 1]\n"
            "Score combinado: [número entre -1 y 1]\n\n"
            f"Texto: '{texto}'"
        )
        response = self.client.chat.completions.create(
            model=self.sentiment_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()

