import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests


@dataclass
class EndpointSet:
    order_submit: str
    order_get_template: str
    trades_paths: List[str]
    perf_summary: str
    perf_latency: str
    telemetry: str
    health_paths: List[str]


DEFAULT_ENDPOINTS = EndpointSet(
    order_submit="/api/orders/orchestrated",
    order_get_template="/api/orders/{orderRef}",
    trades_paths=["/api/trades", "/api/trades/list"],
    perf_summary="/api/system/performance",
    perf_latency="/api/system/performance/latency",
    telemetry="/metrics",
    health_paths=["/api/system/health", "/q/health", "/health"],
)


def make_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def first_reachable(session: requests.Session, base_url: str, paths: Iterable[str], timeout: int = 5) -> Optional[str]:
    for path in paths:
        try:
            response = session.get(make_url(base_url, path), timeout=timeout)
            if response.status_code < 500:
                return path
        except Exception:
            continue
    return None


def ensure_market_ready(session: requests.Session, base_url: str, symbol: str, reason: str) -> List[str]:
    applied: List[str] = []
    actions = (
        f"/api/system/market/open?reason={reason}",
        "/api/system/risk/resume",
        "/api/system/circuit-breakers/market/resume",
        f"/api/system/circuit-breakers/{symbol}/resume",
    )
    for path in actions:
        try:
            response = session.post(make_url(base_url, path), timeout=10)
            if response.status_code < 500:
                applied.append(path)
        except Exception:
            continue
    return applied


def parse_json_or_default(response: requests.Response, default: Any) -> Any:
    try:
        return response.json()
    except Exception:
        return default


def now_ms() -> float:
    return time.perf_counter() * 1000.0
