// Console bootstrap, view routing and cross-module wiring.
let viewer;
let gisMap;
let alertManager;
let tracker;
let sightingSearch;
let eventLog;

/**
 * Which panels each top-level view shows, and how the workspace grid is laid
 * out for it. Every view here is backed by real functionality -- this build
 * has no recording, no device management and no analytics beyond ANPR, so it
 * offers no tabs for them.
 */
const VIEWS = {
  live: { regions: ['feeds', 'map', 'events', 'alerts'], layout: 'layout-live' },
  search: { regions: ['investigate', 'map'], layout: 'layout-investigate' },
  alarms: { regions: ['alerts'], layout: 'layout-single' },
  maps: { regions: ['map'], layout: 'layout-single' },
  system: { regions: ['system'], layout: 'layout-single' },
};

const Dashboard = {
  cameras: [],
  districts: [],
  activeDistrict: '',
  view: 'live',

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

    eventLog = new EventLog('events-body');
    window.eventLog = eventLog;

    alertManager = new AlertManager('alert-feed', 'siren-banner');
    window.alertManager = alertManager;

    tracker = new VehicleTracker('timeline-container', gisMap);
    window.tracker = tracker;

    sightingSearch = new SightingSearch('search-results');
    window.sightingSearch = sightingSearch;

    this.bindControls();
    this.connectLiveChannel();

    await this.loadCameraRegistry();
    await this.loadFacets();
    await this.loadAlerts();
    await this.refreshWorkerStatus();
    await eventLog.loadRecent();
  },

  // ---------------- Access ----------------
  async ensureAuthenticated() {
    let health;
    try {
      health = await API.getHealth();
    } catch (e) {
      Utils.toast(e.message, 'error');
      return true; // Let the rest of the console surface its own errors.
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

      API.setToken(await this.awaitTokenEntry());
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

  // ---------------- View routing ----------------
  setView(view) {
    const spec = VIEWS[view];
    if (!spec) return;
    this.view = view;

    document.querySelectorAll('[data-view]').forEach((btn) => {
      const active = btn.dataset.view === view;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });

    const workspace = document.getElementById('workspace');
    workspace.className = `workspace ${spec.layout}`;

    document.querySelectorAll('[data-region]').forEach((panel) => {
      panel.hidden = !spec.regions.includes(panel.dataset.region);
    });

    // Leaflet measures its container on creation; if the map was hidden or has
    // just changed size it renders into stale dimensions until told otherwise.
    if (spec.regions.includes('map') && gisMap && gisMap.map) {
      setTimeout(() => gisMap.map.invalidateSize(), 60);
    }
    if (spec.regions.includes('feeds') && viewer) {
      setTimeout(() => viewer.render(), 60);
    }
    if (view === 'system') this.renderSystem();
  },

  // ---------------- Clock ----------------
  startClock() {
    const tick = () => {
      // Rendered in Asia/Kolkata explicitly rather than trusting the
      // workstation's timezone, which every other timestamp also honours.
      Utils.setText('system-clock', `${Utils.formatTime(new Date())} IST`);
      Utils.setText('system-date', Utils.formatDatePart(new Date()));
    };
    tick();
    setInterval(tick, 1000);
  },

  // ---------------- Live channel ----------------
  connectLiveChannel() {
    API.connectWebSocket({
      onAlert: (data) => alertManager.handleIncomingAlert(data, gisMap),
      onDetection: (data) => eventLog.push(data),
      onWorkerStatus: (status) => this.applyWorkerStatus(status),
      onStateChange: (state) => this.setConnectionState(state),
    });
  },

  setConnectionState(state) {
    const dot = document.getElementById('ws-dot');
    const label = document.getElementById('ws-label');
    if (!dot || !label) return;

    const text = {
      connected: 'Live', connecting: 'Connecting',
      reconnecting: 'Reconnecting', disconnected: 'Offline',
    }[state] || state;

    dot.className = `dot ${state === 'connected' ? 'dot-ok' : state === 'disconnected' ? 'dot-danger' : 'dot-warn'}`;
    label.textContent = text;
    // "No alerts" and "not connected" look identical on a quiet console and
    // mean opposite things, so the link state is always on screen.
    label.title = state === 'connected'
      ? 'Receiving live detections and alerts'
      : 'Not receiving live alerts — the queue below may be stale';
  },

  applyWorkerStatus(status) {
    viewer.applyWorkerStatus(status);
    const count = (status && status.active_workers_count) || 0;
    Utils.setText('stat-workers-count', count);
    Utils.setText('stat-workers-max', (status && status.max_capacity) || 5);
    Utils.setText('count-anpr', count);
    const dot = document.getElementById('analytics-dot');
    if (dot) dot.className = `dot ${count ? 'dot-ok' : 'dot-idle'}`;
    if (this.view === 'system') this.renderSystem(status);
  },

  // ---------------- Registry ----------------
  async loadCameraRegistry(filters = {}) {
    try {
      const cameras = await API.getCameras(filters);
      this.cameras = cameras;

      const online = cameras.filter(
        (c) => String(c.connectivity_status).toUpperCase() === 'ONLINE',
      ).length;
      Utils.setText('stat-cameras-online', online);
      Utils.setText('stat-cameras-count', cameras.length);
      Utils.setText('count-all', cameras.length);

      viewer.loadCameras(cameras);
      this.fillCameraSelect(cameras);
      gisMap.renderCameras(await API.getCamerasGeoJSON());
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  async loadFacets() {
    try {
      const facets = await API.getCameraFacets();
      this.districts = facets.districts || [];
      this.renderSideViews();
    } catch (e) {
      /* the sidebar degrades to "All feeds" */
    }
  },

  /**
   * Sidebar views are the registry's real districts rather than invented
   * zones, so every entry filters to cameras that actually exist.
   */
  renderSideViews() {
    const host = document.getElementById('side-views');
    if (!host) return;

    const total = this.cameras.length;
    host.innerHTML = '';

    const entries = [{ value: '', label: 'All feeds', count: total }].concat(
      this.districts.map((d) => ({ value: d.value, label: d.value, count: d.count })),
    );

    entries.forEach((entry) => {
      const btn = document.createElement('button');
      btn.className = `side-item${entry.value === this.activeDistrict ? ' active' : ''}`;
      btn.dataset.district = entry.value;
      btn.innerHTML = `${Utils.esc(entry.label)}<span class="side-item-count">${Utils.esc(entry.count)}</span>`;
      btn.addEventListener('click', () => this.selectDistrict(entry.value, entry.label));
      host.appendChild(btn);
    });
  },

  async selectDistrict(district, label) {
    this.activeDistrict = district;
    document.querySelectorAll('#side-views .side-item').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.district === district);
    });
    Utils.setText('feeds-scope', district ? label : 'All districts');
    Utils.setText('map-scope', district ? label : 'Gujarat');

    if (this.view !== 'live' && this.view !== 'maps') this.setView('live');

    try {
      const cameras = await API.getCameras({ district });
      viewer.setVisibleCameras(cameras);
      // Frame the map on the selection so the two panels agree.
      const points = cameras.map((c) => [c.latitude, c.longitude]);
      if (points.length && gisMap.map) {
        gisMap.map.fitBounds(L.latLngBounds(points), { padding: [40, 40] });
      }
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  fillCameraSelect(cameras) {
    const select = document.getElementById('search-camera');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">All cameras</option>';
    cameras.forEach((cam) => {
      const opt = document.createElement('option');
      opt.value = cam.camera_id;
      opt.textContent = `${cam.camera_id} · ${cam.name}`;
      select.appendChild(opt);
    });
    select.value = current;
  },

  // ---------------- Investigation ----------------
  setTrackerTab(tab) {
    document.querySelectorAll('[data-tracker-tab]').forEach((btn) => {
      const active = btn.dataset.trackerTab === tab;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    document.querySelectorAll('[data-tracker-view]').forEach((v) => {
      v.hidden = v.dataset.trackerView !== tab;
    });

    // Each view owns a different export; only the active one's should show,
    // and neither before it has something to export.
    const docket = document.getElementById('btn-export-docket');
    const csv = document.getElementById('btn-export-search');
    if (docket) docket.hidden = tab !== 'trace' || !tracker.currentTrackData;
    if (csv) csv.hidden = tab !== 'search' || !sightingSearch.results.length;
  },

  /** Jump from a search hit into a full route reconstruction of that plate. */
  traceFromSearch(plate) {
    document.getElementById('target-plate-input').value = plate;
    // Carry the search window across so the trace stays scoped to the same
    // incident the operator was already looking at.
    ['from', 'to'].forEach((edge) => {
      const src = document.getElementById(`search-${edge}`);
      const dst = document.getElementById(`trace-${edge}`);
      if (src && dst) dst.value = src.value;
    });
    this.setView('search');
    this.setTrackerTab('trace');
    tracker.searchAndTrace(plate);
  },

  /** Clicking an ANPR event row traces that plate, unscoped. */
  traceFromEvent(plate) {
    document.getElementById('target-plate-input').value = plate;
    this.setView('search');
    this.setTrackerTab('trace');
    tracker.searchAndTrace(plate, { from: '', to: '' });
  },

  // ---------------- Alerts ----------------
  async loadAlerts() {
    try {
      alertManager.setAlerts(await API.getAlerts({ limit: 100 }));
      await alertManager.refreshStats();
    } catch (e) {
      Utils.toast(e.message, 'error');
    }
  },

  async refreshWorkerStatus() {
    try {
      this.applyWorkerStatus(await API.getStreamStatus());
    } catch (e) {
      /* pool status is advisory */
    }
  },

  // ---------------- System ----------------
  async renderSystem(knownStatus) {
    const host = document.getElementById('system-body');
    if (!host) return;
    const esc = Utils.esc.bind(Utils);

    let health = {};
    let status = knownStatus;
    try {
      health = await API.getHealth();
      if (!status) status = health.ai_workers;
    } catch (e) {
      host.innerHTML = `<div class="table-empty"><div class="table-empty-title">Server unreachable</div><div>${esc(e.message)}</div></div>`;
      return;
    }

    const workers = (status && status.workers) || [];
    const rows = workers.length
      ? workers.map((w) => `
          <tr>
            <td class="col-plate">${esc(w.camera_id)}</td>
            <td><span class="status-cell"><span class="dot ${w.connected ? 'dot-ok' : 'dot-warn'}"></span>
              ${w.connected ? 'Streaming' : 'Reconnecting'}</span></td>
            <td class="col-num">${esc(w.frames_read)}</td>
            <td class="col-num">${esc(w.detections_count)}</td>
            <td class="col-num">${esc(w.reconnect_attempts)}</td>
            <td>${esc(w.last_error || '—')}</td>
          </tr>`).join('')
      : `<tr><td colspan="6" class="table-empty">No analytics workers running. Start one from a camera tile.</td></tr>`;

    host.innerHTML = `
      <div class="form-row">
        <span class="form-label">Server</span>
        <span class="status-cell"><span class="dot ${health.status === 'healthy' ? 'dot-ok' : 'dot-danger'}"></span>
          ${esc(health.status || 'unknown')}</span>
        <span class="form-label">Auth</span>
        <span class="status-cell"><span class="dot ${health.auth_required ? 'dot-ok' : 'dot-warn'}"></span>
          ${health.auth_required ? 'Token required' : 'Open — no token configured'}</span>
        <span class="form-label">Dashboards</span>
        <span class="col-num">${esc(health.dashboard_clients ?? 0)}</span>
        <span class="form-label">Workers</span>
        <span class="col-num">${esc((status && status.active_workers_count) || 0)} / ${esc((status && status.max_capacity) || 5)}</span>
      </div>
      ${!health.auth_required ? `<div class="notice">
        SENTINEL_API_TOKEN is not set, so the API is unauthenticated. Anyone who can
        reach this port can read the camera registry and watchlist and control analytics
        workers. Do not expose this beyond localhost.</div>` : ''}
      <table class="data-table">
        <thead><tr><th>Camera</th><th>Stream</th><th>Frames</th><th>Detections</th><th>Reconnects</th><th>Last error</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  },

  // ---------------- Watchlist ----------------
  async openWatchlistModal() {
    try {
      const watchlist = await API.getWatchlist();
      Utils.setText('count-watchlist', watchlist.length);
      const tbody = document.getElementById('watchlist-table-rows');
      tbody.innerHTML = '';

      watchlist.forEach((w) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="col-plate">${Utils.esc(w.plate_number)}</td>
          <td>${Utils.esc(w.crime_category)}</td>
          <td>${Utils.esc(w.vehicle_make_model || '—')}</td>
          <td>${Utils.esc(w.police_station || '—')}
            <span class="col-sub">${Utils.esc(w.fir_number || '—')}</span></td>
        `;
        const cell = document.createElement('td');
        cell.className = 'col-actions';
        const btn = document.createElement('button');
        btn.className = 'btn';
        btn.textContent = 'Trace';
        btn.addEventListener('click', () => {
          document.getElementById('target-plate-input').value = w.plate_number;
          this.closeModal('watchlist-modal');
          this.setView('search');
          this.setTrackerTab('trace');
          tracker.searchAndTrace(w.plate_number, { from: '', to: '' });
        });
        cell.appendChild(btn);
        tr.appendChild(cell);
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
    const btn = document.getElementById('side-sync');
    btn.disabled = true;
    try {
      const data = await API.syncCatalogue();
      Utils.toast(`Catalogue synced: ${data.synced_cameras} cameras (${data.source})`, 'success');
      await this.loadCameraRegistry({ district: this.activeDistrict });
      await this.loadFacets();
    } catch (e) {
      Utils.toast(e.message, 'error');
    } finally {
      btn.disabled = false;
    }
  },

  // ---------------- Wiring ----------------
  bindControls() {
    document.querySelectorAll('[data-view]').forEach((btn) => {
      btn.addEventListener('click', () => this.setView(btn.dataset.view));
    });

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

    // Investigation
    document.querySelectorAll('[data-tracker-tab]').forEach((btn) => {
      btn.addEventListener('click', () => this.setTrackerTab(btn.dataset.trackerTab));
    });
    document.getElementById('btn-track-vehicle').addEventListener('click', () => {
      tracker.searchAndTrace(document.getElementById('target-plate-input').value);
    });
    document.getElementById('target-plate-input').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') document.getElementById('btn-track-vehicle').click();
    });
    document.getElementById('btn-clear-trace-window').addEventListener('click', () => {
      ['trace-from', 'trace-to'].forEach((id) => { document.getElementById(id).value = ''; });
      Utils.toast('Time window cleared — tracing full history.', 'info', 2500);
    });
    document.getElementById('btn-run-search').addEventListener('click', () => sightingSearch.run());
    document.getElementById('btn-clear-search').addEventListener('click', () => sightingSearch.clearForm());
    document.getElementById('btn-export-search').addEventListener('click', () => sightingSearch.exportCsv());
    document.getElementById('btn-export-docket').addEventListener('click', () => tracker.openDocketModal());
    document.getElementById('search-plate').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') sightingSearch.run();
    });

    // Events
    document.getElementById('btn-events-live').addEventListener('click', () => eventLog.setLive(!eventLog.live));
    document.getElementById('btn-events-refresh').addEventListener('click', () => eventLog.loadRecent());

    // Alerts
    document.querySelectorAll('[data-alert-filter]').forEach((btn) => {
      btn.addEventListener('click', () => alertManager.setFilter(btn.dataset.alertFilter));
    });
    document.getElementById('btn-mute-siren').addEventListener('click', () => {
      alertManager.setMuted(!alertManager.muted);
    });

    // Sidebar system entries
    document.getElementById('side-watchlist').addEventListener('click', () => this.openWatchlistModal());
    document.getElementById('side-registry').addEventListener('click', () => this.setView('maps'));
    document.getElementById('side-sync').addEventListener('click', () => this.syncCatalogue());
    document.getElementById('side-anpr').addEventListener('click', () => this.setView('system'));
    document.getElementById('btn-refresh-system').addEventListener('click', () => this.renderSystem());

    document.getElementById('watchlist-form').addEventListener('submit', (e) => this.submitWatchlistEntry(e));

    document.querySelectorAll('[data-close-modal]').forEach((btn) => {
      btn.addEventListener('click', () => this.closeModal(btn.dataset.closeModal));
    });
    document.querySelectorAll('.modal-overlay').forEach((overlay) => {
      overlay.addEventListener('click', (e) => {
        if (e.target === overlay && overlay.id !== 'token-gate') overlay.style.display = 'none';
      });
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach((m) => {
          if (m.id !== 'token-gate') m.style.display = 'none';
        });
      }
    });

    // The alert chime needs a user gesture before the browser allows audio.
    document.addEventListener('click', () => alertManager.initAudio(), { once: true });

    window.addEventListener('resize', Utils.debounce(() => {
      if (gisMap && gisMap.map) gisMap.map.invalidateSize();
    }, 200));
  },
};

document.addEventListener('DOMContentLoaded', () => Dashboard.init());
window.Dashboard = Dashboard;
