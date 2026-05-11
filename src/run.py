import os
import sys
import argparse
import subprocess
from dotenv import load_dotenv
from src.utils.execution_context import get_etl_args, get_current_args

# Cargar variables de entorno
load_dotenv(dotenv_path=".env")

# Relanzar como módulo si se ejecuta como script directo
if __name__ == "__main__" and __package__ is None:
    module = "src.run"
    cmd = [sys.executable, "-m", module] + sys.argv[1:]
    print(f"[RELAUNCH] Ejecutando como módulo: {' '.join(cmd)}")
    sys.exit(subprocess.run(cmd).returncode)

# -------------------- Argumentos --------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Ejecuta el sistema de recomendación de inversiones.")

    # Configuración general
    parser.add_argument("--no-etl", action="store_true", help="Saltea la ejecución del ETL")
    parser.add_argument("--only-agent", action="store_true", help="Ejecuta solo la decisión sin ETL ni modelado")
    parser.add_argument("--threshold", type=float, default=0.55, help="Umbral mínimo para seleccionar activos")
    parser.add_argument("--max-positions", type=int, default=10, help="Cantidad máxima de posiciones a tomar")
    parser.add_argument("--date", type=str, help="Fecha de ejecución en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora de ejecución en formato HHMM")
    parser.add_argument("--min-ret-pct", type=float, default=0.5)
    parser.add_argument("--max-vol-pct", type=float, default=5.0)
    parser.add_argument("--min-liquidez", type=int, default=1_000_000)
    parser.add_argument("--no-accumulate", action="store_true", help="No acumular exportaciones, sobrescribir archivos")



    # Flags para ETL
    parser.add_argument("--skip-alpha", action="store_true")
    parser.add_argument("--skip-fetch_prices", action="store_true", help="Saltear ingesta de precios") 
    parser.add_argument("--skip-fundamentals", action="store_true")
    parser.add_argument("--skip-relevance", action="store_true")
    parser.add_argument("--skip-sentiment", action="store_true")
    parser.add_argument("--force-process_prices", action="store_true", help="Forzar procesamiento de precios incluso sin nuevos datos")
    parser.add_argument("--skip-process_prices", action="store_true", help="Saltear procesamiento de precios")            
    parser.add_argument("--force-fundamentals", action="store_true")
    parser.add_argument("--force-relevance", action="store_true")
    parser.add_argument("--force-sentiment", action="store_true")

    return parser.parse_args(argv)

# -------------------- Ejecución principal --------------------

def run_pipeline(args):

    # Determinar fecha y hora
    if args.date and args.hour:
        date, hour = args.date, args.hour
        print(f"[INFO] Usando fecha/hora manual: {date} {hour}")
    elif args.no_etl or args.only_agent:
        etl_args = get_etl_args()
        date, hour = etl_args["date"], etl_args["hour"]
        print(f"[INFO] Usando fecha/hora del último ETL exitoso: {date} {hour}")
    else:
        current_args = get_current_args()
        date, hour = current_args["date"], current_args["hour"]
        print(f"[INFO] Usando fecha/hora actual del sistema: {date} {hour}")

    # Construcción de flags
    skip_flags = {
    "alpha": args.skip_alpha,
    "fetch_prices": args.skip_fetch_prices,
    "fundamentals": args.skip_fundamentals,
    "relevance": args.skip_relevance,
    "sentiment": args.skip_sentiment,
    "process_prices": args.skip_process_prices,
    }

    force_flags = {
        "process_prices": args.force_process_prices,
        "fundamentals": args.force_fundamentals,
        "relevance": args.force_relevance,
        "sentiment": args.force_sentiment,
    }


    # Crear agente orquestador (lazy import para evitar autogen/openai en ETL-only)
    from src.agents.orchestrator_agent import OrchestratorDecisionAgent
    agent = OrchestratorDecisionAgent(args)


    # Ejecutar orquestación
    decision = agent.run_day(
        run_etl=not args.no_etl and not args.only_agent,
        date=date,
        hour=hour,
        skip_flags=skip_flags,
        force_flags=force_flags,
        only_agent=args.only_agent,
        accumulate=not args.no_accumulate
    )

    # Mostrar resumen en consola
    print("\nResumen de decisiones tomadas:")
    if "decision" in decision:
        long_term = decision["decision"].get("long_term", [])
        intraday = decision["decision"].get("intraday", [])

        print(f" Largo plazo ({len(long_term)} activos):")
        for d in long_term:
            print(f"  - {d['ticker']}: {d.get('justificacion', '')}")

        print(f"\nIntradía ({len(intraday)} activos):")
        for d in intraday:
            print(f"  - {d['ticker']}: {d.get('justificacion', '')}")
    else:
        print(" No se encontraron decisiones en el resultado.")

    print("\n Ejecución completada sin errores.")

    return {"decision": decision, "date": date, "hour": hour}

def main():
    args = parse_args()
    run_pipeline(args)

# -------------------- Entry point --------------------

if __name__ == "__main__":
    main()
