"""Binance Spot **Testnet**-only HTTP client.

Hard-locked to ``https://testnet.binance.vision`` (or any test-supplied
mock URL whose hostname includes ``testnet`` or starts with ``http://localhost``
/ ``http://127.0.0.1``). Live Binance hosts (``api.binance.com``,
``api.binance.us``, ``fapi.binance.com``, etc.) are rejected at construction
and at every request site.

Safety contract:

- The client refuses any URL that is not testnet or local-mock.
- Only a fixed allowlist of endpoints is callable. Withdrawals, futures,
  margin, lending, savings, and convert endpoints are never reachable, even
  if the caller passes their path as a string: the path must match an entry
  in ``ALLOWED_ENDPOINTS``.
- The API secret is HMAC-SHA256-used to sign queries but is never returned,
  logged, or embedded in error messages. Errors that bubble up the network
  stack are scrubbed of both the API key and the API secret before being
  raised.
- ``order_test`` calls ``POST /api/v3/order/test`` (Binance's no-op validation
  endpoint that never places an order). ``place_order`` calls
  ``POST /api/v3/order`` and is expected to be invoked only when the executor
  has cleared its ``order_test`` gate.
- Every signed request includes ``timestamp`` (ms) and ``recvWindow`` per the
  Binance request-security specification.

This module performs *no* business logic. It speaks HTTP only. The
:mod:`src.execution.binance_testnet_executor` module is the only intended
caller from inside the bot and is responsible for env-gating, max-notional,
symbol allowlists, idempotency, and artifact writes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any, Iterable, Mapping
from urllib import error, request

DEFAULT_TESTNET_BASE_URL = "https://testnet.binance.vision"

# The canonical set of testnet/known-mock host substrings. Any base URL whose
# hostname does not contain one of these substrings is rejected. The localhost
# / 127.0.0.1 entries are intentionally limited to ``http://`` to keep the
# allowlist obvious for unit tests that spin up an in-process WSGI mock.
_TESTNET_HOST_SUBSTRINGS: tuple[str, ...] = ("testnet.binance.vision",)
_LOCAL_MOCK_PREFIXES: tuple[str, ...] = (
    "http://localhost",
    "http://127.0.0.1",
)

# Hosts that we must NEVER speak to from this module, even if a misconfigured
# env var tries to. The check is defensive and additive on top of the
# allowlist above.
_FORBIDDEN_HOST_SUBSTRINGS: tuple[str, ...] = (
    "api.binance.com",
    "api1.binance.com",
    "api2.binance.com",
    "api3.binance.com",
    "api4.binance.com",
    "api.binance.us",
    "fapi.binance.com",  # USDT-M futures
    "fapi.binance.us",
    "dapi.binance.com",  # COIN-M futures
    "vapi.binance.com",  # options
    "eapi.binance.com",  # european options
    "papi.binance.com",  # portfolio margin
)

# Endpoint allowlist. Path-only (no query string). Anything not present here
# is rejected with :class:`BinanceTestnetConfigError`. This is the single
# source of truth for what the testnet client is allowed to call.
ALLOWED_ENDPOINTS: frozenset[str] = frozenset(
    {
        "/api/v3/ping",
        "/api/v3/time",
        "/api/v3/exchangeInfo",
        "/api/v3/account",
        "/api/v3/openOrders",
        "/api/v3/allOrders",
        "/api/v3/order",        # POST = place order; GET = query order; DELETE = cancel
        "/api/v3/order/test",   # POST only; validation, never places
    }
)

# Endpoints we explicitly forbid even on testnet. Withdrawals do not exist on
# Binance Spot Testnet but we keep the path here as a defensive marker.
FORBIDDEN_ENDPOINT_SUBSTRINGS: tuple[str, ...] = (
    "/wapi",                  # legacy withdraw API
    "/sapi/v1/capital/withdraw",
    "/sapi/v1/margin",
    "/sapi/v1/lending",
    "/sapi/v1/savings",
    "/sapi/v1/convert",
    "/fapi",                  # futures
    "/dapi",                  # delivery futures
    "/vapi",                  # options
    "/eapi",                  # european options
    "/papi",                  # portfolio margin
)

_REDACTED = "[REDACTED]"
_DEFAULT_RECV_WINDOW_MS = 5000
_DEFAULT_TIMEOUT_SEC = 10.0


class BinanceTestnetConfigError(ValueError):
    """Raised when a base URL, endpoint, or credential is invalid.

    Always carries a non-secret message.
    """


class BinanceTestnetRequestError(RuntimeError):
    """Raised when a testnet HTTP request fails. Always credential-redacted."""


def is_testnet_base_url(base_url: str) -> bool:
    """Return ``True`` only if ``base_url`` points at the public testnet or a
    locally-running mock host explicitly allowed for unit tests.

    The check is strict: a missing scheme, an unknown host, or any
    Binance-live host substring causes ``False``. The function never raises;
    callers are expected to translate ``False`` into a config error.
    """

    if not isinstance(base_url, str) or not base_url.strip():
        return False
    candidate = base_url.strip()
    lowered = candidate.lower()
    for forbidden in _FORBIDDEN_HOST_SUBSTRINGS:
        if forbidden in lowered:
            return False
    for prefix in _LOCAL_MOCK_PREFIXES:
        if lowered.startswith(prefix):
            return True
    parsed = urllib.parse.urlsplit(candidate)
    if not parsed.scheme or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    return any(marker in host for marker in _TESTNET_HOST_SUBSTRINGS)


def _redact(text: str, *secrets: str) -> str:
    """Return ``text`` with each non-empty ``secret`` replaced by ``[REDACTED]``."""

    safe = str(text)
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, _REDACTED)
    return safe


def _validate_endpoint(path: str) -> str:
    if not isinstance(path, str) or not path.startswith("/"):
        raise BinanceTestnetConfigError(
            f"Endpoint path must start with '/': {path!r}"
        )
    cleaned = path.split("?", 1)[0]
    lowered = cleaned.lower()
    for forbidden in FORBIDDEN_ENDPOINT_SUBSTRINGS:
        if forbidden in lowered:
            raise BinanceTestnetConfigError(
                f"Forbidden endpoint blocked: {cleaned!r}"
            )
    if cleaned not in ALLOWED_ENDPOINTS:
        raise BinanceTestnetConfigError(
            f"Endpoint not in allowlist: {cleaned!r}"
        )
    return cleaned


def build_query_string(params: Mapping[str, Any] | None) -> str:
    """Build a deterministic ``key=value&key=value`` query string.

    Keys are sorted to make signatures reproducible. ``None`` values are
    dropped (they would otherwise be sent as the literal ``"None"``).
    """

    if not params:
        return ""
    items: list[tuple[str, str]] = []
    for key in sorted(params.keys()):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, bool):
            items.append((str(key), "true" if value else "false"))
            continue
        items.append((str(key), str(value)))
    return urllib.parse.urlencode(items, doseq=False)


def sign_query(query_string: str, *, api_secret: str) -> str:
    """Return the lowercase hex HMAC-SHA256 of ``query_string`` with ``api_secret``.

    Per Binance security spec, the signature is computed over the *exact*
    query-string the server will see (without the leading ``?``).
    """

    if not isinstance(api_secret, str) or not api_secret:
        raise BinanceTestnetConfigError(
            "sign_query requires a non-empty api_secret"
        )
    digest = hmac.new(
        api_secret.encode("utf-8"),
        msg=query_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return digest


def resolve_credentials(
    *,
    api_key: str | None = None,
    api_secret: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve testnet credentials from explicit args or env.

    Env keys: ``BINANCE_TESTNET_API_KEY``, ``BINANCE_TESTNET_API_SECRET``.
    Live env keys (``BINANCE_API_KEY``, etc.) are deliberately *not* read.
    """

    import os

    source: Mapping[str, str] = env if env is not None else os.environ
    resolved_key = (api_key if api_key is not None else source.get("BINANCE_TESTNET_API_KEY")) or ""
    resolved_secret = (
        api_secret if api_secret is not None else source.get("BINANCE_TESTNET_API_SECRET")
    ) or ""
    resolved_key = resolved_key.strip()
    resolved_secret = resolved_secret.strip()
    if not resolved_key:
        raise BinanceTestnetConfigError(
            "Missing BINANCE_TESTNET_API_KEY (or pass api_key=)."
        )
    if not resolved_secret:
        raise BinanceTestnetConfigError(
            "Missing BINANCE_TESTNET_API_SECRET (or pass api_secret=)."
        )
    return resolved_key, resolved_secret


def mask_api_key(api_key: str) -> str:
    text = str(api_key or "")
    if len(text) <= 4:
        return "*" * len(text)
    return ("*" * (len(text) - 4)) + text[-4:]


class BinanceSpotTestnetClient:
    """Minimal Binance Spot Testnet HTTP client.

    The client:

    - Validates ``base_url`` against the testnet allowlist at construction.
    - Validates every endpoint path against :data:`ALLOWED_ENDPOINTS` at the
      request site.
    - Signs query strings with HMAC-SHA256 over ``api_secret``.
    - Adds ``timestamp`` (server-aligned ms) and ``recvWindow`` to every
      signed request.
    - Redacts both ``api_key`` and ``api_secret`` from any error message it
      raises.
    - Calls ``opener(req, timeout=...)``; tests inject a fake opener so no
      real network I/O ever happens during the test suite.
    """

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str = DEFAULT_TESTNET_BASE_URL,
        recv_window_ms: int = _DEFAULT_RECV_WINDOW_MS,
        timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
        opener: Any = None,
        clock_ms: Any = None,
    ) -> None:
        if not is_testnet_base_url(base_url):
            raise BinanceTestnetConfigError(
                f"base_url is not a testnet host: {base_url!r}"
            )
        if not api_key or not str(api_key).strip():
            raise BinanceTestnetConfigError("api_key is required")
        if not api_secret or not str(api_secret).strip():
            raise BinanceTestnetConfigError("api_secret is required")
        if int(recv_window_ms) <= 0 or int(recv_window_ms) > 60_000:
            raise BinanceTestnetConfigError(
                "recv_window_ms must be in (0, 60000]"
            )
        self._api_key = str(api_key).strip()
        self._api_secret = str(api_secret).strip()
        self._base_url = base_url.rstrip("/")
        self._recv_window_ms = int(recv_window_ms)
        self._timeout_sec = float(timeout_sec)
        self._opener = opener if opener is not None else request.urlopen
        self._clock_ms = clock_ms if clock_ms is not None else (lambda: int(time.time() * 1000))

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key_masked(self) -> str:
        return mask_api_key(self._api_key)

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------

    def ping(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/ping", params=None, signed=False)

    def server_time(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/time", params=None, signed=False)

    def exchange_info(self, symbols: Iterable[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbols:
            normalized = [str(s).upper() for s in symbols if str(s).strip()]
            if normalized:
                params["symbols"] = json.dumps(normalized, separators=(",", ":"))
        return self._request(
            "GET", "/api/v3/exchangeInfo", params=params or None, signed=False
        )

    # ------------------------------------------------------------------
    # Signed endpoints
    # ------------------------------------------------------------------

    def account(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/account", params={}, signed=True)

    def open_orders(self, *, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = str(symbol).upper()
        return self._request("GET", "/api/v3/openOrders", params=params, signed=True)

    def all_orders(
        self, *, symbol: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": str(symbol).upper()}
        if limit is not None:
            params["limit"] = int(limit)
        return self._request("GET", "/api/v3/allOrders", params=params, signed=True)

    def order_test(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/v3/order/test`` — Binance no-op validator. Never places."""

        return self._request("POST", "/api/v3/order/test", params=params, signed=True)

    def place_order(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /api/v3/order`` — places a real testnet order."""

        return self._request("POST", "/api/v3/order", params=params, signed=True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        signed: bool,
    ) -> Any:
        if not is_testnet_base_url(self._base_url):
            # Defense-in-depth: even if someone mutated the attribute after
            # construction, refuse to talk to a non-testnet host.
            raise BinanceTestnetConfigError(
                f"base_url is not a testnet host: {self._base_url!r}"
            )
        cleaned_path = _validate_endpoint(path)
        upper_method = str(method).upper()
        if upper_method not in ("GET", "POST", "DELETE"):
            raise BinanceTestnetConfigError(
                f"Unsupported HTTP method: {method!r}"
            )

        merged: dict[str, Any] = dict(params or {})
        if signed:
            merged["timestamp"] = int(self._clock_ms())
            merged["recvWindow"] = int(self._recv_window_ms)
        query_string = build_query_string(merged)
        if signed:
            signature = sign_query(query_string, api_secret=self._api_secret)
            query_string = f"{query_string}&signature={signature}" if query_string else f"signature={signature}"

        url = f"{self._base_url}{cleaned_path}"
        body: bytes | None = None
        headers = {"X-MBX-APIKEY": self._api_key}
        if upper_method == "GET" or upper_method == "DELETE":
            if query_string:
                url = f"{url}?{query_string}"
        else:
            # POST: per Binance docs, signed POSTs may send params as the body
            # using ``application/x-www-form-urlencoded``. We do that to keep
            # the URL short.
            body = query_string.encode("utf-8") if query_string else b""
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        req = request.Request(url, data=body, headers=headers, method=upper_method)
        try:
            with self._opener(req, timeout=self._timeout_sec) as response:
                raw = response.read()
        except error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            message = _redact(
                f"Binance testnet HTTP {exc.code}: {detail or exc.reason}".strip(),
                self._api_key,
                self._api_secret,
            )
            raise BinanceTestnetRequestError(message) from None
        except error.URLError as exc:
            raise BinanceTestnetRequestError(
                _redact(f"Binance testnet network error: {exc.reason}", self._api_key, self._api_secret)
            ) from None
        except Exception as exc:
            raise BinanceTestnetRequestError(
                _redact(f"Binance testnet request failed: {exc}", self._api_key, self._api_secret)
            ) from None

        try:
            text = raw.decode("utf-8") if raw else ""
        except Exception:
            text = ""
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            raise BinanceTestnetRequestError(
                _redact(
                    f"Binance testnet returned non-JSON body: {text[:512]}",
                    self._api_key,
                    self._api_secret,
                )
            ) from None
        if isinstance(parsed, dict) and "code" in parsed and "msg" in parsed and int(parsed.get("code", 0)) < 0:
            raise BinanceTestnetRequestError(
                _redact(
                    f"Binance testnet API error code={parsed.get('code')} msg={parsed.get('msg')}",
                    self._api_key,
                    self._api_secret,
                )
            )
        return parsed


__all__ = [
    "ALLOWED_ENDPOINTS",
    "BinanceSpotTestnetClient",
    "BinanceTestnetConfigError",
    "BinanceTestnetRequestError",
    "DEFAULT_TESTNET_BASE_URL",
    "FORBIDDEN_ENDPOINT_SUBSTRINGS",
    "build_query_string",
    "is_testnet_base_url",
    "mask_api_key",
    "resolve_credentials",
    "sign_query",
]
