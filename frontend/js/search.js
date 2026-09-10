// Investigative sighting search.
//
// The trace view answers "where did this exact plate go". This answers the
// question that comes first in a real investigation: "what did we see at all,
// near this place, in this window" -- a partial plate, one junction, an hour.
class SightingSearch {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.results = [];
    this.total = 0;
    this.truncated = false;
    this.lastFilters = null;
    this.pageSize = 100;
  }

  // ------------------------------------------------------------------ inputs
  readFilters(offset = 0) {
    const value = (id) => {
      const el = document.getElementById(id);
      return el ? el.value.trim() : '';
    };

    const from = Utils.istInputToUtcIso(value('search-from'));
    const to = Utils.istInputToUtcIso(value('search-to'));

    return {
      plate: Utils.normalizePlate(value('search-plate')),
      camera_id: value('search-camera'),
      vehicle_type: value('search-vehicle-type'),
      min_confidence: value('search-min-confidence') || '',
      from,
      to,
      limit: this.pageSize,
      offset,
    };
  }

  clearForm() {
    ['search-plate', 'search-from', 'search-to'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    ['search-camera', 'search-vehicle-type', 'search-min-confidence'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    this.results = [];
    this.total = 0;
    this.setState(`
      <div class="state-icon">⌕</div>
      <div>Search recorded sightings by partial plate, camera or time window.</div>
      <small>Leave everything blank to see the most recent sightings.</small>
    `);
    this.toggleExport(false);
  }

  setState(html) {
    this.container.innerHTML = `<div class="tracker-state">${html}</div>`;
  }

  toggleExport(enabled) {
    const btn = document.getElementById('btn-export-search');
    if (btn) btn.hidden = !enabled;
  }

  // ------------------------------------------------------------------ query
  async run(offset = 0) {
    const filters = this.readFilters(offset);

    // A window typed backwards is rejected here as well as server-side, so the
    // operator gets the reason instead of an empty table.
    if (filters.from && filters.to && filters.from > filters.to) {
      Utils.toast('The "from" time is later than the "to" time.', 'error');
      return;
    }

    const append = offset > 0;
    if (!append) {
      this.setState('<div class="spinner"></div><div>Searching sightings…</div>');
    }

    try {
      const data = await API.searchDetections(filters);
      this.lastFilters = filters;
      this.total = data.total;
      this.truncated = data.truncated;
      this.results = append ? this.results.concat(data.results) : data.results;

      if (!this.results.length) {
        this.setState(`
          <div class="state-icon">∅</div>
          <div>No sightings match these filters.</div>
          <small>${Utils.esc(this.describeFilters(filters))}</small>
        `);
        this.toggleExport(false);
        return;
      }

      this.render();
      this.toggleExport(true);
    } catch (e) {
      this.setState(`
        <div class="state-icon state-error">!</div>
        <div>Search failed.</div>
        <small>${Utils.esc(e.message)}</small>
      `);
      this.toggleExport(false);
    }
  }

  describeFilters(filters) {
    const parts = [];
    if (filters.plate) parts.push(`plate contains "${filters.plate}"`);
    if (filters.camera_id) parts.push(`camera ${filters.camera_id}`);
    if (filters.vehicle_type) parts.push(filters.vehicle_type.toLowerCase());
    if (filters.min_confidence) parts.push(`confidence ≥ ${filters.min_confidence}`);
    if (filters.from) parts.push(`from ${Utils.formatDateTime(filters.from)}`);
    if (filters.to) parts.push(`to ${Utils.formatDateTime(filters.to)}`);
    return parts.length ? parts.join(' · ') : 'no filters applied';
  }

  // ------------------------------------------------------------------ render
  render() {
    const esc = Utils.esc.bind(Utils);
    this.container.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'timeline-header';
    header.innerHTML = `
      <span>${this.results.length} of <b>${esc(this.total)}</b> sightings</span>
      <span>${esc(this.describeFilters(this.lastFilters || {}))}</span>
    `;
    this.container.appendChild(header);

    const table = document.createElement('table');
    table.className = 'search-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th>Time (IST)</th><th>Plate</th><th>Camera</th>
          <th>Type</th><th>Conf.</th><th></th>
        </tr>
      </thead>
    `;

    const tbody = document.createElement('tbody');
    this.results.forEach((row) => tbody.appendChild(this.buildRow(row)));
    table.appendChild(tbody);
    this.container.appendChild(table);

    if (this.truncated) {
      const more = document.createElement('button');
      more.className = 'btn-xs load-more';
      more.textContent = `Load more (${this.total - this.results.length} remaining)`;
      more.addEventListener('click', () => this.run(this.results.length));
      this.container.appendChild(more);
    }
  }

  buildRow(row) {
    const esc = Utils.esc.bind(Utils);
    const tr = document.createElement('tr');
    // A low-confidence read is a lead, not a fact; mark it in the table rather
    // than making the operator open each row to find out.
    const weak = Number(row.confidence) < 0.6;

    tr.innerHTML = `
      <td class="cell-time" title="${esc(Utils.formatDateTime(row.capture_timestamp))}">
        ${esc(Utils.formatTime(row.capture_timestamp))}
      </td>
      <td><b class="mono-plate">${esc(row.plate_number)}</b></td>
      <td>
        ${esc(row.camera_name || row.camera_id)}
        <small class="cell-sub">${esc(row.department || '')}</small>
      </td>
      <td>${esc(row.vehicle_type || '—')}</td>
      <td class="${weak ? 'cell-weak' : ''}">${esc(Number(row.confidence || 0).toFixed(2))}</td>
    `;

    const actions = document.createElement('td');
    actions.className = 'cell-actions';

    const traceBtn = document.createElement('button');
    traceBtn.className = 'btn-xs';
    traceBtn.textContent = 'Trace';
    traceBtn.title = `Reconstruct the full route for ${row.plate_number}`;
    traceBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (window.Dashboard) window.Dashboard.traceFromSearch(row.plate_number);
    });
    actions.appendChild(traceBtn);

    if (row.snapshot_path) {
      const snap = document.createElement('button');
      snap.className = 'btn-xs';
      snap.textContent = 'Crop';
      snap.addEventListener('click', (e) => {
        e.stopPropagation();
        window.open(row.snapshot_path, '_blank', 'noopener');
      });
      actions.appendChild(snap);
    }

    tr.appendChild(actions);

    tr.addEventListener('click', () => {
      if (window.gisMap) window.gisMap.highlightAlertCamera(row.camera_id);
    });

    return tr;
  }

  // ------------------------------------------------------------------ export
  exportCsv() {
    if (!this.results.length) return;

    const columns = [
      { label: 'Timestamp (IST)', value: (r) => Utils.formatDateTime(r.capture_timestamp) },
      { label: 'Timestamp (UTC)', value: (r) => r.capture_timestamp },
      { label: 'Plate', value: (r) => r.plate_number },
      { label: 'Raw OCR', value: (r) => r.plate_raw },
      { label: 'Confidence', value: (r) => r.confidence },
      { label: 'Vehicle type', value: (r) => r.vehicle_type },
      { label: 'Camera ID', value: (r) => r.camera_id },
      { label: 'Camera', value: (r) => r.camera_name },
      { label: 'Department', value: (r) => r.department },
      { label: 'District', value: (r) => r.district },
      { label: 'Latitude', value: (r) => r.latitude },
      { label: 'Longitude', value: (r) => r.longitude },
      { label: 'Snapshot', value: (r) => r.snapshot_path },
    ];

    // Both zones go in the file: IST for the officer reading it, UTC so the
    // export is unambiguous once it leaves this machine.
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    Utils.downloadCsv(`sentinel-sightings-${stamp}.csv`, Utils.toCsv(this.results, columns));
    Utils.toast(`Exported ${this.results.length} sightings`, 'success');
  }
}

window.SightingSearch = SightingSearch;
