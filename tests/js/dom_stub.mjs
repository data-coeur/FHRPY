/*
 * dom_stub.mjs — the smallest DOM the viewer needs, so that `node --test` can
 * exercise fhrviewer.js without a browser and without any dependency.
 *
 * Elements carry a class list, a style bag, attributes, children, event
 * listeners and a bounding box; a canvas hands out a 2D context that RECORDS
 * what is drawn (fills, texts, and the fill colour in force) instead of
 * painting it, so tests can assert on colours and geometry.
 */
const SVGNS = 'http://www.w3.org/2000/svg';

class ClassList {
  constructor() { this.set = new Set(); }
  add(...c) { c.forEach((x) => this.set.add(x)); }
  remove(...c) { c.forEach((x) => this.set.delete(x)); }
  contains(c) { return this.set.has(c); }
  toggle(c, force) {
    const on = force === undefined ? !this.set.has(c) : !!force;
    if (on) this.set.add(c); else this.set.delete(c);
    return on;
  }
  toString() { return [...this.set].join(' '); }
}

function makeContext(canvas) {
  const ctx = {
    canvas, fillStyle: '', strokeStyle: '', lineWidth: 1, font: '', textAlign: '', textBaseline: '',
    imageSmoothingEnabled: true, calls: [],
  };
  for (const m of ['clearRect', 'beginPath', 'moveTo', 'lineTo', 'stroke', 'fill', 'closePath']) ctx[m] = () => {};
  ctx.fillRect = (x, y, w, h) => ctx.calls.push({ op: 'fillRect', x, y, w, h, style: ctx.fillStyle });
  ctx.fillText = (text, x, y) => ctx.calls.push({ op: 'fillText', text: String(text), x, y, style: ctx.fillStyle });
  ctx.measureText = (t) => ({ width: 8 * String(t).length });
  return ctx;
}

function parseSelector(sel) {
  const m = /^([a-zA-Z]*)(?:\.([\w-]+))?$/.exec(sel.trim());
  if (!m) throw new Error(`selector not supported by the stub: ${sel}`);
  return [m[1] ? m[1].toUpperCase() : null, m[2] || null];
}

export class Element {
  constructor(tag, ns = null) {
    this.tagName = tag.toUpperCase();
    this.namespaceURI = ns;
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.style = {};
    this.classList = new ClassList();
    this.dataset = {};
    this._listeners = {};
    this._text = '';
    this._html = '';
    this.value = '';
    this.scrollHeight = 0;
    this._cw = null;
    this._ch = null;
  }

  get className() { return this.classList.toString(); }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get textContent() { return this._text; }
  set textContent(v) { this._text = String(v); }
  get innerHTML() { return this._html; }
  set innerHTML(v) {
    this._html = String(v);
    for (const c of this.children) c.parentNode = null;
    this.children = [];
    // Enough of a parser for the viewer: `<canvas class="…"></canvas><svg class="…"></svg>`.
    const re = /<(canvas|svg|div)\b([^>]*)>/g;
    let m;
    while ((m = re.exec(this._html))) {
      const el = new Element(m[1], m[1] === 'svg' ? SVGNS : null);
      const cls = /class="([^"]*)"/.exec(m[2]);
      if (cls) el.className = cls[1];
      this.appendChild(el);
    }
  }

  // Layout: sizes are set by the test (`el.clientWidth = …`) or read from an
  // inline `width: NNNpx` / `height: NNNpx` (the offscreen print box).
  get clientWidth() {
    if (this._cw != null) return this._cw;
    const m = /(?:^|;)\s*width:\s*(\d+)px/.exec(this.style.cssText || '');
    return m ? +m[1] : 0;
  }
  set clientWidth(v) { this._cw = v; }
  get clientHeight() {
    if (this._ch != null) return this._ch;
    const m = /height:\s*(\d+)px/.exec(this.style.cssText || '');
    return m ? +m[1] : 0;
  }
  set clientHeight(v) { this._ch = v; }

  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.children.push(c); return c; }
  append(...cs) { cs.forEach((c) => this.appendChild(c)); }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) { this.children.splice(i, 1); c.parentNode = null; } return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }

  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this.className = v; }
  getAttribute(k) { return k === 'class' ? this.className : (k in this.attributes ? this.attributes[k] : null); }
  setAttributeNS(_ns, k, v) { this.setAttribute(k, v); }
  getAttributeNS(_ns, k) { return this.getAttribute(k); }

  addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); }
  removeEventListener(type, fn) { this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(ev) {
    if (!ev.target) {
      try { Object.defineProperty(ev, 'target', { value: this, configurable: true }); } catch (e) { /* noop */ }
    }
    for (const fn of (this._listeners[ev.type] || []).slice()) fn.call(this, ev);
    if (ev.bubbles && this.parentNode) this.parentNode.dispatchEvent(ev);
    return !ev.defaultPrevented;
  }

  getBoundingClientRect() {
    const w = this.clientWidth, h = this.clientHeight;
    return { x: 0, y: 0, left: 0, top: 0, width: w, height: h, right: w, bottom: h };
  }

  querySelectorAll(sel) {
    const [tag, cls] = parseSelector(sel);
    const out = [];
    const walk = (el) => {
      for (const c of el.children) {
        if ((!tag || c.tagName === tag) && (!cls || c.classList.contains(cls))) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }

  focus() {}
  select() {}
  blur() { this.dispatchEvent(new Event('blur')); }
  click() { this.dispatchEvent(new Event('click', { bubbles: true })); }

  getContext() { return this._ctx || (this._ctx = makeContext(this)); }
  toDataURL() { return 'data:image/jpeg;base64,' + Buffer.from([0xff, 0xd8, 0xff, 0xd9]).toString('base64'); }
}

/** Install `document` / `window` globals; returns them. Call once per test file. */
export function installDom() {
  const body = new Element('body');
  const docListeners = {};
  const document = {
    body,
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag, ns),
    querySelector: (sel) => body.querySelector(sel),
    querySelectorAll: (sel) => body.querySelectorAll(sel),
    addEventListener: (t, fn) => (docListeners[t] = docListeners[t] || []).push(fn),
    removeEventListener: (t, fn) => { docListeners[t] = (docListeners[t] || []).filter((f) => f !== fn); },
    dispatchEvent: (ev) => { for (const fn of (docListeners[ev.type] || []).slice()) fn(ev); return true; },
  };
  const window = {
    document, frameElement: null,
    getSelection: () => ({ removeAllRanges() {} }),
    addEventListener() {}, removeEventListener() {},
  };
  window.parent = window;   // no host frame: the postMessage bridge stays quiet
  globalThis.document = document;
  globalThis.window = window;
  return { document, window };
}

/** A DOM-like event with extra fields (`key`, `clientX`…), cancelable by default. */
export function domEvent(type, fields = {}, init = {}) {
  return Object.assign(new Event(type, { bubbles: true, cancelable: true, ...init }), fields);
}
