import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
NORMALIZED_BASE = ROOT / "data" / "raw" / "prices" / "normalized"
FEATURES_BASE = ROOT / "data" / "processed" / "features"
LOG_BASE = ROOT / "data" / "processed" / "features_rebuild_log"

FUNDAMENTALS_DAILY = ROOT / "data" / "processed_daily" / "fundamentals_daily.parquet"
SENTIMENT_DAILY = ROOT / "data" / "processed_daily" / "sentiment_daily.parquet"

REQUIRED_PRICE_COLS = ["open", "high", "low", "close", "volume"]
INDICATOR_COLS = [
    "SMA_20",
    "EMA_20",
    "daily_return",
    "volatility",
    "volume_avg",
    "RSI",
    "MACD",
    "MACD_signal",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
]
INTRADAY_HORIZON_DAYS = 1
LONG_TERM_HORIZON_DAYS = 5
INTRADAY_POSITIVE_THRESHOLD = 0.003
LONG_TERM_POSITIVE_THRESHOLD = 0.02


def _parse_date(value: Optional[str], default: datetime) -> datetime:
    if value:
        return datetime.strptime(value, "%Y-%m-%d")
    return default


def _parse_hour(value: Optional[str]) -> str:
    if value:
        return value
    return datetime.now().strftime("%H%M")


def _date_range(start: datetime, end: datetime) -> List[datetime]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _normalize_ticker(ticker: str) -> str:
    return str(ticker).replace(".US", "").replace(".BA", "")


def _normalize_dates(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_localize(None)
    return dates.dt.normalize()


def _fundamental_columns() -> List[str]:
    try:
        from src.execution.process.process_fundamentals import alpha_cols, finnhub_cols
        return sorted(set(alpha_cols.values()) | set(finnhub_cols.values()))
    except Exception:
        return [
            "pe_ratio",
            "pb_ratio",
            "roe",
            "roa",
            "de_ratio",
            "dividend_yield",
            "eps",
            "shares_outstanding",
            "percent_institutions",
            "percent_insiders",
            "gross_margin",
            "operating_margin",
            "net_margin",
            "free_cash_flow",
            "ytd_return",
        ]


def _pick_date_column(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        lowered = col.lower()
        if "date" in lowered or "timestamp" in lowered or "fecha" in lowered:
            return col
    return None


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()
    df["SMA_20"] = df["close"].rolling(window=20).mean()
    df["EMA_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["daily_return"] = df["close"].pct_change()
    df["volatility"] = df["daily_return"].rolling(window=20).std()
    df["volume_avg"] = df["volume"].rolling(window=20).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    rolling_mean = df["close"].rolling(window=20).mean()
    rolling_std = df["close"].rolling(window=20).std()
    df["bollinger_upper"] = rolling_mean + 2 * rolling_std
    df["bollinger_lower"] = rolling_mean - 2 * rolling_std
    df["bollinger_width"] = df["bollinger_upper"] - df["bollinger_lower"]

    df = df.dropna(subset=INDICATOR_COLS).copy()
    return df


def _add_forward_targets(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.sort_values(["ticker", "date"]).copy()
    grouped = panel.groupby("ticker", group_keys=False)

    next_open = grouped["open"].shift(-INTRADAY_HORIZON_DAYS)
    next_close = grouped["close"].shift(-INTRADAY_HORIZON_DAYS)
    panel["target_regresion_t+1"] = (next_close / next_open) - 1.0
    panel["target_clasificacion_t+1"] = (
        panel["target_regresion_t+1"] > INTRADAY_POSITIVE_THRESHOLD
    ).astype("Int64")

    future_close_long = grouped["close"].shift(-LONG_TERM_HORIZON_DAYS)
    panel["target_regresion_t+5"] = (future_close_long / next_open) - 1.0
    panel["target_clasificacion_t+5"] = (
        panel["target_regresion_t+5"] > LONG_TERM_POSITIVE_THRESHOLD
    ).astype("Int64")
    return panel


def _load_normalized_ticker(path: Path, start_date: datetime, end_date: datetime, lookback_days: int) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if "date" not in df.columns:
        raise ValueError(f"normalizados sin columna date: {path}")

    df["date"] = _normalize_dates(df["date"])
    missing = [c for c in REQUIRED_PRICE_COLS if c not in df.columns]
    if missing:
        print(f"[WARN] {path.name}: faltan columnas {missing}, se omite.")
        return pd.DataFrame()

    for col in REQUIRED_PRICE_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=REQUIRED_PRICE_COLS)
    start_window = start_date - timedelta(days=lookback_days)
    df = df[(df["date"] >= start_window) & (df["date"] <= end_date)].copy()
    if df.empty:
        return df

    df = _compute_indicators(df)
    df = df[(df["date"] >= start_date) & (df["date"] <= end_date)].copy()
    return df


def _load_fundamentals() -> pd.DataFrame:
    if not FUNDAMENTALS_DAILY.exists():
        return pd.DataFrame()
    df = pd.read_parquet(FUNDAMENTALS_DAILY)
    return df if not df.empty else pd.DataFrame()


def _load_sentiment() -> pd.DataFrame:
    if not SENTIMENT_DAILY.exists():
        return pd.DataFrame()
    df = pd.read_parquet(SENTIMENT_DAILY)
    return df if not df.empty else pd.DataFrame()


def _attach_fundamentals(panel: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in _fundamental_columns() if c != "ticker"]
    if fundamentals.empty or "ticker" not in fundamentals.columns:
        for col in cols:
            panel[col] = pd.NA
        return panel

    fundamentals = fundamentals.copy()
    fundamentals["ticker"] = fundamentals["ticker"].astype(str).map(_normalize_ticker)

    date_col = _pick_date_column(fundamentals)
    if date_col:
        fundamentals[date_col] = _normalize_dates(fundamentals[date_col])
        fundamentals = fundamentals.sort_values(date_col)
        panel = panel.sort_values("date")
        panel = pd.merge_asof(
            panel,
            fundamentals[[date_col, "ticker"] + [c for c in cols if c in fundamentals.columns]],
            left_on="date",
            right_on=date_col,
            by="ticker",
            direction="backward",
        )
        panel = panel.drop(columns=[date_col])
    else:
        panel = panel.merge(
            fundamentals[[c for c in fundamentals.columns if c in cols or c == "ticker"]],
            on="ticker",
            how="left",
        )

    for col in cols:
        if col not in panel.columns:
            panel[col] = pd.NA

    if "shares_outstanding" in panel.columns:
        panel["shares_outstanding"] = panel["shares_outstanding"].astype(str).str.replace(",", "", regex=False)
        panel["shares_outstanding"] = pd.to_numeric(panel["shares_outstanding"], errors="coerce")

    return panel


def _attach_sentiment(panel: pd.DataFrame, sentiment: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    if sentiment.empty or "ticker" not in sentiment.columns:
        panel["sentimiento_general"] = 0.0
        panel["sentimiento_especifico"] = 0.0
        return panel

    sentiment = sentiment.copy()
    sentiment["ticker"] = sentiment["ticker"].astype(str).map(_normalize_ticker)

    value_col = None
    for col in ["sentimiento_combinado", "score_combinado", "sentiment"]:
        if col in sentiment.columns:
            value_col = col
            break
    if value_col is None:
        panel["sentimiento_general"] = 0.0
        panel["sentimiento_especifico"] = 0.0
        return panel

    date_col = _pick_date_column(sentiment)
    if date_col:
        sentiment[date_col] = _normalize_dates(sentiment[date_col])
        sentiment = sentiment.sort_values(date_col)

    general = sentiment[sentiment["ticker"] == "GENERAL"]
    specific = sentiment[sentiment["ticker"] != "GENERAL"]

    panel["sentimiento_general"] = 0.0
    panel["sentimiento_especifico"] = pd.NA

    if date_col and not general.empty:
        general = general[[date_col, value_col]].sort_values(date_col)
        panel = panel.sort_values("date")
        panel = pd.merge_asof(
            panel,
            general.rename(columns={value_col: "sent_general"}),
            left_on="date",
            right_on=date_col,
            direction="backward",
        ).drop(columns=[date_col])
    elif not general.empty:
        panel["sentimiento_general"] = float(general[value_col].iloc[-1])

    if date_col and not specific.empty:
        specific = specific.sort_values(date_col)
        panel = pd.merge_asof(
            panel.sort_values("date"),
            specific[[date_col, "ticker", value_col]],
            left_on="date",
            right_on=date_col,
            by="ticker",
            direction="backward",
        )
        panel = panel.drop(columns=[date_col])
        panel = panel.rename(columns={value_col: "sent_specific"})
    elif not specific.empty:
        panel = panel.merge(
            specific[["ticker", value_col]].rename(columns={value_col: "sent_specific"}),
            on="ticker",
            how="left",
        )

    if "sent_general" in panel.columns:
        panel["sentimiento_general"] = panel["sent_general"]
        panel = panel.drop(columns=["sent_general"])
    panel["sentimiento_general"] = pd.to_numeric(panel["sentimiento_general"], errors="coerce").fillna(0.0)

    if "sent_specific" in panel.columns:
        panel["sentimiento_especifico"] = pd.to_numeric(panel["sent_specific"], errors="coerce")
        panel = panel.drop(columns=["sent_specific"])
    panel["sentimiento_especifico"] = pd.to_numeric(panel["sentimiento_especifico"], errors="coerce")
    panel["sentimiento_especifico"] = panel["sentimiento_especifico"].fillna(panel["sentimiento_general"])
    return panel


def _ensure_model_columns(panel: pd.DataFrame) -> pd.DataFrame:
    model_path = ROOT / "models" / "xgb_clf_futuro.pkl"
    if not model_path.exists():
        return panel
    try:
        import joblib
        model = joblib.load(model_path)
        expected = model.get_booster().feature_names
    except Exception as exc:
        print(f"[WARN] No se pudo leer modelo para columnas esperadas: {exc}")
        return panel

    for col in expected:
        if col not in panel.columns:
            panel[col] = pd.NA
    return panel


def _build_indicator_panel(start_date: datetime, end_date: datetime, lookback_days: int) -> pd.DataFrame:
    rows = []
    for path in sorted(NORMALIZED_BASE.glob("*.parquet")):
        ticker = _normalize_ticker(path.stem)
        df = _load_normalized_ticker(path, start_date, end_date, lookback_days)
        if df.empty:
            continue
        df = df.copy()
        df["ticker"] = ticker
        rows.append(df)

    if not rows:
        return pd.DataFrame()

    panel = pd.concat(rows, ignore_index=True)
    panel = panel.drop_duplicates(subset=["date", "ticker"], keep="last")
    panel = panel.sort_values(["ticker", "date"]).reset_index(drop=True)

    keep_cols = ["ticker", "date"] + REQUIRED_PRICE_COLS + INDICATOR_COLS
    extra_cols = [c for c in panel.columns if c not in keep_cols]
    if extra_cols:
        panel = panel.drop(columns=extra_cols)
    return panel


def _build_daily_snapshots(panel: pd.DataFrame, days: List[datetime]) -> pd.DataFrame:
    """
    Daily snapshots: 1 fila por ticker por día.
    Para cada ticker y día, toma la última fila disponible en `panel` con date <= día.
    Robusto: merge_asof por ticker y fuerza columna 'ticker'.
    """
    if panel is None or panel.empty:
        raise ValueError("_build_daily_snapshots: panel vacío")

    if "ticker" not in panel.columns or "date" not in panel.columns:
        raise ValueError(f"_build_daily_snapshots: panel debe tener 'ticker' y 'date'. cols={list(panel.columns)}")

    panel = panel.copy()

    # Normalizar ticker/date y limpiar inválidos
    panel["ticker"] = panel["ticker"].astype(str)
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    panel = panel.dropna(subset=["ticker", "date"])

    # Si quedaron tickers vacíos tipo "nan" o ""
    panel = panel[panel["ticker"].astype(str).str.strip().ne("")]
    panel = panel[panel["ticker"].astype(str).str.lower().ne("nan")]

    tickers = sorted(panel["ticker"].unique().tolist())
    if not tickers:
        raise ValueError("_build_daily_snapshots: no hay tickers válidos en panel después de limpiar")

    if not days:
        raise ValueError("_build_daily_snapshots: days vacío")

    # Calendar (solo fechas, ordenadas)
    cal_dates = pd.DataFrame({"date": [pd.to_datetime(d).normalize() for d in days]})
    cal_dates["date"] = pd.to_datetime(cal_dates["date"], errors="coerce").dt.normalize()
    cal_dates = cal_dates.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    out_parts = []

    for tkr in tickers:
        g = panel[panel["ticker"] == tkr].copy()
        if g.empty:
            continue
        g = g.sort_values("date").reset_index(drop=True)

        cal = cal_dates.copy()
        cal["ticker"] = tkr  # <-- CRÍTICO: garantizamos columna ticker

        merged = pd.merge_asof(
            cal.sort_values("date"),
            g.sort_values("date"),
            on="date",
            direction="backward",
            allow_exact_matches=True,
        )

        if "ticker_x" in merged.columns and "ticker_y" in merged.columns:
            left = merged["ticker_x"].astype("string").str.strip()
            right = merged["ticker_y"].astype("string").str.strip()
            left = left.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            right = right.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            mismatch = (left != right) & left.notna() & right.notna()
            if mismatch.any():
                print(f"[WARN] ticker_x/ticker_y mismatch para {tkr}: {int(mismatch.sum())} filas")
            merged["ticker"] = left.fillna(right).fillna(tkr).astype(str).str.strip()
            merged = merged.drop(columns=["ticker_x", "ticker_y"])
        elif "ticker_x" in merged.columns:
            left = merged["ticker_x"].astype("string").str.strip()
            left = left.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            merged["ticker"] = left.fillna(tkr).astype(str).str.strip()
            merged = merged.drop(columns=["ticker_x"])
        elif "ticker_y" in merged.columns:
            right = merged["ticker_y"].astype("string").str.strip()
            right = right.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
            merged["ticker"] = right.fillna(tkr).astype(str).str.strip()
            merged = merged.drop(columns=["ticker_y"])

        if "ticker" not in merged.columns:
            merged["ticker"] = tkr
        merged["ticker"] = merged["ticker"].astype("string").str.strip()
        merged["ticker"] = merged["ticker"].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA}).fillna(tkr)
        merged["ticker"] = merged["ticker"].astype(str).str.strip()


        out_parts.append(merged)

    if not out_parts:
        raise ValueError("_build_daily_snapshots: no se pudo construir ningún snapshot (out_parts vacío)")

    daily = pd.concat(out_parts, ignore_index=True)

    if "ticker_x" in daily.columns and "ticker_y" in daily.columns:
        left = daily["ticker_x"].astype("string").str.strip()
        right = daily["ticker_y"].astype("string").str.strip()
        left = left.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        right = right.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        mismatch = (left != right) & left.notna() & right.notna()
        if mismatch.any():
            print(f"[WARN] ticker_x/ticker_y mismatch en daily: {int(mismatch.sum())} filas")
        daily["ticker"] = left.fillna(right).fillna(pd.NA)
        daily = daily.drop(columns=["ticker_x", "ticker_y"])
    elif "ticker_x" in daily.columns:
        left = daily["ticker_x"].astype("string").str.strip()
        left = left.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        daily["ticker"] = left.fillna(pd.NA)
        daily = daily.drop(columns=["ticker_x"])
    elif "ticker_y" in daily.columns:
        right = daily["ticker_y"].astype("string").str.strip()
        right = right.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
        daily["ticker"] = right.fillna(pd.NA)
        daily = daily.drop(columns=["ticker_y"])

    if "ticker" not in daily.columns:
        raise ValueError(f"_build_daily_snapshots: resultado sin 'ticker'. cols={list(daily.columns)}")
    daily["ticker"] = daily["ticker"].astype("string").str.strip()
    daily["ticker"] = daily["ticker"].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    daily = daily.dropna(subset=["ticker"])
    daily["ticker"] = daily["ticker"].astype(str).str.strip()
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()


    # Filtrar filas inválidas
    if "close" in daily.columns:
        daily = daily.dropna(subset=["close"])

    daily = daily.sort_values(["ticker", "date"]).reset_index(drop=True)

    # Lags (si existen)
    if "RSI" in daily.columns:
        daily["RSI_t-1"] = daily.groupby("ticker")["RSI"].shift(1)
    if "daily_return" in daily.columns:
        daily["daily_return_t-1"] = daily.groupby("ticker")["daily_return"].shift(1)
    if "MACD" in daily.columns:
        daily["MACD_t-1"] = daily.groupby("ticker")["MACD"].shift(1)

    return daily


def _validate_daily_snapshot(day_df: pd.DataFrame, day_norm: datetime) -> None:
    if day_df.empty:
        return
    if day_df.columns.duplicated().any():
        raise ValueError("snapshot invalido: columnas duplicadas")
    if "ticker" not in day_df.columns:
        raise ValueError("snapshot invalido: falta columna ticker")
    if "date" not in day_df.columns:
        raise ValueError("snapshot invalido: falta columna date")

    tickers = day_df["ticker"].astype("string").str.strip()
    tickers = tickers.replace({"": pd.NA, "nan": pd.NA, "none": pd.NA, "null": pd.NA, "None": pd.NA})
    tickers_lower = tickers.str.lower()
    invalid = tickers.isna() | tickers_lower.isin(["", "nan", "none", "null"])
    if invalid.any():
        raise ValueError("snapshot invalido: ticker vacio o nulo")

    dates = pd.to_datetime(day_df["date"], errors="coerce").dt.normalize()
    if dates.isna().any():
        raise ValueError("snapshot invalido: date no parseable")
    target_day = pd.to_datetime(day_norm).normalize()
    if not (dates == target_day).all():
        raise ValueError("snapshot invalido: date no coincide con el dia")

    max_per_ticker = day_df.groupby("ticker").size().max()
    if max_per_ticker != 1:
        raise ValueError("snapshot invalido: mas de una fila por ticker")


def rebuild_features_history(
    start_date: datetime,
    end_date: datetime,
    hour: str,
    mode: str,
    indicators_lookback_days: int,
    force: bool,
) -> None:
    if not NORMALIZED_BASE.exists():
        raise FileNotFoundError(f"No existe {NORMALIZED_BASE}")

    panel = _build_indicator_panel(start_date, end_date, indicators_lookback_days)
    if panel.empty:
        print("[WARN] Panel vacio, no hay datos para reconstruir.")
        return
    # Clamp end_date to available data range
    panel["date"] = pd.to_datetime(panel["date"], errors="coerce").dt.normalize()
    panel = panel.dropna(subset=["date", "ticker"])

    max_available = panel["date"].max()
    min_available = panel["date"].min()
    print(f"[INFO] panel available range: {min_available.date()} .. {max_available.date()}")

    # If end_date is beyond max available market date, clamp it
    end_dt_norm = pd.to_datetime(end_date).normalize()
    if end_dt_norm > max_available:
        print(f"[WARN] end_date {end_dt_norm.date()} > max_available {max_available.date()} -> clamping")
        end_date = max_available.to_pydatetime()
    days = _date_range(start_date, end_date)

    # Build calendar range for daily snapshots
    daily = _build_daily_snapshots(panel, days)
    daily["date"] = pd.to_datetime(daily["date"], errors="coerce").dt.normalize()

    print("[DEBUG] daily snapshots shape:", daily.shape)
    print("[DEBUG] daily cols:", list(daily.columns)[:40])
    if not daily.empty:
        print("[DEBUG] daily date min/max:", daily["date"].min(), daily["date"].max())
        print("[DEBUG] daily tickers sample:", sorted(daily["ticker"].astype(str).unique())[:10])
        print("[DEBUG] rows per ticker (describe):")
        print(daily.groupby("ticker").size().describe())

    if daily.empty:
        print("[WARN] Snapshots diarios vacios.")
        return

    fundamentals = _load_fundamentals()
    sentiment = _load_sentiment()

    daily = _attach_fundamentals(daily, fundamentals)
    daily = _attach_sentiment(daily, sentiment)

    daily = daily.sort_values(["ticker", "date"]).reset_index(drop=True)
    daily["target_clasificacion"] = (daily["daily_return"] > 0).astype(int)
    daily["RSI_x_volume"] = daily["RSI"] * daily["volume_avg"]
    daily["MACD_x_sentimiento"] = daily["MACD"] * daily["sentimiento_general"]

    for col in daily.columns:
        if col in ["ticker", "date"]:
            continue
        if pd.api.types.is_datetime64_any_dtype(daily[col]):
            continue
        daily[col] = pd.to_numeric(daily[col], errors="coerce")

    required_cols = [
        "RSI",
        "MACD",
        "MACD_signal",
        "bollinger_upper",
        "bollinger_lower",
        "bollinger_width",
        "daily_return",
        "RSI_t-1",
        "daily_return_t-1",
        "MACD_t-1",
    ]
    daily = daily.dropna(subset=[c for c in required_cols if c in daily.columns])

    if mode == "train":
        daily = _add_forward_targets(daily)
        daily = daily.dropna(
            subset=[
                "target_regresion_t+1",
                "target_clasificacion_t+1",
                "target_regresion_t+5",
                "target_clasificacion_t+5",
            ]
        )
    else:
        daily["target_regresion_t+1"] = pd.NA
        daily["target_clasificacion_t+1"] = pd.NA
        daily["target_regresion_t+5"] = pd.NA
        daily["target_clasificacion_t+5"] = pd.NA

    daily = _ensure_model_columns(daily)

    run_ts = datetime.now()
    hour_int = int(hour[:2])
    minute_int = int(hour[2:])

    log_rows = []
    for day in days:
        day_norm = pd.to_datetime(day).normalize().date()
        day_df = daily[daily["date"].dt.date == day_norm].copy()

        out_dir = FEATURES_BASE / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        out_path = out_dir / "features.parquet"

        if out_path.exists() and not force:
            log_rows.append({
                "day": day.strftime("%Y-%m-%d"),
                "tickers_written": 0,
                "skipped_existing": 1,
                "errors_count": 0,
            })
            print(f"[INFO] {day.strftime('%Y-%m-%d')} skip (exists)")
            continue

        if day_df.empty:
            log_rows.append({
                "day": day.strftime("%Y-%m-%d"),
                "tickers_written": 0,
                "skipped_existing": 0,
                "errors_count": 1,
            })
            print(f"[WARN] {day.strftime('%Y-%m-%d')} sin datos")
            continue

        try:
            day_df = day_df.sort_values("ticker").drop_duplicates(subset=["ticker"], keep="last")
            _validate_daily_snapshot(day_df, day)
            timestamp_proceso = datetime(
                year=day.year,
                month=day.month,
                day=day.day,
                hour=hour_int,
                minute=minute_int,
            )
            day_df["timestamp_proceso"] = timestamp_proceso
            day_df["timestamp_ejecucion"] = run_ts

            out_dir.mkdir(parents=True, exist_ok=True)
            day_df.to_parquet(out_path, index=False)

            log_rows.append({
                "day": day.strftime("%Y-%m-%d"),
                "tickers_written": int(len(day_df)),
                "skipped_existing": 0,
                "errors_count": 0,
            })
            print(f"[INFO] {day.strftime('%Y-%m-%d')} tickers={len(day_df)}")
        except Exception as exc:
            log_rows.append({
                "day": day.strftime("%Y-%m-%d"),
                "tickers_written": 0,
                "skipped_existing": 0,
                "errors_count": 1,
            })
            print(f"[ERROR] {day.strftime('%Y-%m-%d')}: {exc}")

    if log_rows:
        log_dir = LOG_BASE / f"{run_ts.year:04d}" / f"{run_ts.month:02d}" / f"{run_ts.day:02d}" / hour
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "rebuild_log.parquet"
        df_log = pd.DataFrame(log_rows)
        df_log.to_parquet(log_path, index=False)
        print(f"[INFO] Log guardado en {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruye features diarios historicos.")
    parser.add_argument("--start-date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--end-date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=252)
    parser.add_argument("--hour", type=str, help="HHMM")
    parser.add_argument("--mode", type=str, choices=["train", "inference"], default="train")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--indicators-lookback-days", type=int, default=400)
    args = parser.parse_args()

    today = datetime.now()
    end_date = _parse_date(args.end_date, today)
    if args.start_date:
        start_date = _parse_date(args.start_date, end_date - timedelta(days=args.lookback_days))
    else:
        start_date = end_date - timedelta(days=args.lookback_days)

    hour = _parse_hour(args.hour)

    rebuild_features_history(
        start_date=start_date,
        end_date=end_date,
        hour=hour,
        mode=args.mode,
        indicators_lookback_days=args.indicators_lookback_days,
        force=args.force,
    )


if __name__ == "__main__":
    main()
