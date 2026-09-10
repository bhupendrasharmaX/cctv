// Centralized API Client & WebSocket Manager
const TOKEN_STORAGE_KEY = 'sentinel_api_token';

const API = {
  baseUrl: window.location.origin,
  _token: null,

  /**
   * Shared platform token, held per browser tab.
   *
   * sessionStorage rather than localStorage: on a shared control-room
   * workstation the token should not outlive the session at that desk.
   */
  get token() {
    if (this._token === null) {
      try {
        this._token = sessionStorage.getItem(TOKEN_STORAGE_KEY) || '';
      } catch (e) {
        this._token = '';
      }
    }
    return this._token;
  },

  setToken(value) {
    this._token = value || '';
    try {
      if (this._token) {
        sessionStorage.setItem(TOKEN_STORAGE_KEY, this._token);
      } else {
        sessionStorage.removeItem(TOKEN_STORAGE_KEY);
      }
    } catch (e) { /* storage unavailable; token stays in memory */ }
  },

  async _request(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;

    let res;
    try {
      res = await fetch(`${this.baseUrl}${path}`, { ...options, headers });
    } catch (networkError) {
      throw new Error('Command server unreachable. Check that the platform is running.');
    }

    if (!res.ok) {
      // FastAPI reports failures as {"detail": ...}; surface that instead of a
      // bare status code, which tells an operator nothing actionable.
      let detail = `Request failed (HTTP ${res.status})`;
      try {
        const body = await res.json();
        if (typeof body.detail === 'string') {
          detail = body.detail;
        } else if (Array.isArray(body.detail) && body.detail.length) {
          detail = body.detail[0].msg || detail;
        }
      } catch (_) { /* non-JSON error body */ }

      const error = new Error(detail);
      error.status = res.status;
      throw error;
    }

    return res.status === 204 ? null : res.json();
  },

  _query(params = {}) {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') search.append(key, value);
    });
    const qs = search.toString();
    return qs ? `?${qs}` : '';
  },

  // ---------------- Registry (Model 1) ----------------
  getCameras(filters = {}) {
    return this._request(`/api/cameras${this._query(filters)}`);
  },

  getCameraFacets() {
    return this._request('/api/cameras/facets');
  },

  getCamerasGeoJSON() {
    return this._request('/api/cameras-geojson');
  },

  syncCatalogue(host) {
    return this._request(`/api/sync-catalogue${this._query({ host })}`, { method: 'POST' });
  },

  // ---------------- Tracking ----------------
  /** `window` is {from, to} as UTC ISO strings; either may be blank. */
  trackVehicle(plate, window = {}) {
    const path = `/api/track-vehicle/${encodeURIComponent(Utils.normalizePlate(plate))}`;
    return this._request(`${path}${this._query({ from: window.from, to: window.to })}`);
  },

  getDetections(filters = {}) {
    return this._request(`/api/detections${this._query(filters)}`);
  },

  /**
   * Investigative sighting search: partial plate, camera, vehicle type,
   * confidence floor and time window. Rows come joined to their camera, with a
   * total so the UI can say how many matches it left off the end.
   */
  searchDetections(filters = {}) {
    return this._request(`/api/detections/search${this._query(filters)}`);
  },

  // ---------------- Watchlist ----------------
  getWatchlist() {
    return this._request('/api/watchlist');
  },

  addToWatchlist(entry) {
    return this._request('/api/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(entry),
    });
  },

  // ---------------- Alerts ----------------
  getAlerts(filters = {}) {
    return this._request(`/api/alerts${this._query({ limit: 30, ...filters })}`);
  },

  getAlertStats() {
    return this._request('/api/alerts/stats');
  },

  acknowledgeAlert(alertId) {
    return this._request(`/api/alerts/${alertId}/acknowledge`, { method: 'POST' });
  },

  resolveAlert(alertId) {
    return this._request(`/api/alerts/${alertId}/resolve`, { method: 'POST' });
  },

  // ---------------- AI stream control ----------------
  getStreamStatus() {
    return this._request('/api/stream-control/status');
  },

  toggleCameraAI(cameraId) {
    return this._request(`/api/stream-control/toggle/${encodeURIComponent(cameraId)}`, { method: 'POST' });
  },

  getHealth() {
    return this._request('/api/health');
  },

  // ---------------- Live channel ----------------
  /**
   * Connect to the alert stream.
   *
   * `handlers` may define onAlert, onDetection, onWorkerStatus and onStateChange.
   * Reconnection backs off instead of hammering a downed server every 3s, and
   * onStateChange drives the header indicator so an operator can tell the
   * difference between "no alerts" and "not connected" -- on a surveillance
   * console those look identical and mean opposite things.
   */
  connectWebSocket(handlers = {}) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // A WebSocket handshake carries no custom headers, so the token travels as
    // a query parameter. It never leaves this origin.
    const suffix = this.token ? `?token=${encodeURIComponent(this.token)}` : '';
    const wsUrl = `${protocol}//${window.location.host}/ws/alerts${suffix}`;

    let ws = null;
    let attempt = 0;
    let heartbeat = null;
    let closedByUs = false;

    const setState = (state) => handlers.onStateChange && handlers.onStateChange(state);

    const connect = () => {
      setState(attempt === 0 ? 'connecting' : 'reconnecting');
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        attempt = 0;
        setState('connected');
        console.log('[WebSocket] Connected to CCTV command center alert stream.');
        // The server blocks on receive_text(); a periodic ping keeps
        // intermediate proxies from reaping an idle connection.
        heartbeat = setInterval(() => {
          if (ws && ws.readyState === WebSocket.OPEN) ws.send('ping');
        }, 25000);
      };

      ws.onmessage = (event) => {
        let msg;
        try {
          msg = JSON.parse(event.data);
        } catch (e) {
          console.error('[WebSocket] Message parsing error:', e);
          return;
        }

        switch (msg.type) {
          case 'WATCHLIST_ALERT':
            handlers.onAlert && handlers.onAlert(msg.data);
            break;
          case 'LIVE_DETECTION':
            handlers.onDetection && handlers.onDetection(msg.data);
            break;
          case 'WORKER_STATUS':
            handlers.onWorkerStatus && handlers.onWorkerStatus(msg.data);
            break;
          default:
            break;
        }
      };

      ws.onclose = () => {
        clearInterval(heartbeat);
        if (closedByUs) return;
        setState('disconnected');
        attempt += 1;
        const delay = Math.min(30000, 1000 * Math.pow(2, Math.min(attempt, 5)));
        console.warn(`[WebSocket] Alert stream closed. Reconnecting in ${delay / 1000}s...`);
        setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // onclose always follows, which is where reconnection is handled.
        if (ws) ws.close();
      };
    };

    connect();

    return () => {
      closedByUs = true;
      clearInterval(heartbeat);
      if (ws) ws.close();
    };
  },
};

window.API = API;
