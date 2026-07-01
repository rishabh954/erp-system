
'use strict';

/* ─────────────────────────────────────────────────────────
   STATE
───────────────────────────────────────────────────────── */
const state = {
  module: null,
  fields: [],          // all fields from API
  selected: [],        // selected field keys
  filters: [],
  sortField: '',
  sortOrder: 'asc',
  rowLimit: '',
  chartType: 'none',
  groupBy: '',
  valueField: '',
  aggregation: 'sum',
  pivot: false,
  pivotRow: '',
  pivotCol: '',
  pivotValue: '',
  pivotAgg: 'sum',
  dateFrom: '',
  dateTo: '',
  dateField: '',
};

/* ─────────────────────────────────────────────────────────
   STEP NAVIGATION
───────────────────────────────────────────────────────── */
function toggleStep(n) {
  const card = document.getElementById(`step${n}Card`);
  const body = document.getElementById(`step${n}Body`);
  const isOpen = body.classList.contains('open');
  // close all
  for (let i = 1; i <= 6; i++) {
    document.getElementById(`step${i}Card`).classList.remove('active', 'open');
    document.getElementById(`step${i}Body`).classList.remove('open');
  }
  if (!isOpen) {
    card.classList.add('active', 'open');
    body.classList.add('open');
  }
}

function moveStep(n) {
  toggleStep(n);
  updateProgress(n);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateProgress(current) {
  document.querySelectorAll('.bp-step').forEach(el => {
    const s = parseInt(el.dataset.step);
    el.classList.remove('active', 'done');
    if (s < current) el.classList.add('done');
    else if (s === current) el.classList.add('active');
  });
}

/* ─────────────────────────────────────────────────────────
   MODULE SELECTION
───────────────────────────────────────────────────────── */
async function selectModule(el) {
  document.querySelectorAll('.module-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  state.module = el.dataset.module;

  // Update step 1 subtitle
  document.getElementById('ssub1').textContent = el.textContent.trim();
  markDone(1);

  // Load fields
  await loadFields(state.module);
  moveStep(2);
}

async function loadFields(module) {
  document.getElementById('fieldList').innerHTML =
    '<div class="text-center py-3 text-muted"><i class="fa-solid fa-spinner fa-spin me-1"></i>Loading…</div>';

  try {
    const res  = await fetch(`/analytics/api/fields/?module=${module}`);
    if (!res.ok) throw new Error('API error');
    const data = await res.json();
    state.fields = data.fields || [];
    renderFieldList();
    populateDynamicSelects();
    updatePreviewBadge();
  } catch (e) {
    state.fields = [];
    document.getElementById('fieldList').innerHTML =
      '<div class="text-danger text-center py-3"><i class="fa-solid fa-circle-exclamation me-1"></i>Failed to load fields.</div>';
  }
}

function renderFieldList() {
  const q = (document.getElementById('fieldSearch').value || '').toLowerCase();
  const filtered = state.fields.filter(f =>
    f.label.toLowerCase().includes(q) || f.key.toLowerCase().includes(q));

  document.getElementById('fieldList').innerHTML = filtered.map(f => `
    <div class="field-item" onclick="toggleField('${f.key}', this)">
      <input type="checkbox" ${state.selected.includes(f.key) ? 'checked' : ''}
             id="fld_${f.key}" class="field-cb" data-key="${f.key}">
      <label for="fld_${f.key}" style="cursor:pointer;flex-grow:1;"> DUMMY_VAR{f.label}</label>
      <span class="field-type"> DUMMY_VAR{f.type || 'text'}</span>
    </div>`).join('') || '<div class="text-muted text-center py-2">No fields found.</div>';

  updateSelectedCount();
}

function filterFields() { renderFieldList(); }

function toggleField(key, row) {
  const cb = row.querySelector('input');
  cb.checked = !cb.checked;
  if (cb.checked) {
    if (!state.selected.includes(key)) state.selected.push(key);
  } else {
    state.selected = state.selected.filter(k => k !== key);
  }
  updateSelectedCount();
  updateColOrder();
}

function selectAllFields(val) {
  state.selected = val ? state.fields.map(f => f.key) : [];
  renderFieldList();
  updateColOrder();
}

function updateSelectedCount() {
  const cbs = document.querySelectorAll('.field-cb:checked');
  state.selected = [...cbs].map(c => c.dataset.key);
  document.getElementById('selectedCount').textContent = `${state.selected.length} selected`;
  if (state.selected.length) {
    document.getElementById('ssub2').textContent = `${state.selected.length} column(s) selected`;
    markDone(2);
  }
  updateColOrder();
}

/* Column order chips */
function updateColOrder() {
  const panel = document.getElementById('colOrderPanel');
  const list  = document.getElementById('colOrderList');
  if (!state.selected.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  list.innerHTML = state.selected.map(k => {
    const f = state.fields.find(x => x.key === k);
    return `<span class="badge rounded-pill px-3 py-2 fw-semibold"
              style="background:rgba(67,97,238,.1);color:var(--brand-primary);font-size:.78rem;cursor:grab;">
              <i class="fa-solid fa-grip-dots-vertical me-1 opacity-50"></i> DUMMY_VAR{f ? f.label : k}
            </span>`;
  }).join('');
}

/* ─────────────────────────────────────────────────────────
   POPULATE DYNAMIC SELECTS (sort, date, chart fields, pivot)
───────────────────────────────────────────────────────── */
function populateDynamicSelects() {
  const fields = state.fields;
  const opts = '<option value="">— Select —</option>' +
    fields.map(f => `<option value="${f.key}"> DUMMY_VAR{f.label}</option>`).join('');

  document.getElementById('sortField').innerHTML = '<option value="">— None —</option>' +
    fields.map(f => `<option value="${f.key}"> DUMMY_VAR{f.label}</option>`).join('');

  const dateFields = fields.filter(f => ['date','datetime'].includes(f.type));
  document.getElementById('dateField').innerHTML = '<option value="">— Auto —</option>' +
    dateFields.map(f => `<option value="${f.key}"> DUMMY_VAR{f.label}</option>`).join('');

  ['groupByField','valueField','pivotRowField','pivotColField','pivotValueField'].forEach(id => {
    document.getElementById(id).innerHTML = opts;
  });
}

/* ─────────────────────────────────────────────────────────
   FILTERS
───────────────────────────────────────────────────────── */
let filterCount = 0;
function addFilter() {
  filterCount++;
  const id = `fr${filterCount}`;
  const fields = state.fields;
  const fieldOpts = fields.map(f => `<option value="${f.key}"> DUMMY_VAR{f.label}</option>`).join('');

  const row = document.createElement('div');
  row.className = 'filter-row';
  row.id = id;
  row.innerHTML = `
    <select class="form-select form-select-sm filter-field"> DUMMY_VAR{fieldOpts}</select>
    <select class="form-select form-select-sm filter-op">
      <option value="eq">= equals</option>
      <option value="ne">≠ not eq</option>
      <option value="gt">&gt; greater</option>
      <option value="lt">&lt; less</option>
      <option value="gte">≥ ≥</option>
      <option value="lte">≤ ≤</option>
      <option value="contains">contains</option>
      <option value="startswith">starts with</option>
      <option value="isnull">is empty</option>
    </select>
    <input type="text" class="form-control form-control-sm filter-val" placeholder="Value…">
    <button class="btn btn-sm btn-outline-danger" onclick="removeFilter('${id}')">
      <i class="fa-solid fa-xmark"></i>
    </button>`;
  document.getElementById('filterRows').appendChild(row);
  markDone(3);
}

function removeFilter(id) {
  document.getElementById(id).remove();
}

function collectFilters() {
  const filters = [];
  document.querySelectorAll('.filter-row').forEach(row => {
    const field = row.querySelector('.filter-field').value;
    const op    = row.querySelector('.filter-op').value;
    const val   = row.querySelector('.filter-val').value;
    if (field) filters.push({ field, op, value: val });
  });
  return filters;
}

/* ─────────────────────────────────────────────────────────
   CHART TYPE
───────────────────────────────────────────────────────── */
function selectChart(el) {
  document.querySelectorAll('.ct-card').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  state.chartType = el.dataset.chart;
  const showFields = state.chartType !== 'none';
  document.getElementById('chartFieldsSection').style.display = showFields ? '' : 'none';
  document.getElementById('ssub5').textContent = el.textContent.trim();
  markDone(5);
}

/* ─────────────────────────────────────────────────────────
   PIVOT
───────────────────────────────────────────────────────── */
function togglePivot() {
  state.pivot = document.getElementById('pivotToggle').checked;
  document.getElementById('pivotFields').style.display = state.pivot ? '' : 'none';
  document.getElementById('ssub6').textContent = state.pivot ? 'Enabled' : 'Cross-tabulation (optional)';
}

/* ─────────────────────────────────────────────────────────
   STEP DONE MARKERS
───────────────────────────────────────────────────────── */
function markDone(n) {
  const el = document.getElementById(`snum${n}`);
  el.classList.add('done');
  el.innerHTML = '<i class="fa-solid fa-check fa-xs"></i>';
  document.querySelector(`[data-step="${n}"]`).classList.add('done');
}

/* ─────────────────────────────────────────────────────────
   COLLECT PAYLOAD
───────────────────────────────────────────────────────── */
function collectPayload() {
  return {
    module:      state.module,
    columns:     state.selected,
    filters:     collectFilters(),
    sort_field:  document.getElementById('sortField').value,
    sort_order:  document.getElementById('sortOrder').value,
    row_limit:   document.getElementById('rowLimit').value,
    date_field:  document.getElementById('dateField').value,
    date_from:   document.getElementById('dateFrom').value,
    date_to:     document.getElementById('dateTo').value,
    chart_type:  state.chartType,
    group_by:    document.getElementById('groupByField').value,
    value_field: document.getElementById('valueField').value,
    aggregation: document.getElementById('aggregation').value,
    is_pivot:    document.getElementById('pivotToggle').checked,
    pivot_row:   document.getElementById('pivotRowField').value,
    pivot_col:   document.getElementById('pivotColField').value,
    pivot_value: document.getElementById('pivotValueField').value,
    pivot_agg:   document.getElementById('pivotAgg').value,
    preview_limit: parseInt(document.getElementById('previewLimit').value),
  };
}

/* ─────────────────────────────────────────────────────────
   LIVE PREVIEW
───────────────────────────────────────────────────────── */
let previewChartInstance = null;

async function runPreview() {
  if (!state.module) {
    alert('Please select a module first.');
    return;
  }
  if (!state.selected.length) {
    alert('Please select at least one column.');
    return;
  }

  const payload = collectPayload();
  document.getElementById('builderPayload').value = JSON.stringify(payload);

  // Show loading
  document.getElementById('previewPlaceholder').style.display = 'none';
  document.getElementById('previewContent').style.display = 'none';
  document.getElementById('previewError').style.display = 'none';
  document.getElementById('previewLoading').style.display = 'flex';
  document.getElementById('previewChartWrapper').style.display = 'none';
  document.getElementById('previewPivotWrapper').style.display = 'none';

  try {
    const res  = await fetch('/analytics/api/preview/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCookie('csrftoken'),
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    const data = await res.json();

    renderPreview(data);
  } catch (e) {
    document.getElementById('previewLoading').style.display = 'none';
    document.getElementById('previewError').style.display = 'flex';
    document.getElementById('previewErrorMsg').textContent = e.message || 'Failed to load preview.';
  }
}

function renderPreview(data) {
  document.getElementById('previewLoading').style.display = 'none';

  // Chart
  if (data.chart && data.chart.type !== 'none' && data.chart.labels) {
    document.getElementById('previewChartWrapper').style.display = '';
    if (previewChartInstance) previewChartInstance.destroy();
    const ctx = document.getElementById('previewChart').getContext('2d');
    const palette = ['#4361ee','#10b981','#f59e0b','#ef4444','#a855f7','#14b8a6','#f97316','#ec4899'];
    const isCircle = ['pie','doughnut'].includes(data.chart.type);
    previewChartInstance = new Chart(ctx, {
      type: data.chart.type === 'area' ? 'line' : data.chart.type,
      data: {
        labels: data.chart.labels,
        datasets: [{
          label: data.chart.value_label || 'Value',
          data: data.chart.values,
          backgroundColor: isCircle ? palette : 'rgba(67,97,238,.2)',
          borderColor:     isCircle ? palette : '#4361ee',
          borderWidth: 2,
          fill: data.chart.type === 'area',
          tension: .4,
          pointRadius: 4,
        }]
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: isCircle, position:'right' },
          tooltip: { mode: 'index' },
        },
        scales: isCircle ? {} : {
          y: { beginAtZero: true, grid: { color:'rgba(var(--border-rgb),.1)' } },
          x: { grid: { display: false } },
        }
      }
    });
  }

  // Pivot
  if (data.pivot) {
    document.getElementById('previewPivotWrapper').style.display = '';
    renderPivotTable(data.pivot, document.getElementById('previewPivotTable'));
  }

  // Data table
  const headers = data.headers || [];
  const rows    = data.rows    || [];

  document.getElementById('previewStats').innerHTML = `
    <span><i class="fa-solid fa-database fa-xs me-1"></i> DUMMY_VAR{rows.length.toLocaleString()} rows</span>
    <span><i class="fa-solid fa-table-columns fa-xs me-1"></i> DUMMY_VAR{headers.length} columns</span> DUMMY_VAR{data.truncated ? '<span class="text-warning"><i class="fa-solid fa-triangle-exclamation fa-xs me-1"></i>Preview truncated</span>' : ''}`;

  document.getElementById('previewThead').innerHTML =
    `<tr> DUMMY_VAR{headers.map(h => `<th> DUMMY_VAR{h}</th>`).join('')}</tr>`;
  document.getElementById('previewTbody').innerHTML =
    rows.map(row => `<tr> DUMMY_VAR{row.map(cell => `<td> DUMMY_VAR{cell ?? ''}</td>`).join('')}</tr>`).join('');

  document.getElementById('previewContent').style.display = '';
}

function renderPivotTable(pivot, table) {
  const { col_headers, row_headers, cells, totals } = pivot;
  let html = '<thead><tr><th></th>';
  col_headers.forEach(c => { html += `<th class="text-center"> DUMMY_VAR{c}</th>`; });
  html += '<th class="text-center fw-bold">Total</th></tr></thead><tbody>';
  row_headers.forEach((row, ri) => {
    html += `<tr><td class="fw-semibold"> DUMMY_VAR{row}</td>`;
    col_headers.forEach((_, ci) => {
      const val = cells[ri]?.[ci];
      html += `<td class="text-end"> DUMMY_VAR{val !== undefined ? val.toLocaleString() : '—'}</td>`;
    });
    html += `<td class="text-end fw-bold"> DUMMY_VAR{(totals?.rows?.[ri] ?? '').toLocaleString()}</td></tr>`;
  });
  // Total row
  html += '<tr class="table-active fw-bold"><td>Total</td>';
  col_headers.forEach((_, ci) => {
    html += `<td class="text-end"> DUMMY_VAR{(totals?.cols?.[ci] ?? '').toLocaleString()}</td>`;
  });
  html += `<td class="text-end"> DUMMY_VAR{(totals?.grand ?? '').toLocaleString()}</td></tr>`;
  html += '</tbody>';
  table.innerHTML = html;
}

/* ─────────────────────────────────────────────────────────
   FORM SUBMIT
───────────────────────────────────────────────────────── */
document.getElementById('saveReportForm').addEventListener('submit', function(e) {
  const payload = collectPayload();
  document.getElementById('builderPayload').value = JSON.stringify(payload);
});

/* ─────────────────────────────────────────────────────────
   UTILS
───────────────────────────────────────────────────────── */
function updatePreviewBadge() {
  const badge = document.getElementById('previewModuleBadge');
  badge.textContent = state.module ? `— ${state.module.charAt(0).toUpperCase() + state.module.slice(1)}` : '';
}

function getCookie(name) {
  const v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
  return v ? v.pop() : '';
}

/* ─────────────────────────────────────────────────────────
   PREVIEW BUTTON (header)
───────────────────────────────────────────────────────── */
document.getElementById('btnRunPreview').addEventListener('click', runPreview);
