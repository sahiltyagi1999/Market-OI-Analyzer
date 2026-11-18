from __future__ import annotations

import csv
import hashlib
import json
import os
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode

import requests

from options_intelligence import analyze_options_market, infer_step, iso_now, safe_num


KITE_ROOT = "https://api.kite.trade"
NIFTY_SPOT_KEY = "NSE:NIFTY 50"
DEFAULT_SNAPSHOT_SECONDS = 180
QUOTE_CHUNK_SIZE = 180
DEFAULT_STRIKES_EACH_SIDE = 8
IST = timezone(timedelta(hours=5, minutes=30))
KITE_LOGIN_ROOT = "https://kite.zerodha.com/connect/login"
AUTH_REQUIRED = "AUTH_REQUIRED"
KITE_CONNECTED = "KITE_CONNECTED"
KITE_DISCONNECTED = "KITE_DISCONNECTED"
KITE_RECONNECTING = "KITE_RECONNECTING"


class KiteConfigError(Exception):
    pass


class KiteApiError(Exception):
    pass


class KiteAuthError(KiteApiError):
    pass


class KiteDataError(KiteApiError):
    pass


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_date(value):
    if isinstance(value, date):
        return value
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def as_quote_key(exchange, tradingsymbol):
    return f"{exchange}:{tradingsymbol}"


def market_state(now=None):
    now = now or datetime.now(IST)
    if now.weekday() >= 5:
        return "CLOSED"
    start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if start <= now <= end:
        return "OPEN"
    if now < start:
        return "PREOPEN"
    return "CLOSED"


class KiteSessionStore:
    def __init__(self, path=None):
        default_path = Path(__file__).resolve().parent / ".kite_session.json"
        self.path = Path(path or os.environ.get("KITE_SESSION_FILE") or default_path)
        self.lock = threading.Lock()

    def load(self):
        with self.lock:
            if not self.path.exists():
                return {}
            try:
                with self.path.open("r", encoding="utf-8") as session_file:
                    data = json.load(session_file)
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    def save(self, data):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as session_file:
                json.dump(data, session_file, separators=(",", ":"), sort_keys=True)
            try:
                os.chmod(tmp_path, 0o600)
            except Exception:
                pass
            tmp_path.replace(self.path)

    def clear(self):
        with self.lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except Exception:
                pass


class KiteTickerManager:
    def __init__(self, api_key, access_token, auth_failure_callback=None):
        self.api_key = api_key
        self.access_token = access_token
        self.enabled = parse_bool(os.environ.get("KITE_ENABLE_WEBSOCKET"), False)
        self.ticker = None
        self.connected = False
        self.connecting = False
        self.error = ""
        self.tokens = set()
        self.ticks = {}
        self.reconnect_attempts = 0
        self.reconnect_timer = None
        self.last_connected_at = None
        self.last_disconnected_at = None
        self.auth_failure_callback = auth_failure_callback
        self.lock = threading.Lock()

    def status(self):
        with self.lock:
            if not self.enabled:
                state = "disabled"
            elif self.connected:
                state = "connected"
            elif self.connecting or self.reconnect_timer:
                state = "reconnecting"
            else:
                state = "disconnected"
            return {
                "enabled": self.enabled,
                "connected": self.connected,
                "state": state,
                "subscribed_tokens": len(self.tokens),
                "error": self.error,
                "tick_count": len(self.ticks),
                "reconnect_attempts": self.reconnect_attempts,
                "last_connected_at": self.last_connected_at,
                "last_disconnected_at": self.last_disconnected_at,
            }

    def update_credentials(self, api_key, access_token):
        restart_needed = False
        with self.lock:
            if self.api_key != api_key or self.access_token != access_token:
                restart_needed = True
            self.api_key = api_key
            self.access_token = access_token
            self.error = ""
        if restart_needed:
            self.stop(clear_tokens=False)
        if self.enabled and access_token:
            self.ensure([])

    def stop(self, clear_tokens=False):
        with self.lock:
            ticker = self.ticker
            self.ticker = None
            self.connected = False
            self.connecting = False
            self.ticks = {}
            if clear_tokens:
                self.tokens = set()
            if self.reconnect_timer:
                self.reconnect_timer.cancel()
                self.reconnect_timer = None
        if ticker:
            try:
                ticker.close()
            except Exception:
                try:
                    ticker.stop()
                except Exception:
                    pass

    def ensure(self, tokens):
        if not self.enabled:
            return
        tokens = {int(token) for token in tokens if token}
        if not self.access_token:
            with self.lock:
                self.error = "Kite access token is not available."
            return
        with self.lock:
            self.tokens.update(tokens)
            ticker = self.ticker
            connected = self.connected
            if ticker and connected:
                subscribe_now = tokens
            elif ticker or self.connecting:
                return
            else:
                subscribe_now = set()
                self.connecting = True

        if ticker and connected:
            self._subscribe(ticker, subscribe_now)
            return

        try:
            from kiteconnect import KiteTicker
        except Exception as exc:
            with self.lock:
                self.error = f"kiteconnect package unavailable: {exc}"
                self.connecting = False
            return

        with self.lock:
            if self.ticker:
                self.connecting = False
                return
            ticker = KiteTicker(
                self.api_key,
                self.access_token,
                reconnect=True,
                reconnect_max_tries=20,
                reconnect_max_delay=60,
            )
            ticker.on_ticks = self._on_ticks
            ticker.on_connect = self._on_connect
            ticker.on_close = self._on_close
            ticker.on_error = self._on_error
            self.ticker = ticker

        try:
            ticker.connect(threaded=True)
        except Exception as exc:
            with self.lock:
                self.error = f"WebSocket connect failed: {exc}"
                self.ticker = None
                self.connecting = False
            self._schedule_reconnect()

    def fresh_tick(self, token, max_age_seconds=45):
        with self.lock:
            tick = self.ticks.get(int(token or 0))
        if not tick:
            return None
        received_at = safe_num(tick.get("_received_at"))
        if time.time() - received_at > max_age_seconds:
            return None
        return tick

    def _subscribe(self, ticker, tokens):
        try:
            items = list(tokens)
            if not items:
                return
            ticker.subscribe(items)
            ticker.set_mode(ticker.MODE_FULL, items)
        except Exception as exc:
            with self.lock:
                self.error = f"WebSocket subscribe failed: {exc}"

    def _on_connect(self, ws, response):
        with self.lock:
            self.connected = True
            self.connecting = False
            self.reconnect_attempts = 0
            self.last_connected_at = iso_now()
            tokens = set(self.tokens)
            self.error = ""
            if self.reconnect_timer:
                self.reconnect_timer.cancel()
                self.reconnect_timer = None
        if tokens:
            self._subscribe(ws, tokens)

    def _on_close(self, ws, code, reason):
        with self.lock:
            self.connected = False
            self.connecting = False
            self.last_disconnected_at = iso_now()
            self.error = f"WebSocket closed: {code} {reason}"
        if self._is_auth_failure(code, reason):
            self._handle_auth_failure("Kite WebSocket authentication failed.")
        else:
            self._schedule_reconnect()

    def _on_error(self, ws, code, reason):
        with self.lock:
            self.error = f"WebSocket error: {code} {reason}"
        if self._is_auth_failure(code, reason):
            self._handle_auth_failure("Kite WebSocket authentication failed.")
        else:
            self._schedule_reconnect()

    def _on_ticks(self, ws, ticks):
        received_at = time.time()
        with self.lock:
            for tick in ticks:
                token = tick.get("instrument_token")
                if not token:
                    continue
                item = dict(tick)
                item["_received_at"] = received_at
                self.ticks[int(token)] = item

    def _is_auth_failure(self, code, reason):
        text = f"{code} {reason}".lower()
        return code in {400, 401, 403} or "token" in text or "auth" in text or "permission" in text

    def _handle_auth_failure(self, message):
        self.stop(clear_tokens=False)
        if self.auth_failure_callback:
            self.auth_failure_callback(message)

    def _schedule_reconnect(self):
        with self.lock:
            if not self.enabled or not self.access_token or self.reconnect_timer or self.connected:
                return
            ticker = self.ticker
            self.ticker = None
            self.reconnect_attempts += 1
            delay = min(60, 2 ** min(self.reconnect_attempts, 6))
            self.connecting = True
            self.reconnect_timer = threading.Timer(delay, self._reconnect_timer_fired)
            self.reconnect_timer.daemon = True
            self.reconnect_timer.start()
        if ticker:
            try:
                ticker.close()
            except Exception:
                pass

    def _reconnect_timer_fired(self):
        with self.lock:
            self.reconnect_timer = None
            self.connecting = False
        self.ensure([])


class KiteMarketService:
    def __init__(self):
        self.api_key = os.environ.get("KITE_API_KEY", "").strip()
        self.api_secret = os.environ.get("KITE_API_SECRET", "").strip()
        self.session_store = KiteSessionStore()
        stored_session = self.session_store.load()
        self.access_token = (
            str(stored_session.get("access_token") or "").strip()
            or os.environ.get("KITE_ACCESS_TOKEN", "").strip()
        )
        self.session_user = {
            key: stored_session.get(key)
            for key in ("user_id", "user_name", "user_shortname", "login_time")
            if stored_session.get(key)
        }
        self.auth_state = AUTH_REQUIRED if not self.access_token else KITE_DISCONNECTED
        self.auth_message = "Kite authentication is required." if not self.access_token else "Kite session loaded; validation pending."
        self.last_authenticated_at = stored_session.get("authenticated_at")
        self.last_validated_at = stored_session.get("last_validated_at")
        self.last_successful_connection_at = stored_session.get("last_successful_connection_at")
        self.snapshot_seconds = int(os.environ.get("LIVE_OPTIONS_SNAPSHOT_SECONDS", str(DEFAULT_SNAPSHOT_SECONDS)))
        self.strikes_each_side = int(os.environ.get("LIVE_OPTIONS_STRIKES_EACH_SIDE", str(DEFAULT_STRIKES_EACH_SIDE)))
        self.request_timeout = float(os.environ.get("KITE_REQUEST_TIMEOUT", "8"))
        self.instrument_cache_ttl = int(os.environ.get("KITE_INSTRUMENT_CACHE_SECONDS", str(60 * 60 * 8)))
        self.quote_cache_ttl = int(os.environ.get("KITE_QUOTE_CACHE_SECONDS", "2"))
        self.weights = self._load_weights()
        self._instruments = None
        self._instruments_at = 0.0
        self._quote_cache = {}
        self._history = deque(maxlen=64)
        self._last_snapshot = None
        self._last_snapshot_at = 0.0
        self._lock = threading.RLock()
        self.ticker = KiteTickerManager(self.api_key, self.access_token, self.mark_auth_required)
        if self.access_token and parse_bool(os.environ.get("KITE_VALIDATE_ON_STARTUP"), True):
            self.validate_session()

    def configured(self):
        return bool(self.api_key and self.access_token and self.auth_state != AUTH_REQUIRED)

    def credentials_configured(self):
        return bool(self.api_key and self.api_secret)

    def _load_weights(self):
        raw = os.environ.get("LIVE_OPTIONS_WEIGHTS", "").strip()
        if not raw:
            return {}
        try:
            import json

            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def status(self):
        websocket = self.ticker.status()
        state = self.auth_state
        if self.auth_state == KITE_CONNECTED and websocket["enabled"]:
            if websocket["state"] == "reconnecting":
                state = KITE_RECONNECTING
            elif not websocket["connected"]:
                state = KITE_DISCONNECTED
        return {
            "configured": self.configured(),
            "credentialsConfigured": self.credentials_configured(),
            "authenticated": self.auth_state == KITE_CONNECTED,
            "authState": state,
            "loginRequired": self.auth_state == AUTH_REQUIRED,
            "loginUrl": "/api/kite/login",
            "message": self.auth_message,
            "marketState": market_state(),
            "user": dict(self.session_user),
            "last_authenticated_at": self.last_authenticated_at,
            "last_validated_at": self.last_validated_at,
            "last_successful_connection_at": self.last_successful_connection_at,
            "snapshot_seconds": self.snapshot_seconds,
            "strikes_each_side": self.strikes_each_side,
            "instrument_cache_loaded": self._instruments is not None,
            "history_count": len(self._history),
            "last_snapshot_at": self._last_snapshot.get("timestamp") if self._last_snapshot else None,
            "websocket": websocket,
        }

    def require_configured(self):
        if not self.api_key:
            raise KiteConfigError("KITE_API_KEY is required for Kite Connect.")
        if not self.access_token or self.auth_state == AUTH_REQUIRED:
            raise KiteAuthError("Kite authentication is required.")

    def headers(self):
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self.api_key}:{self.access_token}",
        }

    def login_url(self):
        if not self.credentials_configured():
            raise KiteConfigError("KITE_API_KEY and KITE_API_SECRET are required for Kite login.")
        return f"{KITE_LOGIN_ROOT}?{urlencode({'v': '3', 'api_key': self.api_key})}"

    def exchange_request_token(self, request_token):
        if not self.credentials_configured():
            raise KiteConfigError("KITE_API_KEY and KITE_API_SECRET are required for Kite login.")
        request_token = str(request_token or "").strip()
        if not request_token:
            raise KiteAuthError("Missing Kite request_token.")
        checksum = hashlib.sha256(
            f"{self.api_key}{request_token}{self.api_secret}".encode("utf-8")
        ).hexdigest()
        try:
            response = requests.post(
                f"{KITE_ROOT}/session/token",
                headers={"X-Kite-Version": "3"},
                data={
                    "api_key": self.api_key,
                    "request_token": request_token,
                    "checksum": checksum,
                },
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise KiteDataError(f"Kite token exchange failed: {exc}") from exc
        except ValueError as exc:
            raise KiteDataError("Kite token exchange returned an invalid response.") from exc

        data = payload.get("data") or {}
        access_token = str(data.get("access_token") or "").strip()
        if payload.get("status") != "success" or not access_token:
            message = payload.get("message") or "Kite token exchange failed."
            raise KiteAuthError(message)

        session = {
            "access_token": access_token,
            "user_id": data.get("user_id"),
            "user_name": data.get("user_name"),
            "user_shortname": data.get("user_shortname"),
            "login_time": data.get("login_time"),
            "authenticated_at": iso_now(),
            "last_validated_at": iso_now(),
            "last_successful_connection_at": iso_now(),
        }
        self.session_store.save(session)
        with self._lock:
            self.access_token = access_token
            self.session_user = {
                key: session.get(key)
                for key in ("user_id", "user_name", "user_shortname", "login_time")
                if session.get(key)
            }
            self.auth_state = KITE_CONNECTED
            self.auth_message = "Kite authenticated."
            self.last_authenticated_at = session["authenticated_at"]
            self.last_validated_at = session["last_validated_at"]
            self.last_successful_connection_at = session["last_successful_connection_at"]
            self._quote_cache = {}
            self._last_snapshot = None
            self._last_snapshot_at = 0.0
        self.ticker.update_credentials(self.api_key, access_token)
        return {
            "success": True,
            "authenticated": True,
            "user": dict(self.session_user),
            "authenticated_at": self.last_authenticated_at,
        }

    def logout(self):
        token = self.access_token
        if token and self.api_key:
            try:
                requests.delete(
                    f"{KITE_ROOT}/session/token",
                    headers={"X-Kite-Version": "3"},
                    params={"api_key": self.api_key, "access_token": token},
                    timeout=self.request_timeout,
                )
            except requests.RequestException:
                pass
        self.mark_auth_required("Kite session logged out.", clear_store=True)
        return {"success": True, "authenticated": False}

    def validate_session(self):
        if not self.access_token:
            self.mark_auth_required("Kite authentication is required.")
            return False
        try:
            self._request("/user/profile")
        except KiteAuthError:
            return False
        except KiteDataError as exc:
            with self._lock:
                self.auth_state = KITE_DISCONNECTED
                self.auth_message = f"Could not validate Kite session: {exc}"
            return False
        with self._lock:
            self.auth_state = KITE_CONNECTED
            self.auth_message = "Kite session is valid."
            self.last_validated_at = iso_now()
            self.last_successful_connection_at = self.last_validated_at
            self._persist_session_fields()
        self.ticker.update_credentials(self.api_key, self.access_token)
        return True

    def mark_auth_required(self, message="Kite authentication is required.", clear_store=True):
        with self._lock:
            self.auth_state = AUTH_REQUIRED
            self.auth_message = message
            self.access_token = ""
            self._quote_cache = {}
            self._last_snapshot = None
            self._last_snapshot_at = 0.0
            if clear_store:
                self.session_store.clear()
        self.ticker.update_credentials(self.api_key, "")
        self.ticker.stop(clear_tokens=False)

    def _persist_session_fields(self):
        existing = self.session_store.load()
        if not self.access_token:
            return
        existing.update({
            "access_token": self.access_token,
            "last_validated_at": self.last_validated_at,
            "last_successful_connection_at": self.last_successful_connection_at,
        })
        existing.update(self.session_user)
        if self.last_authenticated_at:
            existing["authenticated_at"] = self.last_authenticated_at
        self.session_store.save(existing)

    def _mark_connected(self):
        with self._lock:
            if self.auth_state != AUTH_REQUIRED:
                self.auth_state = KITE_CONNECTED
                self.auth_message = "Kite connected."
                self.last_successful_connection_at = iso_now()
                self._persist_session_fields()

    def _is_auth_response(self, response):
        if response.status_code in {401, 403}:
            return True
        if response.status_code not in {400, 403}:
            return False
        try:
            payload = response.json()
        except ValueError:
            return False
        text = " ".join(
            str(payload.get(key) or "")
            for key in ("error_type", "message", "status")
        ).lower()
        return "token" in text or "auth" in text or "permission" in text or "invalid" in text

    def _request(self, path, params=None, raw=False):
        self.require_configured()
        try:
            response = requests.get(
                f"{KITE_ROOT}{path}",
                headers=self.headers(),
                params=params,
                timeout=self.request_timeout,
            )
            if self._is_auth_response(response):
                self.mark_auth_required("Kite access token is invalid or expired.")
                raise KiteAuthError("Kite authentication is required.")
            if response.status_code == 429:
                raise KiteDataError("Kite rate limit reached. Wait briefly before refreshing.")
            response.raise_for_status()
            self._mark_connected()
            return response.text if raw else response.json()
        except (KiteConfigError, KiteAuthError, KiteDataError):
            raise
        except requests.HTTPError as exc:
            detail = ""
            try:
                detail = response.json().get("message") or response.text[:160]
            except Exception:
                detail = response.text[:160] if "response" in locals() else str(exc)
            raise KiteDataError(detail or str(exc)) from exc
        except requests.RequestException as exc:
            with self._lock:
                if self.auth_state != AUTH_REQUIRED:
                    self.auth_state = KITE_DISCONNECTED
                    self.auth_message = "Kite market data is temporarily unavailable."
            raise KiteDataError(f"Kite request failed: {exc}") from exc

    def instruments(self):
        with self._lock:
            if self._instruments is not None and time.time() - self._instruments_at < self.instrument_cache_ttl:
                return self._instruments
        text = self._request("/instruments", raw=True)
        rows = []
        for row in csv.DictReader(StringIO(text)):
            row["instrument_token"] = int(safe_num(row.get("instrument_token")))
            row["strike"] = safe_num(row.get("strike"))
            row["expiry_date"] = parse_date(row.get("expiry"))
            rows.append(row)
        with self._lock:
            self._instruments = rows
            self._instruments_at = time.time()
        return rows

    def nifty_options(self, expiry=None):
        today = datetime.now(IST).date()
        options = [
            row
            for row in self.instruments()
            if row.get("exchange") == "NFO"
            and row.get("name") == "NIFTY"
            and row.get("instrument_type") in {"CE", "PE"}
            and row.get("expiry_date")
            and row["expiry_date"] >= today
        ]
        if not options:
            raise KiteApiError("No live NIFTY option instruments found in Kite instrument master.")

        wanted_expiry = parse_date(expiry) if expiry else None
        if not wanted_expiry:
            configured_expiry = parse_date(os.environ.get("KITE_NIFTY_EXPIRY"))
            wanted_expiry = configured_expiry
        if not wanted_expiry:
            wanted_expiry = min(row["expiry_date"] for row in options)

        selected = [row for row in options if row["expiry_date"] == wanted_expiry]
        if not selected:
            raise KiteApiError(f"No NIFTY options found for expiry {wanted_expiry.isoformat()}.")
        return selected, wanted_expiry

    def quotes(self, keys):
        keys = list(dict.fromkeys(keys))
        fresh = {}
        missing = []
        now = time.time()
        with self._lock:
            for key in keys:
                cached = self._quote_cache.get(key)
                if cached and now - cached[0] < self.quote_cache_ttl:
                    fresh[key] = cached[1]
                else:
                    missing.append(key)

        for idx in range(0, len(missing), QUOTE_CHUNK_SIZE):
            chunk = missing[idx : idx + QUOTE_CHUNK_SIZE]
            if not chunk:
                continue
            data = self._request("/quote", params=[("i", key) for key in chunk])
            payload = data.get("data") or {}
            with self._lock:
                for key, value in payload.items():
                    self._quote_cache[key] = (time.time(), value)
                    fresh[key] = value
        return fresh

    def historical_candles(self, instrument_token, from_time, to_time, interval="3minute", oi=True):
        params = {
            "from": from_time,
            "to": to_time,
            "continuous": 0,
            "oi": 1 if oi else 0,
        }
        data = self._request(
            f"/instruments/historical/{int(instrument_token)}/{interval}",
            params=params,
        )
        candles = data.get("data", {}).get("candles") or []
        parsed = []
        for candle in candles:
            item = {
                "timestamp": candle[0] if len(candle) > 0 else None,
                "open": safe_num(candle[1] if len(candle) > 1 else 0),
                "high": safe_num(candle[2] if len(candle) > 2 else 0),
                "low": safe_num(candle[3] if len(candle) > 3 else 0),
                "close": safe_num(candle[4] if len(candle) > 4 else 0),
                "volume": safe_num(candle[5] if len(candle) > 5 else 0),
            }
            if len(candle) > 6:
                item["oi"] = safe_num(candle[6])
            parsed.append(item)
        return parsed

    def spot_quote(self):
        data = self.quotes([NIFTY_SPOT_KEY])
        quote = data.get(NIFTY_SPOT_KEY) or {}
        if not quote:
            raise KiteApiError("Could not fetch NIFTY 50 spot quote from Kite.")
        return quote

    def build_live_snapshot(self, expiry=None, force=False):
        with self._lock:
            if (
                self._last_snapshot
                and not force
                and time.time() - self._last_snapshot_at < self.snapshot_seconds
            ):
                return self._last_snapshot

        spot_quote = self.spot_quote()
        spot = safe_num(spot_quote.get("last_price"))
        instruments, expiry_date = self.nifty_options(expiry)
        step = infer_step([{"strike": row["strike"]} for row in instruments])
        atm = round(spot / step) * step if spot and step else None
        low = atm - self.strikes_each_side * step if atm else 0
        high = atm + self.strikes_each_side * step if atm else float("inf")

        by_strike = {}
        for row in instruments:
            strike = safe_num(row.get("strike"))
            if atm and (strike < low or strike > high):
                continue
            by_strike.setdefault(strike, {})[row["instrument_type"]] = row

        rows = []
        quote_keys = []
        token_map = {}
        for strike, pair in sorted(by_strike.items()):
            if "CE" not in pair or "PE" not in pair:
                continue
            for side in ("CE", "PE"):
                inst = pair[side]
                key = as_quote_key(inst["exchange"], inst["tradingsymbol"])
                quote_keys.append(key)
                token_map[key] = (strike, side, inst)

        quotes = self.quotes(quote_keys)
        self.ticker.ensure([inst["instrument_token"] for _, _, inst in token_map.values()])
        rows_by_key = {}
        for key, (strike, side, inst) in token_map.items():
            quote = quotes.get(key) or {}
            tick = self.ticker.fresh_tick(inst.get("instrument_token"))
            merged = self._merge_quote_tick(quote, tick)
            rows_by_key[(strike, side)] = {
                "ltp": safe_num(merged.get("last_price")),
                "oi": safe_num(merged.get("oi")),
                "volume": safe_num(merged.get("volume") or merged.get("volume_traded")),
                "average_price": safe_num(merged.get("average_price") or merged.get("average_traded_price")),
                "instrument_token": inst.get("instrument_token"),
                "tradingsymbol": inst.get("tradingsymbol"),
                "timestamp": self._quote_timestamp(merged),
                "is_stale": self._is_stale(merged),
            }

        for strike in sorted({key[0] for key in rows_by_key}):
            ce = rows_by_key.get((strike, "CE"), {})
            pe = rows_by_key.get((strike, "PE"), {})
            if not ce or not pe:
                continue
            rows.append({
                "strike": int(strike),
                "call_ltp": ce.get("ltp"),
                "call_oi": ce.get("oi"),
                "call_volume": ce.get("volume"),
                "call_vwap": ce.get("average_price"),
                "call_token": ce.get("instrument_token"),
                "call_symbol": ce.get("tradingsymbol"),
                "call_stale": ce.get("is_stale"),
                "put_ltp": pe.get("ltp"),
                "put_oi": pe.get("oi"),
                "put_volume": pe.get("volume"),
                "put_vwap": pe.get("average_price"),
                "put_token": pe.get("instrument_token"),
                "put_symbol": pe.get("tradingsymbol"),
                "put_stale": pe.get("is_stale"),
                "is_stale": ce.get("is_stale") or pe.get("is_stale"),
            })

        if not rows:
            raise KiteApiError("No complete CE/PE rows could be built for the selected NIFTY expiry.")

        snapshot = {
            "timestamp": iso_now(),
            "instrument": "NIFTY",
            "source": "kite",
            "expiry": expiry_date.isoformat(),
            "spot": spot,
            "spot_change": safe_num(spot_quote.get("net_change") or spot_quote.get("change")),
            "spot_token": spot_quote.get("instrument_token"),
            "spot_vwap": safe_num(spot_quote.get("average_price")),
            "atm": int(atm) if atm else None,
            "strike_step": int(step),
            "rows": rows,
            "atm_iv": None,
            "iv_percentile": None,
            "iv_note": "Kite quotes do not provide option IV directly; add an IV model or external IV feed to populate this.",
        }

        with self._lock:
            history = list(self._history)
            analysis = analyze_options_market(snapshot, history, self.weights)
            snapshot["levels"] = analysis.get("support_resistance")
            result = {
                "snapshot": snapshot,
                "analysis": analysis,
                "status": self.status(),
            }
            self._history.append(snapshot)
            self._last_snapshot = result
            self._last_snapshot_at = time.time()
        return result

    def _merge_quote_tick(self, quote, tick):
        merged = dict(quote or {})
        if not tick:
            return merged
        mapping = {
            "last_price": "last_price",
            "volume_traded": "volume",
            "average_traded_price": "average_price",
            "oi": "oi",
            "last_trade_time": "last_trade_time",
            "exchange_timestamp": "timestamp",
        }
        for tick_key, quote_key in mapping.items():
            if tick.get(tick_key) not in (None, 0, ""):
                merged[quote_key] = tick.get(tick_key)
        return merged

    def _quote_timestamp(self, quote):
        for key in ("timestamp", "last_trade_time"):
            value = quote.get(key)
            if isinstance(value, datetime):
                return value.astimezone(timezone.utc).isoformat()
            if value:
                return str(value)
        return None

    def _is_stale(self, quote):
        value = quote.get("timestamp") or quote.get("last_trade_time")
        if not isinstance(value, datetime):
            return False
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - value.astimezone(timezone.utc)).total_seconds() > 90


market_service = KiteMarketService()
