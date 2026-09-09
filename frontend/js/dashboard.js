// Dashboard bootstrap and cross-module wiring.
let viewer;
let gisMap;
let alertManager;
let tracker;

const Dashboard = {
  cameras: [],
  detectionTicker: [],

  async init() {
    this.startClock();

    // /api/health is unauthenticated and reports whether a token is required,
    // so the gate only appears on deployments that actually enforce one.
    if (!(await this.ensureAuthenticated())) return;

    gisMap = new GISMap('map');
    gisMap.init();
    window.gisMap = gisMap;

    viewer = new UnifiedViewer('camera-grid');
    window.viewer = viewer;

    alertManager = new AlertManager('alert-feed', 'siren-banner');
    window.alertManager = alertManager;

    tracker = new VehicleTracker('timeline-container', gisMap);
    window.tracker = tracker;

    this.bindControls();
    this.connectLiveChannel();

    await this.loadCameraRegistry();
    await this.loadFacets();
    await this.loadAlerts();
    await this.refreshWorkerStatus();
  },

  // ---------------- Access ----------------
  /**
   * Returns true once the dashboard may proceed. Shows the token gate and
   * waits when the deployment requires a token we do not have (or have wrong).
   */
  async ensureAuthenticated() {
    let health;
    try {
      health = await API.getHealth();
    } catch (e) {
      Utils.toast(e.message, 'error');
      return true; // Let the rest of the dashboard surface its own errors.
    }

    if (!health.auth_required) return true;

    while (true) {
      if (API.token) {
        try {
          await API.getAlertStats();  // cheapest guarded call
          this.hideTokenGate();
          return true;
        } catch (e) {
          if (e.status !== 401) return true;
          API.setToken('');
          this.showTokenGate('That token was not accepted. Try again.');
        }
      } else {
        this.showTokenGate();
      }

      const entered = await this.awaitTokenEntry();
      API.setToken(entered);
    }
  },

  showTokenGate(message) {
    const gate = document.getElementById('token-gate');
    if (!gate) return;
    gate.style.display = 'flex';
    const note = document.getElementById('token-gate-error');
    if (note) {
      note.textContent = message || '';
      note.hidden = !message;
    }
    const input = document.getElementById('token-input');
    if (input) { input.value = ''; input.focus(); }
  },

  hideTokenGate() {
    const gate = document.getElementById('token-gate');
    if (gate) gate.style.display = 'none';
  },

  awaitTokenEntry() {
    return new Promise((resolve) => {
      const form = document.getElementById('token-form');
      const handler = (event) => {
        event.preventDefault();
        form.removeEventListener('submit', handler);
        resolve(document.getElementById('token-input').value.trim());
      };
      form.addEventListener('submit', handler);
    });
  },

  // ---------------- Clock ----------------
  startClock() {
    const tick = () => {
      // Rendered in Asia/Kolkata explicitly. The old clock printed the
      // workstation's local time and appended "IST" regardless of its timezone.
      Utils.setText('system-clock', `${Utils.formatTime(new Date())} IST`);
    };
    tick();
    setInterval(tick, 1000);
  },

  // ---------------- Live channel ----------------
  connectLiveChannel() {
    API.connectWebSocket({
      onAlert: (data) => alertManager.handleIncomingAlert(data, gisMap),
      onDetection: (data) => this.pushDetection(data),
      onWorkerStatus: (status) => viewer.applyWorkerStatus(status),
      onStateChange: (state) => this.setConnectionState(state),
    });
  },

  setConnectionState(state) {
    const dot = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    if (!dot || !label) return;

    const text = {
      connected: 'Live',
      connecting: 'Connecting…',
      reconnecting: 'Reconnecting…',
      disconnected: 'Offline',
    }[state] || state;

    dot.className = `status-dot ${state === 'connected' ? '' : state === 'disconnected' ? 'alert' : 'connecting'}`;
    label.textContent = text;
    label.title = state === 'connected'
      ? 'Receiving live detections and alerts'
      : 'Not receiving live alerts — the feed below may be stale';
  },

  /** Live sighting ticker, capped so it cannot grow without bound. */
  pushDetection(detection) {
    this.detectionTicker.unshift(detection);
    this.detectionTicker = this.detectionTicker.slice(0, 12);

    const host = document.getElementById('detection-ticker');
    if (!host) return;

    host.innerHTML = '';
    this.detectionTicker.forEach((d) => {
      const item = document.createElement('button');
      item.className = 'ticker-item';
      item.title = `${d.camera_name} · ${Utils.formatDateTime(d.timestamp)}`;
      item.innerHTML = `
        <span class="ticker-plate">${Utils.esc(d.plate_number)}</span>
        <span class="ticker-cam">${Utils.esc(d.camera_id)}</span>
        <span class="ticker-time">${Utils.esc(Utils.formatRelative(d.timestamp))}</span>
      `;
      item.addEventListener('click', () => {
        document.getElementById('target-plate-input').value = d.plate_number;
        tracker.searchAndTrace(d.plate_number);
      });
      host.appendChild(item);
    });
  },

  // ---------------- Registry ----------------
  async loadCameraRegistry(filters = {}) {
    try {
      const cameras = await API.getCameras(filters);
      this.cameras = cameras;
      Utils.setText('stat-cameras-count', cameras.length);
      viewer.loadCameras(cameras);

      const geojson = await API.getCamerasGeoJSON();
      gisMap.renderCameras(geojson);
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  async loadFacets() {
    try {
      const facets = await API.getCameraFacets();
      this.fillSelect('filter-department', facets.departments, 'All departments');
      this.fillSelect('filter-district', facets.districts, 'All districts');
      this.fillSelect('filter-status', facets.statuses, 'Any status');
    } catch (e) {
      /* filters degrade to free-text search */
    }
  },

  fillSelect(id, options, placeholder) {
    const select = document.getElementById(id);
    if (!select) return;
    const current = select.value;
    select.innerHTML = `<option value="">${Utils.esc(placeholder)}</option>`;
    (options || []).forEach((opt) => {
      const el = document.createElement('option');
      el.value = opt.value;
      el.textContent = `${opt.value} (${opt.count})`;
      select.appendChild(el);
    });
    select.value = current;
  },

  currentFilters() {
    const value = (id) => (document.getElementById(id) || {}).value || '';
    return {
      search: value('filter-search'),
      department: value('filter-department'),
      district: value('filter-district'),
      status: value('filter-status'),
    };
  },

  async applyFilters() {
    const filters = this.currentFilters();
    try {
      const cameras = await API.getCameras(filters);
      Utils.setText('stat-cameras-count', cameras.length);
      viewer.setVisibleCameras(cameras);
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  // ---------------- Alerts ----------------
  async loadAlerts() {
    try {
      const alerts = await API.getAlerts({ limit: 50 });
      alertManager.setAlerts(alerts);
      await alertManager.refreshStats();
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  async refreshWorkerStatus() {
    try {
      viewer.applyWorkerStatus(await API.getStreamStatus());
    } catch (e) {
      /* pool status is advisory */
    }
  },

  // ---------------- Watchlist ----------------
  async openWatchlistModal() {
    try {
      const watchlist = await API.getWatchlist();
      const tbody = document.getElementById('watchlist-table-rows');
      tbody.innerHTML = '';

      watchlist.forEach((w) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td><b class="mono-plate">${Utils.esc(w.plate_number)}</b></td>
          <td><span class="cell-danger">${Utils.esc(w.crime_category)}</span></td>
          <td>${Utils.esc(w.vehicle_make_model || '—')}</td>
          <td>${Utils.esc(w.police_station || '—')}<br><small>${Utils.esc(w.fir_number || '—')}</small></td>
        `;
        const actionCell = document.createElement('td');
        const btn = document.createElement('button');
        btn.className = 'btn-xs';
        btn.textContent = 'Trace';
        btn.addEventListener('click', () => {
          document.getElementById('target-plate-input').value = w.plate_number;
          this.closeModal('watchlist-modal');
          tracker.searchAndTrace(w.plate_number);
        });
        actionCell.appendChild(btn);
        tr.appendChild(actionCell);
        tbody.appendChild(tr);
      });

      document.getElementById('watchlist-modal').style.display = 'flex';
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  async submitWatchlistEntry(event) {
    event.preventDefault();
    const value = (id) => document.getElementById(id).value.trim();
    const plate = Utils.normalizePlate(value('wl-plate'));

    if (plate.length < 4) {
      Utils.toast('Enter a valid registration number.', 'error');
      return;
    }

    try {
      await API.addToWatchlist({
        plate_number: plate,
        crime_category: value('wl-category'),
        vehicle_make_model: value('wl-model') || null,
        fir_number: value('wl-fir') || null,
        severity: value('wl-severity'),
      });
      Utils.toast(`${plate} added to the active watchlist`, 'success');
      document.getElementById('watchlist-form').reset();
      await this.openWatchlistModal();
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'none';
  },

  async syncCatalogue() {
    const btn = document.getElementById('btn-sync-catalogue');
    btn.disabled = true;
    btn.textContent = 'Syncing…';
    try {
      const data = await API.syncCatalogue();
      Utils.toast(
        `Catalogue synced: ${data.synced_cameras} cameras (source: ${data.source})`,
        'success',
      );
      await this.loadCameraRegistry(this.currentFilters());
      await this.loadFacets();
    } catch (e) {
      Utils.toast(e.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Sync Ingest API';
    }
  },

  // ---------------- Wiring ----------------
  bindControls() {
    document.querySelectorAll('[data-layout-btn]').forEach((btn) => {
      btn.addEventListener('click', () => viewer.setLayout(btn.dataset.layoutBtn));
    });

    document.querySelectorAll('[data-pager]').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (btn.dataset.dir === 'next') viewer.nextPage(); else viewer.prevPage();
      });
    });

    document.querySelectorAll('[data-center]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const [lat, lng, zoom] = btn.dataset.center.split(',').map(Number);
        gisMap.map.setView([lat, lng], zoom);
      });
    });

    document.getElementById('btn-fit-registry').addEventListener('click', () => {
      const points = this.cameras.map((c) => [c.latitude, c.longitude]);
      if (points.length) gisMap.map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
    });

    document.getElementById('toggle-camera-layer').addEventListener('change', (e) => {
      gisMap.setCamerasVisible(e.target.checked);
    });

    const debouncedFilter = Utils.debounce(() => this.applyFilters(), 250);
    document.getElementById('filter-search').addEventListener('input', debouncedFilter);
    ['filter-department', 'filter-district', 'filter-status'].forEach((id) => {
      document.getElementById(id).addEventListener('change', () => this.applyFilters());
    });
    document.getElementById('btn-clear-filters').addEventListener('click', () => {
      ['filter-search', 'filter-department', 'filter-district', 'filter-status']
        .forEach((id) => { document.getElementById(id).value = ''; });
      this.applyFilters();
    });

    document.getElementById('btn-track-vehicle').addEventListener('click', () => {
      tracker.searchAndTrace(document.getElementById('target-plate-input').value);
    });
    document.getElementById('target-plate-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('btn-track-vehicle').click();
    });

    document.getElementById('btn-export-docket').addEventListener('click', () => tracker.openDocketModal());
    document.getElementById('btn-refresh-alerts').addEventListener('click', () => this.loadAlerts());
    document.getElementById('btn-open-watchlist').addEventListener('click', () => this.openWatchlistModal());
    document.getElementById('btn-sync-catalogue').addEventListener('click', () => this.syncCatalogue());
    document.getElementById('watchlist-form').addEventListener('submit', (e) => this.submitWatchlistEntry(e));

    document.getElementById('btn-mute-siren').addEventListener('click', () => {
      alertManager.setMuted(!alertManager.muted);
    });

    document.querySelectorAll('[data-alert-filter]').forEach((btn) => {
      btn.addEventListener('click', () => alertManager.setFilter(btn.dataset.alertFilter));
    });

    document.querySelectorAll('[data-close-modal]').forEach((btn) => {
      btn.addEventListener('click', () => this.closeModal(btn.dataset.closeModal));
    });

    // Click the backdrop or press Escape to dismiss a modal.
    document.querySelectorAll('.modal-overlay').forEach((overlay) => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.style.display = 'none';
      });
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach((m) => { m.style.display = 'none'; });
      }
    });

    // The alert chime needs a user gesture before the browser will allow audio.
    document.addEventListener('click', () => alertManager.initAudio(), { once: true });
  },
};

document.addEventListener('DOMContentLoaded', () => Dashboard.init());
window.Dashboard = Dashboard;
