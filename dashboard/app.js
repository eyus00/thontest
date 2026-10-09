const $ = (selector) => document.querySelector(selector);

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value ?? 0);
}

function renderAssetList(selector, assets, emptyLabel) {
  const container = $(selector);
  container.replaceChildren();
  if (!assets?.length) {
    container.textContent = emptyLabel;
    return;
  }
  for (const asset of assets) {
    const row = document.createElement('span');
    row.className = 'asset-line';
    row.textContent = asset;
    container.append(row);
  }
}

function render(state) {
  const result = state.result || {};
  const best = result.best_feasible;
  const balance = result.continuous_balance;
  const assets = Number(result.asset_count ?? state.asset_count ?? 0);
  const qubits = Number(result.qubit_count ?? state.qubit_count ?? assets * 2);
  const shots = Number(result.total_shots ?? 0);
  const feasible = Number(result.feasible_probability ?? 0);

  $('#sourceTag').textContent = result.source || state.source || 'LOCAL PORTFOLIO DEMO';
  $('#assets').textContent = formatNumber(assets);
  $('#qubits').textContent = formatNumber(qubits);
  $('#orbitQubits').textContent = `${formatNumber(qubits)} qubits`;
  $('#shots').textContent = shots ? formatNumber(shots) : '—';
  $('#backend').textContent = (result.source || '').includes('IQM') ? 'IQM' : 'LOCAL QRISP';
  $('#runButton').disabled = assets <= 0;

  $('#longIndex').textContent = `${formatNumber(state.model?.long_count || 0)} CONTRACTS`;
  $('#shortIndex').textContent = `${formatNumber(state.model?.short_count || 0)} CONTRACTS`;
  renderAssetList('#longAssets', best?.long, 'Waiting for a feasible sample');
  renderAssetList('#shortAssets', best?.short, 'Run QAOA to find a portfolio');
  $('#energyScore').textContent = best?.energy == null ? '—' : Number(best.energy).toFixed(6);

  const carbon = Number(best?.net_carbon ?? 0);
  const sign = carbon > 0 ? '+' : carbon < 0 ? '−' : '';
  $('#netCarbon').innerHTML = `${sign}${formatNumber(Math.abs(carbon))}<span> kg CO₂</span>`;
  $('#feasibleRate').innerHTML = `${(feasible * 100).toFixed(1)}<span>%</span>`;
  $('.validity-panel .bar-rows b i').style.width = `${Math.max(feasible * 100, 1)}%`;
  $('.validity-panel .bar-rows .pale i').style.width = `${Math.max((1 - feasible) * 100, 1)}%`;

  if (balance) {
    const residual = Number(balance.max_abs_normalized_residual);
    $('#balanceStatus').textContent = balance.status === 'numerical_balance_found'
      ? `Numerical balance found · max residual ${residual.toExponential(1)}`
      : `Residual exceeds tolerance · ${residual.toExponential(1)}`;
    $('#balanceDetails').textContent =
      `${(balance.measure_names || []).join(', ')} · ${balance.switch_count} switches. Continuous relaxation only; discrete balance is not guaranteed.`;
  } else {
    $('#balanceStatus').textContent = 'Certificate appears after a run';
    $('#balanceDetails').textContent = 'The discrete portfolio is evaluated separately by the QUBO.';
  }

  $('#runStatus').textContent = assets <= 0
    ? 'Dataset missing. Start with “python qfhackathon.py demo” in Terminal.'
    : best
      ? `${formatNumber(assets)} assets · ${formatNumber(qubits)} qubits · ${formatNumber(shots)} local shots`
      : 'Ready to run the local portfolio solver';
}

async function requestState() {
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load the saved portfolio state.');
  render(await response.json());
}

$('#runButton').addEventListener('click', async () => {
  const button = $('#runButton');
  const label = $('.button-label');
  const status = $('#runStatus');
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  label.textContent = 'Optimizing portfolio…';
  status.textContent = 'Building the QUBO and running local QAOA. This can take a few minutes.';
  try {
    const response = await fetch('/api/run-local', { method: 'POST' });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.output || 'The local QAOA run failed.');
    }
    render(payload.state);
    status.textContent = 'Portfolio updated with a new local QAOA run.';
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
    button.removeAttribute('aria-busy');
    label.textContent = 'Run local QAOA';
  }
});

requestState().catch((error) => {
  $('#runStatus').textContent = error.message;
});
