"""Portfolio valuation in USD using a manual market snapshot.

Read-only. No network. No broker. Manual review only.

Values current positions and cash using the optional manual market snapshot:
- ARS-denominated prices are converted to USD using ``USDARS_MEP`` (or a
  configurable FX key) when available.
- USD prices/cash are used directly.
- Positions or cash without a usable price/FX are kept in the output as
  ``MISSING_PRICE`` / ``MISSING_FX`` and contribute a warning, but never raise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.market_data.manual_snapshot import ManualMarketSnapshot, get_fx_rate
from .portfolio_state import (
    CashBalance,
    ManualPortfolioSnapshot,
    PortfolioPosition,
)


PRICED = "PRICED"
MISSING_PRICE = "MISSING_PRICE"
MISSING_FX = "MISSING_FX"
UNSUPPORTED_CURRENCY = "UNSUPPORTED_CURRENCY"
NO_MARKET_SNAPSHOT = "NO_MARKET_SNAPSHOT"


@dataclass(frozen=True)
class ValuedPosition:
    symbol: str
    asset_class: str
    bucket: str
    quantity: float
    price: Optional[float]
    price_currency: Optional[str]
    market_value: Optional[float]
    valuation_currency: str
    weight_pct: Optional[float]
    valuation_status: str
    warnings: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class ValuedCashBalance:
    currency: str
    amount: float
    bucket: str
    value_usd: Optional[float]
    valuation_status: str
    warnings: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class PortfolioValuation:
    as_of: str
    base_currency: str
    total_value_usd: float
    positions: tuple = field(default_factory=tuple)
    cash: tuple = field(default_factory=tuple)
    bucket_weights: dict = field(default_factory=dict)
    warnings: tuple = field(default_factory=tuple)


def get_usdars_rate(
    market_snapshot: Optional[ManualMarketSnapshot],
    key: str = "USDARS_MEP",
) -> Optional[float]:
    """Return the FX rate (ARS per USD) for ``key`` or ``None``.

    Defensive: returns ``None`` if the snapshot is missing, the pair is absent,
    or the rate is non-positive.
    """
    if market_snapshot is None:
        return None
    fx = get_fx_rate(market_snapshot, key)
    if fx is None:
        return None
    try:
        rate = float(fx.rate)
    except (TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return rate


def _value_position(
    position: PortfolioPosition,
    market_snapshot: Optional[ManualMarketSnapshot],
    usdars_rate: Optional[float],
) -> ValuedPosition:
    warnings: list[str] = []

    if market_snapshot is None:
        return ValuedPosition(
            symbol=position.symbol,
            asset_class=position.asset_class,
            bucket=position.bucket,
            quantity=position.quantity,
            price=None,
            price_currency=None,
            market_value=None,
            valuation_currency="USD",
            weight_pct=None,
            valuation_status=NO_MARKET_SNAPSHOT,
            warnings=(
                f"Position {position.symbol} has no market snapshot; "
                "market value unavailable.",
            ),
        )

    quote = market_snapshot.quotes.get(position.symbol)
    if quote is None:
        return ValuedPosition(
            symbol=position.symbol,
            asset_class=position.asset_class,
            bucket=position.bucket,
            quantity=position.quantity,
            price=None,
            price_currency=None,
            market_value=None,
            valuation_currency="USD",
            weight_pct=None,
            valuation_status=MISSING_PRICE,
            warnings=(
                f"Position {position.symbol} has no price in market snapshot.",
            ),
        )

    price = float(quote.price)
    currency = quote.currency.strip().upper()

    if currency == "USD":
        market_value_usd = price * float(position.quantity)
        return ValuedPosition(
            symbol=position.symbol,
            asset_class=position.asset_class,
            bucket=position.bucket,
            quantity=position.quantity,
            price=price,
            price_currency=currency,
            market_value=market_value_usd,
            valuation_currency="USD",
            weight_pct=None,
            valuation_status=PRICED,
            warnings=tuple(),
        )

    if currency == "ARS":
        if usdars_rate is None:
            warnings.append(
                f"Position {position.symbol} priced in ARS but no USDARS_MEP "
                "rate available; market value not computed."
            )
            return ValuedPosition(
                symbol=position.symbol,
                asset_class=position.asset_class,
                bucket=position.bucket,
                quantity=position.quantity,
                price=price,
                price_currency=currency,
                market_value=None,
                valuation_currency="USD",
                weight_pct=None,
                valuation_status=MISSING_FX,
                warnings=tuple(warnings),
            )
        market_value_usd = (price * float(position.quantity)) / usdars_rate
        return ValuedPosition(
            symbol=position.symbol,
            asset_class=position.asset_class,
            bucket=position.bucket,
            quantity=position.quantity,
            price=price,
            price_currency=currency,
            market_value=market_value_usd,
            valuation_currency="USD",
            weight_pct=None,
            valuation_status=PRICED,
            warnings=tuple(),
        )

    warnings.append(
        f"Position {position.symbol} priced in unsupported currency {currency!r}; "
        "market value not computed."
    )
    return ValuedPosition(
        symbol=position.symbol,
        asset_class=position.asset_class,
        bucket=position.bucket,
        quantity=position.quantity,
        price=price,
        price_currency=currency,
        market_value=None,
        valuation_currency="USD",
        weight_pct=None,
        valuation_status=UNSUPPORTED_CURRENCY,
        warnings=tuple(warnings),
    )


def _value_cash(
    cash: CashBalance, usdars_rate: Optional[float]
) -> ValuedCashBalance:
    currency = cash.currency.strip().upper()
    if currency == "USD":
        return ValuedCashBalance(
            currency=currency,
            amount=cash.amount,
            bucket=cash.bucket,
            value_usd=float(cash.amount),
            valuation_status=PRICED,
            warnings=tuple(),
        )
    if currency == "ARS":
        if usdars_rate is None:
            return ValuedCashBalance(
                currency=currency,
                amount=cash.amount,
                bucket=cash.bucket,
                value_usd=None,
                valuation_status=MISSING_FX,
                warnings=(
                    "ARS cash present but no USDARS_MEP rate available; "
                    "cash value not converted to USD.",
                ),
            )
        return ValuedCashBalance(
            currency=currency,
            amount=cash.amount,
            bucket=cash.bucket,
            value_usd=float(cash.amount) / usdars_rate,
            valuation_status=PRICED,
            warnings=tuple(),
        )
    return ValuedCashBalance(
        currency=currency,
        amount=cash.amount,
        bucket=cash.bucket,
        value_usd=None,
        valuation_status=UNSUPPORTED_CURRENCY,
        warnings=(
            f"Cash currency {currency!r} unsupported; not converted to USD.",
        ),
    )


def _compute_bucket_weights(
    positions: Iterable[ValuedPosition],
    cash: Iterable[ValuedCashBalance],
    total_value_usd: float,
) -> dict[str, float]:
    if total_value_usd <= 0:
        return {}
    by_bucket: dict[str, float] = {}
    for p in positions:
        if p.market_value is None:
            continue
        by_bucket[p.bucket] = by_bucket.get(p.bucket, 0.0) + float(p.market_value)
    for c in cash:
        if c.value_usd is None:
            continue
        by_bucket[c.bucket] = by_bucket.get(c.bucket, 0.0) + float(c.value_usd)
    return {
        bucket: (value / total_value_usd) * 100.0
        for bucket, value in by_bucket.items()
    }


def value_portfolio(
    portfolio: ManualPortfolioSnapshot,
    market_snapshot: Optional[ManualMarketSnapshot] = None,
    fallback_usdars_rate_key: str = "USDARS_MEP",
) -> PortfolioValuation:
    """Value a manual portfolio snapshot in USD.

    Returns a :class:`PortfolioValuation` with per-position and per-cash details.
    Missing prices or FX rates are recorded as warnings on the affected entries
    rather than raised.
    """
    usdars_rate = get_usdars_rate(market_snapshot, key=fallback_usdars_rate_key)

    warnings: list[str] = []
    if market_snapshot is None:
        warnings.append(
            "No market snapshot provided; positions cannot be priced and "
            "bucket weights cannot be computed."
        )
    elif usdars_rate is None and any(
        c.currency.strip().upper() == "ARS" for c in portfolio.cash
    ):
        warnings.append(
            f"Market snapshot lacks {fallback_usdars_rate_key!r} FX rate; "
            "ARS cash will not be converted to USD."
        )

    valued_positions = tuple(
        _value_position(p, market_snapshot, usdars_rate)
        for p in portfolio.positions
    )
    valued_cash = tuple(_value_cash(c, usdars_rate) for c in portfolio.cash)

    # Aggregate any per-entry warnings up to the top-level list (de-duplicated,
    # order-preserving).
    seen: set[str] = set(warnings)
    for entry in (*valued_positions, *valued_cash):
        for w in entry.warnings:
            if w not in seen:
                seen.add(w)
                warnings.append(w)

    total_value_usd = 0.0
    for p in valued_positions:
        if p.market_value is not None:
            total_value_usd += float(p.market_value)
    for c in valued_cash:
        if c.value_usd is not None:
            total_value_usd += float(c.value_usd)

    bucket_weights = _compute_bucket_weights(
        valued_positions, valued_cash, total_value_usd
    )

    if total_value_usd <= 0:
        warnings.append(
            "Portfolio total valued at 0 USD; cannot compute bucket weights."
        )

    # Backfill weight_pct on priced positions (immutable dataclass -> rebuild).
    if total_value_usd > 0:
        rebuilt: list[ValuedPosition] = []
        for p in valued_positions:
            if p.market_value is None:
                rebuilt.append(p)
                continue
            weight = (float(p.market_value) / total_value_usd) * 100.0
            rebuilt.append(
                ValuedPosition(
                    symbol=p.symbol,
                    asset_class=p.asset_class,
                    bucket=p.bucket,
                    quantity=p.quantity,
                    price=p.price,
                    price_currency=p.price_currency,
                    market_value=p.market_value,
                    valuation_currency=p.valuation_currency,
                    weight_pct=weight,
                    valuation_status=p.valuation_status,
                    warnings=p.warnings,
                )
            )
        valued_positions = tuple(rebuilt)

    return PortfolioValuation(
        as_of=portfolio.as_of,
        base_currency=portfolio.base_currency,
        total_value_usd=total_value_usd,
        positions=valued_positions,
        cash=valued_cash,
        bucket_weights=bucket_weights,
        warnings=tuple(warnings),
    )


__all__ = [
    "PRICED",
    "MISSING_PRICE",
    "MISSING_FX",
    "UNSUPPORTED_CURRENCY",
    "NO_MARKET_SNAPSHOT",
    "ValuedPosition",
    "ValuedCashBalance",
    "PortfolioValuation",
    "get_usdars_rate",
    "value_portfolio",
]
