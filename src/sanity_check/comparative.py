import pandas as pd
import matplotlib.pyplot as plt

# Cargar ambos archivos
textblob = pd.read_parquet("data/processed/sentimiento_general_textblob.parquet")
llm = pd.read_parquet("data/processed/sentimiento_general_llm.parquet")

# Extraer valores
scores = {
    "TextBlob": textblob["sentimiento_general"].dropna(),
    "LLM": llm["sentimiento_general"].dropna()
}

# Graficar histogramas
plt.figure(figsize=(10, 5))
for label, data in scores.items():
    plt.hist(data, bins=20, alpha=0.6, label=label)

plt.title("📊 Distribución del Sentimiento General")
plt.xlabel("Puntaje de Sentimiento")
plt.ylabel("Frecuencia")
plt.legend()
plt.tight_layout()
plt.show()
