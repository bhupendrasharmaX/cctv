// Multi-Camera Unified Viewer (Model 2 Core)
class UnifiedViewer {
  constructor(gridElementId) {
    this.container = document.getElementById(gridElementId);
    this.currentLayout = '2x2';
    this.allCameras = [];
    this.activeCameras = [];
    this.peerConnections = {};
    this.animations = {};
    this.aiWorkers = new Set();
    this.selectedCameraId = null;
    this.page = 0;
    // Bumped on every re-render. Animation loops capture the value they were
    // started with and stop as soon as it moves, which is what stops orphaned
    // draw loops accumulating on each layout change.
    this.renderToken = 0;
  }

  get slotCount() {
    return this.currentLayout === '1x1' ? 1 : this.currentLayout === '2x2' ? 4 : 9;
  }

  get pageCount() {
    return Math.max(1, Math.ceil(this.activeCameras.length / this.slotCount));
  }

  setLayout(layout) {
    this.currentLayout = layout;
    this.page = 0;
    this.container.className = `camera-grid grid-${layout}`;
    document.querySelectorAll('[data-layout-btn]').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.layoutBtn === layout);
    });
    this.render();
  }

  loadCameras(cameras) {
    this.allCameras = cameras;
    this.activeCameras = cameras;
    this.page = 0;
    this.render();
  }

  /** Narrow the wall to a filtered subset without refetching the registry. */
  setVisibleCameras(cameras) {
    this.activeCameras = cameras;
    this.page = 0;
    this.render();
  }

  nextPage() {
    this.page = (this.page + 1) % this.pageCount;
    this.render();
  }

  prevPage() {
    this.page = (this.page - 1 + this.pageCount) % this.pageCount;
    this.render();
  }

  /** Reflect the AI worker pool on the tiles. */
  applyWorkerStatus(status) {
    this.aiWorkers = new Set((status && status.active_camera_ids) || []);
    this.activeCameras.forEach((cam) => this.updateTileAIState(cam.camera_id));
    Utils.setText('stat-workers-count', this.aiWorkers.size);
  }

  updateTileAIState(cameraId) {
    const tile = document.getElementById(`tile-${cameraId}`);
    if (!tile) return;
    const on = this.aiWorkers.has(cameraId);
    tile.classList.toggle('ai-active', on);
    const btn = tile.querySelector('[data-ai-toggle]');
    if (btn) {
      btn.textContent = on ? 'AI: ON' : 'AI: OFF';
      btn.classList.toggle('btn-on', on);
    }
    const badge = tile.querySelector('[data-ai-badge]');
    if (badge) badge.hidden = !on;
  }

  teardown() {
    // Invalidating the token stops every in-flight animation loop.
    this.renderToken += 1;
    this.animations = {};
    Object.values(this.peerConnections).forEach((pc) => {
      try { pc.close(); } catch (e) { /* already closed */ }
    });
    this.peerConnections = {};
  }

  render() {
    this.teardown();
    const token = this.renderToken;
    this.container.innerHTML = '';

    if (!this.activeCameras.length) {
      this.container.innerHTML = `
        <div class="grid-empty">
          <div class="grid-empty-title">No cameras match the current filters</div>
          <div class="grid-empty-hint">Clear the registry filters, or run Sync Ingest API to onboard feeds.</div>
        </div>
      `;
      this.updatePager();
      return;
    }

    const start = this.page * this.slotCount;
    const visible = this.activeCameras.slice(start, start + this.slotCount);

    visible.forEach((cam) => this.container.appendChild(this.buildTile(cam)));
    this.updatePager();

    visible.forEach((cam) => {
      this.updateTileAIState(cam.camera_id);
      if (cam.whep_url) {
        this.initWHEPStream(cam.camera_id, cam.whep_url, token);
      } else {
        this.renderSimulatedFeed(cam.camera_id, token);
      }
    });
  }

  updatePager() {
    const label = document.getElementById('grid-page-label');
    if (label) {
      label.textContent = this.activeCameras.length
        ? `${this.page + 1} / ${this.pageCount}  ·  ${this.activeCameras.length} feeds`
        : '0 feeds';
    }
    document.querySelectorAll('[data-pager]').forEach((btn) => {
      btn.disabled = this.pageCount <= 1;
    });
  }

  buildTile(cam) {
    const esc = Utils.esc.bind(Utils);
    const id = esc(cam.camera_id);
    const tile = document.createElement('div');
    tile.className = 'cam-tile';
    tile.id = `tile-${cam.camera_id}`;
    if (cam.camera_id === this.selectedCameraId) tile.classList.add('selected');

    const offline = String(cam.connectivity_status || '').toUpperCase() !== 'ONLINE';

    tile.innerHTML = `
      <div class="cam-overlay">
        <span class="cam-tag" title="${esc(cam.location_description || cam.name)}">
          ${id} · ${esc(cam.name)}
        </span>
        <span class="cam-badges">
          <span data-ai-badge class="cam-badge cam-badge-ai" hidden>AI</span>
          <span class="cam-live-indicator ${offline ? 'is-offline' : ''}">
            <span class="status-dot ${offline ? 'offline' : ''}"></span>
            ${offline ? esc(cam.connectivity_status) : 'LIVE'}
          </span>
        </span>
      </div>
      <div class="video-container">
        <video id="video-${id}" autoplay playsinline muted hidden></video>
        <canvas id="canvas-${id}" width="640" height="360"></canvas>
      </div>
      <div class="cam-meta-strip">
        <span>${esc(cam.department)}</span>
        <span>${esc(cam.camera_type)} · ${esc(cam.codec)}</span>
      </div>
      <div class="cam-controls">
        <button class="btn-xs" data-ai-toggle title="Start or stop AI analytics on this feed">AI: OFF</button>
        <button class="btn-xs" data-focus title="Centre the GIS map on this camera">Focus</button>
      </div>
    `;

    tile.querySelector('[data-ai-toggle]').addEventListener('click', (e) => {
      e.stopPropagation();
      this.toggleAI(cam.camera_id);
    });
    tile.querySelector('[data-focus]').addEventListener('click', (e) => {
      e.stopPropagation();
      this.focusCamera(cam.camera_id);
    });
    tile.addEventListener('click', () => this.selectCamera(cam.camera_id));

    return tile;
  }

  async initWHEPStream(cameraId, whepUrl, token) {
    const videoEl = document.getElementById(`video-${cameraId}`);
    const canvasEl = document.getElementById(`canvas-${cameraId}`);

    try {
      const pc = new RTCPeerConnection({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] });
      this.peerConnections[cameraId] = pc;
      pc.addTransceiver('video', { direction: 'recvonly' });

      pc.ontrack = (event) => {
        if (token !== this.renderToken) return;
        if (videoEl && event.streams && event.streams[0]) {
          videoEl.srcObject = event.streams[0];
          videoEl.hidden = false;
          if (canvasEl) canvasEl.hidden = true;
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
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!response.ok) throw new Error('WHEP endpoint unavailable');
      if (token !== this.renderToken) { pc.close(); return; }

      await pc.setRemoteDescription({ type: 'answer', sdp: await response.text() });
    } catch (e) {
      // Fall back to the representative canvas feed when the gateway's WebRTC
      // port is not reachable (typical during offline development).
      this.renderSimulatedFeed(cameraId, token);
    }
  }

  /**
   * Representative feed used when no live WHEP stream is available.
   * Clearly labelled on-canvas so it can never be mistaken for camera footage.
   */
  renderSimulatedFeed(cameraId, token) {
    const canvas = document.getElementById(`canvas-${cameraId}`);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let frame = 0;

    const draw = () => {
      // Stop when this tile has been replaced. The previous implementation
      // re-looked-up the canvas by id, which the *replacement* tile also
      // matched, so every layout change left another loop running forever.
      if (token !== this.renderToken || !canvas.isConnected) return;
      frame += 1;

      ctx.fillStyle = '#060a12';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.strokeStyle = 'rgba(56, 189, 248, 0.08)';
      ctx.lineWidth = 1;
      for (let x = 0; x < canvas.width; x += 40) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
      }
      for (let y = 0; y < canvas.height; y += 30) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
      }

      ctx.fillStyle = '#111827';
      ctx.beginPath();
      ctx.moveTo(220, 140); ctx.lineTo(420, 140); ctx.lineTo(580, 360); ctx.lineTo(60, 360);
      ctx.closePath(); ctx.fill();

      ctx.strokeStyle = '#facc15';
      ctx.setLineDash([12, 16]);
      ctx.lineDashOffset = -frame * 2;
      ctx.beginPath(); ctx.moveTo(320, 140); ctx.lineTo(320, 360); ctx.stroke();
      ctx.setLineDash([]);

      const carPos = (frame * 3) % 400;
      if (carPos > 40) {
        const yPos = 180 + (carPos * 0.4);
        const scale = 0.6 + (carPos * 0.002);
        ctx.fillStyle = 'rgba(59, 130, 246, 0.85)';
        ctx.fillRect(280 - (scale * 20), yPos, 40 * scale, 24 * scale);
        ctx.fillStyle = 'rgba(254, 240, 138, 0.6)';
        ctx.beginPath();
        ctx.arc(280 - (scale * 15), yPos + (24 * scale), 4 * scale, 0, Math.PI * 2);
        ctx.arc(280 + (scale * 15), yPos + (24 * scale), 4 * scale, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.fillStyle = '#38bdf8';
      ctx.font = '12px monospace';
      ctx.fillText(`CAM: ${cameraId}`, 12, 24);
      ctx.fillText(`${Utils.formatTime(new Date())} IST`, 12, 42);
      ctx.fillText('CODEC: H.264 / TCP', 12, 60);

      // Never let a placeholder read as evidence.
      ctx.fillStyle = 'rgba(148, 163, 184, 0.85)';
      ctx.font = 'bold 11px monospace';
      ctx.fillText('REPRESENTATIVE FEED - NO LIVE STREAM', 12, canvas.height - 14);

      ctx.strokeStyle = 'rgba(6, 182, 212, 0.4)';
      ctx.lineWidth = 1.5;
      const scanY = (frame * 2) % canvas.height;
      ctx.beginPath(); ctx.moveTo(0, scanY); ctx.lineTo(canvas.width, scanY); ctx.stroke();

      this.animations[cameraId] = requestAnimationFrame(draw);
    };

    this.animations[cameraId] = requestAnimationFrame(draw);
  }

  async toggleAI(cameraId) {
    const tile = document.getElementById(`tile-${cameraId}`);
    const btn = tile && tile.querySelector('[data-ai-toggle]');
    if (btn) { btn.disabled = true; btn.textContent = '...'; }

    try {
      // One endpoint that reports the state it landed in -- the old control was
      // labelled "Toggle AI" but only ever started a worker.
      const res = await API.toggleCameraAI(cameraId);
      if (res.running) {
        this.aiWorkers.add(cameraId);
      } else {
        this.aiWorkers.delete(cameraId);
      }
      if (res.pool) Utils.setText('stat-workers-count', res.pool.active_workers_count);
      Utils.toast(res.message, 'success');
    } catch (e) {
      Utils.toast(e.message, 'error');
    } finally {
      if (btn) btn.disabled = false;
      this.updateTileAIState(cameraId);
    }
  }

  selectCamera(cameraId) {
    this.selectedCameraId = cameraId;
    document.querySelectorAll('.cam-tile').forEach((t) => t.classList.remove('selected'));
    const tile = document.getElementById(`tile-${cameraId}`);
    if (tile) tile.classList.add('selected');
  }

  /** Bring a camera onto the visible page, select it, and centre the map on it. */
  focusCamera(cameraId) {
    const index = this.activeCameras.findIndex((c) => c.camera_id === cameraId);
    if (index >= 0) {
      const targetPage = Math.floor(index / this.slotCount);
      if (targetPage !== this.page) {
        this.page = targetPage;
        this.render();
      }
    }
    this.selectCamera(cameraId);
    if (window.gisMap) window.gisMap.highlightAlertCamera(cameraId);
  }
}

window.UnifiedViewer = UnifiedViewer;
