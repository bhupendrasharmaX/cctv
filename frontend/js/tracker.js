// Vehicle Cross-Camera Trajectory & Investigation Docket Manager
class VehicleTracker {
  constructor(timelineContainerId, gisMapInstance) {
    this.container = document.getElementById(timelineContainerId);
    this.gisMap = gisMapInstance;
    this.currentTrackData = null;
    this.lastQueriedAt = null;
  }

  setState(html) {
    this.container.innerHTML = `<div class="tracker-state">${html}</div>`;
  }

  /** Reads the optional incident window from the trace form. */
  readWindow() {
    const value = (id) => {
      const el = document.getElementById(id);
      return el ? el.value.trim() : '';
    };
    return {
      from: Utils.istInputToUtcIso(value('trace-from')),
      to: Utils.istInputToUtcIso(value('trace-to')),
    };
  }

  async searchAndTrace(plateNumber, windowOverride) {
    const normalized = Utils.normalizePlate(plateNumber);
    if (normalized.length < 3) {
      Utils.toast('Enter a valid vehicle registration number.', 'error');
      return;
    }

    const win = windowOverride || this.readWindow();
    if (win.from && win.to && win.from > win.to) {
      Utils.toast('The "from" time is later than the "to" time.', 'error');
      return;
    }

    const exportBtn = document.getElementById('btn-export-docket');
    if (exportBtn) exportBtn.hidden = true;

    const scope = win.from || win.to ? ' within the selected window' : '';
    this.setState(`
      <div class="spinner"></div>
      <div>Reconstructing cross-camera trajectory for <b>${Utils.esc(normalized)}</b>${scope}…</div>
    `);

    try {
      const data = await API.trackVehicle(normalized, win);
      this.currentTrackData = data;
      this.lastQueriedAt = new Date();

      if (!data.total_hops) {
        const bounded = data.window && data.window.bounded;
        // Distinguish "never seen" from "not seen in this window" -- they lead
        // an investigation in opposite directions.
        this.setState(`
          <div class="state-icon">&mdash;</div>
          <div>No CCTV sightings for <b>${Utils.esc(data.plate_number)}</b>${bounded ? ' in this window' : ''}.</div>
          <small>${bounded
            ? 'The vehicle may still have been recorded outside it — try “Any time”.'
            : 'Confirm the registration, or start AI analytics on the relevant feeds and retry.'}</small>
        `);
        if (this.gisMap) this.gisMap.clearRoute();
        return;
      }

      this.renderTimeline(data);
      if (this.gisMap) this.gisMap.plotVehicleRoute(data);
      if (exportBtn) exportBtn.hidden = false;

      if (data.implausible_legs) {
        Utils.toast(
          `${data.implausible_legs} leg(s) imply impossible speeds — possible plate misread or cloned plate.`,
          'error',
          7000,
        );
      }
    } catch (e) {
      this.setState(`
        <div class="state-icon state-error">!</div>
        <div>Could not query vehicle history.</div>
        <small>${Utils.esc(e.message)}</small>
      `);
    }
  }

  renderTimeline(trackData) {
    const esc = Utils.esc.bind(Utils);
    this.container.innerHTML = '';

    const header = document.createElement('div');
    header.className = 'result-bar';
    header.innerHTML = `
      <span>Target <b>${esc(trackData.plate_number)}</b> · ${trackData.total_hops} checkpoints
        · ${trackData.total_detections} frames</span>
      <span>${esc(trackData.total_distance_km)} km tracked</span>
    `;
    this.container.appendChild(header);

    if (trackData.implausible_legs) {
      const warn = document.createElement('div');
      warn.className = 'notice';
      warn.textContent = `${trackData.implausible_legs} leg(s) below need manual verification — the implied speed is not physically achievable.`;
      this.container.appendChild(warn);
    }

    trackData.timeline.forEach((hop, idx) => {
      this.container.appendChild(this.buildHopCard(hop, idx, trackData.timeline.length));
    });
  }

  buildHopCard(hop, idx, total) {
    const esc = Utils.esc.bind(Utils);
    const isStart = idx === 0;
    const isEnd = idx === total - 1;
    const borderCol = isStart ? 'var(--ok)' : isEnd ? 'var(--danger)' : 'var(--accent)';

    const card = document.createElement('div');
    card.className = 'timeline-card';
    if (hop.speed_implausible) card.classList.add('is-implausible');
    card.style.borderLeftColor = borderCol;

    let deltaText;
    if (hop.transit_time_formatted) {
      const speed = hop.est_speed_kmh === null ? 'instantaneous' : `${esc(hop.est_speed_kmh)} km/h`;
      deltaText = `<div class="timeline-delta ${hop.speed_implausible ? 'delta-warn' : ''}">
          ${esc(hop.transit_time_formatted)} · ${esc(hop.distance_from_prev_km)} km · ${speed}
          ${hop.speed_implausible ? '<b class="implausible-tag">IMPLAUSIBLE</b>' : ''}
        </div>`;
    } else {
      deltaText = '<div class="timeline-delta delta-origin">Route origin</div>';
    }

    const dwell = hop.dwell_seconds
      ? ` · dwell ${esc(Utils.formatDuration(hop.dwell_seconds))}`
      : '';

    card.innerHTML = `
      <div class="hop-badge" style="background:${borderCol};">${esc(hop.hop_index)}</div>
      <div class="timeline-info">
        <div class="timeline-camera-name">${esc(hop.camera_name)}</div>
        <div class="timeline-dept">${esc(hop.department)} · ${esc(hop.district)}</div>
        ${deltaText}
      </div>
      <div class="timeline-metrics">
        <div class="timeline-time" title="${esc(Utils.formatDateTime(hop.first_seen))}">
          ${esc(Utils.formatTime(hop.first_seen))}
        </div>
        <div class="timeline-frames">${esc(hop.detection_count)} frames${dwell}</div>
      </div>
    `;

    const thumbWrap = document.createElement('div');
    if (hop.snapshot_path) {
      const img = document.createElement('img');
      img.className = 'timeline-thumb';
      img.src = hop.snapshot_path;
      img.alt = `Snapshot at ${hop.camera_name}`;
      img.addEventListener('click', () => window.open(hop.snapshot_path, '_blank', 'noopener'));
      thumbWrap.appendChild(img);
    } else {
      thumbWrap.className = 'timeline-nothumb';
      thumbWrap.textContent = 'NO CROP';
    }
    card.appendChild(thumbWrap);

    card.addEventListener('click', () => {
      if (this.gisMap) this.gisMap.focusHop(hop.hop_index);
    });

    return card;
  }

  openDocketModal() {
    if (!this.currentTrackData) return;
    const modal = document.getElementById('docket-modal');
    const body = document.getElementById('docket-modal-body');
    if (!modal || !body) return;

    const esc = Utils.esc.bind(Utils);
    const t = this.currentTrackData;

    const rows = t.timeline.map((h) => `
      <tr>
        <td>#${esc(h.hop_index)}</td>
        <td><b>${esc(h.camera_name)}</b><br><small>${esc(h.department)}</small></td>
        <td>${esc(Utils.formatDateTime(h.first_seen))}</td>
        <td>${esc(h.transit_time_formatted || 'Origin point')}</td>
        <td>${h.est_speed_kmh === null || h.est_speed_kmh === undefined ? '—' : esc(h.est_speed_kmh) + ' km/h'}
            ${h.speed_implausible ? '<b class="implausible-tag">VERIFY</b>' : ''}</td>
        <td>${esc(h.detection_count)}</td>
      </tr>
    `).join('');

    const caveat = t.implausible_legs
      ? `<div class="docket-caveat">
           <b>Verification required:</b> ${esc(t.implausible_legs)} transit leg(s) in this record imply speeds
           that are not physically achievable between the stated locations. Treat those legs as an
           unverified automated reading — a plate misread or a cloned plate produces exactly this pattern.
         </div>`
      : '';

    body.innerHTML = `
      <div class="docket-head">
        <h2>GUJARAT STATE POLICE — EVIDENTIARY SURVEILLANCE REPORT</h2>
        <p>Generated by the Unified CCTV Command &amp; Video Analytics System (Model 1 + Model 2)</p>
        <p>Generated ${esc(Utils.formatDateTime(this.lastQueriedAt))} · Target
           <b>${esc(t.plate_number)}</b></p>
        <p>${t.window && t.window.bounded
          ? `Scope: ${esc(Utils.formatDateTime(t.window.from) || 'any earlier time')} — ${esc(Utils.formatDateTime(t.window.to) || 'now')}`
          : 'Scope: complete recorded history (no time window applied)'}</p>
      </div>

      ${caveat}

      <div class="docket-stats">
        <div class="docket-stat">
          <small>Checkpoints</small>
          <div>${esc(t.total_hops)}</div>
        </div>
        <div class="docket-stat">
          <small>Tracked distance</small>
          <div>${esc(t.total_distance_km)} km</div>
        </div>
        <div class="docket-stat">
          <small>First sighting</small>
          <div class="docket-stat-sm">${esc(Utils.formatDateTime(t.first_observed))}</div>
        </div>
        <div class="docket-stat">
          <small>Last sighting</small>
          <div class="docket-stat-sm">${esc(Utils.formatDateTime(t.last_observed))}</div>
        </div>
      </div>

      <h4 class="docket-section">Chronological movement ledger</h4>
      <table class="docket-table">
        <thead>
          <tr>
            <th>Hop</th><th>Location / Department</th><th>Timestamp (IST)</th>
            <th>Transit delta</th><th>Est. speed</th><th>Frames</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>

      <p class="docket-footnote">
        All timestamps are rendered in India Standard Time from UTC records. Estimated speeds are derived
        from straight-line distance between camera positions and are indicative, not measured.
      </p>
    `;

    modal.style.display = 'flex';
  }
}

window.VehicleTracker = VehicleTracker;
