// GIS Map Foundation (Model 1) & Vehicle Trajectory Visualizer
class GISMap {
  constructor(containerId) {
    this.containerId = containerId;
    this.map = null;
    this.cameraLayer = null;
    this.routeLayer = null;
    this.cameraMarkers = {};
    this.hopMarkers = {};
    this.pulseTimers = {};
  }

  init() {
    // Center initially on Ahmedabad/Gandhinagar corridor, Gujarat
    this.map = L.map(this.containerId, {
      zoomControl: true,
      attributionControl: true,
    }).setView([23.0489, 72.5054], 11);

    // CARTO's dark_all basemap now stamps "API KEY REQUIRED" across every tile,
    // which is not something to hand a jury. Standard OSM tiles need no key;
    // the control-room dark treatment is applied in CSS over the tile pane.
    // OSM's tile policy requires the attribution, so it stays switched on.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors',
    }).addTo(this.map);

    this.cameraLayer = L.layerGroup().addTo(this.map);
    this.routeLayer = L.layerGroup().addTo(this.map);
  }

  setCamerasVisible(visible) {
    if (!this.map || !this.cameraLayer) return;
    if (visible) {
      this.cameraLayer.addTo(this.map);
    } else {
      this.map.removeLayer(this.cameraLayer);
    }
  }

  _cameraIcon(status, label) {
    const offline = String(status || '').toUpperCase() !== 'ONLINE';
    const labelHtml = label
      ? `<div class="map-marker-label"><b>${Utils.esc(label.id)}</b><span>${Utils.esc(label.name)}</span></div>`
      : '';
    return L.divIcon({
      className: 'custom-cam-icon',
      html: `<div class="cam-pin ${offline ? 'is-offline' : ''}"></div>${labelHtml}`,
      iconSize: [11, 11],
      iconAnchor: [5, 5],
    });
  }

  renderCameras(geojsonData) {
    this.cameraLayer.clearLayers();
    this.cameraMarkers = {};

    const esc = Utils.esc.bind(Utils);
    (geojsonData.features || []).forEach((f) => {
      const [lng, lat] = f.geometry.coordinates;
      const props = f.properties;
      const offline = String(props.status || '').toUpperCase() !== 'ONLINE';

      const marker = L.marker([lat, lng], { icon: this._cameraIcon(props.status) }).addTo(this.cameraLayer);
      marker._camProps = props;

      // Popups are built as DOM so the "View Stream" action can be a real
      // listener instead of an inline handler carrying interpolated data.
      const popup = document.createElement('div');
      popup.className = 'map-popup';
      popup.innerHTML = `
        <h4>${esc(props.name)}</h4>
        <p><b>ID:</b> ${esc(props.camera_id)}</p>
        <p><b>Department:</b> ${esc(props.department)}</p>
        <p><b>District:</b> ${esc(props.district)}</p>
        <p><b>Type:</b> ${esc(props.camera_type)} (${esc(props.codec)})</p>
        <p><b>Status:</b> <span style="color:${offline ? '#64748b' : '#10b981'};font-weight:700;">
          ${esc(props.status)}</span></p>
        ${props.location_description ? `<p class="popup-desc">${esc(props.location_description)}</p>` : ''}
      `;

      const btn = document.createElement('button');
      btn.className = 'popup-btn';
      btn.textContent = 'View Stream';
      btn.addEventListener('click', () => {
        if (window.viewer) window.viewer.focusCamera(props.camera_id);
      });
      popup.appendChild(btn);

      marker.bindPopup(popup);
      this.cameraMarkers[props.camera_id] = marker;
    });
  }

  highlightAlertCamera(cameraId, pulse = false) {
    const marker = this.cameraMarkers[cameraId];
    if (!marker) return;
    marker.openPopup();
    this.map.panTo(marker.getLatLng(), { animate: true, duration: 1.0 });

    if (!pulse) return;
    const el = marker.getElement();
    if (!el) return;
    el.classList.add('cam-pin-alert');
    clearTimeout(this.pulseTimers[cameraId]);
    this.pulseTimers[cameraId] = setTimeout(() => el.classList.remove('cam-pin-alert'), 9000);
  }

  clearRoute() {
    this.routeLayer.clearLayers();
    this.hopMarkers = {};
  }

  focusHop(hopIndex) {
    const marker = this.hopMarkers[hopIndex];
    if (!marker) return;
    this.map.panTo(marker.getLatLng(), { animate: true });
    marker.openPopup();
  }

  plotVehicleRoute(routeData) {
    this.clearRoute();
    const hops = (routeData && routeData.timeline) || [];
    if (!hops.length) return;

    const esc = Utils.esc.bind(Utils);
    const latlngs = hops.map((h) => [h.latitude, h.longitude]);

    // Draw the route leg by leg so an implausible transit can be drawn
    // differently from a leg the vehicle could actually have travelled.
    for (let i = 1; i < hops.length; i += 1) {
      const leg = [latlngs[i - 1], latlngs[i]];
      const implausible = hops[i].speed_implausible;

      L.polyline(leg, {
        color: implausible ? '#cf5b52' : '#e0a340',
        weight: 7,
        opacity: implausible ? 0.2 : 0.22,
      }).addTo(this.routeLayer);

      L.polyline(leg, {
        color: implausible ? '#cf5b52' : '#e0a340',
        weight: 2.5,
        opacity: 0.95,
        dashArray: implausible ? '3, 6' : null,
        lineCap: 'round',
      }).addTo(this.routeLayer).bindTooltip(
        implausible
          ? `Leg ${i}: implied speed not achievable — verify`
          : `Leg ${i}: ${hops[i].transit_time_formatted} · ${hops[i].est_speed_kmh} km/h`,
        { direction: 'top', sticky: true },
      );
    }

    hops.forEach((hop, idx) => {
      const isStart = idx === 0;
      const isEnd = idx === hops.length - 1;
      const badgeColor = isStart ? '#4caf6a' : isEnd ? '#cf5b52' : '#e0a340';
      const label = isStart ? 'START' : isEnd ? 'LAST SEEN' : `HOP ${hop.hop_index}`;

      const hopIcon = L.divIcon({
        className: 'route-hop-icon',
        html: `
          <div class="hop-pin ${isStart ? 'hop-start' : ''} ${isEnd ? 'hop-end' : ''}">
            <span class="hop-n">${esc(hop.hop_index)}</span>
            <small>${esc(label)}</small>
          </div>
        `,
        iconAnchor: [8, 9],
      });

      const marker = L.marker([hop.latitude, hop.longitude], { icon: hopIcon }).addTo(this.routeLayer);

      const transitInfo = hop.transit_time_formatted
        ? `<p><b>Transit from previous:</b> ${esc(hop.transit_time_formatted)}
             (${hop.est_speed_kmh === null ? 'instantaneous' : esc(hop.est_speed_kmh) + ' km/h'})
             ${hop.speed_implausible ? '<b style="color:#b91c1c;"> — VERIFY</b>' : ''}</p>`
        : '';

      marker.bindPopup(`
        <div class="map-popup">
          <h4 style="color:${badgeColor};">Checkpoint #${esc(hop.hop_index)}: ${esc(hop.camera_name)}</h4>
          <p><b>Department:</b> ${esc(hop.department)}</p>
          <p><b>First seen:</b> ${esc(Utils.formatDateTime(hop.first_seen))}</p>
          <p><b>Last seen:</b> ${esc(Utils.formatDateTime(hop.last_seen))}</p>
          <p><b>Frames:</b> ${esc(hop.detection_count)}</p>
          ${transitInfo}
          ${hop.snapshot_path ? `<img class="popup-thumb" src="${esc(hop.snapshot_path)}" alt="Snapshot"/>` : ''}
        </div>
      `);

      this.hopMarkers[hop.hop_index] = marker;
    });

    if (latlngs.length === 1) {
      this.map.setView(latlngs[0], 14, { animate: true });
    } else {
      this.map.fitBounds(L.latLngBounds(latlngs), { padding: [60, 60], animate: true });
    }
  }
}

window.GISMap = GISMap;
