const $ = (selector) => document.querySelector(selector);
let datasetAvailable = false;

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

function syncPortfolioSettings() {
  const assetCount = Number($('#settingAssets').value);
  const maximumK = Math.floor(assetCount / 2);
  const kSelect = $('#settingK');
  for (const option of kSelect.options) {
    option.disabled = Number(option.value) > maximumK;
  }
  if (Number(kSelect.value) > maximumK) {
    kSelect.value = String(maximumK);
  }
}

function selectedSettings() {
  return {
    n: Number($('#settingAssets').value),
    k: Number($('#settingK').value),
    shots: Number($('#settingShots').value),
    reps: Number($('#settingReps').value),
    backend: $('#settingBackend').value,
  };
}

function render(state) {
  const result = state.result || {};
  const best = result.best_feasible;
  const balance = result.continuous_balance;
  const assets = Number(result.asset_count ?? state.asset_count ?? 0);
  const qubits = Number(result.qubit_count ?? state.qubit_count ?? assets * 2);
  const shots = Number(result.total_shots ?? 0);
  const feasible = Number(result.feasible_probability ?? 0);
  const hardwareRun = (result.source || '').includes('IQM');
  datasetAvailable = assets > 0;

  $('#executionMode').textContent = hardwareRun ? 'IQM HARDWARE RESULT' : 'LOCAL DEMO';
  $('#sourceTag').textContent = result.source || state.source || 'LOCAL PORTFOLIO DEMO';
  $('#assets').textContent = formatNumber(assets);
  $('#qubits').textContent = formatNumber(qubits);
  $('#orbitQubits').textContent = `${formatNumber(qubits)} qubits`;
  $('#shots').textContent = shots ? formatNumber(shots) : '—';
  $('#backend').textContent = hardwareRun ? (result.source.match(/IQM\s+([A-Z]+)/)?.[1] || 'IQM') : 'LOCAL QRISP';
  $('#runButton').disabled = assets <= 0;
  $('#runResonanceButton').disabled = assets <= 0;

  $('#longIndex').textContent = `${formatNumber(state.model?.long_count || 0)} CONTRACTS`;
  $('#shortIndex').textContent = `${formatNumber(state.model?.short_count || 0)} CONTRACTS`;
  renderAssetList('#longAssets', best?.long, 'Waiting for a feasible sample');
  renderAssetList('#shortAssets', best?.short, 'Run QAOA to find a portfolio');
  $('#energyScore').textContent = best?.energy == null ? '—' : Number(best.energy).toFixed(6);

  const hasComponents = best?.carbon_component != null && best?.risk_component != null;
  const carbonComponent = Math.max(0, Number(best?.carbon_component ?? 0));
  const riskComponent = Math.max(0, Number(best?.risk_component ?? 0));
  const componentTotal = carbonComponent + riskComponent;
  const carbonShare = componentTotal ? carbonComponent / componentTotal : 0;
  $('#carbonObjectiveBar').style.width = `${carbonShare * 100}%`;
  $('#riskObjectiveBar').style.width = `${hasComponents ? (1 - carbonShare) * 100 : 0}%`;
  $('#carbonObjectiveValue').textContent = hasComponents ? carbonComponent.toFixed(3) : 'rerun';
  $('#riskObjectiveValue').textContent = hasComponents ? riskComponent.toFixed(3) : 'rerun';

  const carbon = Number(best?.net_carbon ?? 0);
  const grossCarbon = Math.max(0, Number(best?.gross_carbon ?? Math.abs(carbon)));
  const sign = carbon > 0 ? '+' : carbon < 0 ? '−' : '';
  $('#netCarbon').innerHTML = `${sign}${formatNumber(Math.abs(carbon))}<span> kg CO₂</span>`;
  $('#carbonMeterNegative').textContent = `−${formatNumber(grossCarbon)} kg`;
  $('#carbonMeterPositive').textContent = `+${formatNumber(grossCarbon)} kg`;
  const fraction = grossCarbon > 0 ? Math.max(-1, Math.min(1, carbon / grossCarbon)) : 0;
  const fill = $('#carbonMeterFill');
  fill.style.left = `${50 + Math.min(fraction, 0) * 50}%`;
  fill.style.width = `${Math.abs(fraction) * 50}%`;
  fill.classList.toggle('positive', fraction > 0);
  $('#carbonMeterCaption').textContent = `Net exposure is ${Math.abs(fraction * 100).toFixed(1)}% of gross financed exposure`;

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
      ? `${formatNumber(assets)} assets · ${formatNumber(qubits)} qubits · ${formatNumber(shots)} shots`
      : 'Ready to run the portfolio solver';
}

async function runPortfolio(kind) {
  const localButton = $('#runButton');
  const remoteButton = $('#runResonanceButton');
  const status = $('#runStatus');
  const activity = $('#runActivity');
  const buttons = [localButton, remoteButton];
  buttons.forEach((button) => {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
  });
  activity.dataset.mode = kind;
  activity.classList.add('is-running');
  $('#activityTitle').textContent = kind === 'local'
    ? 'Running the local QAOA simulation'
    : 'Preparing the circuit for IQM Resonance';
  $('#activityMode').textContent = kind === 'local' ? 'LOCAL SIMULATION' : 'IQM HARDWARE';
  localButton.querySelector('.button-label').textContent = kind === 'local' ? 'Running local QAOA…' : 'Run local QAOA';
  remoteButton.querySelector('.button-label').textContent = kind === 'resonance' ? 'Preparing Resonance run…' : 'Prepare & run on Resonance';
  status.textContent = kind === 'local'
    ? 'Your computer is simulating QAOA locally; no quantum hardware is used for this run.'
    : 'Your computer prepares the problem and circuit; IQM runs the quantum sampling.';
  try {
    const response = await fetch(`/api/run-${kind}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...(kind === 'resonance' ? selectedSettings() : {}),
        ...(kind === 'resonance' ? { confirmed: true } : {}),
      }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.output || `The ${kind} run failed.`);
    }
    render(payload.state);
    status.textContent = kind === 'local'
      ? 'Portfolio updated with a new local QAOA run.'
      : 'Portfolio updated with the IQM Resonance result.';
    $('#activityTitle').textContent = 'Portfolio result is ready';
    $('#activityMode').textContent = 'COMPLETE';
  } catch (error) {
    status.textContent = error.message;
    $('#activityTitle').textContent = 'Run did not complete';
    $('#activityMode').textContent = 'CHECK STATUS';
  } finally {
    activity.classList.remove('is-running');
    activity.dataset.mode = 'idle';
    buttons.forEach((button) => {
      button.removeAttribute('aria-busy');
    });
    localButton.disabled = !datasetAvailable;
    remoteButton.disabled = !datasetAvailable;
    localButton.querySelector('.button-label').textContent = 'Run local QAOA';
    remoteButton.querySelector('.button-label').textContent = 'Prepare & run on Resonance';
  }
}

$('#settingAssets').addEventListener('change', syncPortfolioSettings);
$('#runButton').addEventListener('click', () => runPortfolio('local'));
$('#runResonanceButton').addEventListener('click', () => {
  const { backend, n, k, shots, reps } = selectedSettings();
  const confirmed = window.confirm(
    `Prepare a circuit for ${n} futures with ${k} positions per leg and ${reps} QAOA layer${reps === 1 ? '' : 's'}, then run ${shots} shots on IQM ${backend.toUpperCase()}? This uses the remote hardware service and may consume account credits.`,
  );
  if (confirmed) runPortfolio('resonance');
});

syncPortfolioSettings();
requestState().catch((error) => {
  $('#runStatus').textContent = error.message;
});

async function requestState() {
  const response = await fetch('/api/state', { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load the saved portfolio state.');
  render(await response.json());
}
