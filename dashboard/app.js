const $ = (selector) => document.querySelector(selector);

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value || 0);
}

function formatSeconds(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  const seconds = Number(value);
  return seconds < 1 ? `${(seconds * 1000).toFixed(1)} ms` : `${seconds.toFixed(2)} s`;
}

function render(state) {
  const result = state.result || {};
  const comparison = state.comparison || {};
  const classical = comparison.classical || {};
  const quantum = comparison.quantum || {};
  const best = result.best_feasible || {};
  const longAssets = best.long || [];
  const shortAssets = best.short || [];
  const carbon = Number(best.net_carbon || 0);
  const feasible = Number(result.feasible_probability || 0);
  $('#sourceTag').textContent = state.source || 'LATEST RESULT';
  const assets = (state.model && state.model.assets_detail) || [];
  const qubits = assets.length * 2;
  $('#qubits').textContent = formatNumber(qubits);
  $('#orbitQubits').textContent = `${formatNumber(qubits)} qubits`;
  $('#backend').textContent = comparison.backend
    ? comparison.backend.toUpperCase()
    : ((state.source || '').includes('IQM') ? (state.source.match(/IQM ([^/]+)/) || [])[1]?.trim() || 'IQM' : 'LOCAL');

  $('#longAssets').innerHTML = longAssets.length ? longAssets.join('<br>') : 'waiting for run';
  $('#shortAssets').innerHTML = shortAssets.length ? shortAssets.join('<br>') : 'waiting for run';
  $('#energyScore').textContent = best.energy != null ? Number(best.energy).toFixed(6) : '—';
  $('#netCarbon').innerHTML = `${formatNumber(Math.abs(carbon))}<span> kg CO₂</span>`;
  $('#feasibleRate').innerHTML = `${(feasible * 100).toFixed(1)}<span>%</span>`;
  $('#feasibleRate').closest('.validity-panel').querySelector('.bar-rows b i').style.width = `${Math.max(feasible * 100, 1)}%`;
  $('#feasibleRate').closest('.validity-panel').querySelector('.pale i').style.width = `${Math.max((1 - feasible) * 100, 1)}%`;
  $('#shots').textContent = formatNumber(result.total_shots || 0);
  $('#states').textContent = formatNumber(result.distinct_bitstrings || 0);
  $('#longCarbon').textContent = longAssets.length ? 'selected' : '—';
  $('#shortCarbon').textContent = shortAssets.length ? 'selected' : '—';
  $('#exposureFill').style.width = `${Math.min(Math.max(Math.abs(carbon) / 20000 * 100, 8), 94)}%`;

  $('#comparisonStamp').textContent = comparison.completed_at
    ? `Assets: ${comparison.asset_count}; qubits: ${comparison.qubit_count}; ${comparison.shots} shots`
    : 'Run a comparison to populate timings';
  $('#classicalTime').textContent = formatSeconds(classical.solve_seconds);
  $('#classicalStates').textContent = classical.states_considered
    ? `${formatNumber(classical.states_considered)} bitstrings considered`
    : 'feasible-state enumeration';
  $('#quboTime').textContent = formatSeconds(classical.qubo_build_seconds);
  $('#compileTime').textContent = formatSeconds(quantum.compile_seconds);
  $('#quantumJobTime').textContent = formatSeconds(quantum.remote_job_seconds);
  $('#quantumTotalTime').textContent = formatSeconds(quantum.end_to_end_seconds);

  $('#assetHeading').textContent = `${assets.length} energy exposures`;
  const maxCarbon = Math.max(...assets.map((asset) => asset.carbon), 1);
  $('#assetBars').innerHTML = assets.map((asset) => `
    <div class="asset-row">
      <span class="asset-name">${asset.asset}</span>
      <b><i style="width:${Math.max(asset.carbon / maxCarbon * 100, 4)}%"></i></b>
      <span class="asset-value">${formatNumber(asset.carbon)} kg</span>
    </div>`).join('');

  const scaling = state.scaling || [];
  const maxFeasible = Math.max(...scaling.map((row) => row.feasible_portfolios || 0), 1);
  $('#scalingRows').innerHTML = scaling.map((row) => `
    <div class="scaling-row">
      <strong>${row.asset_count}</strong>
      <span>${row.qubits} q</span>
      <b><i style="width:${Math.max((row.feasible_portfolios / maxFeasible) * 100, 4)}%"></i></b>
      <span class="scaling-count">${formatNumber(row.feasible_portfolios)}</span>
      <em class="${row.benchmark_kind === 'real_base_assets' ? 'real' : ''}">${row.benchmark_kind === 'real_base_assets' ? 'EIA base' : 'stress'}</em>
    </div>`).join('');
}

async function loadState() {
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load project state');
  render(await response.json());
}

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  window.setTimeout(() => node.classList.remove('show'), 3000);
}

$('#refreshButton').addEventListener('click', async () => {
  try { await loadState(); toast('Results refreshed'); }
  catch (error) { toast(error.message); }
});

$('#compareButton').addEventListener('click', async () => {
  const backend = ($('#backend').textContent || 'Garnet').trim();
  if (!window.confirm(`Run exact classical enumeration, then submit 1,000 shots to IQM ${backend}? This may consume Resonance credits.`)) return;
  const button = $('#compareButton');
  const status = $('#runStatus');
  button.disabled = true;
  button.innerHTML = '<span>◌</span> Comparing…';
  status.textContent = 'Running the classical reference, then waiting for IQM…';
  try {
    const response = await fetch('/api/run-comparison', { method: 'POST' });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.output || 'Comparison failed');
    render(payload.state);
    status.textContent = 'Comparison complete';
    toast('Classical and Resonance timings loaded');
  } catch (error) {
    status.textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = '<span>◷</span> Compare + run Resonance';
  }
});

$('#resetButton').addEventListener('click', async () => {
  if (!window.confirm('Clear the saved Yahoo dataset and run results, then download a fresh Yahoo dataset?')) return;
  const button = $('#resetButton');
  button.disabled = true;
  try {
    const response = await fetch('/api/reset-dataset', { method: 'POST' });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.output || 'Dataset refresh failed');
    render(payload.state);
    toast('Dataset refreshed; previous results cleared');
  } catch (error) {
    $('#runStatus').textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false;
  }
});

$('#runButton').addEventListener('click', async () => {
  const button = $('#runButton');
  const status = $('#runStatus');
  button.disabled = true;
  button.innerHTML = '<span>◌</span> Running QAOA locally';
  status.textContent = 'Qrisp is sampling 256 shots…';
  try {
    const response = await fetch('/api/run-local', { method: 'POST' });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.output || 'Local simulation failed');
    render(payload.state);
    status.textContent = 'Local QAOA complete';
    toast('Local QAOA result loaded');
  } catch (error) {
    status.textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = '<span>▶</span> Run local QAOA';
  }
});

$('#resonanceButton').addEventListener('click', async () => {
  const backend = ($('#backend').textContent || 'Garnet').trim();
  if (!window.confirm(`Submit 1,000 shots to IQM ${backend}? This may consume Resonance credits.`)) return;
  const button = $('#resonanceButton');
  const status = $('#runStatus');
  button.disabled = true;
  button.innerHTML = '<span>◌</span> Submitting to Garnet';
  status.textContent = 'Waiting for IQM Resonance…';
  try {
    const response = await fetch('/api/run-resonance', { method: 'POST' });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.output || 'Resonance submission failed');
    render(payload.state);
    status.textContent = 'Garnet result loaded';
    toast('IQM Garnet result loaded');
  } catch (error) {
    status.textContent = error.message;
    toast(error.message);
  } finally {
    button.disabled = false;
    button.innerHTML = '<span>↗</span> Submit to Garnet';
  }
});

loadState().catch((error) => { $('#runStatus').textContent = error.message; });
