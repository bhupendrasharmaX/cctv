// Centralized API Client & WebSocket Manager
const API = {
  baseUrl: window.location.origin,

  async getCameras() {
    const res = await fetch(`${this.baseUrl}/api/cameras`);
    if (!res.ok) throw new Error('Failed to fetch cameras');
    return await res.json();
  },

  async getCamerasGeoJSON() {
    const res = await fetch(`${this.baseUrl}/api/cameras-geojson`);
    if (!res.ok) throw new Error('Failed to fetch cameras GeoJSON');
    return await res.json();
  },

  async trackVehicle(plate) {
    const clean = encodeURIComponent(plate.trim().toUpperCase());
    const res = await fetch(`${this.baseUrl}/api/track-vehicle/${clean}`);
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Failed to track vehicle');
    }
    return await res.json();
  },

  async getWatchlist() {
    const res = await fetch(`${this.baseUrl}/api/watchlist`);
    if (!res.ok) throw new Error('Failed to fetch watchlist');
    return await res.json();
  },

  async getAlerts() {
    const res = await fetch(`${this.baseUrl}/api/alerts?limit=30`);
    if (!res.ok) throw new Error('Failed to fetch alerts');
    return await res.json();
  },

  async acknowledgeAlert(alertId) {
    const res = await fetch(`${this.baseUrl}/api/alerts/${alertId}/acknowledge`, {
      method: 'POST'
    });
    return await res.json();
  },

  async startCameraAI(cameraId) {
    const res = await fetch(`${this.baseUrl}/api/stream-control/start/${cameraId}`, {
      method: 'POST'
    });
    return await res.json();
  },

  async stopCameraAI(cameraId) {
    const res = await fetch(`${this.baseUrl}/api/stream-control/stop/${cameraId}`, {
      method: 'POST'
    });
    return await res.json();
  },

  connectWebSocket(onAlert, onDetection) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/alerts`;
    let ws = null;

    function connect() {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        console.log('[WebSocket] Connected to CCTV command center alert stream.');
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'WATCHLIST_ALERT' && onAlert) {
            onAlert(msg.data);
          } else if (msg.type === 'LIVE_DETECTION' && onDetection) {
            onDetection(msg.data);
          }
        } catch (e) {
          console.error('[WebSocket] Message parsing error:', e);
        }
      };

      ws.onclose = () => {
        console.warn('[WebSocket] Alert stream closed. Reconnecting in 3s...');
        setTimeout(connect, 3000);
      };

      ws.onerror = (err) => {
        console.error('[WebSocket] Error:', err);
        ws.close();
      };
    }

    connect();
    return () => { if (ws) ws.close(); };
  }
};
