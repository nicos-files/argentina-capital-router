import hashlib
import hmac
import io
import json
import sys
import unittest
import urllib.parse
from pathlib import Path
from urllib import error

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.brokers.binance_spot_testnet import (
    ALLOWED_ENDPOINTS,
    DEFAULT_TESTNET_BASE_URL,
    FORBIDDEN_ENDPOINT_SUBSTRINGS,
    BinanceSpotTestnetClient,
    BinanceTestnetConfigError,
    BinanceTestnetRequestError,
    build_query_string,
    is_testnet_base_url,
    mask_api_key,
    resolve_credentials,
    sign_query,
)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


class _RecordingOpener:
    """Capture the last urllib request without doing any I/O."""

    def __init__(self, response_body: bytes = b'{"ok":true}'):
        self.response_body = response_body
        self.calls: list[dict] = []

    def __call__(self, req, timeout):  # noqa: ANN001
        self.calls.append(
            {
                "url": req.full_url,
                "method": req.get_method(),
                "headers": dict(req.headers),
                "data": req.data,
                "timeout": timeout,
            }
        )
        return _FakeResponse(self.response_body)


API_KEY = "test-api-key-1234567890"
API_SECRET = "test-api-secret-must-not-leak"


class IsTestnetBaseUrlTests(unittest.TestCase):
    def test_accepts_official_testnet_https(self) -> None:
        self.assertTrue(is_testnet_base_url("https://testnet.binance.vision/api"))
        self.assertTrue(is_testnet_base_url("https://testnet.binance.vision/api/"))

    def test_accepts_local_mock_http_only(self) -> None:
        self.assertTrue(is_testnet_base_url("http://localhost:8080/api"))
        self.assertTrue(is_testnet_base_url("http://127.0.0.1:9999/api"))

    def test_rejects_live_binance(self) -> None:
        self.assertFalse(is_testnet_base_url("https://api.binance.com/api"))
        self.assertFalse(is_testnet_base_url("https://api.binance.us/api"))

    def test_rejects_futures_and_margin(self) -> None:
        self.assertFalse(is_testnet_base_url("https://fapi.binance.com/fapi/v1"))
        self.assertFalse(is_testnet_base_url("https://dapi.binance.com/dapi/v1"))
        self.assertFalse(is_testnet_base_url("https://papi.binance.com/papi/v1"))

    def test_rejects_empty_or_garbage(self) -> None:
        self.assertFalse(is_testnet_base_url(""))
        self.assertFalse(is_testnet_base_url("   "))
        self.assertFalse(is_testnet_base_url("not a url"))
        self.assertFalse(is_testnet_base_url(None))  # type: ignore[arg-type]

    def test_rejects_https_localhost_to_keep_explicit_allowlist(self) -> None:
        # Tightening: only http://localhost is the allowed mock prefix.
        self.assertFalse(is_testnet_base_url("https://localhost/api"))


class SignQueryAndQueryStringTests(unittest.TestCase):
    def test_build_query_string_is_deterministic_and_sorted(self) -> None:
        qs = build_query_string({"b": "2", "a": "1", "c": "3"})
        self.assertEqual(qs, "a=1&b=2&c=3")

    def test_build_query_string_drops_none_values(self) -> None:
        qs = build_query_string({"a": "1", "b": None})
        self.assertEqual(qs, "a=1")

    def test_build_query_string_uses_lowercase_bool(self) -> None:
        qs = build_query_string({"flag": True, "other": False})
        self.assertEqual(qs, "flag=true&other=false")

    def test_sign_query_matches_reference_hmac_sha256(self) -> None:
        query = "symbol=BTCUSDT&side=BUY&type=MARKET&quoteOrderQty=25.0&timestamp=1700000000000&recvWindow=5000"
        expected = hmac.new(
            API_SECRET.encode("utf-8"),
            msg=query.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()
        self.assertEqual(sign_query(query, api_secret=API_SECRET), expected)

    def test_sign_query_requires_secret(self) -> None:
        with self.assertRaises(BinanceTestnetConfigError):
            sign_query("a=1", api_secret="")


class ResolveCredentialsTests(unittest.TestCase):
    def test_uses_env(self) -> None:
        env = {
            "BINANCE_TESTNET_API_KEY": API_KEY,
            "BINANCE_TESTNET_API_SECRET": API_SECRET,
        }
        key, secret = resolve_credentials(env=env)
        self.assertEqual(key, API_KEY)
        self.assertEqual(secret, API_SECRET)

    def test_explicit_overrides_env(self) -> None:
        env = {
            "BINANCE_TESTNET_API_KEY": "wrong",
            "BINANCE_TESTNET_API_SECRET": "wrong",
        }
        key, secret = resolve_credentials(api_key=API_KEY, api_secret=API_SECRET, env=env)
        self.assertEqual(key, API_KEY)
        self.assertEqual(secret, API_SECRET)

    def test_missing_api_key_raises(self) -> None:
        with self.assertRaises(BinanceTestnetConfigError) as ctx:
            resolve_credentials(env={"BINANCE_TESTNET_API_SECRET": API_SECRET})
        self.assertIn("BINANCE_TESTNET_API_KEY", str(ctx.exception))
        self.assertNotIn(API_SECRET, str(ctx.exception))

    def test_missing_api_secret_raises(self) -> None:
        with self.assertRaises(BinanceTestnetConfigError) as ctx:
            resolve_credentials(env={"BINANCE_TESTNET_API_KEY": API_KEY})
        self.assertIn("BINANCE_TESTNET_API_SECRET", str(ctx.exception))
        self.assertNotIn(API_KEY, str(ctx.exception))

    def test_does_not_read_live_env_vars(self) -> None:
        env = {
            "BINANCE_API_KEY": "live-must-not-be-read",
            "BINANCE_API_SECRET": "live-must-not-be-read",
        }
        with self.assertRaises(BinanceTestnetConfigError):
            resolve_credentials(env=env)


class MaskApiKeyTests(unittest.TestCase):
    def test_keeps_last_four(self) -> None:
        self.assertEqual(mask_api_key("abcdef1234"), "******1234")

    def test_short_key_fully_masked(self) -> None:
        self.assertEqual(mask_api_key("abcd"), "****")
        self.assertEqual(mask_api_key(""), "")


class BinanceSpotTestnetClientTests(unittest.TestCase):
    def _client(self, opener=None, base_url=DEFAULT_TESTNET_BASE_URL):
        return BinanceSpotTestnetClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            base_url=base_url,
            opener=opener if opener is not None else _RecordingOpener(),
            clock_ms=lambda: 1700000000000,
        )

    def test_construction_rejects_live_base_url(self) -> None:
        for url in (
            "https://api.binance.com/api",
            "https://api.binance.us/api",
            "https://fapi.binance.com",
            "https://papi.binance.com",
        ):
            with self.assertRaises(BinanceTestnetConfigError):
                BinanceSpotTestnetClient(
                    api_key=API_KEY, api_secret=API_SECRET, base_url=url
                )

    def test_construction_accepts_testnet(self) -> None:
        client = self._client()
        self.assertEqual(client.base_url, DEFAULT_TESTNET_BASE_URL)

    def test_ping_calls_unsigned_endpoint(self) -> None:
        opener = _RecordingOpener(b'{}')
        client = self._client(opener=opener)
        client.ping()
        self.assertEqual(len(opener.calls), 1)
        call = opener.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertTrue(call["url"].endswith("/api/v3/ping"))
        # Unsigned: no signature query, no recvWindow.
        self.assertNotIn("signature", call["url"])
        self.assertNotIn("recvWindow", call["url"])

    def test_account_request_is_signed_and_includes_timestamp_and_recv_window(self) -> None:
        opener = _RecordingOpener(b'{"balances":[]}')
        client = self._client(opener=opener)
        client.account()
        call = opener.calls[0]
        parsed = urllib.parse.urlparse(call["url"])
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.assertEqual(parsed.path, "/api/v3/account")
        self.assertIn("timestamp", params)
        self.assertEqual(params["timestamp"], "1700000000000")
        self.assertEqual(params["recvWindow"], "5000")
        # Signature must be the HMAC of (sorted query without signature).
        expected_sig = sign_query(
            "recvWindow=5000&timestamp=1700000000000", api_secret=API_SECRET
        )
        self.assertEqual(params["signature"], expected_sig)

    def test_x_mbx_apikey_header_is_set(self) -> None:
        opener = _RecordingOpener(b'{}')
        client = self._client(opener=opener)
        client.account()
        # urllib normalizes the header name to title-case.
        headers = {k.lower(): v for k, v in opener.calls[0]["headers"].items()}
        self.assertEqual(headers.get("x-mbx-apikey"), API_KEY)

    def test_order_test_uses_post_to_order_slash_test(self) -> None:
        opener = _RecordingOpener(b'{}')
        client = self._client(opener=opener)
        client.order_test(
            params={
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": "25",
                "newClientOrderId": "tnbuy-deadbeef",
            }
        )
        call = opener.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/api/v3/order/test"))
        # Body is x-www-form-urlencoded, alphabetized keys, signed.
        body = call["data"].decode("utf-8")
        self.assertIn("symbol=BTCUSDT", body)
        self.assertIn("signature=", body)
        self.assertIn("timestamp=1700000000000", body)

    def test_place_order_uses_post_to_order(self) -> None:
        opener = _RecordingOpener(b'{"status":"FILLED","fills":[]}')
        client = self._client(opener=opener)
        client.place_order(
            params={
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "quoteOrderQty": "25",
                "newClientOrderId": "tnbuy-deadbeef",
            }
        )
        call = opener.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/api/v3/order"))
        self.assertFalse(call["url"].endswith("/api/v3/order/test"))

    def test_forbidden_endpoint_path_is_blocked(self) -> None:
        # We cannot reach _request directly without going through the
        # public methods, but we can check the validator via a misuse:
        # a path that includes /sapi or /fapi must raise even before any
        # network call.
        from src.brokers.binance_spot_testnet import _validate_endpoint

        for path in (
            "/sapi/v1/capital/withdraw/apply",
            "/sapi/v1/margin/order",
            "/fapi/v1/order",
            "/dapi/v1/order",
            "/papi/v1/order",
        ):
            with self.assertRaises(BinanceTestnetConfigError):
                _validate_endpoint(path)

    def test_unknown_path_is_blocked_even_if_not_explicitly_forbidden(self) -> None:
        from src.brokers.binance_spot_testnet import _validate_endpoint

        with self.assertRaises(BinanceTestnetConfigError):
            _validate_endpoint("/api/v3/unknown")

    def test_secrets_are_redacted_from_http_error(self) -> None:
        # A server response that echoes the API key/secret must be scrubbed.
        leaky_body = (
            f"failed key={API_KEY} secret={API_SECRET} please-do-not-leak"
        ).encode("utf-8")

        class _RaisingOpener:
            def __call__(self, req, timeout):  # noqa: ANN001
                raise error.HTTPError(
                    url=req.full_url,
                    code=401,
                    msg="Unauthorized",
                    hdrs=None,
                    fp=io.BytesIO(leaky_body),
                )

        client = BinanceSpotTestnetClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            base_url=DEFAULT_TESTNET_BASE_URL,
            opener=_RaisingOpener(),
            clock_ms=lambda: 1,
        )
        with self.assertRaises(BinanceTestnetRequestError) as ctx:
            client.account()
        text = str(ctx.exception)
        self.assertNotIn(API_KEY, text)
        self.assertNotIn(API_SECRET, text)
        self.assertIn("[REDACTED]", text)

    def test_secrets_are_redacted_from_url_error(self) -> None:
        class _RaisingOpener:
            def __call__(self, req, timeout):  # noqa: ANN001
                raise error.URLError(
                    reason=f"connection refused with secret {API_SECRET}"
                )

        client = BinanceSpotTestnetClient(
            api_key=API_KEY,
            api_secret=API_SECRET,
            base_url=DEFAULT_TESTNET_BASE_URL,
            opener=_RaisingOpener(),
            clock_ms=lambda: 1,
        )
        with self.assertRaises(BinanceTestnetRequestError) as ctx:
            client.account()
        self.assertNotIn(API_SECRET, str(ctx.exception))

    def test_negative_code_response_is_raised_as_error_redacted(self) -> None:
        body = json.dumps({"code": -1021, "msg": "Timestamp out of recv"}).encode()
        opener = _RecordingOpener(body)
        client = self._client(opener=opener)
        with self.assertRaises(BinanceTestnetRequestError) as ctx:
            client.account()
        self.assertIn("-1021", str(ctx.exception))
        self.assertNotIn(API_SECRET, str(ctx.exception))

    def test_open_orders_passes_symbol_query(self) -> None:
        opener = _RecordingOpener(b'[]')
        client = self._client(opener=opener)
        client.open_orders(symbol="btcusdt")
        call = opener.calls[0]
        self.assertIn("symbol=BTCUSDT", call["url"])
        self.assertIn("/api/v3/openOrders", call["url"])

    def test_all_orders_requires_symbol(self) -> None:
        opener = _RecordingOpener(b'[]')
        client = self._client(opener=opener)
        client.all_orders(symbol="ETHUSDT", limit=50)
        call = opener.calls[0]
        self.assertIn("/api/v3/allOrders", call["url"])
        self.assertIn("limit=50", call["url"])

    def test_exchange_info_with_symbols_uses_symbols_query(self) -> None:
        opener = _RecordingOpener(b'{}')
        client = self._client(opener=opener)
        client.exchange_info(symbols=["btcusdt", "ETHUSDT"])
        call = opener.calls[0]
        self.assertIn("/api/v3/exchangeInfo", call["url"])
        self.assertIn("symbols=", call["url"])
        # symbols are uppercased and JSON-encoded.
        self.assertIn("BTCUSDT", urllib.parse.unquote(call["url"]))


class AllowlistShapeTests(unittest.TestCase):
    def test_allowed_endpoints_does_not_include_anything_forbidden(self) -> None:
        for endpoint in ALLOWED_ENDPOINTS:
            for forbidden in FORBIDDEN_ENDPOINT_SUBSTRINGS:
                self.assertNotIn(
                    forbidden,
                    endpoint,
                    f"forbidden substring {forbidden!r} found in allowlisted endpoint {endpoint!r}",
                )

    def test_allowlist_includes_required_endpoints(self) -> None:
        for required in (
            "/api/v3/order",
            "/api/v3/order/test",
            "/api/v3/account",
            "/api/v3/exchangeInfo",
            "/api/v3/openOrders",
            "/api/v3/allOrders",
        ):
            self.assertIn(required, ALLOWED_ENDPOINTS)

    def test_allowlist_does_not_include_withdraw_or_futures(self) -> None:
        for forbidden in (
            "/sapi/v1/capital/withdraw/apply",
            "/sapi/v1/margin/order",
            "/fapi/v1/order",
            "/dapi/v1/order",
            "/papi/v1/order",
        ):
            self.assertNotIn(forbidden, ALLOWED_ENDPOINTS)


if __name__ == "__main__":
    unittest.main()
