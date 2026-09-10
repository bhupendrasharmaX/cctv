// Shared helpers for the command dashboard.
// Loaded before every other module.

const Utils = {
  /**
   * Escape text before it goes into innerHTML.
   *
   * Everything rendered on this dashboard originates outside the browser:
   * OCR output, operator-entered watchlist records, and camera names synced
   * from the government gateway. Interpolating any of that raw turns a
   * watchlist note into script execution in the control room.
   */
  esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  },

  /** Escape a value for use inside a single-quoted inline handler argument. */
  escAttr(value) {
    return this.esc(value).replace(/\\/g, '\\\\');
  },

  // ---------------------------------------------------------------------
  // Time
  //
  // The backend sends UTC with an explicit offset. Everything on screen is
  // rendered in Asia/Kolkata and labelled IST rather than trusting the
  // workstation clock's timezone -- an operator reading a timestamp off an
  // evidence docket needs it to mean the same thing on every machine in the
  // control room.
  // ---------------------------------------------------------------------
  IST_TZ: 'Asia/Kolkata',

  _fmt(options) {
    return new Intl.DateTimeFormat('en-IN', { timeZone: this.IST_TZ, ...options });
  },

  parseDate(value) {
    if (!value) return null;
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
  },

  formatTime(value) {
    const d = this.parseDate(value);
    if (!d) return '--:--:--';
    return this._fmt({ hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d);
  },

  formatDateTime(value) {
    const d = this.parseDate(value);
    if (!d) return 'Unknown';
    return this._fmt({
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(d) + ' IST';
  },

  /** "4m ago" / "2h ago" -- how stale is this sighting? */
  formatRelative(value) {
    const d = this.parseDate(value);
    if (!d) return '';
    const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
    if (seconds < 5) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  },

  formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return '--';
    const total = Math.max(0, Math.floor(seconds));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return h ? `${h}h ${m}m` : `${m}m ${s}s`;
  },

  // ---------------------------------------------------------------------
  // Toasts
  //
  // Replaces window.alert(), which blocks the whole dashboard -- including
  // the live alert feed and the map -- until someone dismisses it. On a
  // surveillance console that is exactly the wrong failure mode.
  // ---------------------------------------------------------------------
  toast(message, kind = 'info', timeoutMs = 4200) {
    const host = document.getElementById('toast-host');
    if (!host) return;

    const el = document.createElement('div');
    el.className = `toast toast-${kind}`;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.innerHTML = `
      <span class="toast-icon">${kind === 'error' ? '!' : kind === 'success' ? '✓' : 'i'}</span>
      <span class="toast-body">${this.esc(message)}</span>
    `;
    host.appendChild(el);

    const dismiss = () => {
      el.classList.add('toast-leaving');
      setTimeout(() => el.remove(), 220);
    };
    el.addEventListener('click', dismiss);
    setTimeout(dismiss, timeoutMs);
  },

  debounce(fn, waitMs = 250) {
    let timer = null;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), waitMs);
    };
  },

  /** Normalize a plate the same way the backend does, so the UI agrees with it. */
  normalizePlate(plate) {
    return String(plate || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  },

  /** Colour token for a severity label. */
  severityColor(severity) {
    switch (String(severity || '').toUpperCase()) {
      case 'CRITICAL': return 'var(--status-alert)';
      case 'HIGH': return 'var(--status-warning)';
      case 'REVIEW': return 'var(--accent-amber)';
      default: return 'var(--accent-blue)';
    }
  },

  setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  },

  // ---------------------------------------------------------------------
  // Search window inputs
  //
  // <input type="datetime-local"> yields the *workstation's* wall clock with
  // no zone. Everything else on this dashboard is rendered in IST, so the
  // inputs are read as IST too -- otherwise a console whose clock is set to
  // another zone would search a window several hours away from the one the
  // operator typed, and nothing on screen would show the discrepancy.
  //
  // IST is a fixed +05:30 with no daylight saving, so stamping the offset is
  // exact rather than an approximation.
  // ---------------------------------------------------------------------
  IST_OFFSET: '+05:30',

  /** "2026-09-11T14:30" (IST) -> "2026-09-11T09:00:00.000Z" */
  istInputToUtcIso(value) {
    if (!value) return '';
    const withSeconds = value.length === 16 ? `${value}:00` : value;
    const parsed = new Date(`${withSeconds}${this.IST_OFFSET}`);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString();
  },

  /** UTC ISO -> the "YYYY-MM-DDTHH:mm" an IST datetime-local input expects. */
  utcIsoToIstInput(iso) {
    const d = this.parseDate(iso);
    if (!d) return '';
    const parts = this._fmt({
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }).formatToParts(d).reduce((acc, p) => { acc[p.type] = p.value; return acc; }, {});
    return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
  },

  // ---------------------------------------------------------------------
  // CSV export
  // ---------------------------------------------------------------------
  _csvCell(value) {
    const text = value === null || value === undefined ? '' : String(value);
    // Quote when the value could otherwise break the row, and double any
    // embedded quote. A camera name containing a comma is entirely normal.
    return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
  },

  toCsv(rows, columns) {
    const header = columns.map((c) => this._csvCell(c.label)).join(',');
    const body = rows.map(
      (row) => columns.map((c) => this._csvCell(c.value(row))).join(','),
    );
    return [header, ...body].join('\r\n');
  },

  downloadCsv(filename, csvText) {
    // A BOM so Excel opens UTF-8 correctly rather than mangling it.
    const blob = new Blob([`﻿${csvText}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
};

window.Utils = Utils;
