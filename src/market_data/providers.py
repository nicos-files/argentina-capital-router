from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import pandas as pd
import requests
import yfinance as yf

from src.asset_universe import AssetDefinition


REQUIRED_COLS = ["open", "high", "low", "close", "volume"]
YFINANCE_PROVIDER = "yfinance"
ALPHAV_PROVIDER = "alphaV"
ALPHAV_URL = "https://www.alphavantage.co/query"
ALPHAV_API_KEY = ""


@dataclass(frozen=True)
class ProviderHealth:
    provider_name: str
    status: str
    message: str
    checked_at_utc: str


class MarketDataProvider(ABC):
    provider_name: str

    @abstractmethod
    def supports(self, asset: AssetDefinition) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch_price_history(self, asset: AssetDefinition, start_date: str) -> Optional[pd.DataFrame]:
        raise NotImplementedError

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_name=self.provider_name,
            status="healthy",
            message="provider configured",
            checked_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError(f"{self.provider_name} does not implement latest quote access")

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.provider_name} does not implement historical bar access")


class YFinancePriceProvider(MarketDataProvider):
    provider_name = YFINANCE_PROVIDER

    def supports(self, asset: AssetDefinition) -> bool:
        return bool(asset.yfinance_symbol or asset.asset_id)

    def fetch_price_history(self, asset: AssetDefinition, start_date: str) -> Optional[pd.DataFrame]:
        provider_symbol = asset.yfinance_symbol or asset.asset_id
        print(f"[FETCH] {self.provider_name} {asset.asset_id} ({provider_symbol})")
        try:
            df = yf.download(
                provider_symbol,
                start=start_date,
                end=_end_date_exclusive(),
                auto_adjust=False,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            print(f"[FETCH] {asset.asset_id}: error {self.provider_name} {exc}")
            return None
        return _normalize_download(df, asset)


class AlphaVantagePriceProvider(MarketDataProvider):
    provider_name = ALPHAV_PROVIDER

    def supports(self, asset: AssetDefinition) -> bool:
        return _alpha_symbol(asset) is not None

    def health_check(self) -> ProviderHealth:
        status = "healthy" if ALPHAV_API_KEY else "unavailable"
        message = "api key configured" if ALPHAV_API_KEY else "missing api key"
        return ProviderHealth(
            provider_name=self.provider_name,
            status=status,
            message=message,
            checked_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def fetch_price_history(self, asset: AssetDefinition, start_date: str) -> Optional[pd.DataFrame]:
        symbol = _alpha_symbol(asset)
        if not symbol:
            return None

        # Alpha Vantage free rejects TIME_SERIES_DAILY outputsize=full.
        outputsize = "compact"
        if asset.asset_class == "FOREX":
            params = {
                "function": "FX_DAILY",
                "from_symbol": symbol[:3],
                "to_symbol": symbol[3:],
                "outputsize": outputsize,
                "apikey": ALPHAV_API_KEY,
            }
            series_key = "Time Series FX (Daily)"
        else:
            params = {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": outputsize,
                "apikey": ALPHAV_API_KEY,
            }
            series_key = "Time Series (Daily)"

        print(f"[FETCH] {self.provider_name} {asset.asset_id} ({symbol})")
        try:
            response = requests.get(ALPHAV_URL, params=params, timeout=30)
            payload = response.json()
        except Exception as exc:
            print(f"[FETCH] {asset.asset_id}: error {self.provider_name} {exc}")
            return None

        series = payload.get(series_key)
        if not isinstance(series, dict) or not series:
            message = payload.get("Information") or payload.get("Note") or payload.get("Error Message") or "sin datos"
            print(f"[FETCH] {asset.asset_id}: {self.provider_name} sin datos ({message})")
            return None

        df = pd.DataFrame.from_dict(series, orient="index").reset_index().rename(columns={"index": "date"})
        df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]

        if asset.asset_class == "FOREX":
            df = df.rename(
                columns={
                    "1._open": "open",
                    "2._high": "high",
                    "3._low": "low",
                    "4._close": "close",
                }
            )
            if "volume" not in df.columns:
                df["volume"] = 0.0
        else:
            df = df.rename(
                columns={
                    "1._open": "open",
                    "2._high": "high",
                    "3._low": "low",
                    "4._close": "close",
                    "5._volume": "volume",
                }
            )

        normalized = _normalize_download(df, asset)
        if normalized is None or normalized.empty:
            return None
        normalized = normalized[normalized["date"] >= pd.Timestamp(start_date)]
        return normalized if not normalized.empty else None


def build_default_price_providers() -> list[MarketDataProvider]:
    return [YFinancePriceProvider(), AlphaVantagePriceProvider()]


def fetch_price_history_with_fallback(
    asset: AssetDefinition,
    start_date: str,
    providers: Iterable[MarketDataProvider] | None = None,
) -> tuple[str, Optional[pd.DataFrame]]:
    selected = list(providers) if providers is not None else build_default_price_providers()
    attempted_any = False

    for provider in selected:
        if not provider.supports(asset):
            continue
        attempted_any = True
        frame = provider.fetch_price_history(asset, start_date)
        if frame is not None and not frame.empty:
            return provider.provider_name, frame
        print(f"[FETCH] {asset.asset_id}: {provider.provider_name} sin datos utiles")

    if not attempted_any:
        print(f"[FETCH] {asset.asset_id}: sin providers compatibles")
    else:
        print(f"[FETCH] {asset.asset_id}: sin datos utiles")
    fallback_name = selected[0].provider_name if selected else YFINANCE_PROVIDER
    return fallback_name, None


def _end_date_exclusive() -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")


def _normalize_download(df: pd.DataFrame, asset: AssetDefinition) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.reset_index()
    df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
    if "adj_close" in df.columns and "close" not in df.columns:
        df = df.rename(columns={"adj_close": "close"})

    if "date" not in df.columns:
        if "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})
        else:
            return None

    if "volume" not in df.columns and asset.asset_class == "FOREX":
        df["volume"] = 0.0

    missing = [col for col in REQUIRED_COLS if col not in df.columns]
    if missing:
        print(f"[FETCH] {asset.asset_id}: faltan columnas {missing}")
        return None

    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["ticker"] = asset.asset_id
    df["provider_symbol"] = asset.yfinance_symbol or asset.asset_id
    df["asset_class"] = asset.asset_class
    df["market"] = asset.market
    df = df.dropna(subset=["date", "close"]).sort_values("date")
    return df[["date", "ticker"] + REQUIRED_COLS + ["provider_symbol", "asset_class", "market"]]


def _alpha_symbol(asset: AssetDefinition) -> str | None:
    asset_id = asset.asset_id.upper()
    if asset.market == "US":
        return asset_id[:-3] if asset_id.endswith(".US") else asset_id
    if asset.asset_class == "FOREX" and asset_id.endswith(".FX"):
        pair = asset_id[:-3]
        if len(pair) == 6:
            return pair
    return None


