// Real-Time Watchlist Alert Manager
class AlertManager {
  constructor(feedContainerId, sirenBannerId) {
    this.feedContainer = document.getElementById(feedContainerId);
    this.sirenBanner = document.getElementById(sirenBannerId);
    this.audioCtx = null;
    this.unreadAlertsCount = 0;
  }

  initAudio() {
    if (!this.audioCtx) {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        this.audioCtx = new AudioContext();
      }
    }
  }

  playPoliceChime() {
    try {
      this.initAudio();
      if (!this.audioCtx) return;

      const now = this.audioCtx.currentTime;
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();

      osc.type = 'sawtooth';
      // Warble pitch between 880Hz and 660Hz (police siren frequencies)
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.linearRampToValueAtTime(660, now + 0.15);
      osc.frequency.linearRampToValueAtTime(880, now + 0.3);

      gain.gain.setValueAtTime(0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.35);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);

      osc.start(now);
      osc.stop(now + 0.35);
    } catch (e) {
      // Audio context might be restricted before first user interaction
    }
  }

  handleIncomingAlert(alertData, gisMapInstance) {
    this.unreadAlertsCount++;
    const countBadge = document.getElementById('stat-alerts-count');
    if (countBadge) {
      countBadge.textContent = this.unreadAlertsCount;
    }

    // Play siren sound
    this.playPoliceChime();

    // Trigger siren top banner
    if (this.sirenBanner) {
      this.sirenBanner.style.display = 'block';
      this.sirenBanner.innerHTML = `⚠️ CRITICAL WATCHLIST MATCH: [${alertData.plate_number}] DETECTED AT ${alertData.camera_name.toUpperCase()}`;
      setTimeout(() => {
        if (this.sirenBanner) this.sirenBanner.style.display = 'none';
      }, 7000);
    }

    // Highlight camera on GIS map
    if (gisMapInstance && alertData.camera_id) {
      gisMapInstance.highlightAlertCamera(alertData.camera_id);
    }

    // Prepend alert card to feed
    this.renderAlertCard(alertData, true);
  }

  renderAlertCard(alert, isPrepend = false) {
    const card = document.createElement('div');
    card.className = 'alert-card';
    card.id = `alert-${alert.alert_id}`;

    const timeFormatted = new Date(alert.timestamp || alert.created_at).toLocaleTimeString();

    card.innerHTML = `
      <div class="alert-details">
        <h4>
          <span class="status-dot alert"></span>
          <span class="alert-plate">${alert.plate_number}</span>
          <span style="font-size:10px; color:#f87171;">${alert.severity || 'CRITICAL'}</span>
        </h4>
        <div class="alert-meta">
          <b>${alert.camera_name || alert.camera_id}</b> (${alert.department || 'Gujarat Police'})
        </div>
        <div class="alert-meta" style="color:#e2e8f0; margin-top:2px;">
          Crime: <b>${alert.crime_category || 'Suspect Vehicle'}</b> | FIR: ${alert.fir_number || 'Under Surveillance'}
        </div>
        <div class="alert-meta" style="font-size:10px; color:#94a3b8;">
          Timestamp: ${timeFormatted}
        </div>
      </div>
      <div style="display:flex; flex-direction:column; gap:4px; align-items:flex-end;">
        <button class="alert-action-btn" onclick="AlertManager.trackFromAlert('${alert.plate_number}')">
          Trace Route
        </button>
        <button class="btn-xs" onclick="AlertManager.ackAlert(${alert.alert_id})">
          Ack
        </button>
      </div>
    `;

    if (isPrepend && this.feedContainer.firstChild) {
      this.feedContainer.insertBefore(card, this.feedContainer.firstChild);
    } else {
      this.feedContainer.appendChild(card);
    }
  }

  static async ackAlert(alertId) {
    try {
      await API.acknowledgeAlert(alertId);
      const card = document.getElementById(`alert-${alertId}`);
      if (card) {
        card.style.opacity = '0.5';
        card.style.borderColor = '#64748b';
      }
    } catch (e) {
      console.error(e);
    }
  }

  static trackFromAlert(plate) {
    const input = document.getElementById('target-plate-input');
    if (input) {
      input.value = plate;
      document.getElementById('btn-track-vehicle').click();
    }
  }
}
