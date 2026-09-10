// Watchlist alert queue.
//
// A queue, not a card feed: an operator triages these in order and needs
// time, plate, camera, category and status on one scannable line.
class AlertManager {
  constructor(bodyId, sirenBannerId) {
    this.body = document.getElementById(bodyId);
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
      btn.textContent = muted ? 'Siren off' : 'Siren on';
      btn.classList.toggle('btn-on', !muted);
    }
  }

  playChime(severity = 'CRITICAL') {
    if (this.muted) return;
    try {
      const ctx = this.initAudio();
      if (!ctx) return;

      const now = ctx.currentTime;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      // An unconfirmed near-miss gets a softer, lower cue than a confirmed
      // hit, so the two are distinguishable without looking away from the map.
      const isReview = String(severity).toUpperCase() === 'REVIEW';

      osc.type = isReview ? 'sine' : 'square';
      const high = isReview ? 620 : 880;
      const low = isReview ? 500 : 660;
      osc.frequency.setValueAtTime(high, now);
      osc.frequency.linearRampToValueAtTime(low, now + 0.15);
      osc.frequency.linearRampToValueAtTime(high, now + 0.3);

      gain.gain.setValueAtTime(isReview ? 0.06 : 0.12, now);
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
    this.playChime(alertData.severity);
    this.showSiren(alertData);

    if (gisMapInstance && alertData.camera_id) {
      gisMapInstance.highlightAlertCamera(alertData.camera_id, true);
    }

    this.render();
    this.refreshStats();
  }

  showSiren(alertData) {
    if (!this.sirenBanner) return;
    const esc = Utils.esc.bind(Utils);
    const confirmed = alertData.is_confirmed !== false;

    this.sirenBanner.classList.toggle('siren-review', !confirmed);
    this.sirenBanner.innerHTML = confirmed
      ? `WATCHLIST MATCH &mdash; <b>${esc(alertData.plate_number)}</b> at
         ${esc(alertData.camera_name || alertData.camera_id)} &middot;
         ${esc(alertData.crime_category || 'suspect vehicle')}`
      : `POSSIBLE MATCH &mdash; camera read <b>${esc(alertData.plate_number)}</b>, one character from watchlist
         <b>${esc(alertData.matched_watchlist_plate)}</b> &middot; visual confirmation required`;
    this.sirenBanner.style.display = 'block';

    clearTimeout(this.sirenTimer);
    this.sirenTimer = setTimeout(() => {
      this.sirenBanner.style.display = 'none';
    }, 9000);
  }

  // ---------------- Queue ----------------
  setAlerts(alerts) {
    this.alerts = alerts || [];
    this.render();
  }

  setFilter(filter) {
    this.filter = filter;
    document.querySelectorAll('[data-alert-filter]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.alertFilter === filter);
    });
    this.render();
  }

  visibleAlerts() {
    if (this.filter === 'ALL') return this.alerts;
    if (this.filter === 'REVIEW') {
      return this.alerts.filter((a) => String(a.severity).toUpperCase() === 'REVIEW');
    }
    return this.alerts.filter((a) => String(a.status || 'NEW').toUpperCase() === this.filter);
  }

  render() {
    const visible = this.visibleAlerts();

    if (!visible.length) {
      this.body.innerHTML = `
        <div class="table-empty">
          <div class="table-empty-title">No alerts in this view</div>
          <div>Watchlist matches appear here the moment a camera reads one.</div>
        </div>
      `;
      return;
    }

    const table = document.createElement('table');
    table.className = 'data-table';
    table.innerHTML = `
      <thead>
        <tr>
          <th>Time</th><th>Number Plate</th><th>Camera</th>
          <th>Alert Type</th><th>Status</th><th></th>
        </tr>
      </thead>
    `;

    const tbody = document.createElement('tbody');
    visible.forEach((alert) => tbody.appendChild(this.buildRow(alert)));
    table.appendChild(tbody);

    this.body.innerHTML = '';
    this.body.appendChild(table);
  }

  buildRow(alert) {
    const esc = Utils.esc.bind(Utils);
    const severity = String(alert.severity || 'CRITICAL').toUpperCase();
    const status = String(alert.status || 'NEW').toUpperCase();
    const isReview = severity === 'REVIEW';
    const timestamp = alert.timestamp || alert.created_at;
    const matchedPlate = alert.matched_watchlist_plate || alert.matched_plate;

    const tr = document.createElement('tr');
    tr.id = `alert-${alert.alert_id}`;
    if (status === 'NEW') tr.classList.add('row-new');

    // On a near-miss the read plate and the watchlist plate are different
    // facts. Showing only one is how an officer stops the wrong car.
    const plateCell = isReview && matchedPlate
      ? `<span class="alert-plate-pair">
           <span>${esc(alert.plate_number)}</span>
           <span class="alert-plate-arrow">&asymp;</span>
           <span class="alert-plate-matched" title="Watchlist entry it resembles">${esc(matchedPlate)}</span>
         </span>
         <span class="alert-note">Unconfirmed &mdash; verify visually before acting.</span>`
      : esc(alert.plate_number);

    const sightings = Number(alert.sighting_count || 1);
    const statusDot = status === 'NEW' ? 'dot-warn' : status === 'RESOLVED' ? 'dot-ok' : 'dot-idle';

    tr.innerHTML = `
      <td class="col-time">${esc(Utils.formatTime(timestamp))}</td>
      <td class="col-plate">${plateCell}${sightings > 1
        ? `<span class="sighting-chip" title="Repeat sightings folded in">&times;${sightings}</span>` : ''}</td>
      <td>${esc(alert.camera_name || alert.camera_id)}
        <span class="col-sub">${esc(alert.department || '')}</span></td>
      <td>${esc(alert.crime_category || 'Suspect vehicle')}
        <span class="col-sub">FIR ${esc(alert.fir_number || 'not recorded')}</span></td>
      <td>
        <span class="status-cell"><span class="dot ${statusDot}"></span>${esc(this.statusLabel(status, isReview))}</span>
      </td>
    `;

    const actions = document.createElement('td');
    actions.className = 'col-actions';

    const trace = document.createElement('button');
    trace.className = 'btn';
    trace.textContent = 'Trace';
    trace.addEventListener('click', (e) => {
      e.stopPropagation();
      AlertManager.trackFromAlert(alert.plate_number);
    });
    actions.appendChild(trace);

    if (status !== 'RESOLVED') {
      const next = document.createElement('button');
      next.className = 'btn';
      next.textContent = status === 'NEW' ? 'Ack' : 'Resolve';
      next.addEventListener('click', (e) => {
        e.stopPropagation();
        this.updateStatus(alert, status === 'NEW' ? 'acknowledge' : 'resolve', next);
      });
      actions.appendChild(next);
    }

    tr.appendChild(actions);

    tr.addEventListener('click', () => {
      if (window.gisMap) window.gisMap.highlightAlertCamera(alert.camera_id);
    });

    return tr;
  }

  statusLabel(status, isReview) {
    if (status === 'NEW') return isReview ? 'Review' : 'New';
    if (status === 'ACKNOWLEDGED') return 'Acknowledged';
    return 'Resolved';
  }

  async updateStatus(alert, action, button) {
    button.disabled = true;
    try {
      if (action === 'acknowledge') {
        await API.acknowledgeAlert(alert.alert_id);
        alert.status = 'ACKNOWLEDGED';
        Utils.toast(`${alert.plate_number} acknowledged`, 'success');
      } else {
        await API.resolveAlert(alert.alert_id);
        alert.status = 'RESOLVED';
        Utils.toast(`${alert.plate_number} resolved`, 'success');
      }
      this.render();
      this.refreshStats();
    } catch (e) {
      button.disabled = false;
      Utils.toast(e.message, 'error');
    }
  }

  /**
   * Counts come from the server rather than a local tally, so the readout is
   * still right after a reload or a second operator acknowledging.
   */
  async refreshStats() {
    try {
      const stats = await API.getAlertStats();
      Utils.setText('stat-alerts-count', stats.new);
    } catch (e) {
      /* header readout is non-critical */
    }
  }

  static trackFromAlert(plate) {
    const input = document.getElementById('target-plate-input');
    if (!input) return;
    input.value = plate;
    if (window.Dashboard) {
      window.Dashboard.setView('search');
      window.Dashboard.setTrackerTab('trace');
    }
    document.getElementById('btn-track-vehicle').click();
  }
}

window.AlertManager = AlertManager;
