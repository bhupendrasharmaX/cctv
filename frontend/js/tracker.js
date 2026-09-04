// Vehicle Cross-Camera Trajectory & Investigation Docket Manager
class VehicleTracker {
  constructor(timelineContainerId, gisMapInstance) {
    this.container = document.getElementById(timelineContainerId);
    this.gisMap = gisMapInstance;
    this.currentTrackData = null;
  }

  async searchAndTrace(plateNumber) {
    if (!plateNumber || plateNumber.trim().length < 3) {
      alert('Please enter a valid vehicle registration plate.');
      return;
    }

    this.container.innerHTML = `
      <div style="padding:20px; text-align:center; color:#38bdf8;">
        Searching across 80,000 camera index for <b>${plateNumber.toUpperCase()}</b>...
      </div>
    `;

    try {
      const data = await API.trackVehicle(plateNumber);
      this.currentTrackData = data;

      if (data.total_hops === 0) {
        this.container.innerHTML = `
          <div style="padding:20px; text-align:center; color:#94a3b8;">
            No CCTV sightings found for vehicle <b>${data.plate_number}</b>.<br>
            <small>Verify plate number or start AI analytics on active camera feeds.</small>
          </div>
        `;
        return;
      }

      // Render chronological timeline
      this.renderTimeline(data);

      // Plot route on GIS map
      if (this.gisMap) {
        this.gisMap.plotVehicleRoute(data);
      }

      // Enable export docket button
      const exportBtn = document.getElementById('btn-export-docket');
      if (exportBtn) exportBtn.style.display = 'inline-block';

    } catch (e) {
      this.container.innerHTML = `
        <div style="padding:20px; text-align:center; color:#ef4444;">
          Error querying vehicle history: ${e.message}
        </div>
      `;
    }
  }

  renderTimeline(trackData) {
    this.container.innerHTML = '';

    const header = document.createElement('div');
    header.style.cssText = 'padding: 4px 8px; font-size:11px; color:#38bdf8; display:flex; justify-content:space-between;';
    header.innerHTML = `
      <span>Target: <b>${trackData.plate_number}</b> (${trackData.total_hops} Checkpoints)</span>
      <span>Total Distance: <b>${trackData.total_distance_km} km</b></span>
    `;
    this.container.appendChild(header);

    trackData.timeline.forEach((hop, idx) => {
      const card = document.createElement('div');
      card.className = 'timeline-card';

      const isStart = idx === 0;
      const isEnd = idx === trackData.timeline.length - 1;
      const borderCol = isStart ? '#10b981' : isEnd ? '#ef4444' : '#38bdf8';
      card.style.borderLeftColor = borderCol;

      const deltaText = hop.transit_time_formatted
        ? `<div class="timeline-delta">⏱ ${hop.transit_time_formatted} • ${hop.distance_from_prev_km} km (${hop.est_speed_kmh} km/h)</div>`
        : `<div class="timeline-delta" style="color:#10b981;">📍 Route Origin</div>`;

      const snapshotHtml = hop.snapshot_path
        ? `<img src="${hop.snapshot_path}" class="timeline-thumb" alt="Crop" onclick="window.open('${hop.snapshot_path}')"/>`
        : `<div style="width:48px; height:32px; background:#1e293b; border-radius:3px; display:flex; align-items:center; justify-content:center; font-size:9px; color:#64748b;">NO CROP</div>`;

      card.innerHTML = `
        <div class="hop-badge" style="background:${borderCol};">
          ${hop.hop_index}
        </div>
        <div class="timeline-info">
          <div class="timeline-camera-name">${hop.camera_name}</div>
          <div class="timeline-dept">${hop.department} (${hop.district})</div>
          ${deltaText}
        </div>
        <div class="timeline-metrics">
          <div class="timeline-time">${new Date(hop.first_seen).toLocaleTimeString()}</div>
          <div style="font-size:9px; color:#94a3b8;">${hop.detection_count} frames</div>
        </div>
        ${snapshotHtml}
      `;

      this.container.appendChild(card);
    });
  }

  openDocketModal() {
    if (!this.currentTrackData) return;
    const modal = document.getElementById('docket-modal');
    const body = document.getElementById('docket-modal-body');
    if (!modal || !body) return;

    const t = this.currentTrackData;
    let hopsTable = '';
    t.timeline.forEach(h => {
      hopsTable += `
        <tr style="border-bottom: 1px solid #334155;">
          <td style="padding:6px;">#${h.hop_index}</td>
          <td style="padding:6px;"><b>${h.camera_name}</b><br><small>${h.department}</small></td>
          <td style="padding:6px;">${new Date(h.first_seen).toLocaleString()}</td>
          <td style="padding:6px;">${h.transit_time_formatted || 'Origin Point'}</td>
          <td style="padding:6px;">${h.est_speed_kmh ? h.est_speed_kmh + ' km/h' : '-'}</td>
        </tr>
      `;
    });

    body.innerHTML = `
      <div style="font-family: monospace; border-bottom:2px solid #0284c7; padding-bottom:12px; margin-bottom:16px;">
        <h2 style="color:#38bdf8; margin-bottom:4px;">GUJARAT STATE POLICE — EVIDENTIARY SURVEILLANCE REPORT</h2>
        <p style="color:#94a3b8; font-size:11px;">Generated by Gujarat Unified CCTV Command & Video Analytics System (Model 2/Model 1)</p>
        <p style="color:#94a3b8; font-size:11px;">Date & Time: ${new Date().toLocaleString()} | Target: <b>${t.plate_number}</b></p>
      </div>

      <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:12px; margin-bottom:16px;">
        <div style="background:#0f172a; padding:10px; border-radius:6px; border:1px solid #334155;">
          <small style="color:#94a3b8;">Total Checkpoints</small>
          <div style="font-size:18px; font-weight:bold; color:#f8fafc;">${t.total_hops}</div>
        </div>
        <div style="background:#0f172a; padding:10px; border-radius:6px; border:1px solid #334155;">
          <small style="color:#94a3b8;">Total Tracked Distance</small>
          <div style="font-size:18px; font-weight:bold; color:#f8fafc;">${t.total_distance_km} km</div>
        </div>
        <div style="background:#0f172a; padding:10px; border-radius:6px; border:1px solid #334155;">
          <small style="color:#94a3b8;">First Recorded Sighting</small>
          <div style="font-size:13px; font-weight:bold; color:#10b981;">${new Date(t.first_observed).toLocaleTimeString()}</div>
        </div>
      </div>

      <h4 style="margin-bottom:8px; color:#38bdf8;">Chronological Movement Ledger:</h4>
      <table style="width:100%; border-collapse:collapse; font-size:12px; text-align:left;">
        <thead>
          <tr style="background:#1e293b; color:#94a3b8;">
            <th style="padding:6px;">Hop</th>
            <th style="padding:6px;">Location / Department</th>
            <th style="padding:6px;">Timestamp</th>
            <th style="padding:6px;">Transit Delta</th>
            <th style="padding:6px;">Est. Speed</th>
          </tr>
        </thead>
        <tbody>
          ${hopsTable}
        </tbody>
      </table>
    `;

    modal.style.display = 'flex';
  }
}
