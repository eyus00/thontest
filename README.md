# QFHackathon — Carbon-Aware Futures Hedging with QAOA

A self-contained pipeline that downloads energy/commodity futures prices from Yahoo Finance, turns a **carbon-aware long/short portfolio selection** problem into a **QUBO / Ising** model, and solves it three ways:

1. **Exact classical brute force** (the ground-truth reference),
2. **Local QAOA simulation** with [Qrisp](https://qrisp.eu),
3. **QAOA on real hardware** (IQM *Garnet*) through [IQM Resonance](https://resonance.iqm.tech).

Results are decoded, saved as JSON, and shown in a local web dashboard ("Quantum Carbon Hedge / Quantum Console") that can also trigger runs from the browser.

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
          exact enumeration     local QAOA (Qrisp)   QAOA on IQM Garnet
           (classical ref)       (simulator)          (via Resonance)
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
│   └── comparison.css        # Styling for the timing-comparison panel and buttons
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
| **IQM Resonance API token** | *Only* for the `resonance` and `compare` commands, and the dashboard's IQM buttons. |
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

You should see the subcommands `download, classical, local, run, resonance, compare, reset`.

The repo **ships with a sample dataset** (2018-01-03 → 2026-10-09, 15 futures, 2,207 daily returns) in `data/`, so you can run `classical`, `local` and the dashboard immediately without downloading anything.

---

## 5. Quick start

```bash
# (Optional) refresh the dataset from Yahoo Finance
python qfhackathon.py download --start 2018-01-01

# Exact classical solution for the first 5 assets, 2 long + 2 short
python qfhackathon.py classical --n 5 --k 2

# Classical reference + local QAOA simulation
python qfhackathon.py local --n 5 --k 2 --shots 256

# Launch the dashboard
python dashboard_server.py
# → open http://127.0.0.1:8765
```

Example output of the `classical` command on the bundled data:

```
Assets: BZ=F, CL=F, GC=F, HG=F, HO=F
Classical optimum: long=['HG=F', 'HO=F'] short=['BZ=F', 'GC=F'] net_carbon=-1574.26 energy=0.333569
```

For real hardware (needs a token, see [section 7](#7-iqm-resonance-setup-and-environment-variables)):

```bash
export RESONANCE_API_TOKEN='your-token'
python qfhackathon.py resonance --dry-run      # builds + transpiles, submits nothing
python qfhackathon.py resonance --shots 1000   # submits to IQM (consumes credits)
python qfhackathon.py compare                  # classical timing + IQM run + dashboard
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
| `--verbose` | Enables `DEBUG`-level logging. **Must come before the command**, e.g. `python qfhackathon.py --verbose local --n 5`. Default level is `INFO`. Log format: `HH:MM:SS \| LEVEL \| message`. |

Long-running stages (download, enumeration, QAOA, transpilation, hardware job) show an animated terminal spinner (`| / - \`).

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

Runs the exact solver first (as a reference), then QAOA at depth `p = 1` in Qrisp. Writes `data/dashboard_result.json` with the source tag `YAHOO / LOCAL QRISP / <shots> SHOTS`, and prints `Best sampled: …`.

---

### `resonance` — QAOA on IQM hardware

```bash
python qfhackathon.py resonance [--dry-run] [--shots S] [--reps R] [--n N] [--k K] [--yes]
```

| Flag | Default | Description |
|---|---|---|
| `--dry-run` | off | Build and transpile the circuit for the IQM backend, then stop. **No shots are submitted** (no credits used). A token and network access are still required to fetch the backend. |
| `--shots` | `1000` | Shots to submit. |
| `--reps` | `1` | QAOA depth `p` (number of cost/mixer layers). |
| `--n` | `5` | Number of assets. |
| `--k` | `2` | Assets per leg. |
| `--yes` | off | Defined for consistency, but `resonance` **does not prompt for confirmation** — it submits immediately unless `--dry-run` is set. (`--yes` only matters for `compare`.) |

Requires `RESONANCE_API_TOKEN` or `IQM_TOKEN`. If no dataset exists locally, it downloads the default window first. Saves raw counts to `data/resonance_counts.json` and the decoded summary to `data/dashboard_result.json` (source tag `YAHOO / IQM <BACKEND> / <shots> SHOTS`).

---

### `compare` — full classical-vs-quantum workflow + dashboard

```bash
python qfhackathon.py compare [--start DATE] [--n N] [--k K] [--shots S] [--reps R] \
                              [--port P] [--yes] [--no-browser]
```

| Flag | Default | Description |
|---|---|---|
| `--start` | `2018-01-01` | Start date if a dataset must be downloaded (only used when `metadata.csv`/`returns.csv` are missing). |
| `--n` | `5` | Number of assets. |
| `--k` | `2` | Assets per leg. |
| `--shots` | `1000` | Shots for the IQM job. |
| `--reps` | `1` | QAOA depth. |
| `--port` | `8765` | Dashboard port. If busy, a free port is chosen automatically. |
| `--yes` | off | Skip the "this may consume credits" confirmation prompt. |
| `--no-browser` | off | Don't auto-open the browser. |

Steps:

1. Download data if missing.
2. Build the QUBO and **time** it.
3. Run and **time** the exact classical enumeration.
4. Ask `Submit N shots to IQM garnet? This may consume Resonance credits. [y/N]` (skipped with `--yes`). Answering no (or no TTY / EOF) skips quantum and records classical timing only.
5. If confirmed, run the Resonance workflow (same as `resonance`).
6. Write `data/dashboard_comparison.json`.
7. Start the dashboard and (unless `--no-browser`) open it.

There's also a hidden `--no-dashboard` flag (used internally by the dashboard server) that does steps 1–6 and exits.

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

```bash
python dashboard_server.py          # then open http://127.0.0.1:8765
```

The server binds only to `127.0.0.1` (local machine), has no authentication, and reads only this folder's `data/`.

### Buttons

| Button | What it does (via POST) |
|---|---|
| **Run local QAOA** | `POST /api/run-local` → `qfhackathon.py local --n 8 --k 2 --shots 256 --steps 20` |
| **Compare + run Resonance** | `POST /api/run-comparison` → `qfhackathon.py compare --shots 1000 --reps 1 --n 8 --k 2 --yes --no-dashboard` (browser confirm dialog first) |
| **Submit to IQM** | `POST /api/run-resonance` → `qfhackathon.py resonance --shots 1000 --reps 1 --n 8 --k 2` (browser confirm dialog first) |
| **Reset data** | `POST /api/reset-dataset` → `qfhackathon.py reset --yes --refresh` (clears and re-downloads) |
| **↻ (refresh)** | Re-fetches `GET /api/state` without running anything |

The dashboard buttons use **fixed parameters** (8 assets, k = 2); change them in `dashboard_server.py` (`do_POST`) if you want different values. Each request runs the CLI synchronously with a 1-hour timeout.

### HTTP API

| Method & path | Returns |
|---|---|
| `GET /` and static files | Files from `dashboard/` (`.html`, `.css`, `.js` only get proper content types; path traversal outside `dashboard/` is blocked) |
| `GET /api/state` | JSON: `model`, `result`, `source`, `comparison`, `scaling` |
| `POST /api/run-local`, `/api/run-resonance`, `/api/run-comparison`, `/api/reset-dataset` | JSON: `{ok, output, state}`; HTTP 500 on failure, 504 on timeout |

`/api/state` converts tickers (e.g. `CL=F`) to human names (e.g. "WTI crude oil") in the results before sending them to the UI.

### Panels

- **Latest decoded measurement** — long leg, short leg, objective (energy) score, and the source tag.
- **Classical search vs QUBO/QAOA** — five timings: exact classical solve, QUBO build, IQM compile, Resonance job wait, quantum end-to-end.
- **Net carbon exposure** — |net carbon| of the best feasible portfolio, in kg CO₂ per equal-$1,000 position.
- **Feasible probability** — fraction of shots that satisfy all constraints.
- **Run profile** — qubits, shots, distinct bitstrings, backend.
- **Universe composition** — carbon intensity of every asset.
- **Scaling runway** — search-space size and number of feasible portfolios.

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
| `Set RESONANCE_API_TOKEN or IQM_TOKEN before using resonance` | Export the token in the same shell. For the dashboard, export it **before** launching `dashboard_server.py`. |
| Authentication / HTTP errors from Resonance | Wrong/expired token, or wrong `IQM_URL` / `IQM_BACKEND`. |
| `ModuleNotFoundError: qrisp` (or `iqm`, `qiskit`) | Virtual environment not activated, or `pip install -r requirements.txt` failed. |
| Package conflicts between Qiskit / IQM / Qrisp | Try Python 3.11 or 3.12 in a fresh venv; pin versions once you find a working set. |
| `Port 8765 is already in use; selecting an available port.` | Normal — use the URL printed next. Or pass `--port`. |
| Dashboard shows placeholder values (e.g. "waiting for run") | No result file yet. Click **Run local QAOA** or run `local` from the CLI, then **↻**. |
| Dashboard "Reset data" fails | Needs internet for the Yahoo re-download. |
| Dashboard run returns 504 | The subprocess exceeded the 3600 s timeout. |
| `reset` does nothing in a script/CI | No TTY → the prompt gets EOF → cancelled. Add `--yes`. |

---

## 14. Known limitations and quirks

These come from reading the code; they're worth knowing before presenting results.

1. **Asset selection is alphabetical.** `--n` takes the first `n` columns of `returns.csv`. With `--n 5` you get Brent, WTI, Gold, Copper, Heating oil — **not** the five most relevant energy contracts. Reorder columns or add a ticker-selection flag if you want specific assets.
2. **Hardware angles are not optimised.** Every QAOA angle on IQM is fixed at `0.5`. Results are essentially a noisy sample from one untuned circuit.
3. **`resonance` submits without confirmation.** Only `compare` (and the dashboard's browser confirm dialog) asks first. `resonance --yes` does nothing extra.
4. **Dashboard qubit/scaling numbers reflect the whole dataset, not the last run.** The UI counts all downloaded assets (15 → "30 qubits", and scaling for `k = 2`), while dashboard runs actually use `n = 8` (16 qubits). The `k = 2` in the model is also hard-coded.
5. **Some dashboard text is static.** E.g. "exact classical match" under the score, "Long/short symmetry verified", and the initial placeholder numbers in `index.html` are hard-coded, not computed from the run. The exposure bar is scaled against a fixed 20,000 kg.
6. **Docstring vs behaviour.** The classical solver is described as "feasible-state enumeration," but it scans **all** `2^(2n)` bitstrings and filters.
7. **Dashboard run buttons are not mutually exclusive.** The server is threaded with no locking; launching two runs at once can race on the same `data/` files.
8. **No authentication on the dashboard API.** It's bound to localhost only, but anyone with access to your machine's loopback could trigger Resonance submissions (which use your token).
9. **`covariance.csv` is not read by the pipeline** (covariance is recomputed from `returns.csv`), and `exp_return`/`vol` in `metadata.csv` aren't used by the QUBO.
10. **Hard-coded carbon factors.** Emission factors and MMBtu-per-unit values in `FUTURES` are fixed approximations; `kg_co2_per_mmbtu` for metals/agriculture has no effect because their `mmbtu_per_unit` is 0.
11. **Sample data is a snapshot.** The bundled `data/` files were produced by one run (10 assets, 1,000 shots, Garnet). They show the format, but your own runs overwrite them.

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