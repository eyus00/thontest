"""Standalone Yahoo futures and local QAOA workflow for the all_in_one folder."""
from __future__ import annotations

import argparse
import datetime
import itertools
import json
import logging
import os
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import webbrowser

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("qfhackathon")


def configure_logging(verbose=False):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S",
    )


@contextmanager
def progress(label):
    """Show a small terminal spinner while a long operation is running."""
    running = True

    def spin():
        symbols = "|/-\\"
        index = 0
        while running:
            sys.stdout.write(f"\r{label} {symbols[index % len(symbols)]}")
            sys.stdout.flush()
            index += 1
            time.sleep(0.12)
        sys.stdout.write(f"\r{label} done\n")
        sys.stdout.flush()

    thread = threading.Thread(target=spin, daemon=True)
    LOGGER.info("Starting: %s", label)
    thread.start()
    try:
        yield
    finally:
        running = False
        thread.join()

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULT_PATH = DATA_DIR / "dashboard_result.json"
COMPARISON_PATH = DATA_DIR / "dashboard_comparison.json"
GENERATED_DATA_FILES = (
    "prices.csv",
    "returns.csv",
    "metadata.csv",
    "covariance.csv",
    "resonance_counts.json",
    "dashboard_result.json",
    "dashboard_comparison.json",
)
TRADING_DAYS = 252
FUTURES = {
    "CL=F": ("WTI crude oil", "oil", 5.8, 73.15),
    "BZ=F": ("Brent crude oil", "oil", 5.8, 73.15),
    "NG=F": ("Natural gas", "gas", 1.0, 53.06),
    "RB=F": ("RBOB gasoline", "gasoline", 0.125, 70.66),
    "HO=F": ("Heating oil", "heating_oil", 0.1385, 73.15),
    "GC=F": ("Gold", "metal", 0.0, 12.0),
    "SI=F": ("Silver", "metal", 0.0, 18.0),
    "HG=F": ("Copper", "metal", 0.0, 4.5),
    "ZC=F": ("Corn", "agriculture", 0.0, 1.2),
    "ZW=F": ("Wheat", "agriculture", 0.0, 1.0),
    "ZS=F": ("Soybeans", "agriculture", 0.0, 1.5),
    "ZM=F": ("Soybean Meal", "agriculture", 0.0, 1.3),
    "ZL=F": ("Soybean Oil", "agriculture", 0.0, 1.8),
    "ZB=F": ("30-Year Treasury Bond", "bond", 0.0, 0.0),
    "ZN=F": ("10-Year Treasury Note", "bond", 0.0, 0.0),
}


@dataclass
class Universe:
    tickers: list[str]
    types: list[str]
    carbon: np.ndarray
    sigma: np.ndarray


def download(start, end=None):
    import yfinance as yf

    tickers = list(FUTURES)
    with progress("Downloading Yahoo futures"):
        raw = yf.download(tickers, start=start, end=end, auto_adjust=False, group_by="column", progress=False, threads=False)
    if raw.empty:
        raise RuntimeError("Yahoo Finance returned no data")
    prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if not isinstance(prices, pd.DataFrame):
        prices = prices.to_frame()
    if list(prices.columns) == ["Close"]:
        prices.columns = [tickers[0]]
    prices = prices.ffill().dropna(how="any")
    selected = [ticker for ticker in prices.columns if ticker in FUTURES]
    if len(selected) < 2:
        raise RuntimeError("Fewer than two futures had usable price history")
    prices = prices[selected]
    returns = prices.pct_change().dropna(how="any")
    metadata = pd.DataFrame.from_dict(
        {ticker: {"name": FUTURES[ticker][0], "type": FUTURES[ticker][1], "mmbtu_per_unit": FUTURES[ticker][2], "kg_co2_per_mmbtu": FUTURES[ticker][3]} for ticker in selected},
        orient="index",
    )
    metadata.index.name = "ticker"
    metadata["exp_return"] = returns.mean() * TRADING_DAYS
    metadata["vol"] = returns.std() * np.sqrt(TRADING_DAYS)
    metadata["carbon"] = 1000.0 / prices.mean() * metadata["mmbtu_per_unit"] * metadata["kg_co2_per_mmbtu"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    prices.to_csv(DATA_DIR / "prices.csv")
    returns.to_csv(DATA_DIR / "returns.csv")
    metadata.to_csv(DATA_DIR / "metadata.csv")
    returns.cov().mul(TRADING_DAYS).to_csv(DATA_DIR / "covariance.csv")
    LOGGER.info("Saved %d futures and %d observations to %s", len(selected), len(returns), DATA_DIR)


def load(n):
    metadata = pd.read_csv(DATA_DIR / "metadata.csv").set_index("ticker")
    returns = pd.read_csv(DATA_DIR / "returns.csv", index_col=0)
    tickers = [ticker for ticker in returns.columns if ticker in metadata.index][:n]
    if len(tickers) < 2:
        raise RuntimeError("Download the dataset first or choose at least two futures")
    return Universe(tickers, metadata.loc[tickers, "type"].tolist(), metadata.loc[tickers, "carbon"].to_numpy(float), returns[tickers].cov().to_numpy(float) * TRADING_DAYS)


def build_qubo(u, k):
    n = len(u.tickers)
    if not 0 < k <= n // 2:
        raise ValueError("k must be between 1 and floor(n/2)")
    carbon = u.carbon / np.mean(np.abs(u.carbon))
    sigma = u.sigma / max(np.max(np.abs(u.sigma)), 1e-12)
    mapping = np.hstack((np.eye(n), -np.eye(n)))
    q = np.outer(carbon @ mapping, carbon @ mapping) + mapping.T @ sigma @ mapping
    constant = 0.0
    for start in (0, n):
        selector = np.zeros(2 * n)
        selector[start:start + n] = 1
        q += 50 * np.outer(selector, selector)
        q[start:start + n, start:start + n] -= 100 * k * np.eye(n)
        constant += 50 * k * k
    for i in range(n):
        q[i, n + i] += 25
        q[n + i, i] += 25
    return (q + q.T) / 2, constant


def hobby_rice_balance(u, tolerance=1e-5):
    """Numerically balance continuous exposure measures with at most t switches."""
    from scipy.optimize import least_squares

    n = u.n
    measures = []
    names = []

    carbon = np.asarray(u.carbon, dtype=float)
    if np.linalg.norm(carbon) > 1e-12:
        measures.append(carbon)
        names.append("carbon")

    measures.append(np.ones(n))
    names.append("dollar")

    energy_types = {"oil", "gas", "gasoline", "heating_oil"}
    energy_assets = np.array([kind in energy_types for kind in u.types])
    if np.any(energy_assets):
        weights = energy_assets.astype(float) / energy_assets.sum()
        beta_variance = float(weights @ u.sigma @ weights)
        if beta_variance > 1e-12:
            beta = (u.sigma @ weights) / beta_variance
            if np.linalg.norm(beta) > 1e-12:
                measures.append(beta)
                names.append("energy_sector_beta")

    values = np.asarray(measures, dtype=float)
    values /= np.linalg.norm(values, axis=1)[:, None]
    measure_count = len(names)
    prefix = np.column_stack((np.zeros(measure_count), np.cumsum(values, axis=1)))

    def primitive(position):
        index = min(int(position), n)
        if index == n:
            return prefix[:, n]
        return prefix[:, index] + (position - index) * values[:, index]

    def signed_integrals(switches):
        result = np.zeros(measure_count)
        left = 0.0
        sign = 1.0
        for right in (*np.sort(switches), float(n)):
            result += sign * (primitive(right) - primitive(left))
            left = right
            sign = -sign
        return result

    starts = [np.linspace(0, n, measure_count + 2)[1:-1]]
    rng = np.random.default_rng(0)
    starts.extend(np.sort(rng.uniform(0, n, measure_count)) for _ in range(31))
    best = None
    for initial in starts:
        result = least_squares(
            signed_integrals,
            initial,
            bounds=(np.zeros(measure_count), np.full(measure_count, float(n))),
            max_nfev=2000,
            ftol=1e-12,
            xtol=1e-12,
            gtol=1e-12,
        )
        residual = signed_integrals(result.x)
        error = float(np.max(np.abs(residual)))
        if best is None or error < best["error"]:
            best = {
                "switches": np.sort(result.x).tolist(),
                "residual": residual.tolist(),
                "error": error,
            }
        if error <= tolerance:
            break

    return {
        "method": "Hobby-Rice (Borsuk-Ulam) continuous relaxation",
        "status": "numerical_balance_found" if best["error"] <= tolerance else "numerical_residual_above_tolerance",
        "theoretical_guarantee": (
            "For these integrable measures, a continuous +/-1 partition exists "
            "with at most one switch per measure."
        ),
        "discrete_limit": (
            "Switches may split an asset interval. The guarantee does not imply "
            "an exactly balanced discrete portfolio or an optimal QUBO solution."
        ),
        "measure_names": names,
        "switch_count": sum(
            1 for value in best["switches"] if 1e-8 < value < n - 1e-8
        ),
        "switch_positions": best["switches"],
        "normalized_residuals": dict(zip(names, best["residual"])),
        "max_abs_normalized_residual": best["error"],
        "tolerance": tolerance,
    }


def energy(bits, q, constant):
    values = np.asarray(bits, dtype=float)
    return float(values @ q @ values + constant)


def feasible(bits, n, k):
    values = np.asarray(bits, dtype=int)
    return values.size == 2 * n and values[:n].sum() == k and values[n:].sum() == k and not np.any(values[:n] & values[n:])


def exact(q, constant, n, k):
    candidates = []
    with progress(f"Enumerating exact feasible portfolios ({n} assets)"):
        for index in range(1 << (2 * n)):
            bits = tuple((index >> shift) & 1 for shift in range(2 * n - 1, -1, -1))
            if feasible(bits, n, k):
                candidates.append((energy(bits, q, constant), bits))
    return min(candidates)


def describe(bits, u):
    values = np.asarray(bits, dtype=int)
    longs = [u.tickers[i] for i in range(u.n) if values[i]]
    shorts = [u.tickers[i] for i in range(u.n) if values[u.n + i]]
    net = float(u.carbon @ (values[:u.n] - values[u.n:]))
    return f"long={longs} short={shorts} net_carbon={net:.2f}"


def summarize_counts(counts, u, q, constant, k, reverse_bitstrings=False):
    measurements = []
    for raw_bits, raw_count in counts.items():
        bitstring = str(raw_bits).replace(" ", "")
        if len(bitstring) != 2 * u.n or set(bitstring) - {"0", "1"}:
            continue
        ordered = bitstring[::-1] if reverse_bitstrings else bitstring
        bits = tuple(int(bit) for bit in ordered)
        values = np.asarray(bits, dtype=int)
        is_feasible = bool(feasible(bits, u.n, k))
        measurements.append({
            "bitstring": bitstring,
            "count": float(raw_count),
            "energy": energy(bits, q, constant),
            "feasible": is_feasible,
            "long": [u.tickers[i] for i in range(u.n) if values[i]],
            "short": [u.tickers[i] for i in range(u.n) if values[u.n + i]],
            "net_carbon": float(u.carbon @ (values[:u.n] - values[u.n:])),
        })
    total = sum(item["count"] for item in measurements)
    if total <= 0:
        raise ValueError("Measurement counts must contain a positive total")
    for item in measurements:
        item["probability"] = item["count"] / total
    ranked = measurements
    ranked.sort(key=lambda item: (not item["feasible"], item["energy"]))
    feasible_results = [item for item in ranked if item["feasible"]]
    return {
        "total_shots": int(total) if total.is_integer() else total,
        "distinct_bitstrings": len(ranked),
        "feasible_shots": sum(item["count"] for item in feasible_results),
        "feasible_probability": sum(item["probability"] for item in feasible_results),
        "best_feasible": feasible_results[0] if feasible_results else None,
        "top_feasible": feasible_results[:10],
        "top_measured": sorted(ranked, key=lambda item: item["count"], reverse=True)[:10],
    }


def save_dashboard_result(counts, u, q, constant, k, source, reverse_bitstrings=False):
    result = summarize_counts(counts, u, q, constant, k, reverse_bitstrings)
    result["continuous_balance"] = hobby_rice_balance(u)
    result["source"] = source
    RESULT_PATH.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def qubo_to_ising(q, constant=0.0):
    q = (np.asarray(q, dtype=float) + np.asarray(q, dtype=float).T) / 2
    ones = np.ones(q.shape[0])
    fields = -0.5 * q @ ones
    couplings = {
        (i, j): 0.5 * q[i, j]
        for i in range(q.shape[0])
        for j in range(i + 1, q.shape[0])
        if abs(q[i, j]) > 1e-12
    }
    return fields, couplings, float(constant + 0.25 * (ones @ q @ ones + np.trace(q)))


@property
def _n(u):
    return len(u.tickers)
Universe.n = _n


def run_qaoa(q, constant, u, k, shots, steps):
    from qrisp import QuantumArray, QuantumVariable, gphase, rz, rzz, x
    from qrisp.alg_primitives import dicke_state
    from qrisp.qaoa import QAOAProblem, portfolio_mixer

    scale = max(float(np.max(np.abs(q))), 1.0)

    def cost_operator(qarg, gamma):
        qubits = [qarg[0][i] for i in range(u.n)] + [qarg[1][i] for i in range(u.n)]
        gphase(-gamma * constant / scale, qubits[0])
        for i in range(2 * u.n):
            if q[i, i]:
                rz(2 * gamma * q[i, i] / scale, qubits[i])
        for i in range(2 * u.n):
            for j in range(i + 1, 2 * u.n):
                if q[i, j]:
                    rzz(2 * gamma * q[i, j] / scale, qubits[i], qubits[j])

    def key(value):
        return "".join(str(bit) for bit in value.flatten()) if hasattr(value, "flatten") else str(value).replace(" ", "")

    def classical_cost(counts):
        return sum(energy(tuple(int(bit) for bit in key(name)), q, constant) * count for name, count in counts.items())

    def initialize(qarg):
        for i in range(k):
            x(qarg[0][i])
            x(qarg[1][i])
        dicke_state(qarg[0], k)
        dicke_state(qarg[1], k)

    with progress(f"Running local QAOA ({shots} shots)"):
        result = QAOAProblem(cost_operator, portfolio_mixer(), classical_cost, init_function=initialize).run(
            lambda: QuantumArray(QuantumVariable(u.n), shape=(2,)), depth=1, mes_kwargs={"shots": shots}, max_iter=max(steps, 4)
        )
    counts = {key(name): float(count) for name, count in result.items()}
    save_dashboard_result(
        counts, u, q, constant, k, f"YAHOO / LOCAL QRISP / {shots} SHOTS"
    )
    valid = [(energy(tuple(map(int, name)), q, constant), name, count) for name, count in counts.items() if feasible(tuple(map(int, name)), u.n, k)]
    LOGGER.info("QAOA measured %d states; feasible probability=%.3f", len(counts), sum(item[2] for item in valid))
    if valid:
        best = min(valid)
        print("Best sampled:", describe(tuple(map(int, best[1])), u), f"energy={best[0]:.6f}")


def run_classical(args):
    universe = load(args.n)
    q, constant = build_qubo(universe, args.k)
    best_energy, best_bits = exact(q, constant, universe.n, args.k)
    LOGGER.info("Assets: %s", ", ".join(universe.tickers))
    LOGGER.info("Classical optimum: %s energy=%.6f", describe(best_bits, universe), best_energy)


def run_local(args):
    universe = load(args.n)
    q, constant = build_qubo(universe, args.k)
    best_energy, best_bits = exact(q, constant, universe.n, args.k)
    LOGGER.info("Classical reference: %s energy=%.6f", describe(best_bits, universe), best_energy)
    run_qaoa(q, constant, universe, args.k, args.shots, args.steps)


def run_resonance(args):
    """Route and optionally submit the standalone model directly to IQM."""
    started = time.perf_counter()
    from qiskit import QuantumCircuit, transpile
    from qiskit.circuit.library import QAOAAnsatz
    from qiskit.quantum_info import SparsePauliOp
    from iqm.qiskit_iqm import IQMProvider

    token_present = bool(os.environ.get("RESONANCE_API_TOKEN") or os.environ.get("IQM_TOKEN"))
    if not token_present:
        raise RuntimeError("Set RESONANCE_API_TOKEN or IQM_TOKEN before using resonance")
    if not (DATA_DIR / "metadata.csv").exists():
        LOGGER.info("No local Yahoo dataset found; downloading the default window first")
        download("2018-01-01")
    universe = load(args.n)
    q, constant = build_qubo(universe, args.k)
    fields, couplings, ising_constant = qubo_to_ising(q, constant)
    width = 2 * universe.n
    terms = []
    for index, coefficient in enumerate(fields):
        if coefficient:
            word = ["I"] * width
            word[width - 1 - index] = "Z"
            terms.append(("".join(word), coefficient))
    for (first, second), coefficient in couplings.items():
        if coefficient:
            word = ["I"] * width
            word[width - 1 - first] = "Z"
            word[width - 1 - second] = "Z"
            terms.append(("".join(word), coefficient))
    cost = SparsePauliOp.from_list(terms)
    mixer_terms = []
    for start in (0, universe.n):
        for offset in range(universe.n):
            first = start + offset
            second = start + ((offset + 1) % universe.n)
            if first == second:
                continue
            for pauli in ("X", "Y"):
                word = ["I"] * width
                word[width - 1 - first] = pauli
                word[width - 1 - second] = pauli
                mixer_terms.append(("".join(word), 0.5))
    mixer = SparsePauliOp.from_list(mixer_terms).simplify()
    initial = QuantumCircuit(width)
    for index in range(args.k):
        initial.x(index)
        initial.x(universe.n + index)
    provider = IQMProvider(
        os.environ.get("IQM_URL", "https://resonance.iqm.tech"),
        quantum_computer=os.environ.get("IQM_BACKEND", "garnet"),
        token=os.environ.get("RESONANCE_API_TOKEN") or os.environ.get("IQM_TOKEN"),
    )
    backend_name = os.environ.get("IQM_BACKEND", "garnet")
    backend = provider.get_backend(backend_name)
    circuit = QAOAAnsatz(cost_operator=cost, mixer_operator=mixer, initial_state=initial, reps=args.reps)
    circuit.measure_all()
    compile_started = time.perf_counter()
    with progress("Transpiling and binding IQM circuit"):
        transpiled = transpile(circuit, backend=backend, optimization_level=3)
        angles = [0.5] * len(transpiled.parameters)
        bound = transpiled.assign_parameters(dict(zip(transpiled.parameters, angles)))
    compile_seconds = time.perf_counter() - compile_started
    LOGGER.info("%s circuit ready: %d qubits, %d angles", backend_name.upper(), width, len(angles))
    if getattr(args, "dry_run", False):
        LOGGER.info("Resonance dry run passed; no shots submitted")
        return {
            "backend": backend_name,
            "qubits": width,
            "compile_seconds": compile_seconds,
            "remote_job_seconds": None,
            "end_to_end_seconds": time.perf_counter() - started,
        }
    job_started = time.perf_counter()
    with progress(f"Running IQM Resonance/{backend_name.upper()}"):
        counts = backend.run(bound, shots=args.shots).result().get_counts()
    remote_job_seconds = time.perf_counter() - job_started
    output_path = DATA_DIR / "resonance_counts.json"
    output_path.write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    save_dashboard_result(
        counts, universe, q, constant, args.k,
        f"YAHOO / IQM {backend_name.upper()} / {args.shots} SHOTS",
        reverse_bitstrings=True,
    )
    LOGGER.info("Saved hardware counts to %s", output_path)
    return {
        "backend": backend_name,
        "qubits": width,
        "compile_seconds": compile_seconds,
        "remote_job_seconds": remote_job_seconds,
        "end_to_end_seconds": time.perf_counter() - started,
    }


def _confirm_resonance_submission(args) -> bool:
    if args.yes:
        return True
    try:
        answer = input(
            f"Submit {args.shots} shots to IQM {os.environ.get('IQM_BACKEND', 'garnet')}? "
            "This may consume Resonance credits. [y/N] "
        )
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def run_comparison(args):
    if not (DATA_DIR / "metadata.csv").is_file() or not (DATA_DIR / "returns.csv").is_file():
        LOGGER.info("No complete local dataset found; downloading the default Yahoo window")
        download(args.start)

    universe = load(args.n)
    model_started = time.perf_counter()
    q, constant = build_qubo(universe, args.k)
    qubo_build_seconds = time.perf_counter() - model_started
    classical_started = time.perf_counter()
    best_energy, best_bits = exact(q, constant, universe.n, args.k)
    classical_seconds = time.perf_counter() - classical_started
    LOGGER.info("Classical optimum: %s energy=%.6f", describe(best_bits, universe), best_energy)

    backend = os.environ.get("IQM_BACKEND", "garnet")
    quantum = None
    if _confirm_resonance_submission(args):
        quantum = run_resonance(args)
    else:
        LOGGER.info("Resonance submission skipped; showing classical timing only")

    values = np.asarray(best_bits, dtype=int)
    comparison = {
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "asset_count": universe.n,
        "qubit_count": 2 * universe.n,
        "continuous_balance": hobby_rice_balance(universe),
        "shots": args.shots,
        "classical": {
            "method": "Exact feasible-state enumeration",
            "qubo_build_seconds": qubo_build_seconds,
            "solve_seconds": classical_seconds,
            "states_considered": 1 << (2 * universe.n),
            "best_energy": best_energy,
            "long": [universe.tickers[i] for i in range(universe.n) if values[i]],
            "short": [universe.tickers[i] for i in range(universe.n) if values[universe.n + i]],
        },
        "quantum": None if quantum is None else {
            **quantum,
            "method": "QAOA on IQM Resonance",
            "shots": args.shots,
            "remote_job_includes_queue": True,
        },
        "backend": backend,
        "timing_note": (
            "The classical figure times exact enumeration only. Quantum compilation is separate; "
            "the Resonance job duration includes submission and service/queue wait, not just QPU gate time. "
            "These timings use different algorithms and are not an apples-to-apples speedup benchmark."
        ),
    }
    COMPARISON_PATH.write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    LOGGER.info("Saved timing comparison to %s", COMPARISON_PATH)

    if not args.no_dashboard:
        from dashboard_server import create_server

        with create_server(args.port) as server:
            url = f"http://{server.server_address[0]}:{server.server_address[1]}"
            print(f"Dashboard running at {url}")
            if not args.no_browser:
                webbrowser.open(url)
            server.serve_forever()


def reset_dataset(args):
    if not args.yes:
        try:
            answer = input(
                "Delete generated Yahoo dataset and saved result files from this folder? [y/N] "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in {"y", "yes"}:
            LOGGER.info("Dataset reset cancelled")
            return

    removed = []
    for name in GENERATED_DATA_FILES:
        path = DATA_DIR / name
        if path.is_file():
            path.unlink()
            removed.append(name)
    LOGGER.info("Removed generated files: %s", ", ".join(removed) if removed else "none")
    if args.refresh:
        download(args.start)


def add_run_options(parser):
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--k", type=int, default=2)
    parser.add_argument("--shots", type=int, default=256)
    parser.add_argument("--steps", type=int, default=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    download_parser = sub.add_parser("download")
    download_parser.add_argument("--start", default="2018-01-01")
    download_parser.add_argument("--end")
    classical_parser = sub.add_parser("classical", help="run exact classical optimization")
    add_run_options(classical_parser)
    local_parser = sub.add_parser("local", help="run classical reference plus local QAOA")
    add_run_options(local_parser)
    run_parser = sub.add_parser("run", help="compatibility alias for local")
    add_run_options(run_parser)
    resonance_parser = sub.add_parser("resonance", help="run or dry-run IQM Resonance/Garnet")
    resonance_parser.add_argument("--dry-run", action="store_true")
    resonance_parser.add_argument("--shots", type=int, default=1000)
    resonance_parser.add_argument("--reps", type=int, default=1)
    resonance_parser.add_argument("--n", type=int, default=5)
    resonance_parser.add_argument("--k", type=int, default=2)
    resonance_parser.add_argument("--yes", action="store_true", help="confirm submission without prompting")
    comparison_parser = sub.add_parser(
        "compare",
        help="time exact classical solving, submit QAOA to Resonance, then start the dashboard",
    )
    comparison_parser.add_argument("--start", default="2018-01-01")
    comparison_parser.add_argument("--n", type=int, default=5)
    comparison_parser.add_argument("--k", type=int, default=2)
    comparison_parser.add_argument("--shots", type=int, default=1000)
    comparison_parser.add_argument("--reps", type=int, default=1)
    comparison_parser.add_argument("--port", type=int, default=8765)
    comparison_parser.add_argument("--yes", action="store_true", help="confirm submission without prompting")
    comparison_parser.add_argument("--no-dashboard", action="store_true", help=argparse.SUPPRESS)
    comparison_parser.add_argument("--no-browser", action="store_true")
    reset_parser = sub.add_parser(
        "reset",
        help="remove generated dataset and saved results; optionally download a fresh dataset",
    )
    reset_parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    reset_parser.add_argument("--refresh", action="store_true", help="download a fresh dataset after clearing")
    reset_parser.add_argument("--start", default="2018-01-01")
    args = parser.parse_args()
    configure_logging(args.verbose)
    if args.command == "download":
        download(args.start, args.end)
    elif args.command == "classical":
        run_classical(args)
    elif args.command in {"local", "run"}:
        run_local(args)
    elif args.command == "resonance":
        run_resonance(args)
    elif args.command == "compare":
        run_comparison(args)
    elif args.command == "reset":
        reset_dataset(args)


if __name__ == "__main__":
    main()
