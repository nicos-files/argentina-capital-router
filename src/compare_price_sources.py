import pandas as pd
from pathlib import Path
import sys


def load_prices(path: Path, provider: str):
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return None

    df = pd.read_parquet(path)

    # Normalize date handling
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    else:
        # AlphaV style: datetime index
        df = df.reset_index().rename(columns={"index": "date"})
        df["date"] = pd.to_datetime(df["date"])

    # Normalize to date-only (no TZ, no time)
    s = df["date"]
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert(None)
    df["date"] = s.dt.normalize()
    # Keep only expected columns
    cols = ["date"]
    for c in ["open", "high", "low", "close", "volume"]:
        if c in df.columns:
            cols.append(c)

    df = df[cols].copy()
    df["provider"] = provider

    return (
        df
        .sort_values("date")
        .drop_duplicates(subset=["date"])
        .reset_index(drop=True)
    )


def summarize(df: pd.DataFrame, name: str):
    print(f"\n==== {name} ====")
    print("rows:", len(df))
    print("min date:", df["date"].min())
    print("max date:", df["date"].max())
    print("last 10 dates:")
    print(df["date"].tail(10).dt.strftime("%Y-%m-%d").tolist())


def missing_business_days(df: pd.DataFrame, lookback_days=120):
    end = df["date"].max()
    start = end - pd.Timedelta(days=lookback_days)

    expected = pd.bdate_range(start=start, end=end).normalize()
    actual = pd.DatetimeIndex(df["date"].unique()).normalize()

    missing = expected.difference(actual)
    return missing


def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python scripts/compare_price_sources.py <STOOQ_PARQUET> <ALPHAV_PARQUET>")
        sys.exit(1)

    stooq_path = Path(sys.argv[1])
    alphav_path = Path(sys.argv[2])

    stooq = load_prices(stooq_path, "stooq")
    alphav = load_prices(alphav_path, "alphaV")

    if stooq is None or alphav is None:
        sys.exit(1)

    summarize(stooq, "STOOQ")
    summarize(alphav, "ALPHAV")

    print("\n==== MAX DATE COMPARISON ====")
    print("stooq max :", stooq['date'].max().date())
    print("alphaV max:", alphav['date'].max().date())

    print("\n==== MISSING BUSINESS DAYS (last ~120 days) ====")
    m_stooq = missing_business_days(stooq, lookback_days=120)
    m_alpha = missing_business_days(alphav, lookback_days=120)

    print("stooq missing:", len(m_stooq))
    if len(m_stooq):
        print("  sample:", [d.strftime("%Y-%m-%d") for d in m_stooq[:10]])

    print("alphaV missing:", len(m_alpha))
    if len(m_alpha):
        print("  sample:", [d.strftime("%Y-%m-%d") for d in m_alpha[:10]])

    print("\n==== DATES PRESENT IN ALPHAV BUT NOT IN STOOQ ====")
    stooq_dates = set(stooq["date"])
    extra_alpha = alphav[~alphav["date"].isin(stooq_dates)]

    print("count:", len(extra_alpha))
    if len(extra_alpha):
        print("last 15 alpha-only dates:")
        print(extra_alpha["date"].tail(15).dt.strftime("%Y-%m-%d").tolist())


if __name__ == "__main__":
    main()
