import shutil
from pathlib import Path

SRC_DATA = Path("src/data")
DEST_DATA = Path("data")

def move_data_files():
    if not SRC_DATA.exists():
        print("❌ No se encontró src/data/. Nada para mover.")
        return

    moved = 0
    skipped = 0

    for src_file in SRC_DATA.rglob("*"):
        if src_file.is_file():
            rel_path = src_file.relative_to(SRC_DATA)
            dest_file = DEST_DATA / rel_path

            if dest_file.exists():
                print(f"⏩ Ya existe: {dest_file} → se mantiene")
                skipped += 1
                continue

            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_file), str(dest_file))
            print(f"📦 Movido: {src_file} → {dest_file}")
            moved += 1

    print(f"\n✅ Migración completa: {moved} archivos movidos, {skipped} ya existentes.")

if __name__ == "__main__":
    move_data_files()
