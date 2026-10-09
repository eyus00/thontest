const $ = (selector) => document.querySelector(selector);
let datasetAvailable = false;
let orbitCleanupTimer = 0;
let runMessageTimer = 0;
let runMessageSwapTimer = 0;
let activeOrbitClone = null;
let matrixTimer = 0;
let runInProgress = false;
const runMessages = {
  local: [
    'Preparing futures data',
    'Building the portfolio objective',
    'Exploring long / short portfolios',
    'Checking portfolio constraints',
  ],
  resonance: [
    'Preparing futures data',
    'Compiling the QAOA circuit',
    'Sampling on IQM hardware',
    'Decoding the returned samples',
  ],
  dataset: [
    'Connecting to Yahoo Finance',
    'Downloading historical futures',
    'Cleaning prices and returns',
    'Preparing dashboard dataset',
  ],
};

function formatNumber(value, digits = 0) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(value ?? 0);
}

function renderAssetList(selector, assets, emptyLabel) {
  const container = $(selector);
  container.replaceChildren();
  if (!assets?.length) {
    container.classList.add('is-skeleton');
    container.setAttribute('aria-label', emptyLabel);
    for (const width of ['82%', '66%', '74%', '58%']) {
      const row = document.createElement('span');
      row.className = 'asset-line matrix-line';
      row.style.setProperty('--matrix-width', width);
      row.setAttribute('aria-hidden', 'true');
      row.textContent = '01010110 10100101';
      container.append(row);
    }
    return;
  }
  container.classList.remove('is-skeleton');
  container.removeAttribute('aria-label');
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
  datasetAvailable = Boolean(state.dataset_available ?? assets > 0);

  $('#executionMode').textContent = hardwareRun ? 'IQM HARDWARE RESULT' : 'LOCAL DEMO';
  $('#sourceTag').textContent = result.source || state.source || 'LOCAL PORTFOLIO DEMO';
  $('#assets').textContent = formatNumber(assets);
  $('#qubits').textContent = formatNumber(qubits);
  $('#orbitQubits').textContent = `${formatNumber(qubits)} qubits`;
  $('#shots').textContent = shots ? formatNumber(shots) : '—';
  $('#backend').textContent = hardwareRun ? (result.source.match(/IQM\s+([A-Z]+)/)?.[1] || 'IQM') : 'LOCAL QRISP';
  $('#datasetStart').hidden = datasetAvailable;
  $('#solverActions').hidden = !datasetAvailable;
  $('#generateDatasetButton').disabled = runInProgress;
  $('#runButton').disabled = runInProgress || assets <= 0;
  $('#openResonanceSettings').disabled = runInProgress || assets <= 0;

  $('#longIndex').textContent = `${formatNumber(state.model?.long_count || 0)} CONTRACTS`;
  $('#shortIndex').textContent = `${formatNumber(state.model?.short_count || 0)} CONTRACTS`;
  renderAssetList('#longAssets', best?.long, 'Long portfolio positions will appear after a run');
  renderAssetList('#shortAssets', best?.short, 'Short portfolio positions will appear after a run');
  if (best?.long?.length && best?.short?.length) {
    stopMatrixAnimation();
  } else {
    startMatrixAnimation();
  }
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
  $('#netCarbon').innerHTML = best
    ? `${sign}${formatNumber(Math.abs(carbon))}<span> kg CO₂</span>`
    : '—<span> kg CO₂</span>';
  $('#carbonMeterNegative').textContent = best ? `−${formatNumber(grossCarbon)} kg` : '—';
  $('#carbonMeterPositive').textContent = best ? `+${formatNumber(grossCarbon)} kg` : '—';
  const fraction = best && grossCarbon > 0 ? Math.max(-1, Math.min(1, carbon / grossCarbon)) : 0;
  const fill = $('#carbonMeterFill');
  fill.style.left = `${50 + Math.min(fraction, 0) * 50}%`;
  fill.style.width = `${Math.abs(fraction) * 50}%`;
  fill.classList.toggle('positive', fraction > 0);
  $('#carbonMeterCaption').textContent = best
    ? `Net exposure is ${Math.abs(fraction * 100).toFixed(1)}% of gross financed exposure`
    : 'Exposure values appear after a portfolio run';

  $('#feasibleRate').innerHTML = best ? `${(feasible * 100).toFixed(1)}<span>%</span>` : '—<span>%</span>';
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
    ? ''
    : best
      ? `${formatNumber(assets)} assets · ${formatNumber(qubits)} qubits · ${formatNumber(shots)} shots`
      : 'Ready to run the portfolio solver';
}

async function generateDataset() {
  if (runInProgress) return;
  runInProgress = true;
  const button = $('#generateDatasetButton');
  button.disabled = true;
  button.setAttribute('aria-busy', 'true');
  button.textContent = 'Generating futures data…';
  $('#runStatus').textContent = 'Downloading and preparing historical futures data.';
  try {
    startRunVisual('dataset');
    const response = await fetch('/api/generate-dataset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error(payload.output || 'Could not generate the futures dataset.');
    }
    render(payload.state);
    $('#runStatus').textContent = datasetAvailable
      ? `Dataset ready · ${formatNumber(payload.state.asset_count)} futures available. Choose a run method.`
      : 'Dataset download completed, but the data is incomplete. Please retry.';
  } catch (error) {
    $('#runStatus').textContent = error instanceof Error ? error.message : 'Could not generate the futures dataset.';
  } finally {
    try {
      stopRunVisual();
    } finally {
      runInProgress = false;
      button.removeAttribute('aria-busy');
      button.disabled = false;
      button.textContent = 'Generate futures dataset';
      $('#runButton').disabled = !datasetAvailable;
      $('#openResonanceSettings').disabled = !datasetAvailable;
    }
  }
}

async function runPortfolio(kind) {
  if (runInProgress) return;
  runInProgress = true;
  const localButton = $('#runButton');
  const openSettingsButton = $('#openResonanceSettings');
  const remoteButton = $('#runResonanceButton');
  const status = $('#runStatus');
  const buttons = [localButton, openSettingsButton, remoteButton];
  buttons.forEach((button) => {
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
  });
  localButton.textContent = kind === 'local' ? 'Running local QAOA…' : 'Run local QAOA';
  remoteButton.textContent = kind === 'resonance' ? 'Running on Resonance…' : 'Run on Resonance';
  status.textContent = kind === 'local'
    ? 'Your computer is simulating QAOA locally; no quantum hardware is used for this run.'
    : 'Your computer prepares the problem and circuit; IQM runs the quantum sampling.';
  try {
    startRunVisual(kind);
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
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : `The ${kind} run failed.`;
  } finally {
    try {
      stopRunVisual();
    } finally {
      runInProgress = false;
      buttons.forEach((button) => {
        button.removeAttribute('aria-busy');
        button.disabled = !datasetAvailable;
      });
      localButton.textContent = 'Run local QAOA';
      remoteButton.textContent = 'Run on Resonance';
    }
  }
}

function startMatrixAnimation() {
  if (matrixTimer) return;
  const alphabet = '01ABCDEF+-=<>[]{}';
  matrixTimer = window.setInterval(() => {
    document.querySelectorAll('.matrix-line').forEach((line) => {
      const length = Math.max(8, Math.round((Number.parseFloat(line.style.getPropertyValue('--matrix-width')) || 60) / 5));
      line.textContent = Array.from({ length }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join('');
    });
  }, 110);
}

function stopMatrixAnimation() {
  window.clearInterval(matrixTimer);
  matrixTimer = 0;
}

function startRunVisual(kind) {
  window.clearTimeout(orbitCleanupTimer);
  orbitCleanupTimer = 0;
  window.clearInterval(runMessageTimer);
  window.clearTimeout(runMessageSwapTimer);
  const overlay = $('#runVisualOverlay');
  overlay.classList.remove('is-returning');
  activeOrbitClone?.remove();
  const source = $('.hero-orbit');
  const rect = source.getBoundingClientRect();
  const computed = getComputedStyle(source);
  const baseWidth = Number.parseFloat(computed.width) || 330;
  const baseHeight = Number.parseFloat(computed.height) || 280;
  const baseScale = rect.width ? rect.width / baseWidth : 0.68;
  const startX = rect.width ? rect.left + rect.width / 2 : window.innerWidth - 80;
  const startY = rect.height ? rect.top + rect.height / 2 : 115;
  const offsetX = startX - window.innerWidth / 2;
  const offsetY = startY - window.innerHeight / 2;
  const clone = source.cloneNode(true);
  clone.removeAttribute('id');
  clone.querySelectorAll('[id]').forEach((element) => element.removeAttribute('id'));
  clone.classList.add('run-orbit-clone', 'is-preparing');
  clone.style.setProperty('--orbit-start-x', `${offsetX}px`);
  clone.style.setProperty('--orbit-start-y', `${offsetY}px`);
  clone.style.setProperty('--orbit-base-scale', String(baseScale));
  clone.style.setProperty('--orbit-width', `${baseWidth}px`);
  clone.style.setProperty('--orbit-height', `${baseHeight}px`);
  activeOrbitClone = clone;
  $('#runVisualOverlay').append(clone);
  clone.getBoundingClientRect();
  overlay.classList.add('is-active');
  $('#runVisualMode').textContent = kind === 'local'
    ? 'LOCAL QAOA SIMULATION'
    : kind === 'resonance' ? 'IQM RESONANCE HARDWARE' : 'MARKET DATA';
  $('#runVisualTitle').textContent = kind === 'dataset'
    ? 'Preparing the futures dataset'
    : kind === 'local' ? 'Finding a balanced portfolio' : 'Preparing and sampling on IQM';
  const messages = runMessages[kind];
  let messageIndex = 0;
  showRunMessage(messages[messageIndex]);
  runMessageTimer = window.setInterval(() => {
    messageIndex = (messageIndex + 1) % messages.length;
    const message = messages[messageIndex];
    const messageElement = $('.run-visual-message');
    messageElement.classList.add('is-changing');
    runMessageSwapTimer = window.setTimeout(() => {
      showRunMessage(message);
      messageElement.classList.remove('is-changing');
      runMessageSwapTimer = 0;
    }, 180);
  }, 3000);
  requestAnimationFrame(() => {
    clone.classList.remove('is-preparing');
    clone.classList.add('is-centered');
  });
}

function showRunMessage(title) {
  $('#runVisualTitle').textContent = title;
}

function stopRunVisual() {
  window.clearInterval(runMessageTimer);
  runMessageTimer = 0;
  window.clearTimeout(runMessageSwapTimer);
  runMessageSwapTimer = 0;
  const clone = activeOrbitClone;
  if (!clone) return;
  clone.classList.add('is-returning');
  clone.classList.remove('is-centered');
  clone.addEventListener('transitionend', onReturnComplete);
  const overlay = $('#runVisualOverlay');
  overlay.classList.add('is-returning');
  overlay.classList.remove('is-active');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  orbitCleanupTimer = window.setTimeout(cleanup, reducedMotion ? 40 : 1000);

  function onReturnComplete(event) {
    if (event.target === clone && event.propertyName === 'transform') cleanup();
  }

  const cleanup = () => {
    window.clearTimeout(orbitCleanupTimer);
    orbitCleanupTimer = 0;
    clone.removeEventListener('transitionend', onReturnComplete);
    clone.remove();
    overlay.classList.remove('is-returning');
    if (activeOrbitClone === clone) activeOrbitClone = null;
  };
}

$('#settingAssets').addEventListener('change', syncPortfolioSettings);
$('#generateDatasetButton').addEventListener('click', generateDataset);
$('#runButton').addEventListener('click', () => runPortfolio('local'));
$('#openResonanceSettings').addEventListener('click', () => $('#resonanceDialog').showModal());
$('#runResonanceButton').addEventListener('click', () => {
  $('#resonanceDialog').close();
  runPortfolio('resonance');
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
