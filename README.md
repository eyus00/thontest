# QFHackathon All-in-One

This folder is a separate, self-contained combined workflow. The original modular implementation remains in the repository root as the backup/reference version.

From this folder:

```bash
python -m venv .venv
source .venv/bin/activate                 # macOS/Linux
# .venv\Scripts\Activate.ps1             # Windows PowerShell
python3 -m pip install -r requirements.txt
python qfhackathon.py download --start 2018-01-01
python qfhackathon.py classical --n 5 --k 2
python qfhackathon.py local --n 5 --k 2 --shots 256
```

Show more detailed logs with `--verbose` before the command. The CLI prints timestamped stages and animated spinners while downloading, enumerating, optimizing, or submitting.

For Resonance, the standalone folder builds and submits its own IQM circuit:

```bash
export RESONANCE_API_TOKEN='your-token'
python qfhackathon.py resonance --dry-run
python qfhackathon.py resonance --shots 1000
```

Yahoo data is downloaded into this folder's `data/` directory. All commands are self-contained; only the Resonance token and network access are external requirements.

Run the full comparison workflow:

```bash
python qfhackathon.py compare
```

It times exact classical enumeration, asks before submitting the default 1,000-shot QAOA job to the configured IQM backend, records both timings, and then starts the dashboard. Use `--yes` only when you want to skip that credit-use confirmation, `--port 8766` to request another port, or `--no-browser` to avoid opening a browser automatically. The dashboard separates classical solve, QUBO build, IQM compilation, Resonance submit-to-result wait, and quantum end-to-end times. The remote duration includes queue/service wait and must not be interpreted as QPU execution time or a like-for-like quantum speedup.

Clear generated data and saved results, then download a fresh dataset:

```bash
python qfhackathon.py reset --refresh
```

The command asks before deleting. Add `--yes` to confirm non-interactively. Reset only removes the known generated CSV/JSON data files in this folder's `data/`; it leaves source files and unknown files untouched. Omit `--refresh` to clear the data without downloading a replacement.

Start this folder's dashboard and workflow controls locally:

```bash
python dashboard_server.py
```

Open <http://127.0.0.1:8765>. The dashboard serves the frontend bundled in this folder, reads only this folder's `data/`, and runs the local Qrisp or IQM workflow through this folder's launcher. Results from either run are decoded and saved to `data/dashboard_result.json` for the dashboard.

If port `8765` is already in use, the server automatically selects an available local port and prints the URL to open. You can also request a specific port with `python dashboard_server.py --port 8766`.
