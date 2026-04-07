import argparse
import concurrent.futures
import json
import math
import os
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from common import DEFAULT_ENDPOINTS, ensure_market_ready, make_url, now_ms, parse_json_or_default


@dataclass
class SoakConfig:
    base_url: str
    target_orders: int
    target_trades: int
    symbol: str
    client_id_prefix: str
    orders_per_batch: int
    concurrency: int
    poll_interval_seconds: float
    max_wait_seconds: int


class SoakRunner:
    def __init__(self, config: SoakConfig):
        self.config = config
        self.session = requests.Session()
        self.order_latencies_ms: List[float] = []
        self.accepted_orders = 0
        self.rejected_orders = 0
        self.batch_failures = 0

    def _url(self, path: str) -> str:
        return make_url(self.config.base_url, path)

    def _ensure_trading_open(self) -> None:
        ensure_market_ready(
            self.session,
            self.config.base_url,
            self.config.symbol,
            "G2-M6-SOAK",
        )

    def _submit_single_order(self, side: str, qty: int, price: float) -> Tuple[bool, float]:
        payload = {
            "symbol": self.config.symbol,
            "side": side,
            "quantity": qty,
            "price": price,
            "orderType": "2",
            "timeInForce": "0",
            "clientId": f"{self.config.client_id_prefix}-{side}",
            "clOrdId": f"{side}-{uuid.uuid4()}",
        }
        start = now_ms()
        try:
            response = self.session.post(
                self._url(DEFAULT_ENDPOINTS.order_submit),
                json=payload,
                timeout=20,
            )
            latency_ms = now_ms() - start
            if response.status_code in (200, 201):
                body = parse_json_or_default(response, {})
                ok = bool(body.get("success", True))
                return ok, latency_ms
            return False, latency_ms
        except Exception:
            latency_ms = now_ms() - start
            return False, latency_ms

    def _submit_batch_parallel(self, count: int) -> None:
        # Balanced opposing sides to maximize match probability.
        tasks: List[Tuple[str, int, float]] = []
        for i in range(count):
            side = "1" if i % 2 == 0 else "2"
            qty = 100
            # Small price jitter around 150 for realistic matching pressure.
            price = 150.0 + ((i % 5) * 0.01)
            tasks.append((side, qty, price))

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            futures = [
                pool.submit(self._submit_single_order, side, qty, price)
                for side, qty, price in tasks
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    ok, latency_ms = future.result()
                    self.order_latencies_ms.append(latency_ms)
                    if ok:
                        self.accepted_orders += 1
                    else:
                        self.rejected_orders += 1
                except Exception:
                    self.batch_failures += 1

    def _read_trade_count(self) -> int:
        # Try common endpoints observed in repo.
        for path in DEFAULT_ENDPOINTS.trades_paths:
            try:
                response = self.session.get(self._url(path), timeout=20)
                if response.status_code == 200:
                    payload = parse_json_or_default(response, [])
                    if isinstance(payload, list):
                        if self.config.symbol:
                            return sum(1 for x in payload if x.get("symbol") == self.config.symbol)
                        return len(payload)
            except Exception:
                continue
        return 0

    def _read_performance_summary(self) -> Dict:
        try:
            response = self.session.get(self._url(DEFAULT_ENDPOINTS.perf_summary), timeout=20)
            if response.status_code == 200:
                return parse_json_or_default(response, {})
        except Exception:
            pass
        return {}

    def _percentile(self, values: List[float], p: float) -> float:
        if not values:
            return 0.0
        values = sorted(values)
        k = (len(values) - 1) * p
        f = math.floor(k)
        c = min(f + 1, len(values) - 1)
        if f == c:
            return values[f]
        return values[f] + (values[c] - values[f]) * (k - f)

    def run(self) -> Dict:
        self._ensure_trading_open()
        start = time.perf_counter()
        remaining = self.config.target_orders
        phase = 0

        while remaining > 0:
            phase += 1
            batch_size = min(self.config.orders_per_batch, remaining)
            self._submit_batch_parallel(batch_size)
            remaining -= batch_size

            if phase % 10 == 0 or remaining == 0:
                elapsed_s = time.perf_counter() - start
                ops = self.accepted_orders + self.rejected_orders
                throughput = ops / elapsed_s if elapsed_s > 0 else 0.0
                print(
                    f"[progress] phase={phase} accepted={self.accepted_orders} "
                    f"rejected={self.rejected_orders} remaining={remaining} "
                    f"throughput={throughput:.2f} req/s"
                )

        elapsed_s = time.perf_counter() - start
        observed_trades = self._read_trade_count()
        orders_total = self.accepted_orders + self.rejected_orders

        result = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "config": self.config.__dict__,
            "results": {
                "orders_attempted": orders_total,
                "orders_accepted": self.accepted_orders,
                "orders_rejected": self.rejected_orders,
                "batch_failures": self.batch_failures,
                "observed_trades_for_symbol": observed_trades,
                "target_orders": self.config.target_orders,
                "target_trades": self.config.target_trades,
                "target_orders_met": self.accepted_orders >= self.config.target_orders,
                "target_trades_met": observed_trades >= self.config.target_trades,
                "elapsed_seconds": round(elapsed_s, 2),
                "submit_throughput_req_per_sec": round(orders_total / elapsed_s, 2) if elapsed_s > 0 else 0.0,
                "accept_throughput_req_per_sec": round(self.accepted_orders / elapsed_s, 2) if elapsed_s > 0 else 0.0,
            },
            "latency_ms": {
                "avg": round(statistics.fmean(self.order_latencies_ms), 3) if self.order_latencies_ms else 0.0,
                "p50": round(self._percentile(self.order_latencies_ms, 0.50), 3),
                "p95": round(self._percentile(self.order_latencies_ms, 0.95), 3),
                "p99": round(self._percentile(self.order_latencies_ms, 0.99), 3),
                "max": round(max(self.order_latencies_ms), 3) if self.order_latencies_ms else 0.0,
                "samples": len(self.order_latencies_ms),
            },
            "backend_performance_snapshot": self._read_performance_summary(),
        }
        return result


def load_config(path: str) -> SoakConfig:
    with open(path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return SoakConfig(
        base_url=raw.get("base_url", "http://localhost:8090"),
        target_orders=int(raw.get("target_orders", 500000)),
        target_trades=int(raw.get("target_trades", 2000000)),
        symbol=raw.get("symbol", "AAPL"),
        client_id_prefix=raw.get("client_id_prefix", "G2M6"),
        orders_per_batch=int(raw.get("orders_per_batch", 1000)),
        concurrency=int(raw.get("concurrency", 20)),
        poll_interval_seconds=float(raw.get("poll_interval_seconds", 1.5)),
        max_wait_seconds=int(raw.get("max_wait_seconds", 120)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="G2-M6 Soak Runner")
    parser.add_argument(
        "--scenario",
        default=str(Path(__file__).with_name("scenario.example.json")),
        help="Path to scenario JSON file",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).with_name("reports") / "soak-report.json"),
        help="Output report file",
    )
    parser.add_argument(
        "--dashboard-out",
        default=str(
            Path(__file__).resolve().parents[1]
            / "loadtest-dashboard"
            / "public"
            / "loadtest-results.json"
        ),
        help="Optional dashboard-compatible output JSON path",
    )
    args = parser.parse_args()

    cfg = load_config(args.scenario)
    runner = SoakRunner(cfg)
    report = runner.run()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    # Keep compatibility with existing loadtest dashboard schema.
    dashboard_payload = {
        "timestamp": report["timestamp_utc"],
        "users": report["config"]["concurrency"],
        "connected": report["config"]["concurrency"],
        "ordersSent": report["results"]["orders_attempted"],
        "ordersAcked": report["results"]["orders_accepted"],
        "orderRejects": report["results"]["orders_rejected"],
        "latencyIssues": report["results"]["orders_rejected"] + report["results"]["batch_failures"],
        "retries": report["results"]["batch_failures"],
        "elapsedSec": report["results"]["elapsed_seconds"],
        "throughput": report["results"]["accept_throughput_req_per_sec"],
        "connectionRate": 100.0,
        "orderAckRate": round(
            (report["results"]["orders_accepted"] / max(report["results"]["orders_attempted"], 1)) * 100.0, 2
        ),
        "latency": {
            "connect": {"p50": 0, "p95": 0, "p99": 0},
            "logonAck": {"p50": 0, "p95": 0, "p99": 0},
            "orderAck": {
                "p50": report["latency_ms"]["p50"],
                "p95": report["latency_ms"]["p95"],
                "p99": report["latency_ms"]["p99"],
            },
        },
        "config": {
            "host": report["config"]["base_url"],
            "port": 0,
            "symbol": report["config"]["symbol"],
            "targetCompId": report["config"]["client_id_prefix"],
        },
        "kpiTrend": {
            "users": "+0%",
            "connected": "0%",
            "throughput": "n/a",
            "latency": "n/a",
        },
        "latencyDist": [
            {"bucket": "<100ms", "value": 0},
            {"bucket": "100-300ms", "value": 0},
            {"bucket": "300-500ms", "value": 0},
            {"bucket": ">500ms", "value": 0},
        ],
        "failedRows": [],
    }
    dashboard_path = Path(args.dashboard_out)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dashboard_path, "w", encoding="utf-8") as fh:
        json.dump(dashboard_payload, fh, indent=2)

    print(f"[done] report written to {os.fspath(out_path)}")
    print(f"[done] dashboard json written to {os.fspath(dashboard_path)}")
    print(json.dumps(report["results"], indent=2))


if __name__ == "__main__":
    main()
