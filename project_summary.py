import os
import ast
import json

EXCLUDE_DIRS = {".venv", "venv", ".git", "__pycache__", "site-packages", "build", "dist", ".mypy_cache", ".pytest_cache"}
PROJECT_ROOT = "."  # Cambiá si querés apuntar a otro directorio

def is_excluded(path):
    parts = path.split(os.sep)
    return any(part in EXCLUDE_DIRS for part in parts)

def is_data_deep(path):
    parts = path.split(os.sep)
    if "data" in parts:
        data_index = parts.index("data")
        return len(parts) > data_index + 2  # Solo permitimos data/<subcarpeta>
    return False

def summarize_python_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source, filename=path)
        summary = {
            "docstring": ast.get_docstring(tree),
            "classes": [],
            "functions": [],
            "imports": [],
            "subprocess_calls": [],
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                summary["classes"].append(node.name)
            elif isinstance(node, ast.FunctionDef):
                summary["functions"].append(node.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    summary["imports"].append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                summary["imports"].append(node.module)
            elif isinstance(node, ast.Call):
                if hasattr(node.func, "attr") and node.func.attr == "run":
                    summary["subprocess_calls"].append(ast.unparse(node))
        return summary
    except Exception as e:
        return {"error": str(e)}

def detect_requirements():
    reqs = []
    for fname in ["requirements.txt", "pyproject.toml"]:
        if os.path.exists(fname):
            with open(fname, "r", encoding="utf-8") as f:
                lines = f.readlines()
            reqs.extend([line.strip() for line in lines if line.strip() and not line.startswith("#")])
    return reqs

def walk_project(root_dir):
    metadata = {
        "project_root": os.path.abspath(root_dir),
        "folders": [],
        "scripts": {},
        "dependencies": detect_requirements(),
    }

    for dirpath, dirnames, filenames in os.walk(root_dir):
        rel_dir = os.path.relpath(dirpath, root_dir)
        if is_excluded(rel_dir) or is_data_deep(rel_dir):
            continue
        metadata["folders"].append(rel_dir)

        for file in filenames:
            full_path = os.path.join(dirpath, file)
            rel_path = os.path.relpath(full_path, root_dir)
            if file.endswith(".py") and not is_excluded(rel_path) and not is_data_deep(rel_path):
                metadata["scripts"][rel_path] = summarize_python_file(full_path)

    return metadata

if __name__ == "__main__":
    summary = walk_project(PROJECT_ROOT)
    with open("project_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print("✅ Exportación limpia y explicativa en project_summary.json")
