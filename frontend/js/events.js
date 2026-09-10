// Live ANPR event log.
//
// Replaces the horizontal ticker. A scrolling strip of pills cannot be read
// while it moves and shows one field per sighting; an operator needs to scan
// time, plate, camera, class and confidence together, which is a table.
class EventLog {
  constructor(bodyId) {
    this.body = document.getElementById(bodyId);
    this.rows = [];
    this.max = 200;
    this.live = true;
    this.renderEmpty();
  }

  setLive(live) {
    this.live = live;
    const btn = document.getElementById('btn-events-live');
    if (btn) btn.classList.toggle('active', live);
    Utils.setText('events-sub', live ? '(Live)' : '(Paused)');
  }

  /** Seed from history so the table is not blank before the first detection. */
  async loadRecent() {
    try {
      const data = await API.searchDetections({ limit: 60 });
      this.rows = data.results || [];
      this.render();
    } catch (e) {
      this.renderEmpty(e.message);
    }
  }

  /** A detection arriving over the WebSocket. */
  push(detection) {
    if (!this.live) return;
    this.rows.unshift(detection);
    // Capped: a busy junction would otherwise grow this without bound over a
    // shift and take the tab down with it.
    if (this.rows.length > this.max) this.rows.length = this.max;
    this.render(detection.detection_id);
  }

  renderEmpty(error) {
    this.body.innerHTML = `
      <div class="table-empty">
        <div class="table-empty-title">${error ? 'Could not load events' : 'No ANPR events yet'}</div>
        <div>${error
          ? Utils.esc(error)
          : 'Start AI analytics on a feed, or ingest a detection, and reads appear here.'}</div>
      </div>
    `;
  }

  render(highlightId) {
    if (!this.rows.length) {
      this.renderEmpty();
      return;
    }

    const esc = Utils.esc.bind(Utils);
    const table = document.createElement('table');
    table.className = 'data-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th>Time</th><th>Number Plate</th><th>Camera</th>
          <th>Vehicle Type</th><th>Confidence</th>
        </tr>
      </thead>
    `;

    const tbody = document.createElement('tbody');
    this.rows.forEach((row) => {
      const confidence = Number(row.confidence || 0);
      const tr = document.createElement('tr');
      if (row.detection_id === highlightId) tr.classList.add('is-selected');
      tr.title = `${row.camera_name || row.camera_id} — ${Utils.formatDateTime(row.capture_timestamp)}`;

      tr.innerHTML = `
        <td class="col-time">${esc(Utils.formatTime(row.capture_timestamp))}</td>
        <td class="col-plate">${esc(row.plate_number)}</td>
        <td>${esc(row.camera_name || row.camera_id)}
          <span class="col-sub">${esc(row.camera_id)}</span></td>
        <td>${esc(this.vehicleLabel(row.vehicle_type))}</td>
        <td class="col-num ${confidence < 0.6 ? 'conf-weak' : ''}">${(confidence * 100).toFixed(0)}%</td>
      `;

      tr.addEventListener('click', () => {
        if (window.gisMap) window.gisMap.highlightAlertCamera(row.camera_id);
        if (window.Dashboard) window.Dashboard.traceFromEvent(row.plate_number);
      });

      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    this.body.innerHTML = '';
    this.body.appendChild(table);
  }

  vehicleLabel(type) {
    switch (String(type || '').toUpperCase()) {
      case 'MOTORCYCLE': return 'Two Wheeler';
      case 'CAR': return 'Car';
      case 'BUS': return 'Bus';
      case 'TRUCK': return 'Truck';
      default: return type || '—';
    }
  }
}

window.EventLog = EventLog;
