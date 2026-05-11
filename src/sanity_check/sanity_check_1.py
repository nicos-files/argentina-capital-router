import pandas as pd
from pathlib import Path
import yaml

# Ruta al root del proyecto (dos niveles arriba de src/sanity_check)
BASE_DIR = Path(__file__).resolve().parents[2]

# Ruta al config.yaml
CONFIG_PATH = BASE_DIR / "configs" / "config.yaml"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

print("✅ Config cargado correctamente:")
print(config)

path = Path(config["data_path"])

# Crear un DataFrame dummy
df = pd.DataFrame({
    "date": ["2025-01-01", "2025-01-02"],
    "price": [100, 101]
})

# Guardar en parquet
path.parent.mkdir(parents=True, exist_ok=True)
df.to_parquet(path, index=False)

# Leer de nuevo
df_loaded = pd.read_parquet(path)

print("✅ Sanity check passed!")
print(df_loaded)
