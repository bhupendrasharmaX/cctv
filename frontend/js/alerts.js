// Real-Time Watchlist Alert Manager
class AlertManager {
  constructor(feedContainerId, sirenBannerId) {
    this.feedContainer = document.getElementById(feedContainerId);
    this.sirenBanner = document.getElementById(sirenBannerId);
    this.audioCtx = null;
    this.muted = false;
    this.filter = 'ALL';
    this.alerts = [];
    this.sirenTimer = null;
  }

  // ---------------- Audio ----------------
  initAudio() {
    if (!this.audioCtx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (Ctx) this.audioCtx = new Ctx();
    }
    // Browsers start the context suspended until a user gesture.
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume().catch(() => {});
    }
    return this.audioCtx;
  }

  setMuted(muted) {
    this.muted = muted;
    const btn = document.getElementById('btn-mute-siren');
    if (btn) {
      btn.textContent = muted ? '🔇 Muted' : '🔊 Siren On';
      btn.classList.toggle('btn-on', !muted);
    }
  }

  playPoliceChime(severity = 'CRITICAL') {
    if (this.muted) return;
    try {
      const ctx = this.initAudio();
      if (!ctx) return;

      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      // An unconfirmed near-miss gets a softer, lower cue than a confirmed hit,
      // so an operator can tell them apart without looking away from the map.
      const isReview = String(severity).toUpperCase() === 'REVIEW';

      osc.type = isReview ? 'sine' : 'sawtooth';
      const high = isReview ? 620 : 880;
      const low = isReview ? 500 : 660;
      osc.frequency.setValueAtTime(high, now);
      osc.frequency.linearRampToValueAtTime(low, now + 0.15);
      osc.frequency.linearRampToValueAtTime(high, now + 0.3);

      gain.gain.setValueAtTime(isReview ? 0.08 : 0.15, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.35);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.35);
    } catch (e) {
      // Audio is a convenience; never let it break alert rendering.
    }
  }

  // ---------------- Incoming ----------------
  handleIncomingAlert(alertData, gisMapInstance) {
    this.alerts.unshift(alertData);
    this.playPoliceChime(alertData.severity);
    this.showSiren(alertData);

    if (gisMapInstance && alertData.camera_id) {
      gisMapInstance.highlightAlertCamera(alertData.camera_id, true);
    }

    this.renderFeed();
    this.refreshStats();
  }

  showSiren(alertData) {
    if (!this.sirenBanner) return;
    const esc = Utils.esc.bind(Utils);
    const confirmed = alertData.is_confirmed !== false;

    this.sirenBanner.classList.toggle('siren-review', !confirmed);
    this.sirenBanner.innerHTML = confirmed
      ? `⚠️ CRITICAL WATCHLIST MATCH — <b>${esc(alertData.plate_number)}</b> DETECTED AT
         ${esc(String(alertData.camera_name || alertData.camera_id).toUpperCase())}`
      : `🔎 POSSIBLE MATCH — CAMERA READ <b>${esc(alertData.plate_number)}</b>, ONE CHARACTER FROM WATCHLIST
         <b>${esc(alertData.matched_watchlist_plate)}</b> · VISUAL CONFIRMATION REQUIRED`;
    this.sirenBanner.style.display = 'block';

    clearTimeout(this.sirenTimer);
    this.sirenTimer = setTimeout(() => {
      this.sirenBanner.style.display = 'none';
    }, 9000);
  }

  // ---------------- Feed ----------------
  setAlerts(alerts) {
    this.alerts = alerts || [];
    this.renderFeed();
  }

  setFilter(filter) {
    this.filter = filter;
    document.querySelectorAll('[data-alert-filter]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.alertFilter === filter);
    });
    this.renderFeed();
  }

  visibleAlerts() {
    if (this.filter === 'ALL') return this.alerts;
    if (this.filter === 'REVIEW') {
      return this.alerts.filter((a) => String(a.severity).toUpperCase() === 'REVIEW');
    }
    if (this.filter === 'CONFIRMED') {
      return this.alerts.filter((a) => String(a.severity).toUpperCase() !== 'REVIEW');
    }
    return this.alerts.filter((a) => String(a.status || 'NEW').toUpperCase() === this.filter);
  }

  renderFeed() {
    if (!this.feedContainer) return;
    const visible = this.visibleAlerts();

    if (!visible.length) {
      this.feedContainer.innerHTML = `
        <div class="feed-empty">
          <div class="feed-empty-title">No alerts in this view</div>
          <div class="feed-empty-hint">Watchlist matches appear here the moment a camera reads one.</div>
        </div>
      `;
      return;
    }

    this.feedContainer.innerHTML = '';
    visible.forEach((alert) => this.feedContainer.appendChild(this.buildAlertCard(alert)));
  }

  buildAlertCard(alert) {
    const esc = Utils.esc.bind(Utils);
    const severity = String(alert.severity || 'CRITICAL').toUpperCase();
    const status = String(alert.status || 'NEW').toUpperCase();
    const isReview = severity === 'REVIEW';
    const timestamp = alert.timestamp || alert.created_at;

    const card = document.createElement('div');
    card.className = `alert-card sev-${severity.toLowerCase()} status-${status.toLowerCase()}`;
    card.id = `alert-${alert.alert_id}`;

    const matchedPlate = alert.matched_watchlist_plate || alert.matched_plate;
    // On a near-miss the read plate and the watchlist plate are different facts.
    // Showing only one of them is how an officer ends up stopping the wrong car.
    const plateBlock = isReview && matchedPlate
      ? `<span class="alert-plate">${esc(alert.plate_number)}</span>
         <span class="alert-plate-arrow">≈</span>
         <span class="alert-plate-matched" title="Watchlist entry it resembles">${esc(matchedPlate)}</span>`
      : `<span class="alert-plate">${esc(alert.plate_number)}</span>`;

    const sightings = Number(alert.sighting_count || 1);
    const sightingsBadge = sightings > 1
      ? `<span class="alert-chip" title="Repeat sightings folded into this alert">×${sightings}</span>`
      : '';

    card.innerHTML = `
      <div class="alert-details">
        <h4>
          <span class="status-dot alert"></span>
          ${plateBlock}
          <span class="alert-sev-tag" style="color:${Utils.severityColor(severity)};">${esc(severity)}</span>
          ${sightingsBadge}
          ${status !== 'NEW' ? `<span class="alert-chip chip-muted">${esc(status)}</span>` : ''}
        </h4>
        <div class="alert-meta">
          <b>${esc(alert.camera_name || alert.camera_id)}</b> · ${esc(alert.department || 'Gujarat Police')}
        </div>
        <div class="alert-meta alert-meta-strong">
          ${esc(alert.crime_category || 'Suspect Vehicle')} · FIR ${esc(alert.fir_number || 'not recorded')}
        </div>
        ${isReview ? `<div class="alert-review-note">Unconfirmed single-character difference — verify visually before acting.</div>` : ''}
        <div class="alert-meta alert-time" title="${esc(Utils.formatDateTime(timestamp))}">
          ${esc(Utils.formatTime(timestamp))} IST · ${esc(Utils.formatRelative(timestamp))}
        </div>
      </div>
      <div class="alert-actions">
        <button class="alert-action-btn" data-trace>Trace Route</button>
        <button class="btn-xs" data-ack ${status === 'NEW' ? '' : 'disabled'}>Ack</button>
        <button class="btn-xs" data-resolve ${status === 'RESOLVED' ? 'disabled' : ''}>Resolve</button>
      </div>
    `;

    card.querySelector('[data-trace]').addEventListener('click', () => {
      AlertManager.trackFromAlert(alert.plate_number);
    });
    card.querySelector('[data-ack]').addEventListener('click', (e) => {
      this.updateStatus(alert, 'acknowledge', e.currentTarget);
    });
    card.querySelector('[data-resolve]').addEventListener('click', (e) => {
      this.updateStatus(alert, 'resolve', e.currentTarget);
    });

    if (alert.snapshot_path) {
      const img = document.createElement('img');
      img.className = 'alert-thumb';
      img.src = alert.snapshot_path;
      img.alt = `Snapshot of ${alert.plate_number}`;
      img.addEventListener('click', () => window.open(alert.snapshot_path, '_blank', 'noopener'));
      card.appendChild(img);
    }

    return card;
  }

  async updateStatus(alert, action, button) {
    button.disabled = true;
    try {
      if (action === 'acknowledge') {
        await API.acknowledgeAlert(alert.alert_id);
        alert.status = 'ACKNOWLEDGED';
        Utils.toast(`Alert ${alert.plate_number} acknowledged`, 'success');
      } else {
        await API.resolveAlert(alert.alert_id);
        alert.status = 'RESOLVED';
        Utils.toast(`Alert ${alert.plate_number} resolved`, 'success');
      }
      this.renderFeed();
      this.refreshStats();
    } catch (e) {
      button.disabled = false;
      Utils.toast(e.message, 'error');
    }
  }

  /**
   * Counts come from the server rather than a local tally, so the badge is
   * still right after a page reload or a second operator acknowledging.
   */
  async refreshStats() {
    try {
      const stats = await API.getAlertStats();
      Utils.setText('stat-alerts-count', stats.new);
      Utils.setText('stat-alerts-total', stats.total);
    } catch (e) {
      /* header badge is non-critical */
    }
  }

  static trackFromAlert(plate) {
    const input = document.getElementById('target-plate-input');
    if (!input) return;
    input.value = plate;
    // The panel may be showing the search view; tracing into a hidden tab would
    // look to the operator like nothing happened.
    if (window.Dashboard) window.Dashboard.setTrackerTab('trace');
    document.getElementById('btn-track-vehicle').click();
  }
}

window.AlertManager = AlertManager;
