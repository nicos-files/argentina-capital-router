import pandas as pd
from datetime import datetime
import time
import sys
sys.path.append("C:/Users/NAguilar/Proyectos/AutoGen/quant-trading-bot")
from src.agents.agent_definitions import sentiment_agent
# Cargar el log original
df_log = pd.read_parquet("data/logs/llm_interactions.parquet")
df_relevance = df_log[df_log["tipo_análisis"] == "relevance"]

# Filtrar todos los que NO contienen "sí"
df_no_si = df_relevance[
    ~df_relevance["respuesta_llm"].str.lower().str.contains("sí", na=False)
]

# Instanciar el agente con el nuevo prompt amplio
class SentimentAgentAmplio:
    def __init__(self, client, model="gpt-4o"):
        self.client = client
        self.relevance_model = model

    def relevance_filter_amplio(self, texto):
        prompt = (
        "Respondé únicamente con 'Sí' o 'No'. No agregues explicaciones ni comentarios. "
        "Considerá como relevantes los textos que puedan tener implicancia económica, financiera o de mercado, directa o indirecta. "
        "Esto incluye noticias, rumores, opiniones, lenguaje informal o técnico que puedan influir en precios de activos financieros, decisiones de inversión, percepción de riesgo o comportamiento del mercado. "
        "No incluyas textos que solo mencionen marcas, productos, celebridades o eventos sin conexión clara con el ámbito financiero.\n\n"
        f"Texto: '{texto}'"
    )
        response = self.client.chat.completions.create(
            model=self.relevance_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()

# Crear instancia del agente
sentiment_agent_amplio = SentimentAgentAmplio(client=sentiment_agent.client)

# Reprocesar y comparar
resultados = []
recuperados = 0

for _, row in df_no_si.iterrows():
    texto = row["texto_original"]
    respuesta_original = row["respuesta_llm"]
    start = time.time()

    try:
        respuesta_nueva = sentiment_agent_amplio.relevance_filter_amplio(texto).strip().lower()
        respuesta_nueva_norm = (
            respuesta_nueva.replace(".", "").replace("!", "").replace("¡", "").replace("si", "sí").strip()
        )
        estado = "ok" if respuesta_nueva_norm in ["sí", "no"] else "ambiguo"
    except Exception as e:
        respuesta_nueva_norm = None
        estado = "error"

    # Comparar con la respuesta original
    original_es_no = "sí" not in respuesta_original.lower()
    nueva_es_si = respuesta_nueva_norm == "sí"
    fue_recuperado = original_es_no and nueva_es_si

    if fue_recuperado:
        recuperados += 1
        print(f"✅ Recuperado: {texto[:80]}...")

    resultados.append({
        "timestamp": datetime.now().isoformat(),
        "texto_original": texto,
        "respuesta_llm_original": respuesta_original,
        "respuesta_llm_amplia": respuesta_nueva_norm,
        "estado_amplio": estado,
        "fue_recuperado": fue_recuperado,
        "tiempo_respuesta": round(time.time() - start, 3)
    })

# Guardar resultados
df_amplio = pd.DataFrame(resultados)
df_amplio.to_parquet("data/debug/reanalizados_amplio.parquet", index=False)

print(f"\n🎯 Textos recuperados como relevantes: {recuperados} de {len(df_amplio)} ({recuperados / len(df_amplio):.2%})")
