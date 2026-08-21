from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import time
from typing import Any

import pandas as pd
import requests


SOURCE_TIER_1 = "SOURCE_TIER_1_EXCHANGE_OPENAPI"
SOURCE_TIER_2 = "SOURCE_TIER_2_DATA_GOV_TW"
SOURCE_TIER_3 = "SOURCE_TIER_3_MOPS_FSC"
SOURCE_TIER_4 = "SOURCE_TIER_4_SECONDARY_CROSSCHECK"


@dataclass(frozen=True)
class EndpointReceipt:
    endpoint: str
    source_tier: str
    download_timestamp: str
    checksum: str
    http_status: int
    row_count: int
    cache_path: str
    error: str = ""


def roc_date(value: Any) -> pd.Timestamp:
    """Parse compact or separated ROC dates without guessing western years."""
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{2,3})[/.-]?(\d{2})[/.-]?(\d{2})", text)
    if not match:
        return pd.NaT
    return pd.Timestamp(int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3)))


class OfficialFallbackClient:
    """Auditable client for free authoritative Taiwan market data.

    Every attempt emits a receipt. Callers choose the hierarchy explicitly;
    this class never changes provider or accepts a secondary value silently.
    """

    def __init__(
        self,
        cache_dir: Path,
        *,
        throttle_seconds: float = 0.20,
        timeout: float = 45.0,
        attempts: int = 4,
        session: requests.Session | None = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.throttle_seconds = throttle_seconds
        self.timeout = timeout
        self.attempts = attempts
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "tw-mean-reversion-research-data-recovery/3.1",
                "Accept": "application/json,text/csv;q=0.9,*/*;q=0.5",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self.receipts: list[EndpointReceipt] = []

    @staticmethod
    def _key(url: str, params: dict[str, Any] | None) -> str:
        material = json.dumps([url, params or {}], sort_keys=True, default=str).encode()
        return sha256(material).hexdigest()

    @staticmethod
    def _decode(content: bytes, declared: str | None = None) -> str:
        encodings = [declared, "utf-8-sig", "utf-8", "big5", "cp950"]
        for encoding in (x for x in encodings if x):
            try:
                return content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return content.decode("utf-8", errors="replace")

    @staticmethod
    def _row_count(payload: Any) -> int:
        if isinstance(payload, list):
            return len(payload)
        if isinstance(payload, dict):
            for key in ("data", "records", "result"):
                if isinstance(payload.get(key), list):
                    return len(payload[key])
            tables = payload.get("tables")
            if isinstance(tables, list):
                return sum(len(x.get("data", [])) for x in tables if isinstance(x, dict))
        if isinstance(payload, pd.DataFrame):
            return len(payload)
        return 0

    def fetch(
        self,
        url: str,
        *,
        source_tier: str,
        params: dict[str, Any] | None = None,
        parser: str = "json",
        force: bool = False,
    ) -> tuple[Any, EndpointReceipt]:
        key = self._key(url, params)
        suffix = ".json" if parser == "json" else ".csv"
        cache = self.cache_dir / f"{key}{suffix}"
        status = 200
        error = ""
        if cache.exists() and not force:
            content = cache.read_bytes()
            timestamp = pd.Timestamp(cache.stat().st_mtime, unit="s", tz="UTC").isoformat()
        else:
            content = b""
            last_error: Exception | None = None
            for attempt in range(self.attempts):
                try:
                    time.sleep(self.throttle_seconds)
                    response = self.session.get(url, params=params, timeout=self.timeout)
                    status = response.status_code
                    response.raise_for_status()
                    content = response.content
                    cache.write_bytes(content)
                    break
                except Exception as exc:  # receipt preserves the exact failed endpoint
                    last_error = exc
                    error = f"{type(exc).__name__}:{exc}"
                    time.sleep(min(8.0, 0.75 * (2**attempt)))
            if not content:
                receipt = EndpointReceipt(
                    url, source_tier, pd.Timestamp.now(tz="UTC").isoformat(), "",
                    status, 0, str(cache), error,
                )
                self.receipts.append(receipt)
                raise RuntimeError(f"OFFICIAL_SOURCE_FAILED:{url}:{last_error}")
            timestamp = pd.Timestamp.now(tz="UTC").isoformat()
        text = self._decode(content)
        try:
            payload = json.loads(text) if parser == "json" else pd.read_csv(StringIO(text))
        except Exception as exc:
            cache.unlink(missing_ok=True)
            receipt = EndpointReceipt(
                url, source_tier, timestamp, sha256(content).hexdigest(), status,
                0, str(cache), f"PARSE_ERROR:{type(exc).__name__}:{exc}",
            )
            self.receipts.append(receipt)
            raise RuntimeError(f"OFFICIAL_PARSE_FAILED:{url}:{type(exc).__name__}") from exc
        receipt = EndpointReceipt(
            url, source_tier, timestamp, sha256(content).hexdigest(), status,
            self._row_count(payload), str(cache), error,
        )
        self.receipts.append(receipt)
        return payload, receipt

    def receipts_frame(self) -> pd.DataFrame:
        return pd.DataFrame([asdict(x) for x in self.receipts])

    def twse_openapi(self, path: str) -> tuple[Any, EndpointReceipt]:
        return self.fetch(
            f"https://openapi.twse.com.tw/v1/{path.lstrip('/')}",
            source_tier=SOURCE_TIER_1,
        )

    def tpex_openapi(self, path: str) -> tuple[Any, EndpointReceipt]:
        return self.fetch(
            f"https://www.tpex.org.tw/openapi/v1/{path.lstrip('/')}",
            source_tier=SOURCE_TIER_1,
        )

    def twse_daily(self, date: pd.Timestamp) -> tuple[Any, EndpointReceipt]:
        date = pd.Timestamp(date)
        return self.fetch(
            "https://wwwc.twse.com.tw/rwd/zh/afterTrading/MI_INDEX",
            source_tier=SOURCE_TIER_1,
            params={"date": date.strftime("%Y%m%d"), "type": "ALLBUT0999", "response": "json"},
        )

    def twse_actions(self, start: pd.Timestamp, end: pd.Timestamp) -> tuple[Any, EndpointReceipt]:
        params = {
            "startDate": pd.Timestamp(start).strftime("%Y%m%d"),
            "endDate": pd.Timestamp(end).strftime("%Y%m%d"),
            "response": "json",
        }
        errors = []
        for host in ("wwwc.twse.com.tw", "www.twse.com.tw"):
            try:
                return self.fetch(
                    f"https://{host}/rwd/zh/exRight/TWT49U",
                    source_tier=SOURCE_TIER_1,
                    params=params,
                )
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError("TWSE_ACTION_FALLBACKS_EXHAUSTED:" + "|".join(errors))
