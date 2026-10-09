# Antipode — Carbon-Aware Futures Hedging with QAOA

A self-contained pipeline that uses historical Yahoo Finance futures data, turns a **carbon-aware long/short portfolio selection** problem into a **QUBO / Ising** model, and solves it classically and with local QAOA:

1. **Exact classical brute force** (the ground-truth reference),
2. **Local QAOA simulation** with [Qrisp](https://qrisp.eu).

Use `python qfhackathon.py demo` (or `python qfhackathon.py dashboard`) to open the Antipode dashboard. The dashboard starts without solving a portfolio: if the data is missing, choose **Generate futures dataset** in the page, then run local QAOA or configure an IQM Resonance run. This keeps every demonstration step visible and avoids pre-filled results from an earlier run.

---

## Table of contents

1. [What the project does](#1-what-the-project-does)
2. [Repository layout](#2-repository-layout)
3. [Requirements](#3-requirements)
4. [Installation](#4-installation)
5. [Quick start](#5-quick-start)
6. [CLI reference (all commands and flags)](#6-cli-reference-all-commands-and-flags)
7. [IQM Resonance setup and environment variables](#7-iqm-resonance-setup-and-environment-variables)
8. [The dashboard](#8-the-dashboard)
9. [How it works (technical deep dive)](#9-how-it-works-technical-deep-dive)
10. [Data files reference](#10-data-files-reference)
11. [Reading the timing comparison correctly](#11-reading-the-timing-comparison-correctly)
12. [Scaling and practical limits](#12-scaling-and-practical-limits)
13. [Troubleshooting](#13-troubleshooting)
14. [Known limitations and quirks](#14-known-limitations-and-quirks)
15. [Suggested repository cleanup](#15-suggested-repository-cleanup)

---

## 1. What the project does

### The financial problem

Given a universe of futures contracts (crude oil, natural gas, gasoline, metals, grains, Treasuries, ...), choose:

- **`k` assets to go long**, and
- **`k` different assets to go short**,

so that the resulting **long/short hedge** simultaneously:

- has a **net carbon exposure close to zero** (long carbon minus short carbon is balanced), and
- has **low variance**, using the annualised covariance matrix of the assets' daily returns.

An asset can't be both long and short, and each leg must contain **exactly `k`** assets.

### The pipeline

```
 Yahoo Finance ──► prices / returns / covariance / carbon metadata  (data/*.csv)
                                  │
                                  ▼
                   QUBO matrix Q (2n binary variables)
                    │                 │                  │
                    ▼                 ▼                  ▼
          exact enumeration     local QAOA (Qrisp)
           (classical ref)       (simulator)
                    └────────────────┬─────────────────┘
                                     ▼
                  decoded measurement counts → data/dashboard_result.json
                                     ▼
                         browser dashboard (localhost)
```

### Decision variables

For `n` assets there are `2n` binary variables (= `2n` qubits):

- bits `0 … n-1` — **long** flag for each asset,
- bits `n … 2n-1` — **short** flag for each asset.

A bitstring is **feasible** only if exactly `k` long bits are set, exactly `k` short bits are set, and no asset is both long and short.

---

## 2. Repository layout

```
.
├── qfhackathon.py            # Tiny entry point: calls qfhackathon_core.main()
├── qfhackathon_core.py       # All logic: download, QUBO, exact solver, QAOA, IQM, CLI
├── dashboard_server.py       # Local HTTP server: serves the UI + JSON API + runs the CLI
├── requirements.txt          # Python dependencies (unpinned)
├── dashboard/
│   ├── index.html            # Dashboard markup
│   ├── app.js                # Fetches /api/state, renders it, wires up the buttons
│   ├── styles.css            # Main styling (also @imports Google Fonts)
│   └── showcase.css          # Responsive presentation dashboard refinements
├── data/                     # Generated data and results (see section 10)
│   ├── prices.csv
│   ├── returns.csv
│   ├── covariance.csv
│   ├── metadata.csv
│   ├── dashboard_result.json
│   ├── dashboard_comparison.json
│   └── resonance_counts.json
├── .gitattributes            # `* text=auto` (line-ending normalisation)
├── __pycache__/              # Compiled bytecode (should not be committed)
└── .DS_Store                 # macOS metadata (should not be committed)
```

Everything is **relative to the folder containing the scripts**. Data is always read from and written to `./data/`, regardless of your working directory.

---

## 3. Requirements

| Requirement | Notes |
|---|---|
| **Python 3.10+** | The bundled `__pycache__` shows the project was developed on Python 3.14. If installing Qrisp / Qiskit / IQM packages fails on a very new Python, try 3.11 or 3.12. |
| **Internet access** | Needed for the Yahoo download, for pip, for the dashboard's Google Fonts (cosmetic; falls back to system fonts), and for Resonance. Local classical/QAOA runs on already-downloaded data work offline. |
| **IQM Resonance API token** | Only for the optional `resonance` and `compare` CLI commands. |
| **A modern browser** | For the dashboard. |

Python packages (`requirements.txt`):

| Package | Used for |
|---|---|
| `numpy`, `pandas` | Data handling, covariance, QUBO matrices |
| `yfinance` | Downloading futures prices |
| `qrisp` | Local QAOA (`QAOAProblem`, Dicke-state init, portfolio mixer, simulator) |
| `qiskit` | Building the QAOA circuit for hardware (`QAOAAnsatz`, `SparsePauliOp`, `transpile`) |
| `qiskit-aer` | Qiskit simulator backend |
| `iqm-client[qiskit]` | `IQMProvider` to talk to IQM Resonance/Garnet |
| `scipy` | Numerical support used by the quantum libraries (classical optimiser in the QAOA loop) |

> **Tip:** `requirements.txt` is unpinned, and Qiskit / IQM / Qrisp versions must be mutually compatible. Once you have a working environment, run `python -m pip freeze > requirements.lock.txt` so teammates can reproduce it exactly.

---

## 4. Installation

```bash
# 1. Enter the project folder
cd thontest-main            # or whatever you named it

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\Activate.ps1         # Windows PowerShell
# .venv\Scripts\activate.bat         # Windows cmd.exe

# 4. Install dependencies
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Verify the install:

```bash
python qfhackathon.py --help
```

You should see the subcommands `demo, dashboard, download, classical, local, run, resonance, compare, reset`.

The repository may include a bundled dataset in `data/`. Use `reset` to remove generated files and saved results; the dashboard can then build a fresh dataset when you start the demo.

---

## 5. Quick start — demo mode

```bash
python qfhackathon.py demo
```

The dashboard-first demo opens without running either solver or displaying an old saved portfolio. If data is unavailable, select **Generate futures dataset** in the dashboard. When it is ready, choose **Run local QAOA** or **Run on Resonance**.

Options set the run defaults and data range, or prevent automatic browser launch:

```bash
python qfhackathon.py demo --n 6 --k 2 --shots 128 --steps 8 --no-browser
```

To reset and start with no cached dataset or portfolio:

```bash
python qfhackathon.py reset --yes
python qfhackathon.py demo
```

Then click **Generate futures dataset** in the browser. Use `python qfhackathon.py dashboard` as an equivalent dashboard-only command. Use `Ctrl+C` in the terminal to stop the server. No packages are installed automatically when starting the app; dependency setup is a separate one-time environment step.

For a focused CLI-only run, use:

```bash
python qfhackathon.py local --n 8 --k 2 --shots 256 --steps 20
```

---

## 6. CLI reference (all commands and flags)

General form:

```bash
python qfhackathon.py [--verbose] <command> [command options]
```

### Global flag

| Flag | Description |
|---|---|
| `--verbose` | Enables detailed debug logging. **Must come before the command**, e.g. `python qfhackathon.py --verbose local --n 5`. Default output is concise. |

Long-running stages show an animated terminal spinner when attached to an interactive terminal, and simple progress lines when output is piped. The app does not install or update packages automatically.

### `demo` / `dashboard` — open the dashboard-first demo

```bash
python qfhackathon.py demo [--n N] [--k K] [--shots S] [--steps T] [--start DATE] [--port P] [--no-browser]
python qfhackathon.py dashboard [--n N] [--k K] [--shots S] [--steps T] [--start DATE] [--port P] [--no-browser]
```

Starts a clean dashboard session without downloading data or precomputing a portfolio. If no dataset is present, the page offers **Generate futures dataset**; after download, choose local QAOA or open the Resonance settings. Defaults are 8 assets, 2 positions per leg, 256 shots and 20 optimizer steps for local runs. The `--start` date is used if the dashboard generates data. Press `Ctrl+C` to stop the server.

---

### `download` — fetch Yahoo Finance data

```bash
python qfhackathon.py download [--start YYYY-MM-DD] [--end YYYY-MM-DD]
```

| Flag | Default | Description |
|---|---|---|
| `--start` | `2018-01-01` | First date to download. |
| `--end` | *(none = up to today)* | End date, passed to `yfinance` (exclusive). |

What it does:

1. Downloads **unadjusted close prices** (`auto_adjust=False`) for the 15 futures tickers.
2. Forward-fills gaps, then drops any date where **any** ticker is still missing — so the usable history starts at the date when the *youngest* contract has data.
3. Computes daily percent-change returns.
4. Computes per-asset metadata (annualised expected return, annualised volatility, carbon intensity).
5. Writes `prices.csv`, `returns.csv`, `metadata.csv`, `covariance.csv` into `data/`.

Fails with an error if Yahoo returns nothing or fewer than 2 usable tickers.

---

### `classical` — exact brute-force solution

```bash
python qfhackathon.py classical [--n N] [--k K]
```

| Flag | Default | Description |
|---|---|---|
| `--n` | `5` | Number of assets to use (the **first `n` columns** of `returns.csv`, which are alphabetical by ticker — see [quirks](#14-known-limitations-and-quirks)). |
| `--k` | `2` | Assets per leg. Must satisfy `1 ≤ k ≤ floor(n/2)`. |
| `--shots`, `--steps` | `256`, `10` | Accepted (shared option set) but **ignored** by `classical`. |

Enumerates all `2^(2n)` bitstrings, keeps the feasible ones, and prints the lowest-energy portfolio.

---

### `local` (alias: `run`) — classical reference + local QAOA

```bash
python qfhackathon.py local [--n N] [--k K] [--shots S] [--steps T]
python qfhackathon.py run   ...   # identical alias
```

| Flag | Default | Description |
|---|---|---|
| `--n` | `5` | Number of assets (first `n` in the dataset). |
| `--k` | `2` | Assets per leg; `1 ≤ k ≤ floor(n/2)`. |
| `--shots` | `256` | Measurement shots for the QAOA simulation. |
| `--steps` | `10` | Maximum classical-optimiser iterations for QAOA (internally `max(steps, 4)`). |

Runs the exact solver first (as a reference), then QAOA at depth `p = 1` in Qrisp. Writes `data/dashboard_result.json` with the source tag `YAHOO / LOCAL QRISP / <shots> SHOTS`, including the selected universe, asset/qubit counts, and numerical continuous-balance result. Prints the exact reference and best feasible sampled portfolio separately.

---

### `resonance` — QAOA on IQM hardware

```bash
python qfhackathon.py resonance [--dry-run] [--shots S] [--reps R] [--n N] [--k K] [--backend {emerald,garnet,sirius}]
```

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Build and transpile the circuit for the IQM backend, then stop. **No shots are submitted** (no credits used). A token and network access are still required to fetch the backend. |
| `--shots` | `1000` | Shots to submit. |
| `--reps` | `1` | QAOA depth `p` (number of cost/mixer layers). |
| `--n` | `5` | Number of assets. |
| `--k` | `2` | Assets per leg. |
| `--backend` | `garnet` or `IQM_BACKEND` | IQM Resonance backend identifier: `emerald`, `garnet`, or `sirius`. |
| `--yes` | off | Accepted for CLI consistency; the specialist `resonance` command itself submits without prompting. Use `--dry-run` to compile without submitting. |

Requires `RESONANCE_API_TOKEN` or `IQM_TOKEN`. If no dataset exists locally, it downloads the default window first. Saves raw counts to `data/resonance_counts.json` and the decoded summary to `data/dashboard_result.json` (source tag `YAHOO / IQM <BACKEND> / <shots> SHOTS`).

---

### `compare` — CLI timing summary with optional IQM run

```bash
python qfhackathon.py compare [--start DATE] [--n N] [--k K] [--shots S] [--reps R] \
                              [--yes] [--dashboard] [--port P] [--no-browser]
```

| Flag | Default | Description |
|---|---|---|
| `--start` | `2018-01-01` | Start date if a dataset must be downloaded (only used when `metadata.csv`/`returns.csv` are missing). |
| `--n` | `5` | Number of assets. |
| `--k` | `2` | Assets per leg. |
| `--shots` | `1000` | Shots for the IQM job. |
| `--reps` | `1` | QAOA depth. |
| `--yes` | off | Skip the "this may consume credits" confirmation prompt. |
| `--dashboard` | off | Also open the presentation dashboard after the timing summary. |
| `--port` | `8765` | Dashboard port, only used with `--dashboard`. |
| `--no-browser` | off | Don't auto-open the browser. |

Steps:

1. Download data if missing.
2. Build the QUBO and **time** it.
3. Run and **time** the exact classical enumeration.
4. Ask `Submit N shots to IQM garnet? This may consume Resonance credits. [y/N]` (skipped with `--yes`). Answering no (or no TTY / EOF) skips quantum and records classical timing only.
5. If confirmed, run the Resonance workflow (same as `resonance`).
6. Write `data/dashboard_comparison.json` and print build, exact-solve, and (when run) hardware timings. Timings include different methods and are not a speedup comparison.
7. Start the dashboard only when `--dashboard` is supplied.

---

### `reset` — clear generated data

```bash
python qfhackathon.py reset [--yes] [--refresh] [--start DATE]
```

| Flag | Default | Description |
|---|---|---|
| `--yes` | off | Skip the `[y/N]` confirmation. |
| `--refresh` | off | After deleting, download a fresh dataset. |
| `--start` | `2018-01-01` | Start date for the `--refresh` download. |

Deletes **only** these known files from `data/`: `prices.csv`, `returns.csv`, `metadata.csv`, `covariance.csv`, `resonance_counts.json`, `dashboard_result.json`, `dashboard_comparison.json`. Source code and any other files are untouched. With no TTY and no `--yes`, the reset is cancelled.

---

### `dashboard_server.py` flags

```bash
python dashboard_server.py [--port PORT]
```

| Flag | Default | Description |
|---|---|---|
| `--port` | `8765` | Port to bind on `127.0.0.1`. If taken, prints a notice and picks any free port. Watch the console for the URL. |

---

## 7. IQM Resonance setup and environment variables

1. Create an account at [resonance.iqm.tech](https://resonance.iqm.tech) and generate an **API token**.
2. Export it in the **same shell** that runs the CLI **or the dashboard server** (the dashboard launches CLI subprocesses that inherit your environment).

```bash
# macOS / Linux
export RESONANCE_API_TOKEN='your-token'

# Windows PowerShell
$env:RESONANCE_API_TOKEN = 'your-token'
```

| Variable | Default | Purpose |
|---|---|---|
| `RESONANCE_API_TOKEN` | — | API token (preferred). |
| `IQM_TOKEN` | — | Alternative token variable; used if `RESONANCE_API_TOKEN` is unset. |
| `IQM_URL` | `https://resonance.iqm.tech` | Resonance endpoint. |
| `IQM_BACKEND` | `garnet` | Quantum computer name passed to `IQMProvider`. |

Never commit your token. Test connectivity and circuit compatibility for free with `python qfhackathon.py resonance --dry-run`.

---

## 8. The dashboard

For the full guided presentation, use `python qfhackathon.py demo`. To serve the current saved result without running a solve, use:

```bash
python dashboard_server.py
```

The server binds only to `127.0.0.1` (local machine), has no authentication, and reads only this folder's `data/`.

The Antipode dashboard starts with no computed portfolio for each `demo`/`dashboard` session, even when an older saved result exists. If the data files are absent, use **Generate futures dataset** in the page; it downloads Yahoo futures history and enables the run actions once valid data is ready. This also works after `python qfhackathon.py reset --yes`. No solver runs before you ask it to.

The dashboard has two separate run actions:

- **Run local QAOA** runs the Qrisp-based simulation on your computer. It does not use IQM hardware. The local optimizer uses the demo's default settings.
- **Run on Resonance** opens a settings dialog for futures count, positions per leg, shots, hardware layers, and IQM model. When submitted, the app prepares the problem and circuit on your computer, sends the circuit to the selected IQM backend for quantum sampling, then decodes and displays the returned samples. This is not a locally solved portfolio being sent to IQM. The hardware circuit currently uses fixed initial angles and a Qiskit circuit path that differs from the local Qrisp simulation.

Hardware submission may consume Resonance credits and requires `RESONANCE_API_TOKEN` or `IQM_TOKEN` in the server process environment. While either run is active, the orbital graphic floats to the center and cycles through concise stage hints. These animations are visual feedback, not live per-stage telemetry. Run controls are restored after success or failure. Before a result is available, the portfolio cards show animated, unreadable matrix-style placeholder data.

The objective meter shows the carbon and covariance contributions for the selected feasible portfolio; it is not a return or profit score. The carbon meter is signed around a zero-balance marker and scaled to that portfolio's gross financed carbon exposure. Historical saved results made before contribution fields were added show “rerun” until a new solve is run. Local runs invoke Qrisp; remote runs invoke the existing Qiskit/IQM path, whose circuit initialization and fixed angles are not identical to the local Qrisp circuit. A browser run invokes the CLI synchronously with a 1-hour timeout. Repeated and concurrent browser requests are prevented from racing over shared result files.

### HTTP API

| Method & path | Returns |
|---|---|
| `GET /` and static files | Files from `dashboard/` (`.html`, `.css`, `.js` only get proper content types; path traversal outside `dashboard/` is blocked) |
| `GET /api/state` | JSON: selected-run `model`, `result`, `source`, `asset_count`, `qubit_count` |
| `POST /api/generate-dataset` | Generates the default Yahoo dataset (or the dashboard's configured `--start` date); returns `{ok, output, state}` |
| `POST /api/run-local` | JSON body: `{n, k, shots, steps}`; returns `{ok, output, state}` |
| `POST /api/run-resonance` | JSON body: `{n, k, shots, reps, backend, confirmed}`; requires `confirmed: true`; returns `{ok, output, state}` |

The API validates portfolio dimensions, shot/layer limits and the IQM backend allow-list. A missing hardware credential or provider/backend error is returned visibly by the dashboard; no dependencies are installed automatically.

`/api/state` converts tickers (e.g. `CL=F`) to human names (e.g. "WTI crude oil") in the results before sending them to the UI.

### Panels

- **Selected portfolio** — sampled long and short legs with the QUBO objective score.
- **Objective breakdown** — carbon and covariance contribution values and their relative share of the objective.
- **Net financed carbon** — signed exposure estimate for equal-$1,000 positions; this is not emissions reduction.
- **Feasible shots** — fraction of QAOA samples satisfying all portfolio constraints.
- **Profile X** — selected asset count, corresponding qubit count, shots and backend.
- **Hobby–Rice balance certificate** — numerical continuous-relaxation result and explicit warning that it does not certify discrete optimality.

Detailed timing benchmarks remain in the CLI. Local simulation and IQM hardware are presented as separate run choices.

---

## 9. How it works (technical deep dive)

All logic lives in `qfhackathon_core.py`.

### 9.1 Asset universe and carbon model

15 futures are defined in the `FUTURES` dict as `ticker: (name, type, mmbtu_per_unit, kg_co2_per_mmbtu)`:

| Group | Tickers |
|---|---|
| Oil | `CL=F` (WTI), `BZ=F` (Brent) |
| Gas / refined | `NG=F`, `RB=F` (RBOB gasoline), `HO=F` (heating oil) |
| Metals | `GC=F` (gold), `SI=F` (silver), `HG=F` (copper) |
| Agriculture | `ZC=F`, `ZW=F`, `ZS=F`, `ZM=F`, `ZL=F` |
| Bonds | `ZB=F` (30-yr), `ZN=F` (10-yr) |

The **carbon intensity** per asset is:

```
carbon = 1000 / mean_price × mmbtu_per_unit × kg_co2_per_mmbtu
```

i.e. kg CO₂ embodied in a **$1,000 position**, using the average historical price. Only fossil fuels have non-zero `mmbtu_per_unit`; metals, grains and bonds end up with `carbon = 0`.

`metadata.csv` also stores annualised `exp_return` and `vol` (252 trading days). **These two are informational only; the QUBO uses just carbon and covariance.**

### 9.2 Loading a sub-universe (`load`)

`load(n)` reads `metadata.csv` and `returns.csv`, takes the **first `n` tickers in `returns.csv` column order** (alphabetical), and builds the annualised covariance matrix `Σ = cov(returns) × 252`. Requires at least 2 assets.

### 9.3 QUBO construction (`build_qubo`)

With `x = [long bits, short bits]` (length `2n`) and `w = long − short`:

1. **Normalise:** carbon is divided by its mean absolute value; Σ by its max absolute entry.
2. **Mapping matrix** `M = [I | −I]` (so `M·x = long − short`).
3. **Objective:**
   `E(x) = (carbon · w)² + wᵀ Σ w`
   — squared net carbon (drive it to zero) plus portfolio variance.
4. **Constraint penalties** (weight 50 each), added as quadratic terms:
   - `50·(Σ long bits − k)²`
   - `50·(Σ short bits − k)²`
   - `50·long_i·short_i` for each asset (no asset on both sides)
5. Symmetrise: `Q ← (Q + Qᵀ)/2`. A constant offset `100·k²` (= `50k² + 50k²`) is tracked separately.

Energy of a bitstring: `E = bᵀ Q b + constant` (function `energy`). Feasibility is checked by `feasible()`.

`k` is validated: `0 < k ≤ floor(n/2)`.

### 9.3.1 Continuous balance certificate (Hobby–Rice)

Before reporting a sampled portfolio, `hobby_rice_balance()` numerically searches for a Hobby–Rice sign partition of the continuous relaxation: each asset occupies a unit interval and switch points may split an asset's interval. The balanced measures are nonzero carbon exposure, equal-dollar notional, and (when estimable) beta to an equal-weight basket of the selected oil, gas, gasoline, and heating-oil futures. The sector beta is a proxy derived from the annualised covariance matrix, not an independently sourced market-sector index.

Hobby–Rice, proved using Borsuk–Ulam, guarantees that a continuous ±1 partition balancing `t` integrable measures exists with at most `t` switches. The implementation uses deterministic multi-start least squares to find and report a numerical residual for that certificate; it does not claim that a numerical optimizer verifies the theorem. Switches can split asset intervals, so this existence result does not guarantee an exactly balanced discrete portfolio, a feasible QUBO bitstring, or an optimal solution. The QUBO and its discrete constraints remain unchanged.

### 9.4 Exact classical solver (`exact`)

Iterates over **all `2^(2n)` bitstrings**, keeps those passing `feasible()`, and returns the minimum-energy one. This is a pure-Python brute force: simple and certain, but cost grows **4× per extra asset**.

### 9.5 Local QAOA with Qrisp (`run_qaoa`)

- State: a `QuantumArray` of two `QuantumVariable(n)` registers (long, short).
- **Initial state:** each register is prepared as a **Dicke state** with `k` excitations (uniform superposition over all `k`-subsets), so the circuit starts inside the feasible subspace.
- **Mixer:** Qrisp's `portfolio_mixer()` (a particle-number-preserving XY-type mixer) keeps the state in that subspace.
- **Cost operator:** built from `rz` (diagonal terms) and `rzz` (pairwise terms), with coefficients scaled by `max(|Q|, 1)`, plus a global phase for the constant.
- **Classical loop:** `QAOAProblem(...).run(depth=1, shots=…, max_iter=max(steps, 4))` optimises the angles by minimising the expected energy from measurement counts.
- Output counts are decoded, scored, ranked, and saved to `dashboard_result.json`.

### 9.6 Decoding results (`summarize_counts`)

For every measured bitstring: parse bits, compute energy, test feasibility, list long/short tickers, compute net carbon (`carbon · (long − short)`), and compute its probability. Outputs `total_shots`, `distinct_bitstrings`, `feasible_shots`, `feasible_probability`, `best_feasible`, `top_feasible` (10), and `top_measured` (10, by count). Bitstrings with the wrong length or non-binary characters are skipped. For hardware counts, `reverse_bitstrings=True` corrects Qiskit's little-endian ordering.

### 9.7 IQM hardware path (`run_resonance`)

1. `qubo_to_ising` converts `Q` into Ising fields `hᵢ`, couplings `Jᵢⱼ`, and a constant offset.
2. The **cost Hamiltonian** is a `SparsePauliOp` of `Z` and `ZZ` terms.
3. The **mixer** is an XY ring mixer (`XX + YY` between neighbours) built **separately within the long block and the short block**, preserving the number of selected assets per leg.
4. **Initial state:** `X` gates on the first `k` qubits of each block (one computational-basis feasible state).
5. `QAOAAnsatz(reps=--reps)` + `measure_all()` is **transpiled to the IQM backend at `optimization_level=3`**.
6. **All QAOA angles are bound to a fixed `0.5`** — there is **no variational optimisation loop on hardware**; a single circuit is run with `--shots` shots.
7. Counts are saved to `data/resonance_counts.json`, decoded, and saved to `dashboard_result.json`.

Returned timings: `compile_seconds` (transpile + bind), `remote_job_seconds` (submit → result, **includes queue/network wait**), and `end_to_end_seconds`.

Because the angles aren't tuned and the circuit is noisy, the fraction of shots that land on feasible portfolios is usually small. The bundled sample hardware result has 1.4% feasible shots, and the best sampled hedge isn't guaranteed to match the classical optimum.

---

## 10. Data files reference

All in `data/`. All except the README-documented ones are regenerated by commands.

| File | Created by | Contents |
|---|---|---|
| `prices.csv` | `download` | Daily close prices; `Date` index, one column per ticker. |
| `returns.csv` | `download` | Daily percent-change returns. |
| `covariance.csv` | `download` | Annualised (`×252`) covariance of returns, all tickers. *(Informational: `load()` recomputes covariance from `returns.csv` for the chosen subset.)* |
| `metadata.csv` | `download` | `ticker, name, type, mmbtu_per_unit, kg_co2_per_mmbtu, exp_return, vol, carbon`. |
| `dashboard_result.json` | `local`, `resonance`, `compare` | Latest decoded measurement summary (see 9.6) plus a `source` tag. |
| `dashboard_comparison.json` | `compare` | Timing comparison: classical (`qubo_build_seconds`, `solve_seconds`, `states_considered`, `best_energy`, long/short), quantum (`compile_seconds`, `remote_job_seconds`, `end_to_end_seconds`, `shots`), `backend`, `timing_note`. |
| `resonance_counts.json` | `resonance`, `compare` | Raw `{bitstring: count}` from hardware. |

Note that `dashboard_result.json` only reflects the **most recent** run (local *or* hardware); each run overwrites it.

---

## 11. Reading the timing comparison correctly

The comparison is deliberately **not** a speedup benchmark:

- The classical figure is a **brute-force enumeration** in Python; it is not a state-of-the-art solver (MIQP/branch-and-bound/heuristics).
- The quantum figure is **one fixed-angle QAOA circuit** with sampling; it doesn't guarantee the optimum.
- `remote_job_seconds` **includes network and queue wait**, not just QPU gate time.
- Different algorithms are being timed.

Treat the numbers as observed wall-clock times for this specific small instance. The dashboard shows this caveat directly under the timing panel.

---

## 12. Scaling and practical limits

| Assets `n` | Qubits `2n` | Bitstrings `2^(2n)` |
|---|---|---|
| 5 | 10 | 1,024 |
| 8 | 16 | 65,536 |
| 10 | 20 | 1,048,576 |
| 12 | 24 | 16,777,216 |
| 15 | 30 | 1,073,741,824 |

Number of *feasible* portfolios: `C(n, k) × C(n − k, k)`. For `n = 8, k = 2` that's 28 × 15 = 420.

- `classical`/`compare` take noticeably longer each time you add an asset; `n ≥ 13` with the pure-Python enumerator becomes impractical, and `n = 15` is not feasible.
- Local Qrisp simulation memory also grows exponentially with `2n` qubits.
- The IQM Garnet device has a limited number of qubits and connectivity; transpilation depth grows with `n` and `--reps`.

---

## 13. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Download the dataset first or choose at least two futures` | `data/` is empty or `--n < 2`. Run `python qfhackathon.py download`. |
| `k must be between 1 and floor(n/2)` | Lower `--k` or raise `--n`. |
| `Yahoo Finance returned no data` / `Fewer than two futures had usable price history` | Network/Yahoo rate limit, or the `--start`/`--end` window is too narrow. Retry or widen the window. |
| `Set RESONANCE_API_TOKEN or IQM_TOKEN before using resonance` | Export the token in the same shell before running the optional `resonance` or `compare` CLI command. |
| Authentication / HTTP errors from Resonance | Wrong/expired token, or wrong `IQM_URL` / `IQM_BACKEND`. |
| `ModuleNotFoundError: qrisp` (or `iqm`, `qiskit`) | Virtual environment not activated, or `pip install -r requirements.txt` failed. |
| Package conflicts between Qiskit / IQM / Qrisp | Try Python 3.11 or 3.12 in a fresh venv; pin versions once you find a working set. |
| `Port 8765 is already in use; selecting an available port.` | Normal — use the URL printed next. Or pass `--port`. |
| Dashboard shows placeholder values (e.g. "waiting for run") | No result file yet. Click **Run local QAOA** or run `local` from the CLI, then **↻**. |
| Dashboard run returns 504 | The subprocess exceeded the 3600 s timeout. |
| `reset` does nothing in a script/CI | No TTY → the prompt gets EOF → cancelled. Add `--yes`. |

---

## 14. Known limitations and quirks

These come from reading the code; they're worth knowing before presenting results.

1. **Asset selection is alphabetical.** `--n` takes the first `n` columns of `returns.csv`. With `--n 5` you get Brent, WTI, Gold, Copper, Heating oil — **not** the five most relevant energy contracts.
2. **Hardware angles are not optimised.** Every QAOA angle on IQM is fixed at `0.5`. Results are essentially a noisy sample from one untuned circuit.
3. **`resonance` submits without confirmation.** This specialist command can consume credits; use `--dry-run` to compile without submitting.
4. **The dashboard is local-only.** It binds to loopback and has no authentication; anyone with access to the local machine may trigger a local QAOA run.
5. **The QUBO has no expected-return term.** `exp_return` and `vol` in metadata are informational; the current portfolio objective balances estimated financed carbon and covariance risk, not profitability.
6. **Docstring vs behaviour.** The classical solver is described as "feasible-state enumeration," but it scans **all** `2^(2n)` bitstrings and filters.
7. **The dashboard run button uses fixed settings.** The guided `demo` command accepts custom `n`, `k`, `shots` and `steps`.
8. **`covariance.csv` is not read by the pipeline** (covariance is recomputed from `returns.csv`), and `exp_return`/`vol` in `metadata.csv` aren't used by the QUBO.
9. **Hard-coded carbon factors.** Emission factors and MMBtu-per-unit values in `FUTURES` are fixed approximations; `kg_co2_per_mmbtu` for metals/agriculture has no effect because their `mmbtu_per_unit` is 0.
10. **Sample data is a snapshot.** The bundled prices, returns and metadata are historical snapshots; local QAOA runs overwrite the saved dashboard result.

---

## 15. Suggested repository cleanup

- Add a `.gitignore`:
  ```
  __pycache__/
  .venv/
  .DS_Store
  *.pyc
  ```
- Remove the committed `__pycache__/` and `.DS_Store` (`git rm -r --cached __pycache__ .DS_Store`).
- Pin dependency versions once a working environment is found.
- Decide whether `data/` (about 1.2 MB of regenerable CSVs and results) should be committed or generated on demand.