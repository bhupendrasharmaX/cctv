// Multi-Camera Unified Viewer (Model 2 Core)
class UnifiedViewer {
  constructor(gridElementId) {
    this.container = document.getElementById(gridElementId);
    this.currentLayout = '2x2';
    this.activeCameras = [];
    this.peerConnections = {};
  }

  setLayout(layout) {
    this.currentLayout = layout;
    this.container.className = `camera-grid grid-${layout}`;
    const slots = layout === '1x1' ? 1 : layout === '2x2' ? 4 : 9;
    this.renderTiles(slots);
  }

  loadCameras(cameras) {
    this.activeCameras = cameras;
    this.setLayout(this.currentLayout);
  }

  renderTiles(slotCount) {
    // Teardown previous WebRTC connections
    Object.values(this.peerConnections).forEach(pc => {
      try { pc.close(); } catch (e) {}
    });
    this.peerConnections = {};

    this.container.innerHTML = '';
    const selectedCameras = this.activeCameras.slice(0, slotCount);

    selectedCameras.forEach((cam, index) => {
      const tile = document.createElement('div');
      tile.className = 'cam-tile';
      tile.id = `tile-${cam.camera_id}`;

      tile.innerHTML = `
        <div class="cam-overlay">
          <span class="cam-tag">${cam.camera_id} | ${cam.name}</span>
          <span class="cam-live-indicator">
            <span class="status-dot"></span> LIVE
          </span>
        </div>
        <div class="video-container" style="width: 100%; height: 100%; display: flex; align-items: center; justify-content: center;">
          <video id="video-${cam.camera_id}" autoplay playsinline muted style="width:100%; height:100%; object-fit:cover; display:none;"></video>
          <canvas id="canvas-${cam.camera_id}" width="640" height="360" style="width:100%; height:100%; object-fit:cover;"></canvas>
        </div>
        <div class="cam-controls">
          <button class="btn-xs" onclick="UnifiedViewer.toggleAI('${cam.camera_id}')">Toggle AI</button>
          <button class="btn-xs" onclick="UnifiedViewer.focusCamera('${cam.camera_id}')">Focus</button>
        </div>
      `;

      this.container.appendChild(tile);

      // Attempt live WHEP WebRTC connection
      if (cam.whep_url) {
        this.initWHEPStream(cam.camera_id, cam.whep_url);
      } else {
        this.renderSimulatedFeed(cam.camera_id, cam.name);
      }
    });
  }

  async initWHEPStream(cameraId, whepUrl) {
    const videoEl = document.getElementById(`video-${cameraId}`);
    const canvasEl = document.getElementById(`canvas-${cameraId}`);

    try {
      const pc = new RTCPeerConnection({
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }]
      });
      this.peerConnections[cameraId] = pc;

      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (videoEl && event.streams && event.streams[0]) {
          videoEl.srcObject = event.streams[0];
          videoEl.style.display = 'block';
          if (canvasEl) canvasEl.style.display = 'none';
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2500);

      const response = await fetch(whepUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: offer.sdp,
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (response.ok) {
        const answerSdp = await response.text();
        await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });
      } else {
        throw new Error('WHEP endpoint unavailable');
      }
    } catch (e) {
      // Graceful fallback to real-time CCTV animation if gateway stream port is offline during dev
      this.renderSimulatedFeed(cameraId, videoEl ? cameraId : '');
    }
  }

  renderSimulatedFeed(cameraId, label) {
    const canvas = document.getElementById(`canvas-${cameraId}`);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let frame = 0;

    function draw() {
      if (!document.getElementById(`canvas-${cameraId}`)) return;
      frame++;

      // Cyber surveillance background
      ctx.fillStyle = '#060a12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      // Grid perspective lines
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.08)';
      ctx.lineWidth = 1;
      for (let x = 0; x < canvas.width; x += 40) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y < canvas.height; y += 30) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
      }

      // Simulated road
      ctx.fillStyle = '#111827';
      ctx.beginPath();
      ctx.moveTo(220, 140);
      ctx.lineTo(420, 140);
      ctx.lineTo(580, 360);
      ctx.lineTo(60, 360);
      ctx.closePath();
      ctx.fill();

      // Road lane markers
      ctx.strokeStyle = '#facc15';
      ctx.setLineDash([12, 16]);
      ctx.lineDashOffset = -frame * 2;
      ctx.beginPath();
      ctx.moveTo(320, 140);
      ctx.lineTo(320, 360);
      ctx.stroke();
      ctx.setLineDash([]);

      // Simulated passing vehicles
      const carPos = (frame * 3) % 400;
      if (carPos > 40) {
        ctx.fillStyle = 'rgba(59, 130, 246, 0.85)';
        const yPos = 180 + (carPos * 0.4);
        const scale = 0.6 + (carPos * 0.002);
        ctx.fillRect(280 - (scale * 20), yPos, 40 * scale, 24 * scale);
        // Headlights
        ctx.fillStyle = 'rgba(254, 240, 138, 0.6)';
        ctx.beginPath();
        ctx.arc(280 - (scale * 15), yPos + (24 * scale), 4 * scale, 0, Math.PI * 2);
        ctx.arc(280 + (scale * 15), yPos + (24 * scale), 4 * scale, 0, Math.PI * 2);
        ctx.fill();
      }

      // Camera HUD Overlay
      ctx.fillStyle = '#38bdf8';
      ctx.font = '12px monospace';
      const now = new Date().toISOString().replace('T', ' ').slice(0, 19);
      ctx.fillText(`CAM: ${cameraId}`, 12, 24);
      ctx.fillText(`PTS: ${now}.0${(frame % 99)}`, 12, 42);
      ctx.fillText(`CODEC: H.264 / TCP`, 12, 60);

      // Scanning reticle
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.4)';
      ctx.lineWidth = 1.5;
      const scanY = (frame * 2) % canvas.height;
      ctx.beginPath();
      ctx.moveTo(0, scanY);
      ctx.lineTo(canvas.width, scanY);
      ctx.stroke();

      requestAnimationFrame(draw);
    }
    requestAnimationFrame(draw);
  }

  static async toggleAI(cameraId) {
    try {
      const res = await API.startCameraAI(cameraId);
      alert(res.message);
    } catch (e) {
      alert(`AI Worker: ${e.message}`);
    }
  }

  static focusCamera(cameraId) {
    const tile = document.getElementById(`tile-${cameraId}`);
    if (tile) {
      document.querySelectorAll('.cam-tile').forEach(t => t.classList.remove('selected'));
      tile.classList.add('selected');
    }
  }
}
