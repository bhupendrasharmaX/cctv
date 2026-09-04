// GIS Map Foundation (Model 1) & Vehicle Trajectory Visualizer
class GISMap {
  constructor(containerId) {
    this.containerId = containerId;
    this.map = null;
    this.cameraLayer = null;
    this.routeLayer = null;
    this.cameraMarkers = {};
  }

  init() {
    // Center initially on Ahmedabad/Gandhinagar corridor, Gujarat
    this.map = L.map(this.containerId, {
      zoomControl: true,
      attributionControl: false
    }).setView([23.0489, 72.5054], 11);

    // High-contrast Dark Matter CartoDB tiles
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19,
      subdomains: 'abcd',
    }).addTo(this.map);

    this.cameraLayer = L.layerGroup().addTo(this.map);
    this.routeLayer = L.layerGroup().addTo(this.map);
  }

  renderCameras(geojsonData) {
    this.cameraLayer.clearLayers();
    this.cameraMarkers = {};

    const features = geojsonData.features || [];
    features.forEach(f => {
      const [lng, lat] = f.geometry.coordinates;
      const props = f.properties;

      // Custom SVG Camera Pin
      const icon = L.divIcon({
        className: 'custom-cam-icon',
        html: `
          <div style="
            background: rgba(6, 182, 212, 0.9);
            border: 2px solid #ffffff;
            border-radius: 50%;
            width: 22px;
            height: 22px;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 0 10px rgba(6, 182, 212, 0.8);
            cursor: pointer;
          ">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2.5">
              <path d="M23 7l-7 5 7 5V7z"/>
              <rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
            </svg>
          </div>
        `,
        iconSize: [22, 22],
        iconAnchor: [11, 11]
      });

      const marker = L.marker([lat, lng], { icon }).addTo(this.cameraLayer);

      const popupContent = `
        <div style="font-family: sans-serif; color: #0f172a; min-width: 200px;">
          <h4 style="margin:0 0 4px; font-size:13px; color:#0284c7;">${props.name}</h4>
          <p style="margin:0 0 2px; font-size:11px;"><b>ID:</b> ${props.camera_id}</p>
          <p style="margin:0 0 2px; font-size:11px;"><b>Department:</b> ${props.department}</p>
          <p style="margin:0 0 2px; font-size:11px;"><b>Type:</b> ${props.camera_type} (${props.codec})</p>
          <p style="margin:0 0 6px; font-size:11px;"><b>Status:</b> <span style="color:green;font-weight:bold;">${props.status}</span></p>
          <button style="background:#0284c7; color:white; border:none; border-radius:4px; padding:3px 8px; font-size:10px; cursor:pointer;"
            onclick="UnifiedViewer.focusCamera('${props.camera_id}')">View Stream</button>
        </div>
      `;

      marker.bindPopup(popupContent);
      this.cameraMarkers[props.camera_id] = marker;
    });
  }

  highlightAlertCamera(cameraId) {
    const marker = this.cameraMarkers[cameraId];
    if (marker) {
      marker.openPopup();
      this.map.panTo(marker.getLatLng(), { animate: true, duration: 1.0 });
    }
  }

  plotVehicleRoute(routeData) {
    this.routeLayer.clearLayers();

    if (!routeData || !routeData.timeline || routeData.timeline.length === 0) {
      return;
    }

    const hops = routeData.timeline;
    const latlngs = hops.map(h => [h.latitude, h.longitude]);

    // 1. Draw glowing polyline connecting the camera hops
    const polyline = L.polyline(latlngs, {
      color: '#38bdf8',
      weight: 4,
      opacity: 0.85,
      dashArray: '8, 8',
      lineCap: 'round'
    }).addTo(this.routeLayer);

    // Glow underlay
    L.polyline(latlngs, {
      color: '#06b6d4',
      weight: 8,
      opacity: 0.35
    }).addTo(this.routeLayer);

    // 2. Add numbered hop markers (Hop 1, Hop 2, Hop 3...)
    hops.forEach((hop, idx) => {
      const isStart = idx === 0;
      const isEnd = idx === hops.length - 1;
      const badgeColor = isStart ? '#10b981' : isEnd ? '#ef4444' : '#3b82f6';
      const label = isStart ? 'START' : isEnd ? 'LAST SEEN' : `HOP ${hop.hop_index}`;

      const hopIcon = L.divIcon({
        className: 'route-hop-icon',
        html: `
          <div style="
            background: ${badgeColor};
            border: 2px solid #ffffff;
            border-radius: 12px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 800;
            color: white;
            box-shadow: 0 0 12px ${badgeColor};
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 4px;
          ">
            <span>#${hop.hop_index}</span>
            <small style="font-size:9px;">${label}</small>
          </div>
        `,
        iconAnchor: [30, 12]
      });

      const hopMarker = L.marker([hop.latitude, hop.longitude], { icon: hopIcon }).addTo(this.routeLayer);

      const transitInfo = hop.transit_time_formatted
        ? `<p style="margin:2px 0; font-size:11px;"><b>Transit from Prev:</b> ${hop.transit_time_formatted} (${hop.est_speed_kmh} km/h)</p>`
        : '';

      const hopPopup = `
        <div style="font-family: sans-serif; color: #0f172a; min-width: 220px;">
          <h4 style="margin:0 0 4px; font-size:13px; color:${badgeColor};">Checkpoint #${hop.hop_index}: ${hop.camera_name}</h4>
          <p style="margin:2px 0; font-size:11px;"><b>Department:</b> ${hop.department}</p>
          <p style="margin:2px 0; font-size:11px;"><b>First Seen:</b> ${new Date(hop.first_seen).toLocaleTimeString()}</p>
          <p style="margin:2px 0; font-size:11px;"><b>Last Seen:</b> ${new Date(hop.last_seen).toLocaleTimeString()}</p>
          ${transitInfo}
          ${hop.snapshot_path ? `<img src="${hop.snapshot_path}" style="width:100%; border-radius:4px; margin-top:6px;"/>` : ''}
        </div>
      `;
      hopMarker.bindPopup(hopPopup);
    });

    // 3. Smoothly zoom and fit map bounds to the route
    if (latlngs.length > 0) {
      this.map.fitBounds(polyline.getBounds(), { padding: [60, 60], animate: true });
    }
  }
}
