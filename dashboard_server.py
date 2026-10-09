"""Serve the standalone dashboard and run only this folder's workflow."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import errno
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
DATA_DIR = ROOT / "data"
RESULT_PATH = DATA_DIR / "dashboard_result.json"
DEMO_ASSETS = 8
DEMO_K = 2
RUN_LOCK = threading.Lock()


class DashboardHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def __init__(
        self,
        server_address,
        request_handler_class,
        run_options: dict[str, int | str],
        *,
        start_fresh: bool = False,
        dataset_start: str = "2018-01-01",
    ) -> None:
        self.run_options = run_options
        self.start_fresh = start_fresh
        self.dataset_start = dataset_start
        self.has_generated_dataset = False
        self.has_completed_run = False
        super().__init__(server_address, request_handler_class)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def state(*, include_saved_result: bool = True) -> dict:
    metadata_path = DATA_DIR / "metadata.csv"
    returns_path = DATA_DIR / "returns.csv"
    if metadata_path.is_file():
        with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
            metadata = list(csv.DictReader(metadata_file))
    else:
        metadata = []
    dataset_available = returns_path.is_file() and len(metadata) >= 2
    result = read_json(RESULT_PATH, {}) if dataset_available and include_saved_result else {}

    best = result.get("best_feasible") or {}
    bitstring = best.get("bitstring", "")
    carbon_by_ticker = {
        row["ticker"]: float(row["carbon"])
        for row in metadata
    }
    if best and best.get("gross_carbon") is None:
        best["gross_carbon"] = sum(
            carbon_by_ticker.get(ticker, 0.0)
            for ticker in best.get("long", []) + best.get("short", [])
        )
    asset_count = (
        result.get("asset_count")
        or len(result.get("universe", []))
        or (len(bitstring) // 2 if bitstring else 0)
        or (min(DEMO_ASSETS, len(metadata)) if dataset_available else 0)
    )
    ticker_to_name = {row["ticker"]: row["name"] for row in metadata}
    selected = result.get("universe") or [
        row["ticker"] for row in metadata[:asset_count]
    ]
    k = result.get("k") or len(best.get("long", [])) or DEMO_K
    asset_details = [
        {"asset": row["name"], "carbon": float(row["carbon"])}
        for row in metadata
        if row["ticker"] in selected
    ]
    assets = [asset["asset"] for asset in asset_details]

    def convert_assets(obj):
        if isinstance(obj, dict):
            if "long" in obj and isinstance(obj["long"], list):
                obj["long"] = [ticker_to_name.get(t, t) for t in obj["long"]]
            if "short" in obj and isinstance(obj["short"], list):
                obj["short"] = [ticker_to_name.get(t, t) for t in obj["short"]]
            for key, value in obj.items():
                convert_assets(value)
        elif isinstance(obj, list):
            for item in obj:
                convert_assets(item)

    convert_assets(result)

    return {
        "model": {
            "assets": assets,
            "data_source": "yahoo",
            "long_count": k,
            "short_count": k,
            "assets_detail": asset_details,
        },
        "result": result,
        "source": result.get("source", "YAHOO / STANDALONE DATASET" if assets else "NO DATASET"),
        "asset_count": asset_count,
        "qubit_count": result.get("qubit_count", asset_count * 2),
        "dataset_available": dataset_available,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/state":
            include_saved = (
                (not self.server.start_fresh and not self.server.has_generated_dataset)
                or self.server.has_completed_run
            )
            self._send(200, json.dumps(state(include_saved_result=include_saved)).encode(), "application/json")
            return
        if path == "/":
            path = "/index.html"
        requested = (DASHBOARD / path.lstrip("/")).resolve()
        if DASHBOARD not in requested.parents or not requested.is_file():
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(requested.suffix, "application/octet-stream")
        self._send(200, requested.read_bytes(), content_type)

    def do_POST(self) -> None:
        endpoint = urlparse(self.path).path
        if endpoint not in {"/api/generate-dataset", "/api/run-local", "/api/run-resonance"}:
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return

        if endpoint == "/api/generate-dataset":
            try:
                command = self._dataset_command()
            except (ValueError, UnicodeDecodeError) as error:
                self._send(
                    400,
                    json.dumps({"ok": False, "output": str(error)}).encode(),
                    "application/json",
                )
                return
        else:
            try:
                options = self._run_options()
            except (ValueError, UnicodeDecodeError) as error:
                self._send(
                    400,
                    json.dumps({"ok": False, "output": str(error)}).encode(),
                    "application/json",
                )
                return

        if endpoint == "/api/run-local":
            command = [
                sys.executable, str(ROOT / "qfhackathon.py"), "local",
                "--n", str(options["n"]),
                "--k", str(options["k"]),
                "--shots", str(options["shots"]),
                "--steps", str(options["steps"]),
            ]
        elif endpoint == "/api/run-resonance":
            if options.get("confirmed") is not True:
                self._send(400, json.dumps({
                    "ok": False,
                    "output": "Hardware submission requires explicit confirmation.",
                }).encode(), "application/json")
                return
            command = [
                sys.executable, str(ROOT / "qfhackathon.py"), "resonance",
                "--n", str(options["n"]),
                "--k", str(options["k"]),
                "--shots", str(options["shots"]),
                "--reps", str(options["reps"]),
                "--backend", str(options["backend"]),
                "--yes",
            ]

        if not RUN_LOCK.acquire(blocking=False):
            self._send(
                409,
                json.dumps({"ok": False, "output": "A portfolio run is already in progress."}).encode(),
                "application/json",
            )
            return

        try:
            process = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
                timeout=3600, check=False,
            )
            output = process.stdout + process.stderr
            if process.returncode == 0:
                if endpoint == "/api/generate-dataset":
                    self.server.has_generated_dataset = True
                    self.server.has_completed_run = False
                else:
                    self.server.has_completed_run = True
            include_saved = (
                (not self.server.start_fresh and not self.server.has_generated_dataset)
                or self.server.has_completed_run
            )
            payload = {
                "ok": process.returncode == 0,
                "output": "" if process.returncode == 0 else output[-2500:],
                "state": state(include_saved_result=include_saved) if process.returncode == 0 else None,
            }
            self._send(
                200 if process.returncode == 0 else 500,
                json.dumps(payload).encode(),
                "application/json",
            )
        except subprocess.TimeoutExpired:
            self._send(
                504,
                json.dumps({"ok": False, "output": "Simulation timed out"}).encode(),
                "application/json",
            )
        except OSError as error:
            self._send(
                500,
                json.dumps({"ok": False, "output": str(error)}).encode(),
                "application/json",
            )
        finally:
            RUN_LOCK.release()

    def _dataset_command(self) -> list[str]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request content length.") from error
        if not 0 <= content_length <= 2048:
            raise ValueError("Dataset request is too large.")
        payload = json.loads(self.rfile.read(content_length) or b"{}")
        if not isinstance(payload, dict) or payload.keys() - {"start"}:
            raise ValueError("Dataset request must contain only a start date.")
        start = payload.get("start", self.server.dataset_start)
        if not isinstance(start, str):
            raise ValueError("Dataset start date must be YYYY-MM-DD.")
        try:
            parsed_start = date.fromisoformat(start)
        except ValueError as error:
            raise ValueError("Dataset start date must be YYYY-MM-DD.") from error
        if parsed_start.isoformat() != start:
            raise ValueError("Dataset start date must be YYYY-MM-DD.")
        return [
            sys.executable, str(ROOT / "qfhackathon.py"), "download",
            "--start", start,
        ]

    def _run_options(self) -> dict[str, int | str | bool]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid request content length.") from error
        if not 0 < content_length <= 2048:
            raise ValueError("Run settings request is empty or too large.")
        payload = json.loads(self.rfile.read(content_length))
        if not isinstance(payload, dict):
            raise ValueError("Run settings must be a JSON object.")
        allowed = {"n", "k", "shots", "steps", "reps", "backend", "confirmed"}
        if payload.keys() - allowed:
            raise ValueError("Run settings contain unsupported fields.")

        defaults = self.server.run_options
        values: dict[str, int | str | bool] = {
            "n": payload.get("n", defaults["n"]),
            "k": payload.get("k", defaults["k"]),
            "shots": payload.get("shots", defaults["shots"]),
            "steps": payload.get("steps", defaults["steps"]),
            "reps": payload.get("reps", defaults["reps"]),
            "backend": payload.get("backend", defaults["backend"]),
            "confirmed": payload.get("confirmed", False),
        }
        metadata_path = DATA_DIR / "metadata.csv"
        if not metadata_path.is_file() or not (DATA_DIR / "returns.csv").is_file():
            raise ValueError("Generate the futures dataset from the dashboard first.")
        with metadata_path.open(newline="", encoding="utf-8") as metadata_file:
            available_assets = sum(1 for _ in csv.DictReader(metadata_file))
        integer_limits = {
            "n": (2, min(15, available_assets)),
            "shots": (32, 10000),
            "steps": (1, 100),
            "reps": (1, 3),
        }
        for name, (minimum, maximum) in integer_limits.items():
            value = values[name]
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
        if type(values["k"]) is not int or not 1 <= values["k"] <= values["n"] // 2:
            raise ValueError("k must be an integer between 1 and floor(n/2).")
        if values["backend"] not in {"emerald", "garnet", "sirius"}:
            raise ValueError("backend must be emerald, garnet, or sirius.")
        if type(values["confirmed"]) is not bool:
            raise ValueError("confirmed must be a boolean.")
        return values

    def log_message(self, format: str, *args) -> None:
        return


def create_server(
    port: int,
    n: int = DEMO_ASSETS,
    k: int = DEMO_K,
    shots: int = 256,
    steps: int = 20,
    *,
    start_fresh: bool = False,
    dataset_start: str = "2018-01-01",
) -> DashboardHTTPServer:
    run_options = {
        "n": n, "k": k, "shots": shots, "steps": steps, "reps": 1,
        "backend": "garnet",
    }
    try:
        return DashboardHTTPServer(
            ("127.0.0.1", port), DashboardHandler, run_options,
            start_fresh=start_fresh, dataset_start=dataset_start,
        )
    except OSError as error:
        if error.errno != errno.EADDRINUSE or port == 0:
            raise
        print(f"Port {port} is already in use; selecting an available port.")
        return DashboardHTTPServer(
            ("127.0.0.1", 0), DashboardHandler, run_options,
            start_fresh=start_fresh, dataset_start=dataset_start,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the standalone QFHackathon dashboard.")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with create_server(args.port) as server:
        print(f"Standalone dashboard running at http://{server.server_address[0]}:{server.server_address[1]}")
        server.serve_forever()
