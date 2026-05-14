"""Manual-input quality checks.

Manual review only. No network. No broker. No live trading. No orders.

These checks are layered on top of the schema validation done by the
existing loaders. The loaders enforce structural correctness and
``manual_review_only`` / ``live_trading_enabled`` invariants; this module
adds *semantic* checks intended to catch realistic mistakes a human can
make while filling in manual snapshots:

- TODO/placeholder markers left over from generated templates.
- Suspicious numeric placeholders (prices/FX equal to 1.0, etc.).
- Snapshot date mismatches against the workflow date.
- Symbols outside of the configured Argentina/CEDEAR universe.
- Missing FX rates required for ARS conversion.
- Portfolio positions without a matching market quote.

Everything is reported as a structured ``InputQualityIssue``. In strict
mode (``combine_quality_reports(..., strict=True)``), a curated subset of
warning codes is promoted to ``ERROR`` so the workflow can refuse to
proceed before producing artifacts.

This module is read-only. It does not call the network, does not write
files, and does not introduce broker or trading logic.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence

from src.manual_execution.execution_tracker import ManualExecutionLog
from src.market_data.ar_symbols import ArgentinaAsset, normalize_ar_symbol
from src.market_data.manual_snapshot import (
    ManualMarketSnapshot,
    normalize_fx_pair,
)
from src.portfolio.portfolio_state import ManualPortfolioSnapshot


SEVERITY_ERROR = "ERROR"
SEVERITY_WARNING = "WARNING"
SEVERITY_INFO = "INFO"

_VALID_SEVERITIES = frozenset(
    {SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO}
)

# Codes whose WARNING-severity issues are promoted to ERROR in strict mode.
#
# ``MISSING_RATE_INPUT`` is intentionally *not* promoted: a missing rate
# input usually triggers the broader ``INCOMPLETE_SNAPSHOT`` warning,
# which already fails strict mode. ``MISSING_RATE_INPUT`` exists only to
# give the user a more specific message about *which* rate is missing.
_STRICT_PROMOTABLE_CODES = frozenset(
    {
        "TODO_MARKER",
        "PLACEHOLDER_VALUE",
        "SNAPSHOT_DATE_MISMATCH",
        "UNKNOWN_SYMBOL",
        "INCOMPLETE_SNAPSHOT",
        "MISSING_REQUIRED_FX",
        "MISSING_POSITION_PRICE",
    }
)

# Rate-input keys that the workflow considers "expected" for a fully
# specified market snapshot. Missing any of these surfaces a
# ``MISSING_RATE_INPUT`` warning. The list is intentionally short and
# does not include exotic / optional keys.
_EXPECTED_RATE_KEYS: tuple[str, ...] = (
    "money_market_monthly_pct",
    "caucion_monthly_pct",
    "expected_fx_devaluation_monthly_pct",
)

# Case-insensitive markers in string fields that indicate a placeholder.
_TODO_PATTERNS = (
    re.compile(r"\btodo\b", re.IGNORECASE),
    re.compile(r"\bplaceholder\b", re.IGNORECASE),
    re.compile(r"template\s+file", re.IGNORECASE),
    re.compile(r"\breplace\b", re.IGNORECASE),
)

# Numeric values that look like obvious placeholders.
_PLACEHOLDER_PRICE = 1.0
_PLACEHOLDER_FX_RATE = 1.0
_PLACEHOLDER_QUANTITY = 1.0
_PLACEHOLDER_AVG_COST = 1.0
_PLACEHOLDER_CASH = 1.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputQualityIssue:
    severity: str
    code: str
    message: str
    path: Optional[str] = None
    symbol: Optional[str] = None

    def __post_init__(self) -> None:  # pragma: no cover - trivial guard
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"InputQualityIssue: invalid severity {self.severity!r}"
            )


@dataclass(frozen=True)
class InputQualityReport:
    ok: bool
    strict: bool
    issues: tuple[InputQualityIssue, ...] = field(default_factory=tuple)

    @property
    def errors_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_ERROR)

    @property
    def warnings_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_WARNING)

    @property
    def infos_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == SEVERITY_INFO)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "strict": bool(self.strict),
            "errors_count": self.errors_count,
            "warnings_count": self.warnings_count,
            "infos_count": self.infos_count,
            "issues": [asdict(issue) for issue in self.issues],
        }


# ---------------------------------------------------------------------------
# Detectors (raw-JSON level)
# ---------------------------------------------------------------------------


def _walk(obj: Any, path: str = ""):
    """Yield ``(path, value)`` for every leaf in a JSON-like object."""
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            child = f"{path}.{key}" if path else str(key)
            yield from _walk(value, child)
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            child = f"{path}[{index}]"
            yield from _walk(value, child)
    else:
        yield path, obj


def detect_todo_markers(
    obj: Any, path: str = ""
) -> list[InputQualityIssue]:
    """Recursively detect TODO/placeholder markers in string fields."""
    issues: list[InputQualityIssue] = []
    for leaf_path, value in _walk(obj, path=path):
        if not isinstance(value, str) or not value.strip():
            continue
        for pattern in _TODO_PATTERNS:
            if pattern.search(value):
                issues.append(
                    InputQualityIssue(
                        severity=SEVERITY_WARNING,
                        code="TODO_MARKER",
                        message=(
                            f"placeholder/TODO marker detected: {value!r}"
                        ),
                        path=leaf_path or None,
                    )
                )
                break
    return issues


def detect_placeholder_numeric_values(
    obj: Any, snapshot_kind: str
) -> list[InputQualityIssue]:
    """Detect obvious numeric placeholders for a given snapshot kind.

    ``snapshot_kind`` accepts ``"market"`` or ``"portfolio"``. Anything else
    is treated as unknown and yields no issues.
    """
    issues: list[InputQualityIssue] = []
    if not isinstance(obj, Mapping):
        return issues

    if snapshot_kind == "market":
        quotes = obj.get("quotes")
        if isinstance(quotes, list):
            for index, quote in enumerate(quotes):
                if not isinstance(quote, Mapping):
                    continue
                price = quote.get("price")
                if _is_placeholder_number(price, _PLACEHOLDER_PRICE):
                    issues.append(
                        InputQualityIssue(
                            severity=SEVERITY_WARNING,
                            code="PLACEHOLDER_VALUE",
                            message=(
                                f"quote price looks like a placeholder ({price})"
                            ),
                            path=f"quotes[{index}].price",
                            symbol=_safe_str(quote.get("symbol")),
                        )
                    )
        fx_rates = obj.get("fx_rates")
        if isinstance(fx_rates, Mapping):
            for pair, entry in fx_rates.items():
                if not isinstance(entry, Mapping):
                    continue
                rate = entry.get("rate")
                if _is_placeholder_number(rate, _PLACEHOLDER_FX_RATE):
                    issues.append(
                        InputQualityIssue(
                            severity=SEVERITY_WARNING,
                            code="PLACEHOLDER_VALUE",
                            message=(
                                f"fx rate looks like a placeholder ({rate})"
                            ),
                            path=f"fx_rates.{pair}.rate",
                        )
                    )
        rates = obj.get("rates")
        if isinstance(rates, Mapping) and rates:
            all_zero = True
            for entry in rates.values():
                if not isinstance(entry, Mapping):
                    all_zero = False
                    break
                value = entry.get("value")
                try:
                    if float(value) != 0.0:
                        all_zero = False
                        break
                except (TypeError, ValueError):
                    all_zero = False
                    break
            if all_zero:
                issues.append(
                    InputQualityIssue(
                        severity=SEVERITY_WARNING,
                        code="PLACEHOLDER_VALUE",
                        message=(
                            "all rate inputs are zero - "
                            "looks like an unedited template"
                        ),
                        path="rates",
                    )
                )

    elif snapshot_kind == "portfolio":
        positions = obj.get("positions")
        if isinstance(positions, list):
            for index, position in enumerate(positions):
                if not isinstance(position, Mapping):
                    continue
                quantity = position.get("quantity")
                avg_cost = position.get("average_cost")
                if _is_placeholder_number(
                    quantity, _PLACEHOLDER_QUANTITY
                ) and _is_placeholder_number(avg_cost, _PLACEHOLDER_AVG_COST):
                    issues.append(
                        InputQualityIssue(
                            severity=SEVERITY_WARNING,
                            code="PLACEHOLDER_VALUE",
                            message=(
                                "position quantity/average_cost both equal 1.0 - "
                                "looks like a placeholder"
                            ),
                            path=f"positions[{index}]",
                            symbol=_safe_str(position.get("symbol")),
                        )
                    )
        cash = obj.get("cash")
        if isinstance(cash, list):
            for index, balance in enumerate(cash):
                if not isinstance(balance, Mapping):
                    continue
                amount = balance.get("amount")
                if _is_placeholder_number(amount, _PLACEHOLDER_CASH):
                    issues.append(
                        InputQualityIssue(
                            severity=SEVERITY_WARNING,
                            code="PLACEHOLDER_VALUE",
                            message=(
                                f"cash amount looks like a placeholder ({amount})"
                            ),
                            path=f"cash[{index}].amount",
                        )
                    )
    return issues


# ---------------------------------------------------------------------------
# Cross-field validators (parsed-snapshot level)
# ---------------------------------------------------------------------------


def validate_snapshot_dates(
    expected_date: Optional[str],
    market_snapshot: Optional[ManualMarketSnapshot] = None,
    portfolio_snapshot: Optional[ManualPortfolioSnapshot] = None,
    execution_log: Optional[ManualExecutionLog] = None,
) -> list[InputQualityIssue]:
    """Validate that snapshot ``as_of`` matches the workflow's expected date."""
    issues: list[InputQualityIssue] = []
    if not expected_date:
        return issues
    expected = str(expected_date).strip()
    if not expected:
        return issues

    def _check(label: str, value: Optional[str]) -> None:
        if value is None:
            return
        if str(value).strip() != expected:
            issues.append(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="SNAPSHOT_DATE_MISMATCH",
                    message=(
                        f"{label} as_of={value!r} does not match "
                        f"expected_date={expected!r}"
                    ),
                    path=f"{label}.as_of",
                )
            )

    if market_snapshot is not None:
        _check("market_snapshot", market_snapshot.as_of)
    if portfolio_snapshot is not None:
        _check("portfolio_snapshot", portfolio_snapshot.as_of)
    if execution_log is not None:
        _check("execution_log", execution_log.as_of)
        for index, execution in enumerate(execution_log.executions):
            executed_at = getattr(execution, "executed_at", None)
            if isinstance(executed_at, str) and executed_at.strip():
                # Compare just the date prefix so timestamps like
                # "2026-05-12T15:30:00-03:00" still match the expected date.
                if not executed_at.startswith(expected):
                    issues.append(
                        InputQualityIssue(
                            severity=SEVERITY_WARNING,
                            code="SNAPSHOT_DATE_MISMATCH",
                            message=(
                                f"execution executed_at={executed_at!r} does "
                                f"not match expected_date={expected!r}"
                            ),
                            path=f"executions[{index}].executed_at",
                            symbol=getattr(execution, "symbol", None),
                        )
                    )
    return issues


def validate_symbols_in_universe(
    market_snapshot: Optional[ManualMarketSnapshot],
    portfolio_snapshot: Optional[ManualPortfolioSnapshot],
    universe_assets: Sequence[ArgentinaAsset],
) -> list[InputQualityIssue]:
    """Flag quote/position symbols missing from the configured universe."""
    issues: list[InputQualityIssue] = []
    if not universe_assets:
        return issues
    universe_symbols = {asset.symbol for asset in universe_assets}

    def _check(symbol: str, where: str, path: str) -> None:
        try:
            normalized = normalize_ar_symbol(symbol)
        except (TypeError, ValueError):
            normalized = symbol
        if normalized not in universe_symbols:
            issues.append(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="UNKNOWN_SYMBOL",
                    message=(
                        f"{where} symbol {normalized!r} is not in the "
                        "configured Argentina/CEDEAR universe"
                    ),
                    path=path,
                    symbol=normalized,
                )
            )

    if market_snapshot is not None:
        for index, symbol in enumerate(market_snapshot.quotes.keys()):
            _check(symbol, "market quote", f"quotes[{index}]")
    if portfolio_snapshot is not None:
        for index, position in enumerate(portfolio_snapshot.positions):
            _check(
                position.symbol,
                "portfolio position",
                f"positions[{index}]",
            )
    return issues


# ---------------------------------------------------------------------------
# Snapshot-level validators
# ---------------------------------------------------------------------------


def validate_market_snapshot_quality(
    raw_market_data: Optional[Mapping[str, Any]],
    market_snapshot: ManualMarketSnapshot,
    expected_date: Optional[str] = None,
    universe_assets: Optional[Sequence[ArgentinaAsset]] = None,
    strict: bool = False,
) -> InputQualityReport:
    issues: list[InputQualityIssue] = []

    if raw_market_data is not None:
        issues.extend(detect_todo_markers(raw_market_data))
        issues.extend(
            detect_placeholder_numeric_values(raw_market_data, "market")
        )

    if market_snapshot.completeness != "complete":
        issues.append(
            InputQualityIssue(
                severity=SEVERITY_WARNING,
                code="INCOMPLETE_SNAPSHOT",
                message=(
                    "market snapshot completeness is "
                    f"{market_snapshot.completeness!r}, expected 'complete'"
                ),
                path="quality.completeness",
            )
        )

    issues.extend(
        validate_snapshot_dates(
            expected_date, market_snapshot=market_snapshot
        )
    )

    if universe_assets:
        issues.extend(
            validate_symbols_in_universe(
                market_snapshot=market_snapshot,
                portfolio_snapshot=None,
                universe_assets=universe_assets,
            )
        )

    # Missing USDARS_MEP when any quote is denominated in ARS.
    has_ars_quote = any(
        q.currency.upper() == "ARS" for q in market_snapshot.quotes.values()
    )
    if has_ars_quote:
        try:
            usdars_key = normalize_fx_pair("USDARS_MEP")
        except ValueError:
            usdars_key = "USDARS_MEP"
        if usdars_key not in market_snapshot.fx_rates:
            issues.append(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="MISSING_REQUIRED_FX",
                    message=(
                        "at least one quote is in ARS but USDARS_MEP "
                        "is not in fx_rates"
                    ),
                    path="fx_rates.USDARS_MEP",
                )
            )

    # Targeted per-key warnings for expected rate inputs. The broader
    # ``INCOMPLETE_SNAPSHOT`` warning already fails strict mode when any
    # rate is missing; this one just makes the missing key obvious in the
    # report instead of forcing the reader to diff completeness manually.
    for rate_key in _EXPECTED_RATE_KEYS:
        if rate_key not in market_snapshot.rates:
            issues.append(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="MISSING_RATE_INPUT",
                    message=(
                        f"expected rate input {rate_key!r} is missing; "
                        "supply it via --*-pct CLI flags or a manual snapshot"
                    ),
                    path=f"rates.{rate_key}",
                )
            )

    issues.append(
        InputQualityIssue(
            severity=SEVERITY_INFO,
            code="MANUAL_REVIEW_ONLY",
            message="manual_review_only=true / live_trading_enabled=false",
            path="manual_review_only",
        )
    )

    return _finalize(issues, strict=strict)


def validate_portfolio_snapshot_quality(
    raw_portfolio_data: Optional[Mapping[str, Any]],
    portfolio_snapshot: ManualPortfolioSnapshot,
    expected_date: Optional[str] = None,
    market_snapshot: Optional[ManualMarketSnapshot] = None,
    universe_assets: Optional[Sequence[ArgentinaAsset]] = None,
    strict: bool = False,
) -> InputQualityReport:
    issues: list[InputQualityIssue] = []

    if raw_portfolio_data is not None:
        issues.extend(detect_todo_markers(raw_portfolio_data))
        issues.extend(
            detect_placeholder_numeric_values(raw_portfolio_data, "portfolio")
        )

    if portfolio_snapshot.completeness != "complete":
        issues.append(
            InputQualityIssue(
                severity=SEVERITY_WARNING,
                code="INCOMPLETE_SNAPSHOT",
                message=(
                    "portfolio snapshot completeness is "
                    f"{portfolio_snapshot.completeness!r}, expected 'complete'"
                ),
                path="quality.completeness",
            )
        )

    issues.extend(
        validate_snapshot_dates(
            expected_date, portfolio_snapshot=portfolio_snapshot
        )
    )

    if universe_assets:
        issues.extend(
            validate_symbols_in_universe(
                market_snapshot=None,
                portfolio_snapshot=portfolio_snapshot,
                universe_assets=universe_assets,
            )
        )

    if market_snapshot is not None:
        # Any portfolio position must have a matching quote, else its value
        # is unknown.
        for index, position in enumerate(portfolio_snapshot.positions):
            if position.symbol not in market_snapshot.quotes:
                issues.append(
                    InputQualityIssue(
                        severity=SEVERITY_WARNING,
                        code="MISSING_POSITION_PRICE",
                        message=(
                            f"portfolio position {position.symbol!r} has no "
                            "matching quote in the market snapshot"
                        ),
                        path=f"positions[{index}]",
                        symbol=position.symbol,
                    )
                )
        # ARS cash or ARS-priced positions require USDARS_MEP to value in USD.
        try:
            usdars_key = normalize_fx_pair("USDARS_MEP")
        except ValueError:
            usdars_key = "USDARS_MEP"
        needs_ars_fx = any(
            balance.currency.upper() == "ARS"
            for balance in portfolio_snapshot.cash
        )
        if not needs_ars_fx:
            for position in portfolio_snapshot.positions:
                quote = market_snapshot.quotes.get(position.symbol)
                if quote is not None and quote.currency.upper() == "ARS":
                    needs_ars_fx = True
                    break
        if needs_ars_fx and usdars_key not in market_snapshot.fx_rates:
            issues.append(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="MISSING_REQUIRED_FX",
                    message=(
                        "ARS amounts present but USDARS_MEP missing in "
                        "the market snapshot - portfolio cannot be valued in USD"
                    ),
                    path="fx_rates.USDARS_MEP",
                )
            )
    else:
        issues.append(
            InputQualityIssue(
                severity=SEVERITY_INFO,
                code="MARKET_SNAPSHOT_NOT_PROVIDED",
                message=(
                    "no market snapshot provided; portfolio valuation will be partial"
                ),
            )
        )

    return _finalize(issues, strict=strict)


def validate_execution_log_quality(
    raw_execution_data: Optional[Mapping[str, Any]],
    execution_log: ManualExecutionLog,
    expected_date: Optional[str] = None,
    strict: bool = False,
) -> InputQualityReport:
    issues: list[InputQualityIssue] = []

    if raw_execution_data is not None:
        issues.extend(detect_todo_markers(raw_execution_data))

    if execution_log.completeness != "complete":
        issues.append(
            InputQualityIssue(
                severity=SEVERITY_WARNING,
                code="INCOMPLETE_SNAPSHOT",
                message=(
                    "execution log completeness is "
                    f"{execution_log.completeness!r}, expected 'complete'"
                ),
                path="quality.completeness",
            )
        )

    issues.extend(
        validate_snapshot_dates(expected_date, execution_log=execution_log)
    )
    return _finalize(issues, strict=strict)


# ---------------------------------------------------------------------------
# Combination + strict promotion
# ---------------------------------------------------------------------------


def combine_quality_reports(
    *reports: InputQualityReport, strict: bool = False
) -> InputQualityReport:
    """Combine multiple reports; promote select WARNINGs to ERROR in strict mode."""
    all_issues: list[InputQualityIssue] = []
    for report in reports:
        if report is None:
            continue
        all_issues.extend(report.issues)
    return _finalize(all_issues, strict=strict)


def _finalize(
    issues: Iterable[InputQualityIssue], *, strict: bool
) -> InputQualityReport:
    promoted: list[InputQualityIssue] = []
    for issue in issues:
        if (
            strict
            and issue.severity == SEVERITY_WARNING
            and issue.code in _STRICT_PROMOTABLE_CODES
        ):
            promoted.append(
                InputQualityIssue(
                    severity=SEVERITY_ERROR,
                    code=issue.code,
                    message=issue.message,
                    path=issue.path,
                    symbol=issue.symbol,
                )
            )
        else:
            promoted.append(issue)
    ok = not any(i.severity == SEVERITY_ERROR for i in promoted)
    return InputQualityReport(ok=ok, strict=bool(strict), issues=tuple(promoted))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_placeholder_number(value: Any, placeholder: float) -> bool:
    try:
        return float(value) == float(placeholder)
    except (TypeError, ValueError):
        return False


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:  # pragma: no cover - defensive
        return None
    return s or None


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "SEVERITY_INFO",
    "InputQualityIssue",
    "InputQualityReport",
    "combine_quality_reports",
    "detect_placeholder_numeric_values",
    "detect_todo_markers",
    "validate_execution_log_quality",
    "validate_market_snapshot_quality",
    "validate_portfolio_snapshot_quality",
    "validate_snapshot_dates",
    "validate_symbols_in_universe",
]
