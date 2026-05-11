from pathlib import Path
import yaml
import pandas as pd
import duckdb

# -----------------------------
# 1️⃣ Cargar config
# -----------------------------
CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "config.yaml"

if not CONFIG_PATH.exists():
    raise FileNotFoundError(f"No se encontró config.yaml en {CONFIG_PATH}")

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

print("✅ Config cargado correctamente:")
print(config)

# -----------------------------
# 2️⃣ Crear dataset dummy
# -----------------------------
raw_dir = Path(config["data_path_raw"])
raw_dir.mkdir(parents=True, exist_ok=True)

df_raw = pd.DataFrame({
    "date": pd.date_range("2025-01-01", periods=5),
    "price": [100, 101, 102, 103, 104]
})

raw_file = raw_dir / "test_1.parquet"
df_raw.to_parquet(raw_file, index=False)
print(f"✅ Dataset dummy creado en {raw_file}")

# -----------------------------
# 3️⃣ Leer con DuckDB
# -----------------------------
con = duckdb.connect()
query = f"SELECT *, AVG(price) OVER() AS avg_price FROM '{raw_file}'"
df_duck = con.execute(query).df()

print("✅ Lectura con DuckDB exitosa:")
print(df_duck)

# -----------------------------
# 4️⃣ Guardar resultados
# -----------------------------
results_dir = Path(config["data_path_results"])
results_dir.mkdir(parents=True, exist_ok=True)

result_file = results_dir / "test_results.parquet"
df_duck.to_parquet(result_file, index=False)
print(f"✅ Resultados guardados en {result_file}")

# -----------------------------
# 5️⃣ Sanity check final
# -----------------------------
if result_file.exists():
    print("🎯 Sanity check completo: todo funciona correctamente")
else:
    print("❌ Error: archivo de resultados no creado")
