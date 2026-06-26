/*
 * FHRViewer — vanilla ES module CTG (cardiotocography / fetal heart rate) viewer.
 *
 * A clean, dependency-free re-implementation of the legacy jQuery/PHP viewer
 * (fhrgraphplot-source.js / fhrsignal-source.js / fhrviewer-source.js /
 * scrollbar-source.js). No jQuery, no bootstrap, no build step, no AJAX/PHP.
 *
 * The drawing maths (grid geometry, winlength scaling, vertical mappings,
 * drawSigFast, drawPeriods/fillSurface, measurer and marks) are ported
 * verbatim from the original so the output matches the reference viewer.
 *
 * New features beyond the original:
 *   - toggle colored zones (acc green / dec red / contraction TOCO)
 *   - independent FHR / MHR channel visibility
 *   - linear interpolation across missing points ("interpolate gaps" mode)
 *   - configurable channels displayed per graph
 *   - dynamic height + responsive width (ResizeObserver)
 *   - public JS API + event emitter + postMessage bridge for a Python backend
 *
 * Binary format (little-endian), ported from fhrsignal-source.js:
 *   Header: [uint32 magic][uint32 startEpoch seconds]
 *   Optional [uint32 code] (1234567 recording / 1234568 finished) — skipped if present.
 *   Then N samples at 4 Hz:
 *     .rcf / .fhr  (6 bytes):  u16 FHR1, u16 FHR2, u8 TOCO, u8 qual
 *     .rcfm        (8 bytes):  u16 FHR1, u16 FHR2, u16 MHR, u8 TOCO, u8 qual
 *     .rcfa       (12 bytes):  + u16 FHRi (preprocessed), u16 baseline
 *   Scaling: FHR/MHR/FHRi/baseline = raw/4 ; TOCO = raw/2.
 *   Missing / lost signal = value 0 (or <=40 for FHR) -> breaks the curve.
 */

const SVGNS = 'http://www.w3.org/2000/svg';
const MAGIC = 1234555;          // header magic (validity check, best-effort)
const CODE_RECORDING = 1234567; // optional data-stream code
const CODE_FINISHED = 1234568;
const GRID_COLOR = '#AAFFAA';   // classic CTG green paper

const DEFAULT_COLORS = {
  FHR1: '#FF0000',     // red
  FHR2: '#0000FF',     // blue
  MHR: '#FF00FF',      // magenta
  FHRi: '#AAAAAA',     // preprocessed (gray)
  baseline: '#202020', // baseline (near-black)
  TOCO: '#000000',
};

/* ----------------------------------------------------------------------------
 * Signals — in-memory recording (parsing + markers), no network.
 * ------------------------------------------------------------------------- */
class Signals {
  constructor() {
    this.srate = 4;
    this.minRCF = 50;
    this.maxRCF = 210;
    this.minTOCO = 0;
    this.maxTOCO = 100;
    this.start = -1;
    this.lastTime = -1;
    this.bytesBySample = 8;
    this.editingMark = false;
    this._reset();
  }

  _reset(startTime = 0) {
    this.RCF1 = [];
    this.RCF2 = [];
    this.RCFm = [];
    this.RCFi = [];
    this.baselineRCF = [];
    this.TOCO = [];
    this.Marks = [];
    this.start = startTime;
    this.lastTime = startTime;
    this.badSigPoints = 0;
  }

  /** Decode an ArrayBuffer into the signal arrays. `ext` selects bytes/sample. */
  loadBuffer(arrayBuffer, ext = 'rcfm') {
    const last = (ext || '').toLowerCase().replace('.', '').slice(-1);
    if (last === 'r' || last === 'f') this.bytesBySample = 6;
    else if (last === 'm') this.bytesBySample = 8;
    else if (last === 'a') this.bytesBySample = 12;
    else this.bytesBySample = 8;

    const view = new DataView(arrayBuffer);
    const total = view.byteLength;
    let off = 0;
    // Header: magic + startEpoch. (Some files carry magic=0; tolerate that.)
    view.getUint32(0, true); // magic (unused beyond documentation)
    const startEpoch = view.getUint32(4, true);
    off = 8;

    // Optional code word: present in the legacy streamed data payload.
    if (total - off >= 4) {
      const code = view.getUint32(off, true);
      if (code === CODE_RECORDING || code === CODE_FINISHED) off += 4;
    }

    // If the remaining bytes are not a whole number of samples, the code word
    // was probably absent; off stays at 8 (header only).
    if ((total - off) % this.bytesBySample !== 0 && (total - 8) % this.bytesBySample === 0) {
      off = 8;
    }

    this._reset(startEpoch);
    const nSamp = Math.floor((total - off) / this.bytesBySample);
    for (let i = 0; i < nSamp; i++) {
      const o = off + i * this.bytesBySample;
      if (this.bytesBySample === 6) {
        this._addData(view.getUint16(o, true), view.getUint16(o + 2, true),
          view.getUint8(o + 4), view.getUint8(o + 5), 0, 0, 0);
      } else if (this.bytesBySample === 8) {
        this._addData(view.getUint16(o, true), view.getUint16(o + 2, true),
          view.getUint8(o + 6), view.getUint8(o + 7), view.getUint16(o + 4, true), 0, 0);
      } else { // 12
        this._addData(view.getUint16(o, true), view.getUint16(o + 2, true),
          view.getUint8(o + 6), view.getUint8(o + 7), view.getUint16(o + 4, true),
          view.getUint16(o + 8, true), view.getUint16(o + 10, true));
      }
    }
  }

  _addData(rcf1, rcf2, toco, qual, rcfm = 0, rcfi = 0, baseline = 0) {
    const f1 = rcf1 / 4, f2 = rcf2 / 4;
    this.RCF1.push(f1);
    this.RCF2.push(f2);
    this.TOCO.push(toco / 2);
    if (this.bytesBySample > 6) {
      this.RCFm.push(rcfm / 4);
      if (this.bytesBySample > 8) {
        this.RCFi.push(rcfi / 4);
        this.baselineRCF.push(baseline / 4);
      }
    }
    this.lastTime += 1 / this.srate;
    if (f1 === 0 && f2 === 0) this.badSigPoints++;
  }

  /** Percentage of signal-loss between first and last non-null sample. */
  signalLoss() {
    let s0 = 0, first = -1, last = -1;
    for (let i = 0; i < this.RCF1.length; i++) {
      if (this.RCF1[i] > 0 || this.RCF2[i] > 0) {
        if (first === -1) first = i;
        last = i;
      }
      if (this.RCF1[i] === 0 && this.RCF2[i] === 0) s0++;
    }
    const s = this.RCF1.length;
    if (first === -1) return 100;
    return Math.round((1000 * (s0 + 2 - first - s + last)) / (last - first + 1)) / 10;
  }

  /** Parse a marker text blob: one mark per line, `SSSSSSS text` (7-digit sample). */
  loadMarkers(text) {
    this.Marks = [];
    const lines = (text || '').split('\n');
    for (const line of lines) {
      if (line.length > 5) {
        this.Marks.push([parseInt(line.substr(0, 7), 10), line.substring(8, 3000)]);
      }
    }
  }

  setMarks(list) {
    // Accept [[sample, text], ...]; keep sorted by sample.
    this.Marks = (list || []).map((m) => [Math.round(m[0]), String(m[1])]);
    this.Marks.sort((a, b) => a[0] - b[0]);
  }

  getMarks() {
    return this.Marks.map((m) => [m[0], m[1]]);
  }

  addMarks(s, t) {
    let index = 0;
    for (let i = 0; i < this.Marks.length; i++) if (this.Marks[i][0] < s) index++;
    this.Marks.splice(index, 0, [s, t]);
    return index;
  }

  updateMark(n, t) {
    this.Marks[n][1] = t;
    if (t === '') this.Marks.splice(n, 1);
  }
}

/* ----------------------------------------------------------------------------
 * ScrollBar — draggable thumb over a track. Calls back via onScroll(value,fast).
 * ------------------------------------------------------------------------- */
class ScrollBar {
  constructor(container, onScroll) {
    this.container = container;
    this.onScroll = onScroll;
    this.pageRatio = 0.1;
    this.value = 0;
    this.mouseDownOffset = -1;
    this.mouseDownValue = 0;

    this.dragger = document.createElement('div');
    this.dragger.className = 'scrollbarDragger';
    const bar = document.createElement('div');
    bar.className = 'scrollbarDraggerBar';
    this.dragger.appendChild(bar);
    this.container.appendChild(this.dragger);

    this._onTrackClick = (e) => this.clickContainer(e);
    this.container.addEventListener('click', this._onTrackClick);
    this.dragger.addEventListener('mousedown', (e) => this.mouseDownDragger(e));
  }

  setValue(v, follow, fast = 0) {
    v = Math.min(1, Math.max(0, v));
    this.value = v;
    this.dragger.style.left = `${v * (1 - this.pageRatio) * 100}%`;
    if (follow !== false && this.onScroll) this.onScroll(v, fast);
  }

  setPageRatio(r) {
    r = Math.min(1, Math.max(0.05, r));
    this.pageRatio = r;
    this.dragger.style.width = `${r * 100}%`;
    this.dragger.style.left = `${this.value * (1 - this.pageRatio) * 100}%`;
  }

  clickContainer(e) {
    const rect = this.container.getBoundingClientRect();
    const posX = e.clientX - rect.left - this.pageRatio * 0.5 * rect.width;
    this.setValue(posX / (rect.width * (1 - this.pageRatio)), true);
  }

  mouseDownDragger(e) {
    if (window.getSelection) window.getSelection().removeAllRanges();
    this.mouseDownOffset = e.clientX;
    this.mouseDownValue = this.value;
    this._move = (ev) => this.mouseMoveDragger(ev);
    this._up = (ev) => this.mouseUpDragger(ev);
    document.addEventListener('mousemove', this._move);
    document.addEventListener('mouseup', this._up);
    this.container.removeEventListener('click', this._onTrackClick);
    e.stopPropagation();
  }

  mouseMoveDragger(e) {
    const rect = this.container.getBoundingClientRect();
    const deltaX = (e.clientX - this.mouseDownOffset) / (rect.width * (1 - this.pageRatio));
    this.setValue(this.mouseDownValue + deltaX, true, true);
  }

  mouseUpDragger(e) {
    document.removeEventListener('mousemove', this._move);
    document.removeEventListener('mouseup', this._up);
    this.mouseDownOffset = -1;
    e.preventDefault();
    setTimeout(() => this.container.addEventListener('click', this._onTrackClick), 0);
    this.setValue(this.value, true, false);
  }
}

/* ----------------------------------------------------------------------------
 * GraphPlot — canvas grid + curves + svg overlays. Ported maths.
 * ------------------------------------------------------------------------- */
class GraphPlot {
  constructor(container, viewer) {
    this.viewer = viewer;
    this.container = container;
    this.signals = new Signals();
    this.canvas = container.querySelector('canvas.background-canvas');
    this.svg = container.querySelector('svg.frontground-svg');
    this.ctx = this.canvas.getContext('2d');
    this.ctx.imageSmoothingEnabled = false;

    this.eventTextEdit = document.createElement('textarea');
    this.eventTextEdit.className = 'eventTextEdit';
    container.appendChild(this.eventTextEdit);

    this.BorderLeft = 0;
    this.BorderRight = 0;
    this.BorderTop = 0;
    this.BorderBottom = 15;
    this.mouseMode = 'None';
    this.editingMark = -1;
    this.displayMorpho = true;   // colored zones toggle
    this.fullGrid = 1;
    this.is3cm = 0;
    this.time = 0;

    // New-feature state.
    this.interpolate = false;
    this.interpMaxGap = 4 * 30; // bridge gaps up to 30 s by default
    this.channels = null;       // explicit list of channels to display, else auto

    this.bufferCanvas = document.createElement('canvas');
    this.bufferContext = this.bufferCanvas.getContext('2d');
    this.markRects = [];
    this.measurer = {};
    this.newMark = {};

    this.eventTextEdit.addEventListener('keyup', () => {
      this.eventTextEdit.style.height = '0px';
      this.eventTextEdit.style.height = `${this.eventTextEdit.scrollHeight}px`;
    });
    this.svg.addEventListener('mousemove', (e) => this.mouseMove(e), true);
  }

  /* --- geometry ----------------------------------------------------------- */
  resize() {
    const h = this.container.clientHeight;
    const w = this.container.clientWidth;
    this.canvas.height = h;
    this.canvas.width = w;
    this.svg.setAttributeNS(null, 'width', w);
    this.svg.setAttributeNS(null, 'height', h);
    this.TotalWidth = w;
    this.TotalHeight = h;
    this.bufferCanvas.width = w;
    this.bufferCanvas.height = h;
    this.graphWidth = w - this.BorderLeft - this.BorderRight;
    this.graphHeight = h - this.BorderTop - this.BorderBottom;
    this.RCFTOCOSpace = 0.05 * this.graphHeight;
    this.TOCOHeight = (1 / 3) * (this.graphHeight - this.RCFTOCOSpace);
    this.RCFHeight = this.graphHeight - this.RCFTOCOSpace - this.TOCOHeight;
    const sizeof20bpm = (this.RCFHeight * 20) / (this.signals.maxRCF - this.signals.minRCF);
    this.winlength = (this.graphWidth * 60) / sizeof20bpm / (1 + 2 * this.is3cm);
  }

  /* --- which FHR channels to plot ---------------------------------------- */
  _activeChannels() {
    // Returns [{name, arr, color}], honoring explicit channel list + visibility.
    const s = this.signals;
    let candidates;
    if (this.signals.bytesBySample === 6) {
      candidates = [['FHR1', s.RCF1], ['FHR2', s.RCF2]];
    } else if (this.signals.bytesBySample === 8) {
      candidates = [['FHR1', s.RCF1], ['FHR2', s.RCF2], ['MHR', s.RCFm]];
    } else {
      candidates = [['FHRi', s.RCFi], ['FHR1', s.RCF1], ['FHR2', s.RCF2],
        ['MHR', s.RCFm]];
      if (this.displayMorpho) candidates.push(['baseline', s.baselineRCF]);
    }
    const visible = this.viewer.channelVisible;
    let list = candidates;
    if (this.channels && this.channels.length) {
      const set = new Set(this.channels);
      list = candidates.filter(([name]) => set.has(name));
    }
    return list
      .filter(([name]) => visible[name] !== false)
      .map(([name, arr]) => ({ name, arr, color: DEFAULT_COLORS[name] || '#000' }));
  }

  /* --- gap interpolation -------------------------------------------------- */
  _maybeInterpolate(arr) {
    if (!this.interpolate) return arr;
    const out = arr.slice();
    const valid = (v) => v > 40 && !Number.isNaN(v);
    let lastValid = -1;
    for (let i = 0; i < out.length; i++) {
      if (valid(out[i])) {
        if (lastValid >= 0 && i - lastValid > 1 && i - lastValid <= this.interpMaxGap) {
          const v0 = out[lastValid], v1 = out[i];
          for (let k = lastValid + 1; k < i; k++) {
            out[k] = v0 + ((v1 - v0) * (k - lastValid)) / (i - lastValid);
          }
        }
        lastValid = i;
      }
    }
    return out;
  }

  /* --- drawing primitives ------------------------------------------------- */
  hline(x1, x2, y, w, color) {
    this.ctx.beginPath();
    const r = 0.5 * w;
    this.ctx.moveTo(Math.round(x1), Math.round(y - r) + r);
    this.ctx.lineTo(Math.round(x2), Math.round(y - r) + r);
    this.ctx.lineWidth = w;
    this.ctx.strokeStyle = color;
    this.ctx.stroke();
  }

  vline(x, y1, y2, w, color) {
    this.ctx.beginPath();
    const r = 0.5 * w;
    this.ctx.moveTo(Math.round(x - r) + r, Math.round(y1));
    this.ctx.lineTo(Math.round(x - r) + r, Math.round(y2));
    this.ctx.lineWidth = w;
    this.ctx.strokeStyle = color;
    this.ctx.stroke();
  }

  drawAxes() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.TotalWidth, this.TotalHeight);
    // light-green CTG paper background
    ctx.fillStyle = '#EEFFEE';
    ctx.fillRect(0, 0, this.TotalWidth, this.TotalHeight);

    ctx.font = '18px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const textheight = 22;

    // grey band over 50..100 bpm
    ctx.fillStyle = '#F8F8F8';
    ctx.fillRect(this.BorderLeft, this.BorderTop + (50 * this.RCFHeight) / 160,
      this.graphWidth, (50 * this.RCFHeight) / 160);

    // vertical time lines
    for (let j = 0; j <= ((this.winlength + 60) * (1 + this.is3cm * 2)) / 30; j++) {
      const ty = (j * 30) / (1 + this.is3cm * 2) - (this.time % 60);
      const x = (ty * this.graphWidth) / this.winlength + this.BorderLeft;
      if (j % (2 + 4 * this.is3cm) === 0) {
        this.vline(x, this.BorderTop, this.BorderTop + this.RCFHeight, 2, GRID_COLOR);
        this.vline(x, this.BorderTop + this.RCFHeight + this.RCFTOCOSpace,
          this.BorderTop + this.graphHeight, 2, GRID_COLOR);
      } else if (this.fullGrid) {
        this.vline(x, this.BorderTop, this.BorderTop + this.RCFHeight, 1, GRID_COLOR);
        this.vline(x, this.BorderTop + this.RCFHeight + this.RCFTOCOSpace,
          this.BorderTop + this.graphHeight, 1, GRID_COLOR);
      }
    }

    // horizontal FHR lines (every 5 bpm)
    for (let j = 0; j <= 32; j++) {
      const ty = this.BorderTop + (j * 5 * this.RCFHeight) / 160;
      if (this.fullGrid) {
        if (j === 10 || j === 20) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 4, GRID_COLOR);
        else if (j % 2 === 0) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 2, GRID_COLOR);
        else this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 1, GRID_COLOR);
      } else if (j === 10 || j === 20) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 3, GRID_COLOR);
      else if (j % 2 === 0) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 1, GRID_COLOR);
    }

    // FHR numeric labels
    for (let j = 2; j <= 32; j += 4) {
      const ty = this.BorderTop + (j * 5 * this.RCFHeight) / 160;
      if (this.fullGrid || j % 8 === 2) {
        for (let i = 600 - (this.time % 600); i < this.winlength; i += 600) {
          const text = (210 - 5 * j).toString();
          const textwidth = ctx.measureText(text).width + 4;
          const textx = this.BorderLeft + (i / this.winlength) * this.graphWidth - textwidth / 2;
          const texty = ty - textheight / 2;
          if (j === 10) {
            ctx.fillStyle = '#F8F8F8';
            ctx.fillRect(textx, texty + textheight / 2, textwidth, textheight / 2);
            ctx.fillStyle = '#FFFFFF';
            ctx.fillRect(textx, texty, textwidth, textheight / 2);
          } else if (j === 18 || j === 14) {
            ctx.fillStyle = '#F8F8F8';
            ctx.fillRect(textx, texty, textwidth, textheight);
          } else {
            ctx.fillStyle = '#FFFFFF';
            ctx.fillRect(textx, texty, textwidth, textheight);
          }
          ctx.fillStyle = GRID_COLOR;
          ctx.fillText(text, textx + textwidth / 2, texty + textheight / 2);
        }
      }
    }

    // horizontal TOCO lines
    for (let j = 0; j <= 9; j++) {
      const ty = this.BorderTop + this.RCFHeight + this.RCFTOCOSpace + (j * 10 * this.TOCOHeight) / 100;
      if (this.fullGrid) {
        if (j === 8) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 4, GRID_COLOR);
        else if (j % 2 === 0) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 2, GRID_COLOR);
        else this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 1, GRID_COLOR);
      } else if (j === 8) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 3, GRID_COLOR);
      else if (j % 2 === 0) this.hline(this.BorderLeft, this.BorderLeft + this.graphWidth, ty, 1, GRID_COLOR);
    }
    for (let j = 0; j <= 9; j += 2) {
      const ty = this.BorderTop + this.RCFHeight + this.RCFTOCOSpace + (j * 10 * this.TOCOHeight) / 100;
      if (this.fullGrid || j % 4 === 0) {
        for (let i = 600 - (this.time % 600); i < this.winlength; i += 600) {
          const text = (100 - 10 * j).toString();
          const textwidth = ctx.measureText(text).width + 4;
          const textx = this.BorderLeft + (i / this.winlength) * this.graphWidth - textwidth / 2;
          const texty = ty - textheight / 2;
          ctx.fillStyle = '#FFFFFF';
          ctx.fillRect(textx, texty, textwidth, textheight);
          ctx.fillStyle = GRID_COLOR;
          ctx.fillText(text, textx + textwidth / 2, texty + textheight / 2);
        }
      }
    }

    // time-tick labels along the bottom (HHhMM)
    ctx.font = '14px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#000000';
    const t = new Date();
    const secGap = 600 / (1 + this.is3cm);
    for (let i = 0; i < this.winlength / secGap; i++) {
      const textx = this.BorderLeft + ((secGap - (this.time % secGap) + i * secGap) / this.winlength) * this.graphWidth;
      const texty = this.TotalHeight - this.BorderBottom;
      t.setTime((Math.floor(this.time / secGap + 1) + i) * secGap * 1000);
      const text = ('00' + t.getHours()).slice(-2) + 'h' + ('00' + t.getMinutes()).slice(-2);
      ctx.fillText(text, textx, texty);
    }
    this.hline(this.BorderLeft, this.TotalWidth - this.BorderRight, this.TotalHeight - this.BorderBottom, 1, '#000000');
  }

  /* --- colored zones (periods) ------------------------------------------- */
  drawPeriods() {
    if (!this.displayMorpho) return;
    const s = this.signals;
    const zeros = new Array(s.TOCO.length).fill(0);
    if (!s.Marks) return;
    for (let i = 0; i < s.Marks.length; i++) {
      const m = s.Marks[i];
      if (!m || m[1][0] !== '$') continue;
      const type = m[1].substring(2, 5);
      const startSamp = m[0];
      const durSamp = parseInt(m[1].substring(6), 10);
      const S = this.BorderLeft + (startSamp / s.srate - (this.time - s.start)) / this.winlength * this.graphWidth;
      const W = (durSamp / s.srate) / this.winlength * this.graphWidth;
      if (type === 'CON') {
        this.ctx.fillStyle = '#99990033';
        this.fillSurface(s.TOCO, zeros, startSamp, startSamp + durSamp, 0);
      } else if (type === 'ACC') {
        this.ctx.fillStyle = '#00FF0033';
        this.fillSurface(this._baselineFor(s), s.RCFi.length ? s.baselineRCF : this._baselineFor(s),
          startSamp, startSamp + durSamp, 1, s.RCFi.length ? s.RCFi : s.RCF1);
      } else if (type === 'DEC') {
        this.ctx.fillStyle = '#FF000033';
        this.fillSurface(this._baselineFor(s), s.RCFi.length ? s.baselineRCF : this._baselineFor(s),
          startSamp, startSamp + durSamp, 1, s.RCFi.length ? s.RCFi : s.RCF1);
      } else if (type === 'NTA' || type === 'URS') {
        this.ctx.fillStyle = '#55555533';
        this.ctx.fillRect(S, this.BorderTop, W, this.RCFHeight);
      }
    }
  }

  // For 6/8-byte files there is no server baseline; fall back to a flat band.
  _baselineFor(s) {
    if (s.baselineRCF.length) return s.baselineRCF;
    if (!this._flatBaseline || this._flatBaseline.length !== s.RCF1.length) {
      this._flatBaseline = new Array(s.RCF1.length).fill(140);
    }
    return this._flatBaseline;
  }

  fillSurface(Top, Bottom, S, E, isRCF, TopOverride) {
    const top = TopOverride || Top;
    this.ctx.beginPath();
    const s = this.signals;
    const d = Math.round((this.time - s.start) * s.srate);
    let M2, H, T, M1;
    if (isRCF) { M2 = s.maxRCF; H = this.RCFHeight; T = this.BorderTop; M1 = s.minRCF; }
    else { M2 = s.maxTOCO; H = this.TOCOHeight; T = this.BorderTop + this.RCFHeight + this.RCFTOCOSpace; M1 = s.minTOCO; }

    if (E > d && S < d + this.winlength * s.srate) {
      let firstTime = true;
      for (let i = Math.round(Math.max(S - d, 0, -d)); i < Math.min(E - d, top.length - d - 1); i++) {
        const x1 = this.BorderLeft + (i * this.graphWidth) / (s.srate * this.winlength);
        const y1 = T + (H * (M2 - top[d + i])) / (M2 - M1);
        if (firstTime) { firstTime = false; this.ctx.moveTo(x1, y1); } else this.ctx.lineTo(x1, y1);
      }
      for (let i = Math.round(Math.min(E - d, top.length - d - 1)); i >= Math.max(S - d, 0, -d); i--) {
        const x1 = this.BorderLeft + (i * this.graphWidth) / (s.srate * this.winlength);
        const y1 = T + (H * (M2 - Bottom[d + i])) / (M2 - M1);
        this.ctx.lineTo(x1, y1);
      }
    }
    this.ctx.closePath();
    this.ctx.fill();
  }

  /* --- signal curves ------------------------------------------------------ */
  drawSigFast() {
    const s = this.signals;
    if (s.start < 0 || s.RCF1.length === 0) return;
    const d = Math.round((this.time - s.start) * s.srate);
    const channels = this._activeChannels();

    for (const ch of channels) {
      const arr = this._maybeInterpolate(ch.arr);
      let y0 = NaN;
      this.ctx.beginPath();
      this.ctx.lineWidth = 1;
      this.ctx.strokeStyle = ch.color;
      for (let k = 0; k <= this.winlength * s.srate; k += 4) {
        const x1 = this.BorderLeft + (k * this.graphWidth) / (s.srate * this.winlength);
        const v = arr[d + k];
        const ok = v > 40 && !Number.isNaN(v)
          && (this.interpolate
            || (arr[d + k - 1] > 40 && arr[d + k - 2] > 40 && arr[d + k - 3] > 40));
        if (ok) {
          const y1 = this.BorderTop + (this.RCFHeight * (s.maxRCF - v)) / (s.maxRCF - s.minRCF);
          if (!Number.isNaN(y0)) this.ctx.lineTo(x1, y1); else this.ctx.moveTo(x1, y1);
          y0 = y1;
        } else y0 = NaN;
      }
      this.ctx.stroke();
    }

    // TOCO (filled to baseline + line)
    if (this.viewer.channelVisible.TOCO !== false) {
      let y0 = NaN;
      this.ctx.beginPath();
      this.ctx.strokeStyle = DEFAULT_COLORS.TOCO;
      for (let k = 0; k <= this.winlength * s.srate; k += 4) {
        const x1 = this.BorderLeft + (k * this.graphWidth) / (s.srate * this.winlength);
        const v = s.TOCO[d + k];
        if (!Number.isNaN(v) && v !== undefined) {
          const y1 = this.BorderTop + this.RCFHeight + this.RCFTOCOSpace
            + (this.TOCOHeight * (s.maxTOCO - v)) / (s.maxTOCO - s.minTOCO);
          if (!Number.isNaN(y0)) this.ctx.lineTo(x1, y1); else this.ctx.moveTo(x1, y1);
          y0 = y1;
        } else y0 = NaN;
      }
      this.ctx.stroke();
    }
  }

  /* --- markers ------------------------------------------------------------ */
  intersectRect(r1, r2) {
    return !((r2.x > r1.x + r1.w || r2.x + r2.w < r1.x) || (r2.y > r1.y + r1.h || r2.y + r2.h < r1.y));
  }

  drawMarks() {
    const s = this.signals;
    this.markRects = [];
    const all = [{ x: this.graphWidth - 200, y: this.BorderTop, w: 200, h: 21 }];
    this.ctx.font = '16px Arial';
    this.ctx.textAlign = 'left';
    this.ctx.textBaseline = 'top';
    if (!s.Marks) return;
    for (let i = 0; i < s.Marks.length; i++) {
      const m = s.Marks[i];
      if (!m || m[1][0] === '$') continue;
      const tmpx0 = m[0] / s.srate - (this.time - s.start);
      const tmpx = this.BorderLeft + (tmpx0 / this.winlength) * this.graphWidth;
      const color = m[1][0] === '£' ? '#0000FF' : '#FFBB00';
      this.ctx.fillStyle = color;
      const dtext = m[1].replace('£', '');
      const texts = dtext.split('\r');
      for (let k = 0; k < texts.length; k++) {
        let j = 0;
        const rect = { x: tmpx + 3, y: this.BorderTop, w: this.ctx.measureText(texts[k]).width, h: 17 };
        while (j < all.length) {
          if (this.intersectRect(rect, all[j])) { rect.y += 5; j = 0; } else j++;
        }
        all.push(rect);
        if (k === 0) {
          if (tmpx0 > 0 && tmpx0 < this.winlength) this.vline(tmpx, rect.y, this.BorderTop + this.graphHeight, 1, color);
          this.markRects.push(rect);
        }
        if (i !== this.editingMark && tmpx0 > 0 && tmpx0 < this.winlength) {
          this.ctx.fillText(texts[k], tmpx + 3, rect.y);
        }
      }
    }
  }

  /* --- measurer / new-mark tools (SVG overlay) --------------------------- */
  removeMouseMode() {
    if (this.mouseMode === 'Measurer1' || this.mouseMode === 'Measurer2') {
      this._svgRemove(this.measurer.hline, this.measurer.vline, this.measurer.textY);
      if (this.mouseMode === 'Measurer2') {
        this._svgRemove(this.measurer.hline2, this.measurer.vline2, this.measurer.textDY, this.measurer.textDX);
      }
    } else if (this.mouseMode === 'NewMarkPostioning') {
      this._svgRemove(this.newMark.vline, this.newMark.textEvent);
    }
    this.mouseMode = 'None';
    this.container.style.cursor = 'pointer';
  }

  _svgRemove(...els) { for (const el of els) if (el && el.parentNode) el.parentNode.removeChild(el); }

  _svgLine(x1, y1, x2, y2, stroke) {
    const l = document.createElementNS(SVGNS, 'line');
    l.setAttributeNS(null, 'x1', x1); l.setAttributeNS(null, 'y1', y1);
    l.setAttributeNS(null, 'x2', x2); l.setAttributeNS(null, 'y2', y2);
    l.setAttributeNS(null, 'stroke', stroke); l.style.strokeWidth = 1;
    this.svg.appendChild(l); return l;
  }

  _svgText(x, y) {
    const t = document.createElementNS(SVGNS, 'text');
    if (x !== undefined) t.setAttributeNS(null, 'x', x);
    if (y !== undefined) t.setAttributeNS(null, 'y', y);
    t.setAttributeNS(null, 'font-size', 16);
    t.setAttributeNS(null, 'font-weight', 'bold');
    this.svg.appendChild(t); return t;
  }

  initializeMeasurer() {
    this.measurer.hline = this._svgLine(this.BorderLeft, -100, this.graphWidth + this.BorderLeft, -100, 'black');
    this.measurer.textY = this._svgText(this.BorderLeft + 5, undefined);
    this.measurer.vline = this._svgLine(-100, this.BorderTop, -100, this.BorderTop + this.graphHeight, 'black');
    this.mouseMode = 'Measurer1';
    this.container.style.cursor = 'auto';
  }

  initializeMeasurer2() {
    this.measurer.hline2 = this._svgLine(this.BorderLeft, -100, this.graphWidth + this.BorderLeft, -100, 'black');
    this.measurer.textDY = this._svgText();
    this.measurer.vline2 = this._svgLine(-100, this.BorderTop, -100, this.BorderTop + this.graphHeight, 'black');
    this.measurer.textDX = this._svgText();
    this.mouseMode = 'Measurer2';
  }

  initializeNewMark(defaultText) {
    const color = (defaultText === 'Question' || (defaultText.length > 0 && defaultText[0] === '£')) ? '#0000FF' : '#FFBB00';
    this.newMark.textEvent = this._svgText(0, this.BorderTop + 17);
    this.newMark.textEvent.setAttributeNS(null, 'fill', color);
    this.newMark.textEvent.textContent = defaultText;
    this.newMark.vline = this._svgLine(-100, this.BorderTop, -100, this.BorderTop + this.graphHeight, color);
    this.mouseMode = 'NewMarkPostioning';
    this.container.style.cursor = 'text';
  }

  newMarkEdit(shifted) {
    const s = this.signals;
    const x1 = parseFloat(this.newMark.vline.getAttributeNS(null, 'x1'));
    const text = this.newMark.textEvent.textContent;
    const samp = ((x1 / this.graphWidth) * this.winlength + this.time - s.start) * s.srate;
    this.removeMouseMode();
    if (text === 'Question') {
      this.viewer._emit('question', { seconds: Math.round(samp / 4), epoch: s.start + samp / 4 });
      s.addMarks(samp, '£Question');
      this.redraw();
      this.viewer._markersChanged();
    } else {
      this.editingMark = s.addMarks(samp, text);
      s.editingMark = true;
      this.redraw();
      let tmpx = s.Marks[this.editingMark][0] / s.srate - (this.time - s.start);
      tmpx = this.BorderLeft + (tmpx / this.winlength) * this.graphWidth;
      this.eventTextEdit.style.left = `${tmpx + 3}px`;
      this.eventTextEdit.style.top = '2px';
      this.eventTextEdit.style.display = 'block';
      this.eventTextEdit.value = s.Marks[this.editingMark][1];
      setTimeout(() => { this.eventTextEdit.focus(); this.eventTextEdit.select(); }, 0);
      if (text !== '') this.validateMark(shifted);
    }
  }

  validateMark(shifted = false) {
    const s = this.signals;
    s.updateMark(this.editingMark, this.eventTextEdit.value);
    this.eventTextEdit.style.display = 'none';
    this.editingMark = -1;
    s.editingMark = false;
    this.redraw();
    this.viewer._markersChanged();
    if (shifted) setTimeout(() => this.initializeNewMark(this.eventTextEdit.value), 0);
  }

  checkEditable(x, y) {
    const s = this.signals;
    for (let i = 0; i < this.markRects.length && this.editingMark === -1; i++) {
      const r = this.markRects[i];
      if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) {
        let n = -1;
        for (let j = 0; j <= i; j++) { n++; while (s.Marks[n][1][0] === '$') n++; }
        if (s.Marks[n][1][0] !== '£') {
          this.editingMark = n;
          s.editingMark = true;
          this.redraw();
          this.eventTextEdit.style.left = `${r.x + 2}px`;
          this.eventTextEdit.style.top = `${r.y + 2}px`;
          this.eventTextEdit.style.display = 'block';
          this.eventTextEdit.value = s.Marks[n][1];
          setTimeout(() => { this.eventTextEdit.focus(); this.eventTextEdit.select(); }, 0);
          return true;
        }
      }
    }
    return false;
  }

  mouseMove(event) {
    const rect = this.canvas.getBoundingClientRect();
    const mousex = Math.round(event.clientX - rect.left - 0.5) + 0.5;
    const mousey = Math.round(event.clientY - rect.top - 0.5) + 0.5;
    if (this.mouseMode === 'Measurer1') {
      this.measurer.hline.setAttributeNS(null, 'y1', mousey);
      this.measurer.hline.setAttributeNS(null, 'y2', mousey);
      this.measurer.vline.setAttributeNS(null, 'x1', mousex);
      this.measurer.vline.setAttributeNS(null, 'x2', mousex);
      this.measurer.textY.setAttributeNS(null, 'y', mousey - 5);
      if (mousey < this.RCFHeight + this.RCFTOCOSpace) {
        this.measurer.Y1 = ((this.RCFHeight - mousey) / this.RCFHeight) * 160 + 50;
        this.measurer.textY.textContent = `${this.measurer.Y1.toFixed(1)} bpm`;
      } else {
        this.measurer.Y1 = -((this.graphHeight - mousey) / this.TOCOHeight) * 100;
        this.measurer.textY.textContent = Math.round(-this.measurer.Y1);
      }
      this.measurer.T1 = (mousex / this.graphWidth) * this.winlength + this.time;
    } else if (this.mouseMode === 'Measurer2') {
      this.measurer.hline2.setAttributeNS(null, 'y1', mousey);
      this.measurer.hline2.setAttributeNS(null, 'y2', mousey);
      this.measurer.vline2.setAttributeNS(null, 'x1', mousex);
      this.measurer.vline2.setAttributeNS(null, 'x2', mousex);
      this.measurer.textDY.setAttributeNS(null, 'y', mousey - 5);
      this.measurer.textDY.setAttributeNS(null, 'x', mousex + 30);
      this.measurer.textDX.setAttributeNS(null, 'y', 20);
      this.measurer.textDX.setAttributeNS(null, 'x', mousex + 5);
      if (this.measurer.Y1 > 0) {
        this.measurer.textDY.textContent = `${Math.abs(((this.RCFHeight - mousey) / this.RCFHeight) * 160 + 50 - this.measurer.Y1).toFixed(1)} bpm`;
      } else {
        this.measurer.textDY.textContent = Math.abs(Math.round(((this.graphHeight - mousey) / this.TOCOHeight) * 100 + this.measurer.Y1));
      }
      const dt = Math.abs((mousex / this.graphWidth) * this.winlength + this.time - this.measurer.T1);
      let sec = `${Math.round(dt % 60)}`;
      if (sec.length === 1) sec = `0${sec}`;
      this.measurer.textDX.textContent = `${Math.floor(dt / 60)}min${sec}`;
    } else if (this.mouseMode === 'NewMarkPostioning') {
      this.newMark.vline.setAttributeNS(null, 'x1', mousex);
      this.newMark.vline.setAttributeNS(null, 'x2', mousex);
      this.newMark.textEvent.setAttributeNS(null, 'x', mousex + 5);
    }
  }

  /* --- master redraw ------------------------------------------------------ */
  redraw() {
    this.resize();
    this.drawAxes();
    this.drawPeriods();
    this.drawSigFast();
    this.drawMarks();
  }
}

/* ----------------------------------------------------------------------------
 * FHRViewer — public, host-driveable controller.
 * ------------------------------------------------------------------------- */
const BUTTONS = [
  ['previouspage', '◀', 'Previous page'],
  ['nextpage', '▶', 'Next page'],
  ['measure', '↕', 'Measure'],
  ['addevent', '✎', 'Add event'],
  ['addquestion', '?', 'Add question'],
  ['3cm', '3cm', '1cm / 3cm per minute'],
  ['zones', '▦', 'Toggle colored zones'],
  ['mhr', 'MHR', 'Toggle MHR'],
  ['interpolate', '⤳', 'Interpolate gaps'],
  ['download', '⤓', 'Download recording + markers'],
];

export class FHRViewer {
  /**
   * @param {HTMLElement|string} host host element or selector
   * @param {Object} [opts]
   *   height, scale (cm/min: 1 or 3), channels (array of channel names),
   *   signalsPerGraph (number), interpolate (bool), zones (bool),
   *   onMessage (function for the postMessage bridge fallback).
   */
  constructor(host, opts = {}) {
    this.host = typeof host === 'string' ? document.querySelector(host) : host;
    this.opts = opts;
    this._listeners = {};
    this.channelVisible = { FHR1: true, FHR2: true, MHR: true, FHRi: true, baseline: true, TOCO: true };
    this._messageSink = opts.onMessage || null;

    this._buildDOM();
    this.graph = new GraphPlot(this.graphEl, this);
    this.scrollBar = new ScrollBar(this.scrollEl, (v, fast) => this._onScroll(v, fast));

    // apply options
    if (Array.isArray(opts.channels)) this.graph.channels = opts.channels.slice();
    else if (typeof opts.signalsPerGraph === 'number') {
      this.graph.channels = ['FHRi', 'FHR1', 'FHR2', 'MHR'].slice(0, opts.signalsPerGraph);
    }
    if (opts.scale === 3) this.graph.is3cm = 1;
    if (opts.interpolate) this.graph.interpolate = true;
    if (opts.zones === false) this.graph.displayMorpho = false;

    this._wireEvents();

    if (typeof opts.height === 'number') this.setHeight(opts.height);

    // responsive width
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => {
        if (this.graph.signals.start >= 0) this.graph.redraw();
        this._updateScrollBar();
      });
      this._ro.observe(this.graphEl);
    }
  }

  /* --- DOM ---------------------------------------------------------------- */
  _buildDOM() {
    this.host.classList.add('fhr-viewer');
    this.host.innerHTML = '';

    this.graphEl = document.createElement('div');
    this.graphEl.className = 'graph';
    const canvas = document.createElement('canvas');
    canvas.className = 'background-canvas';
    const svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('class', 'frontground-svg');
    const loss = document.createElement('div');
    loss.className = 'signalloss';
    loss.innerHTML = 'Signal loss: <span>0</span> %';
    this.graphEl.append(canvas, svg, loss);

    const controllers = document.createElement('div');
    controllers.className = 'controllers';
    const icons = document.createElement('div');
    icons.className = 'controller-icons';
    this._btn = {};
    for (const [name, label, title] of BUTTONS) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = `btn-fhr-icons btn-${name}`;
      b.title = title;
      b.textContent = label;
      icons.appendChild(b);
      this._btn[name] = b;
    }
    this.scrollEl = document.createElement('div');
    this.scrollEl.className = 'fhr-viewer-scrollbar';
    controllers.append(icons, this.scrollEl);

    this.resizebar = document.createElement('div');
    this.resizebar.className = 'resizebar';

    this.host.append(this.graphEl, controllers, this.resizebar);

    // reflect initial toggle states
    if (this.opts.zones !== false) this._btn.zones.classList.add('active');
    if (this.opts.scale === 3) this._btn['3cm'].classList.add('active');
    if (this.opts.interpolate) this._btn.interpolate.classList.add('active');
    this._btn.mhr.classList.add('active');
  }

  _wireEvents() {
    this._btn.previouspage.addEventListener('click', () => { this.previouspage(); this._emit('button:prevpage', {}); });
    this._btn.nextpage.addEventListener('click', () => { this.nextpage(); this._emit('button:nextpage', {}); });
    this._btn.measure.addEventListener('click', () => { this._toggleMouseMode('measure'); this._emit('button:measure', {}); });
    this._btn.addevent.addEventListener('click', () => { this._toggleMouseMode('event'); this._emit('button:addevent', {}); });
    this._btn.addquestion.addEventListener('click', () => { this._toggleMouseMode('question'); this._emit('button:addquestion', {}); });
    this._btn['3cm'].addEventListener('click', () => { this.toggle3cm(); this._emit('button:3cm', { is3cm: this.graph.is3cm }); });
    this._btn.zones.addEventListener('click', () => { this.setZonesVisible(!this.graph.displayMorpho); this._emit('button:zones', { on: this.graph.displayMorpho }); });
    this._btn.mhr.addEventListener('click', () => { this.setChannelVisible('MHR', this.channelVisible.MHR === false); this._emit('button:mhr', { on: this.channelVisible.MHR }); });
    this._btn.interpolate.addEventListener('click', () => { this.setInterpolate(!this.graph.interpolate); this._emit('button:interpolate', { on: this.graph.interpolate }); });
    this._btn.download.addEventListener('click', () => { this.download(); this._emit('button:download', {}); });

    // graph drag-to-pan + click (measure / new mark / edit)
    this._panState = null;
    this.graphEl.addEventListener('mousedown', (e) => this._graphMouseDown(e));

    // resizebar drag
    this.resizebar.addEventListener('mousedown', (e) => this._resizeDown(e));
  }

  /* --- scroll / paging ---------------------------------------------------- */
  _onScroll(v, fast) {
    const g = this.graph, s = g.signals;
    const sigLength = s.lastTime - s.start;
    g.time = Math.max(v * (sigLength - g.winlength + 120), 0) + s.start;
    g.redraw();
    this._emit('scroll', { time: g.time, value: v });
  }

  _updateScrollBar() {
    const g = this.graph, s = g.signals;
    if (s.start < 0 || !g.winlength) return;
    this.scrollBar.setPageRatio(g.winlength / (s.lastTime - s.start + 120));
    this.scrollBar.setValue((g.time - s.start) / (s.lastTime - s.start - g.winlength + 120), false);
  }

  nextpage() {
    const g = this.graph, s = g.signals;
    let t = g.time + g.winlength - 60;
    const tmax = s.lastTime - g.winlength + 120;
    if (t > tmax) t = tmax;
    g.time = Math.max(t, s.start);
    g.redraw();
    this._updateScrollBar();
    this._emit('scroll', { time: g.time });
  }

  previouspage() {
    const g = this.graph, s = g.signals;
    let t = g.time - g.winlength + 60;
    if (t < s.start) t = s.start;
    g.time = t;
    g.redraw();
    this._updateScrollBar();
    this._emit('scroll', { time: g.time });
  }

  /* --- mouse interactions ------------------------------------------------- */
  _toggleMouseMode(kind) {
    const g = this.graph;
    const prev = g.mouseMode;
    if (g.mouseMode !== 'None') {
      g.removeMouseMode();
      for (const n of ['measure', 'addevent', 'addquestion']) this._btn[n].classList.remove('active');
    }
    if (kind === 'measure' && prev !== 'Measurer1' && prev !== 'Measurer2') {
      g.initializeMeasurer(); this._btn.measure.classList.add('active');
    } else if (kind === 'event' && prev !== 'NewMarkPostioning') {
      g.initializeNewMark(''); this._btn.addevent.classList.add('active');
    } else if (kind === 'question' && prev !== 'NewMarkPostioning') {
      g.initializeNewMark('Question'); this._btn.addquestion.classList.add('active');
    }
  }

  _graphMouseDown(e) {
    const g = this.graph;
    if (g.mouseMode === 'Measurer1') { g.initializeMeasurer2(); return; }
    if (g.mouseMode === 'Measurer2') { g.removeMouseMode(); g.initializeMeasurer(); return; }
    if (g.mouseMode === 'NewMarkPostioning') {
      for (const n of ['addevent', 'addquestion']) this._btn[n].classList.remove('active');
      if (e.which >= 2) { g.removeMouseMode(); e.preventDefault(); return; }
      g.newMarkEdit(e.shiftKey);
      return;
    }
    // None: editing or pan
    if (g.editingMark !== -1) {
      const r = g.eventTextEdit.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
        g.validateMark(e.shiftKey);
      }
      return;
    }
    const rect = this.graphEl.getBoundingClientRect();
    if (g.checkEditable(e.clientX - rect.left, e.clientY - rect.top)) return;
    // start panning
    this._panState = { x0: e.clientX, t0: g.time };
    this._panMove = (ev) => this._graphPan(ev);
    this._panUp = () => {
      document.removeEventListener('mousemove', this._panMove);
      document.removeEventListener('mouseup', this._panUp);
      this.graph.redraw();
    };
    document.addEventListener('mousemove', this._panMove);
    document.addEventListener('mouseup', this._panUp);
  }

  _graphPan(e) {
    const g = this.graph, s = g.signals;
    const deltaX = e.clientX - this._panState.x0;
    const secPerPx = g.winlength / g.graphWidth;
    let t = this._panState.t0 - secPerPx * deltaX;
    const tmax = s.lastTime - g.winlength + 120;
    if (t > tmax) t = tmax;
    if (t < s.start) t = s.start;
    g.time = t;
    g.redraw();
    this._updateScrollBar();
    this._emit('scroll', { time: g.time });
  }

  /* --- resizebar ---------------------------------------------------------- */
  _resizeDown(e) {
    const startH = this.host.clientHeight;
    const startY = e.clientY;
    const move = (ev) => { this.setHeight(startH + (ev.clientY - startY)); };
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      this._emit('heightChange', { height: this.host.clientHeight });
    };
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  }

  /* ====================================================================== *
   *  PUBLIC API
   * ====================================================================== */
  loadBuffer(arrayBuffer, ext = 'rcfm') {
    this._buffer = arrayBuffer;             // keep for download
    this._ext = (ext || 'rcfm').replace('.', '');
    this.graph.signals.loadBuffer(arrayBuffer, ext);
    if (this.graph.time === 0 || this.graph.time < this.graph.signals.start) {
      this.graph.time = this.graph.signals.start;
    }
    const span = this.graphEl.querySelector('.signalloss span');
    if (span) span.textContent = this.graph.signals.signalLoss();
    this.graph.redraw();
    this._updateScrollBar();
    return this;
  }

  loadMarkers(text) { this.graph.signals.loadMarkers(text); this.graph.redraw(); this._markersChanged(); return this; }

  setMarkers(list) { this.graph.signals.setMarks(list); this.graph.redraw(); this._markersChanged(); return this; }

  getMarkers() { return this.graph.signals.getMarks(); }

  /** Serialize markers to the on-disk marker-file format (7-digit sample + text). */
  markersText() {
    return this.getMarkers()
      .map((m) => String(m[0]).padStart(7, '0') + ' ' + m[1])
      .join('\n');
  }

  /** Trigger a client-side download of the recording and its marker file. */
  download(basename = 'recording') {
    const dl = (data, type, fname) => {
      const url = URL.createObjectURL(new Blob([data], { type }));
      const a = document.createElement('a');
      a.href = url; a.download = fname;
      document.body.appendChild(a); a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    if (this._buffer) dl(this._buffer, 'application/octet-stream', `${basename}.${this._ext}`);
    dl(this.markersText() + '\n', 'text/plain', `${basename}.marks`);
    return this;
  }

  /** Scroll to an epoch (>= 100000) or a fraction (0..1). */
  scrollTo(epochOrFraction) {
    const g = this.graph, s = g.signals;
    if (epochOrFraction >= 0 && epochOrFraction <= 1) {
      this._onScroll(epochOrFraction, false);
    } else {
      g.time = Math.min(Math.max(epochOrFraction, s.start), s.lastTime - g.winlength + 120);
      g.redraw();
      this._updateScrollBar();
      this._emit('scroll', { time: g.time });
    }
    return this;
  }

  setScale(cmPerMin) {
    this.graph.is3cm = cmPerMin === 3 ? 1 : 0;
    this._btn['3cm'].classList.toggle('active', !!this.graph.is3cm);
    this.graph.redraw();
    this._updateScrollBar();
    this._emit('scaleChange', { cmPerMin: this.graph.is3cm ? 3 : 1, is3cm: this.graph.is3cm });
    return this;
  }

  toggle3cm() { return this.setScale(this.graph.is3cm ? 1 : 3); }

  setHeight(px) {
    this.host.style.height = `${px}px`;
    if (this.graph.signals.start >= 0) this.graph.redraw();
    this._updateScrollBar();
    this._emit('heightChange', { height: px });
    return this;
  }

  setChannelVisible(name, visible) {
    this.channelVisible[name] = visible;
    if (name === 'MHR') this._btn.mhr.classList.toggle('active', visible !== false);
    this.graph.redraw();
    return this;
  }

  setChannels(list) { this.graph.channels = Array.isArray(list) ? list.slice() : null; this.graph.redraw(); return this; }

  setZonesVisible(on) {
    this.graph.displayMorpho = !!on;
    this._btn.zones.classList.toggle('active', !!on);
    this.graph.redraw();
    this._emit('zonesChange', { on: !!on });
    return this;
  }

  setInterpolate(on) {
    this.graph.interpolate = !!on;
    this._btn.interpolate.classList.toggle('active', !!on);
    this.graph.redraw();
    this._emit('interpolateChange', { on: !!on });
    return this;
  }

  /* --- event emitter + bridge -------------------------------------------- */
  on(event, cb) { (this._listeners[event] = this._listeners[event] || []).push(cb); return this; }

  off(event, cb) {
    if (!this._listeners[event]) return this;
    if (!cb) { delete this._listeners[event]; return this; }
    this._listeners[event] = this._listeners[event].filter((f) => f !== cb);
    return this;
  }

  _emit(event, detail) {
    detail = detail || {};
    (this._listeners[event] || []).forEach((cb) => { try { cb(detail); } catch (e) { /* noop */ } });
    // bridge to host (Python) — postMessage + optional injected sink.
    const msg = { source: 'fhrviewer', event, detail };
    try { if (window.parent && window.parent !== window) window.parent.postMessage(msg, '*'); } catch (e) { /* noop */ }
    try { if (this._messageSink) this._messageSink(msg); } catch (e) { /* noop */ }
    // also dispatch a CustomEvent on the host element
    this.host.dispatchEvent(new CustomEvent(`fhr-${event}`, { detail, bubbles: true }));
  }

  _markersChanged() { this._emit('markersChange', { markers: this.getMarkers() }); }
}

// Convenience: auto-upgrade any element with data-fhr-viewer (optional).
export function upgradeAll(root = document) {
  const out = [];
  root.querySelectorAll('[data-fhr-viewer]').forEach((el) => out.push(new FHRViewer(el)));
  return out;
}

export default FHRViewer;
