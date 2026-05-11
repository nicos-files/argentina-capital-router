import os
from fastparquet import ParquetFile

RAW_PATH = "data/processed/sentimiento/relevantes"

print(f"📁 Revisando archivos en: {RAW_PATH}\n")
total = 0

for archivo in os.listdir(RAW_PATH):
    if archivo.endswith(".parquet"):
        path = os.path.join(RAW_PATH, archivo)
        try:
            pf = ParquetFile(path)
            filas = pf.count()  # ✅ corregido
            total += filas
            print(f"✅ {archivo}: {filas} filas")
        except Exception as e:
            print(f"⚠️ Error en {archivo}: {e}")

print(f"\n📊 Total acumulado: {total} textos")
