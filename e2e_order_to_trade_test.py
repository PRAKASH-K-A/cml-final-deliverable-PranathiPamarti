import json
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests
from common import DEFAULT_ENDPOINTS, ensure_market_ready, make_url


@dataclass
class E2EConfig:
    base_url: str = "http://localhost:8090"
    symbol: str = "AAPL"
    buy_qty: int = 100
    sell_qty: int = 100
    buy_price: float = 150.25
    sell_price: float = 150.25
    client_id_prefix: str = "G2M6-E2E"
    max_wait_seconds: int = 30
    poll_interval_seconds: float = 0.75


class E2EOrderToTradeValidator:
    def __init__(self, config: E2EConfig):
        self.config = config
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return make_url(self.config.base_url, path)

    def _post(self, path: str, payload: Dict) -> Dict:
        response = self.session.post(
            self._url(path),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _get(self, path: str) -> Dict:
        response = self.session.get(self._url(path), timeout=30)
        response.raise_for_status()
        return response.json()

    def ensure_trading_ready(self) -> None:
        ensure_market_ready(
            self.session,
            self.config.base_url,
            self.config.symbol,
            "G2-M6-E2E",
        )

    def submit_order(self, side: str, quantity: int, price: float) -> Dict:
        cl_ord_id = f"{side}-{uuid.uuid4()}"
        payload = {
            "symbol": self.config.symbol,
            "side": side,  # FIX side code expected by backend (1=BUY,2=SELL)
            "quantity": quantity,
            "price": price,
            "orderType": "2",
            "timeInForce": "0",
            "clientId": f"{self.config.client_id_prefix}-{int(time.time())}",
            "clOrdId": cl_ord_id,
        }
        return self._post(DEFAULT_ENDPOINTS.order_submit, payload)

    def fetch_order(self, order_ref: str) -> Dict:
        return self._get(DEFAULT_ENDPOINTS.order_get_template.format(orderRef=order_ref))

    def fetch_trades(self) -> List[Dict]:
        for path in DEFAULT_ENDPOINTS.trades_paths:
            try:
                trades = self._get(path)
                if isinstance(trades, list):
                    return trades
            except Exception:
                continue
        return []

    def wait_for_fill_or_trade(
        self,
        buy_ref: str,
        sell_ref: str,
    ) -> Dict:
        deadline = time.time() + self.config.max_wait_seconds

        while time.time() < deadline:
            buy_state: Optional[Dict] = None
            sell_state: Optional[Dict] = None
            try:
                buy_state = self.fetch_order(buy_ref)
                sell_state = self.fetch_order(sell_ref)
            except Exception:
                pass

            trades = self.fetch_trades()
            has_trade_symbol = any(t.get("symbol") == self.config.symbol for t in trades)

            buy_status = (buy_state or {}).get("status", "")
            sell_status = (sell_state or {}).get("status", "")
            terminal = {"FILLED", "PARTIALLY_FILLED", "CANCELED", "REJECTED"}
            if has_trade_symbol or (buy_status in terminal and sell_status in terminal):
                return {
                    "buy_state": buy_state,
                    "sell_state": sell_state,
                    "trade_seen": has_trade_symbol,
                    "trade_count_for_symbol": sum(1 for t in trades if t.get("symbol") == self.config.symbol),
                }

            time.sleep(self.config.poll_interval_seconds)

        raise TimeoutError("Timed out waiting for order-to-trade lifecycle completion")

    def run(self) -> Dict:
        started = time.time()
        self.ensure_trading_ready()

        buy = self.submit_order("1", self.config.buy_qty, self.config.buy_price)
        sell = self.submit_order("2", self.config.sell_qty, self.config.sell_price)

        buy_ref = buy.get("orderRefNumber")
        sell_ref = sell.get("orderRefNumber")
        if not buy_ref or not sell_ref:
            raise RuntimeError("Missing orderRefNumber in orchestrated order responses")

        lifecycle = self.wait_for_fill_or_trade(buy_ref, sell_ref)
        elapsed_ms = round((time.time() - started) * 1000.0, 2)

        result = {
            "success": True,
            "symbol": self.config.symbol,
            "buy_order_ref": buy_ref,
            "sell_order_ref": sell_ref,
            "elapsed_ms": elapsed_ms,
            "lifecycle": lifecycle,
        }
        return result


def main() -> None:
    validator = E2EOrderToTradeValidator(E2EConfig())
    result = validator.run()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
