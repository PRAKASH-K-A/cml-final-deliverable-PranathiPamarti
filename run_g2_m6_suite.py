import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict


def run_step(name: str, cmd: list) -> Dict:
    print(f"[step] {name}: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return {
        "name": name,
        "command": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run complete G2-M6 suite")
    parser.add_argument("--scenario", default="scenario.local.json")
    parser.add_argument("--base-url", default="http://localhost:8090")
    parser.add_argument("--reports-dir", default="reports")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    reports = root / args.reports_dir
    reports.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    steps = [
        run_step(
            "E2E Order To Trade",
            [py, str(root / "e2e_order_to_trade_test.py")],
        ),
        run_step(
            "Soak Runner",
            [
                py,
                str(root / "soak_runner.py"),
                "--scenario",
                str(root / args.scenario),
                "--out",
                str(reports / "soak-report.json"),
            ],
        ),
        run_step(
            "Latency Hotspot Report",
            [
                py,
                str(root / "latency_hotspot_report.py"),
                "--base-url",
                args.base_url,
                "--scenario",
                str(root / args.scenario),
                "--out-dir",
                str(reports),
            ],
        ),
    ]

    suite = {
        "base_url": args.base_url,
        "scenario": args.scenario,
        "steps": steps,
        "all_passed": all(s["returncode"] == 0 for s in steps),
    }
    (reports / "suite-summary.json").write_text(json.dumps(suite, indent=2), encoding="utf-8")
    print(f"[done] suite summary written to {reports / 'suite-summary.json'}")

    if not suite["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
