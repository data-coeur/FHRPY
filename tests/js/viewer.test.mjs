/*
 * Unit tests of fhrviewer.js — `npm test` runs them: Node >= 20 globs the
 * quoted pattern itself (`node --test 'tests/js/*.test.mjs'`), no browser and
 * no dependency. The DOM comes from ./dom_stub.mjs; the canvas context records
 * what is drawn so colours and geometry can be asserted.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { installDom, domEvent, canvasContexts } from './dom_stub.mjs';

const { document } = installDom();
const { FHRViewer, Signals } = await import('../../fhrpy/viewer/web/fhrviewer.js');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

const EPOCH = 1_800_000_000;
const MAGIC = 1234555;

/**
 * Synthetic recording (never real data): `samples` = [{fhr1, fhr2, mhr, toco, q}]
 * in bpm / units, encoded with a 4- or 8-byte header, 6 / 8 / 12 bytes per
 * sample, an optional legacy stream code word and `extra` trailing bytes
 * (a file still being written).
 */
function encode(samples, { header = 4, stride = 8, code = null, epoch = EPOCH, extra = 0 } = {}) {
  const b = new ArrayBuffer(header + (code ? 4 : 0) + samples.length * stride + extra);
  const v = new DataView(b);
  let o = 0;
  if (header === 8) { v.setUint32(0, MAGIC, true); v.setUint32(4, epoch, true); o = 8; }
  else { v.setUint32(0, epoch, true); o = 4; }
  if (code) { v.setUint32(o, code, true); o += 4; }
  for (const s of samples) {
    v.setUint16(o, (s.fhr1 || 0) * 4, true);
    v.setUint16(o + 2, (s.fhr2 || 0) * 4, true);
    if (stride === 6) { v.setUint8(o + 4, (s.toco || 0) * 2); v.setUint8(o + 5, s.q || 0); }
    else {
      v.setUint16(o + 4, (s.mhr || 0) * 4, true);
      v.setUint8(o + 6, (s.toco || 0) * 2);
      v.setUint8(o + 7, s.q || 0);
      if (stride === 12) { v.setUint16(o + 8, (s.fhri || 0) * 4, true); v.setUint16(o + 10, (s.baseline || 0) * 4, true); }
    }
    o += stride;
  }
  return b;
}
const flat = (n, fhr1 = 140) => Array.from({ length: n }, () => ({ fhr1, fhr2: 0, mhr: 0, toco: 30 }));
const seconds = (s) => flat(s * 4);
const range = (a, b) => Array.from({ length: b - a }, (_, i) => a + i);

function makeViewer(opts = {}, width = 1000, height = 300) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const v = new FHRViewer(host, { height: 220, interpolate: false, scale: 1, ...opts });
  // the stub has no layout: give the graph a size so that the axis gets drawn
  v.graph.container.clientWidth = width;
  v.graph.container.clientHeight = height;
  return { v, host, g: v.graph, ctx: v.graph.ctx };
}
const texts = (ctx) => ctx.calls.filter((c) => c.op === 'fillText');

/* ---------------------------------------------------------------- decoder */

test('decoder: the header length is detected by divisibility in the real cases (#14)', () => {
  const s = new Signals();
  // 4-byte header (epoch only), 6 B/sample: FHRMA dataset and acquisition `.fhr`
  s.loadBuffer(encode(flat(12), { header: 4, stride: 6 }), 'fhr');
  assert.equal(s.bytesBySample, 6);
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  assert.equal(s.RCF1[0], 140);
  assert.equal(s.Q.length, 12);
  // 8-byte header (magic + epoch): recorder `.rcfm`
  s.loadBuffer(encode(flat(12), { header: 8, stride: 8 }), 'rcfm');
  assert.equal(s.bytesBySample, 8);
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  assert.equal(s.TOCO[0], 30);
  // 8-byte header followed by the legacy stream code word
  s.loadBuffer(encode(flat(12), { header: 8, stride: 8, code: 1234567 }), 'rcfm');
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  assert.equal(s.RCF1[11], 140);
  // a file still being written (a partial sample at the end): the preference of the extension applies
  s.loadBuffer(encode(flat(12), { header: 4, stride: 6, extra: 3 }), 'fhr');
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  s.loadBuffer(encode(flat(12), { header: 8, stride: 8, extra: 3 }), 'rcfm');
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  // a 4-byte header with 8-byte samples also divides as "8 + code word": the word must really be one
  s.loadBuffer(encode(flat(12), { header: 4, stride: 8 }), 'rcfm');
  assert.equal(s.start, EPOCH);
  assert.equal(s.RCF1.length, 12);
  // empty or truncated buffers do not throw
  s.loadBuffer(new ArrayBuffer(0), 'fhr');
  assert.equal(s.RCF1.length, 0);
  s.loadBuffer(new ArrayBuffer(3), 'rcfm');
  assert.equal(s.RCF1.length, 0);
});

test('decoder: opts.bytesPerSample / opts.headerBytes and the per-call layout override the extension rule (#14)', () => {
  const buf = encode(flat(10).map((x, i) => ({ ...x, mhr: 80 + i })), { header: 4, stride: 8 });
  // OpenCTG's `.fhr` is 8 bytes/sample with MHR: said once at construction…
  const { v } = makeViewer({ bytesPerSample: 8 });
  v.loadBuffer(buf, 'fhr');
  assert.equal(v.graph.signals.bytesBySample, 8);
  assert.equal(v.graph.signals.RCFm[3], 83);
  assert.equal(v.graph.signals.RCF1.length, 10);
  // …or per call
  const { v: v2 } = makeViewer();
  v2.loadBuffer(buf, 'fhr', { bytesPerSample: 8 });
  assert.equal(v2.graph.signals.RCFm[3], 83);
  // FHRPY's default is untouched: `.fhr` stays 6 bytes/sample without MHR
  v2.loadBuffer(encode(flat(10), { header: 4, stride: 6 }), 'fhr');
  assert.equal(v2.graph.signals.bytesBySample, 6);
  assert.equal(v2.graph.signals.RCFm.length, 0);
  // a forced header length is obeyed even when detection would say otherwise
  const { v: v3 } = makeViewer({ headerBytes: 8 });
  v3.loadBuffer(encode(flat(10), { header: 8, stride: 8 }), 'rcfm');
  assert.equal(v3.graph.signals.start, EPOCH);
  v3.loadBuffer(encode(flat(10), { header: 4, stride: 8 }), 'rcfm');
  assert.equal(v3.graph.signals.start, 140 * 4);     // read from byte 4: the first sample's FHR1 word
  v3.loadBuffer(encode(flat(10), { header: 4, stride: 6 }), 'fhr', { headerBytes: 4 });
  assert.equal(v3.graph.signals.start, EPOCH);
  assert.equal(v3.graph.signals.RCF1.length, 10);
});

test('decoder: the bundled example_recording.fhr (4-byte header, 6 B/sample) is decoded from the right offset (#14)', (t) => {
  const file = readFileSync(path.join(root, 'examples', 'example_recording.fhr'));
  const buf = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);
  const s = new Signals();
  s.loadBuffer(buf, 'fhr');
  assert.equal(s.bytesBySample, 6);
  assert.equal(s.start, 0);                                   // anonymised epoch
  assert.equal(s.RCF1.length, (file.byteLength - 4) / 6);
  const v = new DataView(buf);
  for (let i = 0; i < 40; i++) assert.equal(s.RCF1[i], v.getUint16(4 + i * 6, true) / 4);
  const plausible = (arr) => arr.filter((x) => x === 0 || (x >= 50 && x <= 210)).length / arr.length;
  const good = plausible(s.RCF1);
  s.loadBuffer(buf, 'fhr', { headerBytes: 8 });                // what the viewer assumed before
  const bad = plausible(s.RCF1);
  t.diagnostic(`FHR1 samples on the 50-210 grid: header 4 -> ${good.toFixed(3)}, header 8 -> ${bad.toFixed(3)}`);
  assert.ok(good > 0.99, `header 4: ${good}`);
  assert.ok(bad < good, `header 8: ${bad}`);
});

/* ------------------------------------------------------------ labels, scale */

test('opts.labels translates the tooltips and captions; missing keys keep the English defaults (#15)', () => {
  const { host } = makeViewer({ labels: {
    previouspage: 'Page précédente', 'scale.text': '3cm<br>/min', 'mhr.text': 'RCM',
    follow: 'Suivre le direct', resizebar: 'Glisser pour changer la hauteur',
  } });
  assert.equal(host.querySelector('.btn-previouspage').title, 'Page précédente');
  assert.equal(host.querySelector('.btn-nextpage').title, 'Next page');
  assert.equal(host.querySelector('.btn-scale').innerHTML, '3cm<br>/min');
  assert.equal(host.querySelector('.btn-mhr').innerHTML, '− RCM');
  assert.equal(host.querySelector('.btn-follow').title, 'Suivre le direct');
  assert.equal(host.querySelector('.resizebar').title, 'Glisser pour changer la hauteur');
  const { host: plain } = makeViewer();
  assert.ok(plain.querySelector('.btn-follow').title.startsWith('Follow live'));
  assert.equal(plain.querySelector('.resizebar').title, 'Drag to resize the viewer height');
});

test('opts.scale / setScale switch between 1 and 3 cm/min (already upstream, pinned here)', () => {
  const { v, g } = makeViewer({ scale: 3 });
  v.loadBuffer(encode(seconds(3600)), 'rcfm');
  assert.equal(g.is3cm, 1);
  const w3 = g.winlength;
  const events = [];
  v.on('scaleChange', (e) => events.push(e.cmPerMin));
  v.setScale(1);
  assert.equal(g.is3cm, 0);
  assert.ok(Math.abs(g.winlength - 3 * w3) < 1e-6);
  assert.deepEqual(events, [1]);
});

/* ------------------------------------------------------------------ delays */

const FM20 = { doppler: 1, scalp: 0, mecg: 0, mhrToco: 6, mhrOximeter: 12.5, toco: null };

test('opts.delays / setDelays: each channel is moved earlier by the delay of its own sensor, the file never (#16)', () => {
  // FHR1 by Doppler and FHR2 by scalp both show a burst at samples 10..19; the MHR by SpO2 at 60..69.
  const samples = Array.from({ length: 100 }, (_, i) => ({
    fhr1: i >= 10 && i < 20 ? 140 : 0, fhr2: i >= 10 && i < 20 ? 150 : 0, mhr: i >= 60 && i < 70 ? 80 : 0, toco: 30,
    q: (i >= 10 && i < 20 ? 0x01 | 0x04 | 0x08 : 0) | (i >= 60 && i < 70 ? 0x10 : 0),
  }));
  const { v, g } = makeViewer();
  v.loadBuffer(encode(samples, { header: 4, stride: 8 }), 'rcfm');
  const s = g.signals;
  const where = (name, arr) => g._displayArray(name, arr).map((x, i) => (x > 0 ? i : -1)).filter((i) => i >= 0);
  // without delays nothing moves: the raw arrays themselves are drawn
  assert.equal(v.getDelays(), null);
  assert.equal(g._displayArray('FHR1', s.RCF1), s.RCF1);
  assert.deepEqual(where('FHR1', s.RCF1), range(10, 20));
  // with the FM20 delays: Doppler 1 s = 4 samples earlier, scalp not at all, SpO2 pulse 12.5 s = 50 samples earlier
  v.setDelays(FM20);
  assert.deepEqual(where('FHR1', s.RCF1), range(6, 16));
  assert.deepEqual(where('FHR2', s.RCF2), range(10, 20));
  assert.deepEqual(where('MHR', s.RCFm), range(10, 20));
  // unknown delay (null) = raw; the tail left by a shift is blank; the file is untouched
  assert.equal(g._displayArray('TOCO', s.TOCO), s.TOCO);
  assert.ok(g._displayArray('MHR', s.RCFm).slice(50).every((x) => x === 0));
  assert.equal(s.RCF1[10], 140);
  assert.equal(s.RCF1[6], 0);
  // every drawn channel goes through the display array (what drawSigFast iterates)
  assert.equal(g._activeChannels().find((c) => c.name === 'FHR1').arr[6], 140);
  // MHR from the Toco transducer (isTOCOMHR bit): 6 s = 24 samples; from a maternal ECG (sensor marker): reference
  v.loadBuffer(encode(samples.map((x) => ({ ...x, q: x.q | (x.mhr ? 0x20 : 0) })), { header: 4, stride: 8 }), 'rcfm');
  assert.deepEqual(where('MHR', g.signals.RCFm), range(36, 46));
  v.loadBuffer(encode(samples, { header: 4, stride: 8 }), 'rcfm');
  v.loadMarkers('0000000 £Purple=Maternal ECG\n');
  assert.deepEqual(where('MHR', g.signals.RCFm), range(60, 70));
  // changing the sensor marker alone re-aligns the channel: the cache keys on the
  // version of the marks, not on how many there are
  v.setMarkers([[0, '£Purple=SpO2 pulse']]);
  assert.deepEqual(where('MHR', g.signals.RCFm), range(10, 20));
  // live update: the appended samples are shifted too (the cache follows the data)
  v.loadBuffer(encode([...samples, { fhr1: 130, q: 0x01 }], { header: 4, stride: 8 }), 'rcfm');
  assert.equal(g._displayArray('FHR1', g.signals.RCF1)[96], 130);
  // accepted at construction, announced, and back to raw
  assert.deepEqual(makeViewer({ delays: FM20 }).v.getDelays(), FM20);
  const events = [];
  v.on('delaysChange', (e) => events.push(e.delays));
  v.setDelays(null);
  assert.deepEqual(events, [null]);
  assert.deepEqual(where('FHR1', g.signals.RCF1), [...range(10, 20), 100]);
});

/* --------------------------------------------------------------- time zone */

test('opts.timeZone / setTimezone: the axis follows the IANA zone, DST included; an unknown zone falls back (#17)', () => {
  const { v, g, ctx } = makeViewer({ timeZone: 'Asia/Tokyo' });
  // 1755000000 = 2025-08-12 12:00:00 UTC -> 21:00 in Tokyo (no DST), 14:00 in Paris (CEST)
  v.loadBuffer(encode(seconds(3600), { epoch: 1755000000 }), 'rcfm');
  const labels = () => texts(ctx).map((c) => c.text).filter((t) => /^\d\dh\d\d$/.test(t));
  ctx.calls.length = 0; g.redraw();
  assert.equal(labels()[0], '21h10');
  assert.ok(labels().every((l) => l.startsWith('21h') || l.startsWith('22h')));
  const events = [];
  v.on('timezoneChange', (e) => events.push([e.offsetSeconds, e.timeZone]));
  ctx.calls.length = 0; v.setTimezone('Europe/Paris');
  assert.equal(labels()[0], '14h10');
  ctx.calls.length = 0; v.setTimezone(0);
  assert.equal(labels()[0], '12h10');
  ctx.calls.length = 0; v.setTimezone(3600);
  assert.equal(labels()[0], '13h10');
  ctx.calls.length = 0; v.setTimezone('Nowhere/Land');   // unknown: back to the offset, no exception
  assert.equal(labels()[0], '13h10');
  assert.deepEqual(events, [[0, 'Europe/Paris'], [0, null], [3600, null], [3600, null]]);
});

/* ----------------------------------------------------------------- markers */

test('markers: `§` never drawn nor editable, `£!` red and protected, `£` blue, free markers orange and editable (#18)', () => {
  const { v, g, ctx } = makeViewer();
  v.loadMarkers('0000000 §monitor model=M1350A serial=DE12345678\n0000040 £!Monitor failure 503\n0000080 £Red=Doppler\n0000120 Labour starts\n');
  // the stub has no layout: give the graph a geometry by hand and draw the markers alone
  g.graphWidth = 1000; g.winlength = 1200; g.BorderLeft = 0; g.BorderTop = 0; g.graphHeight = 300;
  ctx.calls.length = 0; g.drawMarks();
  const drawn = texts(ctx).map((c) => [c.text, c.style]);
  assert.ok(!drawn.some(([t]) => /monitor model|DE12345678|M1350A/.test(t)));
  assert.deepEqual(drawn, [['Monitor failure 503', '#c2483b'], ['Red=Doppler', '#0000FF'], ['Labour starts', '#FFBB00']]);
  assert.equal(g.markRects.length, 3);
  const [failure, doppler, free] = g.markRects;
  assert.equal(g.checkEditable(failure.x, failure.y), false);
  assert.equal(g.checkEditable(doppler.x, doppler.y), false);
  assert.equal(g.checkEditable(free.x, free.y), true);
  assert.equal(g.editingMark, 3);      // index in the full list: the § line counts, it is just never drawn
  assert.equal(v.getMarkers().length, 4);
});

test('markers: `§` lines alone do not show the markers toggle; `§` and `£!` survive markersText() (#18)', () => {
  const { v, host } = makeViewer();
  v.loadBuffer(encode(seconds(600)), 'rcfm');
  v.loadMarkers('0000000 §monitor model=M1350A serial=X\n');
  assert.equal(host.querySelector('.btn-markers').style.display, 'none');
  v.loadMarkers('0000000 §monitor model=M1350A serial=X\n0000040 £!Monitor failure 503\n');
  assert.equal(host.querySelector('.btn-markers').style.display, '');
  assert.equal(v.markersText(), '0000000 §monitor model=M1350A serial=X\n0000040 £!Monitor failure 503');
});

test('marker editing: Enter validates, Escape cancels, blur validates once, a typed line break becomes \\r (#20)', () => {
  const { v, g } = makeViewer();
  v.loadBuffer(encode(seconds(3600)), 'rcfm');
  const changes = [];
  v.on('markersChange', (e) => changes.push(e.markers.map((m) => m[1])));
  const ta = g.eventTextEdit;
  const newMark = () => { g.initializeNewMark(''); g.newMark.vline.setAttributeNS(null, 'x1', '500'); g.newMarkEdit(false); };
  // Enter validates (no line break inserted)
  newMark();
  assert.notEqual(g.editingMark, -1);
  ta.value = 'test';
  const enter = domEvent('keydown', { key: 'Enter' });
  ta.dispatchEvent(enter);
  assert.equal(enter.defaultPrevented, true);
  assert.equal(g.editingMark, -1);
  assert.equal(ta.style.display, 'none');
  assert.deepEqual(v.getMarkers().map((m) => m[1]), ['test']);
  assert.equal(changes.length, 1);
  // Escape cancels: the mark being created disappears, nothing is announced
  newMark();
  ta.value = 'draft';
  ta.dispatchEvent(domEvent('keydown', { key: 'Escape' }));
  assert.equal(g.editingMark, -1);
  assert.deepEqual(v.getMarkers().map((m) => m[1]), ['test']);
  assert.equal(changes.length, 1);
  // blur validates; a second blur (the hidden field losing focus) touches nothing; `\n` -> `\r`
  newMark();
  ta.value = 'epidural\nstarted';
  ta.dispatchEvent(new Event('blur'));
  ta.dispatchEvent(new Event('blur'));
  assert.equal(g.editingMark, -1);
  assert.deepEqual(v.getMarkers().map((m) => m[1]).sort(), ['epidural\rstarted', 'test']);
  assert.equal(changes.length, 2);
  // Escape on an existing mark restores its text
  g.redraw();
  const rect = g.markRects[0];
  assert.equal(g.checkEditable(rect.x, rect.y), true);
  ta.value = 'changed';
  ta.dispatchEvent(domEvent('keydown', { key: 'Escape' }));
  assert.deepEqual(v.getMarkers().map((m) => m[1]).sort(), ['epidural\rstarted', 'test']);
  assert.equal(changes.length, 2);
});

test('the reference cursor (crosshair + 30 bpm x 15 s box) leaves the graph with the pointer (#20)', () => {
  const { v, g } = makeViewer();
  v.loadBuffer(encode(seconds(600)), 'rcfm');
  g.svg.dispatchEvent(domEvent('mousemove', { clientX: 300, clientY: 100 }));
  assert.ok(g.svg.querySelector('rect'));
  g.svg.dispatchEvent(domEvent('mouseleave'));
  assert.equal(g.svg.querySelector('rect'), null);
  assert.equal(g.svg.querySelector('line'), null);
});

/* ------------------------------------------------------------------- print */

test('print(): cmPerMin 3 triples the pages; paper, header and footer land in the PDF; A4 by default (#19)', async () => {
  const { v } = makeViewer();
  v.loadBuffer(encode(seconds(3600)), 'rcfm');
  const capture = async (opts) => {
    let blob = null;
    const saved = URL.createObjectURL, savedRevoke = URL.revokeObjectURL;
    URL.createObjectURL = (b) => { blob = b; return 'blob:test'; };
    URL.revokeObjectURL = () => {};
    try { v.print(opts); } finally { URL.createObjectURL = saved; URL.revokeObjectURL = savedRevoke; }
    const text = Buffer.from(await blob.arrayBuffer()).toString('latin1');
    return { text, type: blob.type, pages: (text.match(/\/Type \/Page\b(?!s)/g) || []).length };
  };
  const a4 = await capture({});
  assert.equal(a4.type, 'application/pdf');
  assert.ok(a4.text.startsWith('%PDF-'));
  assert.ok(a4.text.includes('/MediaBox [0 0 842 595]'));
  assert.ok(a4.pages >= 2, `${a4.pages} pages`);
  // a print with no text options is the one this viewer always made: no page numbers
  assert.ok(!a4.text.includes(') Tj'));
  const numbered = await capture({ pageNumbers: true });
  assert.ok(numbered.text.includes(`(page 1/${numbered.pages}) Tj`));
  const fast = await capture({ cmPerMin: 3 });
  assert.ok(fast.pages >= 2.5 * a4.pages, `${fast.pages} pages at 3 cm/min vs ${a4.pages}`);
  const letter = await capture({ paper: 'letter', header: ['Bed 3 — Jane (Doe)', 'started 12:00'], footer: 'FHRPY print' });
  assert.ok(letter.text.includes('/MediaBox [0 0 792 612]'));
  assert.ok(letter.text.includes('/BaseFont /Helvetica'));
  assert.ok(letter.text.includes('(Bed 3 \\227 Jane \\(Doe\\)) Tj'));
  assert.ok(letter.text.includes('(started 12:00) Tj'));
  assert.ok(letter.text.includes('(FHRPY print) Tj'));
  // the header block brings "page i/n" with it, and pageNumbers can veto it
  assert.ok(letter.text.includes(`(page 1/${letter.pages}) Tj`));
  const quiet = await capture({ header: ['Bed 3'], pageNumbers: false });
  assert.ok(quiet.text.includes('(Bed 3) Tj') && !quiet.text.includes('/n) Tj'));
});

/* ------------------------------------------------------------- follow live */

test('follow live: locked on the live end across loads, released by the user, re-attached by the control (#22)', () => {
  const { v, g, host } = makeViewer({ follow: true });
  const btn = host.querySelector('.btn-follow');
  // the control sits at the right end of the scrollbar row, after the track that holds the thumb
  const row = host.querySelector('.fhr-viewer-scrollbar');
  assert.ok(row.children[0].classList.contains('scrollbarTrack'));
  assert.ok(row.children[0].querySelector('.scrollbarDragger'));
  assert.equal(row.children[row.children.length - 1], btn);
  assert.ok(btn.classList.contains('active'));
  const scrolls = [], follows = [];
  v.on('scroll', (e) => scrolls.push(e));
  v.on('followChange', (e) => follows.push(e.on));
  const end = (sec) => g.signals.start + sec - g.winlength + 120;
  v.loadBuffer(encode(seconds(3600)), 'rcfm');
  assert.ok(g.winlength > 600 && g.winlength < 3600);
  assert.equal(g.time, end(3600));
  assert.deepEqual(scrolls.at(-1), { time: end(3600), source: 'follow' });
  v.loadBuffer(encode(seconds(7200)), 'rcfm');
  assert.equal(g.time, end(7200));
  // thumb at the far right (not exactly 1: the ratio divides two differences of
  // epoch-scale seconds, whose last bits are lost — a sub-pixel offset)
  assert.ok(v.scrollBar.value > 0.999999 && v.scrollBar.value <= 1);
  // the user goes back: following is released and the next load leaves the view alone
  v.previouspage();
  assert.equal(v.getFollow(), false);
  assert.ok(!btn.classList.contains('active'));
  assert.deepEqual(follows, [false]);
  const t = g.time;
  v.loadBuffer(encode(seconds(10800)), 'rcfm');
  assert.equal(g.time, t);
  // the control re-attaches (jump to the end, highlighted); a second click releases
  btn.click();
  assert.equal(v.getFollow(), true);
  assert.equal(g.time, end(10800));
  assert.deepEqual(follows, [false, true]);
  btn.click();
  assert.equal(v.getFollow(), false);
  // navigating back to the live end re-arms following, as chat / log viewers do
  v.previouspage();
  assert.equal(v.getFollow(), false);
  while (g.time < end(10800)) v.nextpage();
  assert.equal(v.getFollow(), true);
  // a programmatic scrollTo() does not change the state: the next load returns to the end
  v.scrollTo(g.signals.start);
  assert.equal(v.getFollow(), true);
  v.loadBuffer(encode(seconds(10801)), 'rcfm');
  assert.equal(g.time, end(10801));
  // a change of paper speed changes the window: the live end stays in view
  v.setScale(3);
  assert.equal(g.time, end(10801));
  // off by default
  assert.equal(makeViewer().v.getFollow(), false);
  // a recording shorter than the window is always "at the live end": paging it
  // must not arm following on its own, and must not release an explicit one
  const short = makeViewer();
  short.v.loadBuffer(encode(seconds(60)), 'rcfm');
  assert.ok(short.g.signals.lastTime - short.g.signals.start + 120 <= short.g.winlength);
  short.v.nextpage();
  short.v.previouspage();
  assert.equal(short.v.getFollow(), false);
  short.v.setFollow(true);
  short.v.nextpage();
  assert.equal(short.v.getFollow(), true);
});

/* -------------------------------------------------------------- MHR button */

test('the MHR toggle wears the colour of the MHR curve and says what the next click does (#23)', () => {
  const { v, host } = makeViewer();
  const b = host.querySelector('.btn-mhr');
  assert.equal(b.style.color, '#FF00FF');
  assert.equal(b.innerHTML, '− MHR');
  assert.ok(b.classList.contains('active'));
  b.click();
  assert.equal(v.channelVisible.MHR, false);
  assert.equal(b.innerHTML, '+ MHR');
  assert.ok(!b.classList.contains('active'));
  v.setChannelVisible('MHR', true);
  assert.equal(b.innerHTML, '− MHR');
  assert.ok(b.classList.contains('active'));
});

/* ------------------------------------------------------------------- paper */

test('white paper; the label chip on the 160 line is white above the band edge and grey below (#24)', () => {
  const { v, g, ctx } = makeViewer();
  v.loadBuffer(encode(seconds(1800)), 'rcfm');
  ctx.calls.length = 0; g.redraw();
  const fills = ctx.calls.filter((c) => c.op === 'fillRect');
  assert.deepEqual([fills[0].style, fills[0].x, fills[0].y, fills[0].w, fills[0].h], ['#FFFFFF', 0, 0, g.TotalWidth, g.TotalHeight]);
  assert.ok(!ctx.calls.some((c) => c.style === '#EEFFEE'));
  const yA = g.BorderTop + ((210 - 160) / 160) * g.RCFHeight;   // the 160 line = upper edge of the safe band
  // the chips painted right before a label's text (narrow fills, unlike the paper and the band)
  const chipsBefore = (label) => {
    const i = ctx.calls.findIndex((c) => c.op === 'fillText' && c.text === label);
    assert.ok(i > 0, `label ${label} drawn`);
    const out = [];
    for (let j = i - 1; j >= 0 && ctx.calls[j].op === 'fillRect' && ctx.calls[j].w < 100; j--) out.unshift(ctx.calls[j]);
    return out;
  };
  const c160 = chipsBefore('160');
  assert.equal(c160.length, 2);
  assert.equal(c160[0].style, '#FFFFFF');
  assert.ok(c160[0].y < yA && c160[0].y + c160[0].h > yA);         // the whole chip, white, across the edge
  assert.equal(c160[1].style, '#F0F0F0');
  assert.ok(Math.abs(c160[1].y - yA) < 1e-9);                        // grey starts at the edge…
  assert.ok(Math.abs((c160[1].y + c160[1].h) - (c160[0].y + c160[0].h)) < 1e-9);   // …and ends with the chip
  const c200 = chipsBefore('200');
  assert.equal(c200.length, 1);
  assert.equal(c200[0].style, '#FFFFFF');
  const c140 = chipsBefore('140');                                   // fully inside the band: grey all over
  assert.equal(c140.length, 2);
  assert.equal(c140[1].h, c140[0].h);
});

/* -------------------------------------------------- print geometry & paper */

/** Capture the PDF `print()` hands to the browser, as latin1 text plus its page count. */
async function capturePdf(v, opts) {
  let blob = null;
  const saved = URL.createObjectURL, savedRevoke = URL.revokeObjectURL;
  URL.createObjectURL = (b) => { blob = b; return 'blob:test'; };
  URL.revokeObjectURL = () => {};
  try { v.print(opts); } finally { URL.createObjectURL = saved; URL.revokeObjectURL = savedRevoke; }
  const text = Buffer.from(await blob.arrayBuffer()).toString('latin1');
  return { text, pages: (text.match(/\/Type \/Page\b(?!s)/g) || []).length };
}

const PT_PER_CM = 28.3465;
const A4_HEIGHT_PT = 595;
/** What a page keeps for the header block and the footer (PRINT_*_RESERVE_PT). */
const A4_FREE_PT = A4_HEIGHT_PT - (20 + 8 + 8 * 11 + 26) - 16;

test("printGeometry(): the scales come from the graph's own ratios, and a wider FHR range clamps to the page (#27)", () => {
  const { v } = makeViewer();
  v.loadBuffer(encode(seconds(1800)), 'rcfm');
  // Default 50-210 bpm over the 2/3 of the graph the FHR takes: 8 cm at 20 bpm/cm,
  // 4 cm of TOCO for 0-100, i.e. 25 units/cm — derived, never assumed twice.
  const g = v.printGeometry();
  assert.equal(g.bpmPerCm, 20);
  assert.ok(Math.abs(g.fhrHeightCm - 8) < 1e-6, `${g.fhrHeightCm} cm of FHR`);
  assert.ok(Math.abs(g.tocoHeightCm - 4) < 1e-6, `${g.tocoHeightCm} cm of TOCO`);
  assert.equal(g.tocoRange, 100);
  assert.ok(Math.abs(g.tocoPerCm - 25) < 1e-6);
  assert.equal(g.cmPerMin, 1);
  // The strip is the graph PLUS the band that carries the time axis.
  assert.ok(Math.abs(g.stripHeightCm - (g.graphHeightCm + 15 / 37.8)) < 1e-9);
  // The speed button stretches the time axis; the vertical scale does not move.
  const fast = v.printGeometry({ cmPerMin: 3 });
  assert.equal(fast.cmPerMin, 3);
  assert.equal(fast.bpmPerCm, 20);

  // A range wider than the default would run the strip off the sheet: the paper
  // wins, and every announced scale follows what it can hold — the speed too,
  // since the time window is derived from the vertical scale.
  v.setRange(30, 250);
  const wide = v.printGeometry({ paper: 'A4' });
  assert.ok(wide.stripHeightCm * PT_PER_CM <= A4_FREE_PT + 1e-9);
  assert.ok(wide.bpmPerCm > 20);
  assert.ok(Math.abs(wide.tocoPerCm - 100 / wide.tocoHeightCm) < 1e-9);
  assert.ok(Math.abs(wide.cmPerMin - 20 / wide.bpmPerCm) < 1e-9);
  assert.ok(wide.cmPerMin < 1, `${wide.cmPerMin} cm/min`);
});

test('print(): the strip is placed at the height printGeometry() announces, between header and footer (#27)', async () => {
  const { v } = makeViewer();
  v.loadBuffer(encode(seconds(1800)), 'rcfm');
  const placement = (text) => {
    const m = /q ([\d.]+) 0 0 ([\d.]+) ([\d.]+) ([\d.]+) cm \/Im Do Q/.exec(text);
    return { width: +m[1], height: +m[2], x: +m[3], y: +m[4] };
  };
  const plain = await capturePdf(v, {});
  const box = placement(plain.text);
  assert.ok(Math.abs(box.height - v.printGeometry().stripHeightCm * PT_PER_CM) < 0.5, `${box.height} pt`);
  // A clamped strip still sits above the footer line and below the header block.
  v.setRange(30, 250);
  const header = [[{ text: 'Bed 3 — ', bold: true }, { text: 'Jane Doe' }], 'started 12:00'];
  const wide = await capturePdf(v, { paper: 'A4', header, footer: 'FHRPY print' });
  const clamped = placement(wide.text);
  assert.ok(Math.abs(clamped.height - v.printGeometry({ paper: 'A4' }).stripHeightCm * PT_PER_CM) < 0.5);
  assert.ok(clamped.y > 16, `strip bottom at ${clamped.y} pt, above the footer`);
  assert.ok(clamped.y + clamped.height <= A4_HEIGHT_PT - 20 - (8 + header.length * 11) + 0.5);
});

test('print(): axis, figures, chips and line widths measure on paper what they measure on screen (#27)', () => {
  const { v, g, ctx } = makeViewer();
  v.loadBuffer(encode(seconds(1800)), 'rcfm');
  const SCREEN_PX_PER_CM = 37.8, A4_WIDTH_CM = 27;
  ctx.calls.length = 0;
  g.redraw();
  const screen = ctx.calls.slice();
  const before = canvasContexts.length;
  v.print({ paper: 'A4', header: ['x'], footer: '', fillLastPage: true });
  // The print draws on offscreen canvases of its own: keep the widest one.
  const printCtx = canvasContexts.slice(before).sort((a, b) => b.canvas.width - a.canvas.width)[0];
  const printed = printCtx.calls;
  const printPxPerCm = printCtx.canvas.width / A4_WIDTH_CM;
  assert.ok(printPxPerCm > SCREEN_PX_PER_CM, 'the strip really is oversampled');

  /** The distinct values of one kind of screen-pixel size, in centimetres. */
  const inCm = (calls, pxPerCm, pick, keep = () => true) =>
    [...new Set(calls.map(pick).filter((x) => Number.isFinite(x)).map((x) => +(x / pxPerCm).toFixed(3)))]
      .filter(keep).sort((a, b) => a - b);
  const fontPx = (c) => (c.op === 'font' ? parseFloat(c.text) : NaN);
  assert.ok(inCm(screen, SCREEN_PX_PER_CM, fontPx).length > 1);
  assert.deepEqual(inCm(printed, printPxPerCm, fontPx), inCm(screen, SCREEN_PX_PER_CM, fontPx));
  // The chips the bpm / mmHg figures sit in (a chip kept at screen height on an
  // oversampled surface clips the digits it holds).
  const chipPx = (c) => (c.op === 'fillRect' ? c.h : NaN);
  const small = (cm) => cm < 1;
  const printedChips = inCm(printed, printPxPerCm, chipPx, small);
  assert.ok(printedChips.length > 0);
  assert.deepEqual(printedChips, inCm(screen, SCREEN_PX_PER_CM, chipPx, small));
  // And the line widths: grid, curves and frame keep their weight in millimetres.
  const widthPx = (c) => (c.op === 'lineWidth' ? c.w : NaN);
  const printedWidths = inCm(printed, printPxPerCm, widthPx);
  assert.ok(printedWidths.length > 1);
  assert.deepEqual(printedWidths, inCm(screen, SCREEN_PX_PER_CM, widthPx));
  // The band under the trace that carries the time axis, too.
  const axisBand = (calls, canvas, pxPerCm) =>
    (canvas.height - calls.filter((c) => c.op === 'fillText').at(-1).y) / pxPerCm;
  assert.ok(Math.abs(axisBand(printed, printCtx.canvas, printPxPerCm)
    - axisBand(screen, ctx.canvas, SCREEN_PX_PER_CM)) < 1e-3);
});

test('print(): bold runs, a logo and the WinAnsi 0x80-0x9F block reach the PDF; the xref stays intact (#27)', async () => {
  const { v } = makeViewer();
  v.loadBuffer(encode(seconds(1800)), 'rcfm');
  /** Every cross-reference offset lands on the header of the object it numbers. */
  const assertXref = (pdf) => {
    const startxref = +/startxref\s+(\d+)/.exec(pdf)[1];
    const table = /xref\s+0 (\d+)\s([\s\S]*)/.exec(pdf.slice(startxref));
    const offsets = [...table[2].matchAll(/(\d{10}) \d{5} [nf]/g)].map((m) => +m[1]);
    assert.equal(offsets.length, +table[1]);
    offsets.slice(1).forEach((o, i) => assert.match(pdf.slice(o, o + 12), new RegExp(`^${i + 1} 0 obj`)));
  };
  const logo = { jpeg: new Uint8Array([0xff, 0xd8, 0xff, 0xd9]), width: 120, height: 34, heightPt: 22 };
  // A label is bold, the value it introduces is not; « Maternité du Cœur »
  // carries the ligature the 0x80-0x9F block encodes, and a value typed on two
  // lines must not swallow the rest of the line.
  const header = [
    [{ text: 'Maternité du Cœur — ', bold: true }, { text: 'Bed 3' }],
    [{ text: 'Comment: ', bold: true }, { text: 'first\nsecond' }],
    'plain line',
  ];
  const withLogo = await capturePdf(v, { paper: 'A4', header, footer: '20 € — “quoted”', logo });
  assert.ok(withLogo.text.includes('/BaseFont /Helvetica-Bold'));
  assert.ok(withLogo.text.includes(`/Subtype /Image /Width ${logo.width}`));
  assert.ok(withLogo.text.includes('/Lo 5 0 R'));
  assert.match(withLogo.text, /\/Lo Do/);
  assert.ok(withLogo.text.includes('/F2 10 Tf (Maternit\\351 du C\\234ur \\227 ) Tj'));   // œ = 0x9c, — = 0x97
  assert.ok(withLogo.text.includes('/F1 10 Tf (Bed 3) Tj'));
  assert.ok(withLogo.text.includes('(first second) Tj'));       // the newline is a space, not a broken string
  assert.ok(withLogo.text.includes('(plain line) Tj'));          // a bare string is still a line
  assert.ok(withLogo.text.includes('(20 \\200 \\227 \\223quoted\\224) Tj'));   // euro and typographic quotes
  assertXref(withLogo.text);

  // Without a logo the numbering does not move: object 5 is `null` and nothing is painted.
  const bare = await capturePdf(v, { paper: 'A4', header, footer: '' });
  assert.ok(bare.text.includes('5 0 obj\nnull'));
  assert.ok(!bare.text.includes('/Lo 5 0 R'));
  assert.ok(!/\/Lo Do/.test(bare.text));
  assertXref(bare.text);
});
