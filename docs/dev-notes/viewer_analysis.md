# FHR / CTG Cardiotocography Web Viewer — Technical Architecture

Source analysed (all in `/home/sam/Desktop/fhr-demo/web/src/old/js/` unless noted):
`fhr-source.js` (older monolith, 2019 lines — contains GraphPlot + Signals + FHRViewer + ScrollBar in one file),
`fhrviewer-source.js` (newer FHRViewer + ScrollBar only),
`fhrgraphplot-source.js` (newer GraphPlot only, has `is3cm`, periods, £-questions),
`fhrsignal-source.js` (newer Signals only, has mark-refresh polling),
`GetBinaryFile.js`, `jdataview.js`,
CSS: `/home/sam/Desktop/fhr-demo/web/src/css/fhrviewer.css`, `style.css`,
DOM template confirmed in `/home/sam/Desktop/fhr-demo/web/src/functions.php` lines 79–103.

NOTE ON DUPLICATION: `fhr-source.js` is a *single-file older build* that bundles GraphPlot+Signals+FHRViewer+ScrollBar. The newer split files (`fhrgraphplot-source.js`, `fhrsignal-source.js`, `fhrviewer-source.js`, `scrollbar-source.js`) supersede it and add: 3cm scaling, contraction/acc/dec period shading (`drawPeriods`/`fillSurface`), `£`-prefixed "Question" marks, `Start`/`End` cut-extract marks, premark buttons, and 5s mark-refresh polling. Re-implementation should follow the **split/newer** versions. Functions identical between the two are noted once.

---

## 1. Custom elements / Web components, attributes, lifecycle

These are NOT real custom elements (no `customElements.define`). They are plain tag names (`<fhr-viewer>`, `<fhr-viewer-scrollbar>`) used as CSS/jQuery selectors and upgraded imperatively on `$(document).ready`.

### Bootstrap (fhrviewer-source.js lines 575–593)
```js
$(document).ready(function () {
    setWidth();                       // sizes .monito tiles for multi-monitor grids m22/m23/m34
    $(window).resize(setWidth);
    var i=0;
    $('fhr-viewer').each(function () {
        var fhrViewer = new FHRViewer(this);   // one controller per <fhr-viewer>
        fhrViewerObjects[i++]=fhrViewer;       // global registry array
    });
});
```

### `<fhr-viewer>` — root element. DOM template (functions.php 79–103):
```html
<fhr-viewer data-file='...' data-3cm="false" data-full-parent="0" data-mode="normal" id='fhrviewerN'>
  <div class="graph">
     <canvas class="background-canvas"></canvas>   <!-- grid + signal curves (raster) -->
     <svg class="frontground-svg" xmlns="..."></svg> <!-- measurer/new-mark overlays (vector) -->
     <div class="signalloss">Perte de signal : <span>0</span> %</div>
  </div>
  <div class="controllers">
     <div class="controller-icons"> ...buttons... </div>
     <fhr-viewer-scrollbar data-pageratio='0.1' data-value='0'></fhr-viewer-scrollbar>
     <div class="patient-bar">...</div>
  </div>
  <div class="resizebar"></div>
</fhr-viewer>
```
A `<textarea class="eventTextEdit">` is appended into `.graph` at runtime by the GraphPlot constructor (used to type marker text).

### Attributes read by `FHRViewer` constructor (fhrviewer-source.js 4–26):
| Attribute | Default | Meaning |
|---|---|---|
| `data-mode` | `"normal"` | `"realtime"` enables live AJAX polling + a 1 Hz `RealTimeMove` follow timer (`setInterval(...,1000)`). |
| `data-3cm` | `"false"` | `"true"` ⇒ `graph.is3cm=true`: 3 cm/min paper speed (1/3 the seconds per screen) and activates `.btn-3cm`. |
| `data-full-parent` | `0` | `1` ⇒ viewer height = parent height − controllers height; hides resizebar. |
| `data-file` | `""` | filename passed to `signals.newRecordFromFile()`. |
| `data-php-reader-url` | `'./rcfphpreader/'` | (legacy, mostly unused). |
| `data-samples-to-display` | `0` | (legacy/unused in draw path). |
| `data-pageratio`, `data-value` | `0.1`, `0` | on `<fhr-viewer-scrollbar>`, initial thumb width / position. |

### Lifecycle (FHRViewer constructor tail, fhrviewer-source.js 513–551):
1. `new ScrollBar($('fhr-viewer-scrollbar'))`, `new GraphPlot($('div.graph'))`.
2. Wire DOM events (buttons, touch, resizebar, scrollbar `scrolling`, window resize/beforeprint).
3. Register signal callbacks: `signals.fileLoadedEvent = this.fileLoaded`, `signals.fileFullyLoadedEvent`, `signals.stateChanged`.
4. `graph.newQuestion`, `graph.newExtract` bound to FHRViewer methods.
5. `signals.newRecordFromFile(data-file)` → kicks off binary download chain.
6. If `realtime`: start `RealTimeMove` 1 s interval.

GraphPlot/Signals/ScrollBar each guard prototype definition with `if (typeof X.initialized == "undefined")` so methods are defined once on the prototype.

---

## 2. Binary file format(s): .rcf / .rcfm / .rcfa

### Extension → bytes/sample (fhrsignal-source.js 87–94, newRecordFromFile):
```js
if(filename ends 'r' or 'f') this.bytesBySample=6;   // .rcf / .fhr  → FHR1,FHR2,TOCO,qual
else if(ends 'm')            this.bytesBySample=8;   // .rcfm        → +MHR (RCFm)
else if(ends 'a')            this.bytesBySample=12;  // .rcfa        → +preprocessed FHR (RCFi) + baseline
```

### Three HTTP endpoints (all PHP, all to be REMOVED — see §5):
- `downloadhead.php?filename=` → header. Read by `fileHeadLoaded`.
- `downloadmarks.php?filename=` → text marks. Read by `fileMarkLoaded`.
- `downloaddata.php?deb=<byteOffset>&filename=` → sample data, streamed (progress callback). Read by `fileProgress`/`fileLoaded`.

### Header (fileHeadLoaded, fhrsignal-source.js 110–127):
```js
var view = new jDataView(objBinaryFile.Content, 0, len, true); // littleEndian=true
if(view.getUint32()==1234555) {        // magic number 0x0012D5BB validity check
    this.newRecord(view.getUint32());  // 2nd uint32 = start time = UNIX epoch SECONDS
}
```
So header = 8 bytes: `[magic uint32 = 1234555][startTime uint32 = epoch seconds]`.

### Data stream (fileProgress, fhrsignal-source.js 164–198):
```js
var code=view.getUint32();             // first 4 bytes of DATA payload
this.isRecording=(code == 1234567);    // 1234567 = still recording; (1234568 = finished)
view.seek(4 + bytesBySample*(RCF1.length - downloadedSampleBeforeUpdate));
for (i ...; i < Math.floor((len-4)/bytesBySample); i++) {
   if(bytesBySample==6)  addData(getUint16, getUint16, getUint8, getUint8);
   if(bytesBySample==8)  r=[u16,u16,u16,u8,u8];      addData(r0,r1, r3,r4, r2);
   if(bytesBySample==12) r=[u16,u16,u16,u8,u8,u16,u16]; addData(r0,r1, r3,r4, r2, r5, r6);
}
```

### Per-sample byte layout (little-endian), sampling rate `srate = 4 Hz` (Signals ctor):
| bytes/sample | fields in file order | maps to |
|---|---|---|
| **6** (.rcf/.fhr) | u16 FHR1, u16 FHR2, u8 TOCO, u8 qual | RCF1, RCF2, TOCO, (qual unused) |
| **8** (.rcfm) | u16 FHR1, u16 FHR2, **u16 MHR**, u8 TOCO, u8 qual | RCF1, RCF2, RCFm(MHR), TOCO, qual |
| **12** (.rcfa) | u16 FHR1, u16 FHR2, u16 MHR, u8 TOCO, u8 qual, **u16 FHRi**, **u16 baseline** | RCF1, RCF2, RCFm, TOCO, qual, RCFi(preprocessed), baselineRCF |

### Scaling (addData, fhrsignal-source.js 201–228):
```
RCF1f = u16/4;  RCF2f = u16/4;  RCFm = u16/4;  RCFi = u16/4;  baseline = u16/4;
TOCOf = u8/2;   // TOCO 0..200 raw → 0..100
lastTime += 1/srate;             // advance 0.25s per sample
if (RCF1f==0 && RCF2f==0) badSigPoints++;  // signal-loss counter
```
Signals stored as plain JS arrays: `RCF1, RCF2, RCFm, RCFi, baselineRCF, TOCO`. FHR value range used in plotting = 50..210 bpm (`minRCF/maxRCF`), TOCO 0..100 (`minTOCO/maxTOCO`).

### Filesize math = 32 bytes/sec:
8 bytes/sample (.rcfm) × 4 Hz = **32 bytes/sec**, matching the PHP filesize check. (.rcf=24 B/s, .rcfa=48 B/s.) Number of samples = `(filesize − 8 header) / bytesBySample`; duration seconds = samples/4.

### jdataview.js
Standard vjeux jDataView library. Used only for `getUint8/16/32` and `seek`. `objBinaryFile.Content` is a binary string built by `GetBinaryFile`/`bin2arr`. In a clean rewrite, replace with native `ArrayBuffer` + `DataView` (`fetch(...).arrayBuffer()`), which removes jdataview.js and GetBinaryFile.js entirely.

---

## 3. Canvas background grid + SVG frontground

Two stacked layers, both `position:absolute; left:0; top:0; width/height:100%` (fhrviewer.css 134–140):
- `canvas.background-canvas` — drawn via 2D context `this.ctx`. Holds the green CTG grid, axis labels, time ticks, the signal curves (rasterised), period shading, and marker text/vlines.
- `svg.frontground-svg` — interactive vector overlay for the measurer crosshairs and the in-progress "new mark" vline+label only.

### Geometry (resize, fhrgraphplot-source.js 38–57):
```
graphWidth  = canvas.width  - BorderLeft(0) - BorderRight(0)
graphHeight = canvas.height - BorderTop(0)  - BorderBottom(15)
RCFTOCOSpace = 0.05 * graphHeight                       // gap between FHR & TOCO panes
TOCOHeight   = 1/3 * (graphHeight - RCFTOCOSpace)
RCFHeight    = graphHeight - RCFTOCOSpace - TOCOHeight   // ≈ 2/3, the FHR pane
sizeof20bpm  = RCFHeight * 20 / (maxRCF-minRCF)          // px per 20 bpm
winlength    = graphWidth*60/sizeof20bpm / (1 + 2*is3cm) // SECONDS visible across width
```
`winlength` is THE key scaling number: seconds visible on screen. 1cm/min normal vs 3cm/min: divide by `(1+2*is3cm)` → 3× when `is3cm`. (In `fhr-source.js` the divisor is absent — that old build has no 3cm support.) Print mode (`resizeForPrint`) forces `winlength = 26*60/(1+2*is3cm)` and width `= 26*sizeof20bpm` (26 cm of paper).

### Vertical scale mapping (used everywhere curves/grid drawn):
- FHR sample value `v` (bpm) → `y = BorderTop + RCFHeight*(maxRCF - v)/(maxRCF-minRCF)`  (50–210 bpm over RCFHeight).
- TOCO value `v` → `y = BorderTop + RCFHeight + RCFTOCOSpace + TOCOHeight*(maxTOCO - v)/(maxTOCO-minTOCO)` (0–100 over TOCOHeight).
- X: `x = BorderLeft + sampleIndex * graphWidth / (srate * winlength)`; sample index `d = round((time-start)*srate)` is the left-edge sample.

### `drawAxes()` (fhrgraphplot-source.js 931–1065):
- `clearRect` whole canvas.
- Grey band `#F8F8F8` over the 50–100 bpm region (filled rect at `BorderTop+50*RCFHeight/160 … +50*RCFHeight/160`).
- **Vertical time lines** every 30 s (`/(1+is3cm*2)` spacing), heavy (`#AAFFAA` w=2) every minute (`j%(2+4*is3cm)==0`), thin every 30 s when `fullGrid`. Offset by `-(time%60)` so the grid scrolls with data.
- **Horizontal FHR lines** loop `j=0..32`, `ty=BorderTop+j*5*RCFHeight/160` ⇒ a line every 5 bpm; thick (`w=4`) at j==10 & j==20 (i.e. **160 and 110 bpm**, the normal band boundaries), medium every 10 bpm, thin every 5 bpm. Colour `#AAFFAA`.
- **FHR numeric labels** `(210 - 5*j)` for `j=2..32 step 4` → 200,180,...,60, repeated every 600 s column, drawn on white/`#F8F8F8` background boxes.
- **Horizontal TOCO lines** `j=0..9`, every 10 units; thick at j==8 (=20). Labels `(100-10*j)` every 600 s.
- **Time tick labels** along the bottom: `HHhMM` every `secGap=600/(1+is3cm)` seconds, computed from `time` as a real wall-clock `Date` (`t.setTime((floor(time/secGap+1)+i)*secGap*1000)`).
- Bottom black baseline `hline`.

Grid colour is `#AAFFAA` (light green) — classic CTG green paper.

### Signal curves
Three render paths (only two used now):
- **`drawSigFast()`** (708–795) — the active path (`redraw` calls it unconditionally now, line 1105 `if(true)`). Uses `ctx.beginPath()/moveTo/lineTo/stroke`, steps every 4 samples (1 s), `lineWidth=1`. Per-channel colour arrays selected by `bytesBySample`.
- **`drawSigPixel()`** (612–706) — precise per-pixel rasteriser via `getImageData`/custom `line()` Bresenham-ish writing into `imageData.data`, then `putImageData`. Slower; kept for non-fast redraws in the old monolith.
- **`drawSigSVG()`** (512–610) — builds an SVG `<path d=...>` appended to the svg layer. Test code, **not** called by `redraw`.

Channels & colours (drawSigFast):
- 6B: RCF1 `#FF0000` (red), RCF2 `#0000FF` (blue), TOCO `#000000`.
- 8B: + RCFm/MHR `#FF00FF` (magenta).
- 12B + morpho on: RCFi `#AAAAAA`, RCF1 red, RCF2 blue, RCFm magenta, baseline `#202020`; morpho off drops baseline.
Gap handling: a point is plotted only if `value>40 && !isNaN`; otherwise `y0=NaN` breaks the path (pen up) — see §7.

---

## 4. Scrolling / paging logic

### Time model
`graph.time` = wall-clock epoch seconds of the LEFT edge of the visible window. `signals.start`/`signals.lastTime` bound the record. Visible span = `winlength` seconds.

### ScrollBar component (scrollbar-source.js)
- Appends `<div class="scrollbarDragger"><div class="scrollbarDraggerBar"></div></div>`.
- State: `pageRatio` (thumb width fraction, clamped 0.05–1), `value` (0–1 position).
- `setPageRatio(r)` → thumb width `r*100%`, left `value*(1-r)*100%`.
- `setValue(v,follow,fast)` → clamps 0–1, sets `.scrollbarDragger` left, and if `follow` fires `this.container.trigger("scrolling",[v,fast])`.
- Drag: `mouseDownDragger`→`mouseMoveDragger` computes `deltaX/(width*(1-pageRatio))`, calls `setValue(...,true,fast=true)`. Click on track: `clickContainer` centres thumb on click X.
- External hooks: `'scrollingto'`→`externalScrollingTo`, `'changepageratio'`→`externalPageRatioChange` (let Python/host set value/ratio via attribute + event).

### FHRViewer.scroll (fhrviewer-source.js 137–146) — listens to `'scrolling'`:
```js
this.graph.time = Math.max(v*(sigLength - winlength + 120), 0) + signals.start;
this.graph.redraw(fast);
```
(+120 = 2 min of trailing slack so you can scroll slightly past the end.)

### updateScrollBar (79–84) — inverse, sets the thumb from current time:
```js
scrollBar.setPageRatio(winlength / (lastTime-start + 120));
scrollBar.setValue((time-start)/(lastTime-start-winlength+120), false);  // follow=false (no re-fire)
```

### Paging buttons
- `nextpage()` (237): `time += winlength-60` (one page minus 1 min overlap), clamped to end.
- `previouspage()` (252): `time -= winlength-60`, clamped to start.

### Pan / inertia (touch + mouse drag on the graph)
- `touchstart`/`graphClick`→`touchstartmove(x)` stores `initialTouchX`, `initialTouchTime`.
- `touchmovemove(x)` (213): `deltaX=x-initialTouchX`, `secondPerPixel=winlength/graphWidth`, `time=initialTouchTime - secondPerPixel*deltaX`, clamped, `redraw(true)` (fast) + `updateScrollBar`. Keeps last 3 (x,t) for velocity.
- `touchend`→`timingMove` runs a `setInterval(...,16ms)` inertial fling using a polynomial decay (lines 348–391) until velocity ≤0 or an edge is hit, then a final `redraw(false)`.

### scrollTo(x) (fhrgraphplot 1067) — pixel-shift optimisation: copies the still-valid portion of the old canvas into a buffer canvas and blits it shifted, only redrawing the newly-exposed strip when `|diffx|<=winlength` (else full `redraw`). Note: has a latent bug referencing `this.graph.time` inside GraphPlot.

---

## 5. Real-time / AJAX parts to REMOVE (PHP-free target)

All network I/O lives in **Signals** (fhrsignal-source.js / fhr-source.js) plus the two helpers in **GetBinaryFile.js**. To make it standalone+Python-driven, replace the whole download chain with a single in-memory load (e.g. `setData(buffer)` from a Python-served `fetch`).

Functions to strip / replace:
- `GetBinaryFile.js`: `getUTF8file()`, `GetBinaryFile()`, `bin2arr()` — XHR helpers. Replace with `fetch`.
- `Signals.newRecordFromFile` → calls `GetBinaryFile(...downloadhead.php...)`.
- `Signals.reQueryNewRecord` — re-polls header every 5 s waiting for a record (realtime).
- `Signals.fileHeadLoaded` — keep the *parsing* (magic 1234555 + start time) but drop the `setTimeout(reQueryNewRecord)` realtime retry and `getUTF8file(downloadmarks.php)` call.
- `Signals.fileMarkLoaded` / `reQueryMarks` / `fileMarkUpdated` — fetch + 5 s mark re-poll. Replace mark source with host-injected array.
- `Signals.fileProgress` — keep sample-decoding loop, but `code==1234567` "isRecording" + `stateChanged` realtime branches go away.
- `Signals.fileLoaded` — strip the `setTimeout(resendQuery / reQueryNewRecord)` realtime tail.
- `Signals.resendQuery` — incremental `downloaddata.php?deb=...` polling. Remove.
- `Signals.addMarkQuery` / `editMarkQuery` / `removeMarkQuery` — POST mark CRUD to PHP via `getUTF8file`. Replace with events to the host (Python) or a JS callback.
- `FHRViewer.RealTimeMove` + `setInterval(...,1000)` (514) — auto-follow-end in realtime. Remove or gate behind a flag.
- `FHRViewer.setPauseRealTime` / `.btn-RT` handling — realtime pause UI. Remove.
- `FHRViewer.updateSignal` (`container.on('update')` → `resendQuery`+`reQueryMarks`). Remove.
- `FHRViewer.stateChanged` (444–508) — huge PHP-form / `update-ajax.php` / `update-list.php` / patient-form reset block tied to the hospital app. **Delete entirely** (references `theform.*`, `$.ajax`, `setButtonInfoPatiente`, `.popuped-info-patiente`, `.NoMonitor`).
- `FHRViewer.btnFullScreen` → `window.location='file.php?...'`; `btnPrint` → `fileprint.php`; `newExtract` → `downloadextract.php`. These navigate to PHP pages — replace with host callbacks or remove.

Everything in **GraphPlot** (rendering, grid, measurer, marks geometry) and **ScrollBar** is PHP-free already.

---

## 6. Measure tool and Add-event tool

### Measure tool (`btn-measure`, `e.data.obj=="measure"`)
State machine in `graph.mouseMode`: `None → Measurer1 → Measurer2 → (click) back to Measurer1`.
- `initializeMeasurer()` (fhrgraphplot 104) creates SVG `measurer.hline`, `measurer.vline`, `measurer.textY`; sets `mouseMode="Measurer1"`, cursor `auto`.
- `mouseMove` in Measurer1 (242): tracks crosshair; if `mousey < RCFHeight+RCFTOCOSpace` it reads FHR `Y1=(RCFHeight-mousey)/RCFHeight*160+50` and shows `"<x> bpm"`, else TOCO `Y1=-(graphHeight-mousey)/TOCOHeight*100`. Stores `T1 = mousex/graphWidth*winlength + time` (time of point).
- `graphClick` while Measurer1 → `initializeMeasurer2()`: adds second crosshair (`hline2/vline2`) + delta labels `textDY` (Δbpm or ΔTOCO) and `textDX` (`<min>min<ss>` time delta between the two points). Click again resets to a fresh Measurer1.
- `removeMouseMode()` removes all SVG measurer elements and sets `mouseMode='None'`.

### Add-event / marker tool (`btn-addevent`, `btn-addquestion`, `btn-premark`, `btn-cut`)
`btnMouseMode` (fhrviewer-source.js 148) toggles button active states and calls `graph.initializeNewMark(defaultText)`:
- `btn-addevent` → `''`; `btn-addquestion` → `'Question'`; `btn-premark` → the button's own innerHTML (predefined label); `btn-cut` → alternates `'Start'`/`'End'` (this.startendcut toggles).
- `initializeNewMark(text)` (fhrgraphplot 175): colour `#0000FF` if text=="Question" or starts with `£`, else `#FFBB00`; creates SVG `newMark.textEvent` + `newMark.vline`; `mouseMode="NewMarkPostioning"`; cursor `text`.
- `mouseMove` in NewMarkPostioning moves the vline+label to the cursor.
- `graphClick` while NewMarkPostioning → `newMarkEdit(shiftKey)` (right-click `e.which>=2` cancels via `removeMouseMode`).

### `newMarkEdit(shifted)` (fhrgraphplot 203):
```js
samp = (newMark.vline.x1/graphWidth*winlength + time-start)*srate;   // sample index
if text=="Question": newQuestion(round(samp/4)); signals.addMarks(samp,"£Question");
else: editingMark = signals.addMarks(samp, text);
      // show eventTextEdit <textarea> at the mark x, prefilled, focused & selected
      // if text=="End": find latest "Start" mark < samp; newExtract(start/4, samp/4)  (PHP extract)
      // if text!="": validateMark(shifted)
```
`validateMark(shifted)` (325) → `signals.udpateMark(editingMark, textarea.val())`, hide textarea, `editingMark=-1`, redraw; if `shifted` immediately re-opens a new mark with same text (rapid multi-marking).
Clicking on an existing mark label (`checkEditable`, 297) re-opens its textarea for editing; empty text deletes the mark.

---

## 7. Missing points / signal loss / interpolation toggle

### Gap rendering (the "pen-up" rule)
In every draw routine the test is identical:
```js
if (SigRCF[j][d+s] > 40 && !isNaN(SigRCF[j][d+s])) { ...lineTo/moveTo... y0=y1; }
else  y0 = NaN;     // breaks the polyline → gap left blank
```
So any FHR value ≤40 bpm OR `0` (the file's "no signal" sentinel, since raw 0/4=0) is treated as missing and the curve is interrupted. `drawSigFast` additionally requires the previous 3 sub-samples >40 (line 756) to avoid drawing across short dropouts. TOCO uses only `!isNaN` (TOCO 0 is valid).

### Signal-loss metric (`Signals.signalLoss`, fhrsignal-source.js 64–84)
Counts samples where both RCF1==0 && RCF2==0 between the first and last non-null sample, returns a 0.1%-rounded percentage; displayed in `.signalloss span` by `FHRViewer.fileLoaded` (line 336).

### Where linear interpolation could be toggled
There is **no interpolation today** — gaps are simply not drawn. A clean reimplementation would add it at the per-channel plotting loop in `drawSigFast`/`drawSigPixel`: instead of resetting `y0=NaN` on a missing sample, optionally bridge across short gaps (e.g. when the gap length < N samples, `lineTo` the next valid point). Best done as a pre-pass `interpolate(channelArray, maxGap)` producing a filled copy, gated by a `this.interpolate` flag / `data-interpolate` attribute, applied to RCF1/RCF2/RCFm. The `RCFi` channel (12-byte .rcfa) is already a server-side preprocessed/cleaned FHR and effectively serves this role today.

---

## 8. User-facing controls / buttons & events fired

Buttons are inside `<div class="controller-icons">` (functions.php 87–95). Wiring at fhrviewer-source.js 532–543.

| Selector | Handler | Effect / event the Python wrapper should expose |
|---|---|---|
| `.btn-previouspage` | `previouspage()` | page back; should emit a "scroll/timechange" event with new `graph.time`. |
| `.btn-nextpage` | `nextpage()` | page forward; same. |
| `.btn-measure` (`{obj:'measure'}`) | `btnMouseMode` | enter/exit measure mode. |
| `.btn-addevent` (`{obj:'event'}`) | `btnMouseMode` | start a free-text marker. |
| `.btn-addquestion` (`{obj:'question'}`) | `btnMouseMode` | start a "Question" (£) marker → fires `newQuestion`. |
| `.btn-premark` (`{obj:'premark'}`) | `btnMouseMode` | start a predefined-label marker. |
| `.btn-cut` (`{obj:'cut'}`) | `btnMouseMode` | place Start/End cut marks → triggers extract. |
| `.btn-3cm` | `btn3cm()` | toggle 1cm↔3cm; **fires `container.trigger("change3cmScale", is3cm)`**. |
| `.btn-morpho` | `btnMorpho()` | toggle display of RCFi/baseline morpho channels + period shading. |
| `.btn-print` | `btnPrint()` | opens `fileprint.php` (remove). |
| `.btn-fullscreen` | `btnFullScreen()` | navigates to `file.php` (remove). |
| `.btn-RT` (realtime only) | toggled by `RealTimeMove`/`setPauseRealTime` | follow-live toggle (remove for offline). |

### Custom DOM events already emitted (jQuery `.trigger`) — the Python/host listener surface:
- **`scrolling`** `[value, fast]` — fired by ScrollBar on user scroll; FHRViewer listens to drive `graph.time`. (Primary "user moved the trace" signal.)
- **`scrollingto`**, **`changepageratio`** — *inbound* events the host can fire ON `<fhr-viewer-scrollbar>` to programmatically set position / thumb width (read from `data-value` / `data-pageratio`).
- **`resize`** `[height]` — fired by `resizeMouseUp` / `resizeTouchEnd` after the user drags the resizebar.
- **`newQuestion`** `[sec, start+sec]` — fired by `FHRViewer.newQuestion` when a Question marker is placed (the key annotation hook).
- **`change3cmScale`** `[is3cm]` — fired by `btn3cm`.
- **`update`** — *inbound*: host fires it to trigger `updateSignal()` (realtime refresh; remove offline).

For the rewrite, formalise these as `CustomEvent`s on `<fhr-viewer>`: `fhr-scroll {time}`, `fhr-marker-add/edit/remove {sample,text}`, `fhr-question {seconds}`, `fhr-scale-change {is3cm}`, `fhr-morpho-change {on}`, `fhr-resize {height}`, plus button-specific `fhr-page {dir}`.

---

## 9. Marker / annotation data structures

`Signals.Marks` = array of `[sampleIndex, text]` pairs (sampleIndex in samples @4 Hz; `sample/4` = seconds). Loaded from `downloadmarks.php` text, one mark per line: `parseInt(line.substr(0,7))` = sample (7-digit zero-padded), `line.substring(8)` = text (fhrsignal-source.js 130–136, 149–157).

Text conventions encode the marker type:
- Plain text → ordinary user event, colour `#FFBB00` (amber); `\r` splits into multiple stacked lines (drawMarks 374).
- Leading `£` → **Question** marker, colour `#0000FF` (blue); not editable inline, not POSTed as a normal mark.
- Leading `$` → **morphological period** (NOT a label, drawn as shaded zone by `drawPeriods`, skipped by `drawMarks`). Format: `$ <TYPE> <durationSamples>`:
  - `type = text.substring(2,5)` ∈ `CON` (contraction), `ACC` (acceleration), `DEC` (deceleration), `NTA`, `URS`.
  - `duration = parseInt(text.substring(6)) / srate` seconds.

CRUD: `addMarks(sample,text)` inserts sorted by sample, returns index, and `addMarkQuery` POSTs (unless "Question"). `udpateMark(n,t)` edits or, if `t==""`, removes (`removeMarkQuery` + splice). `editMarkQuery`/`removeMarkQuery` POST to PHP (replace with host callback).

`markRects` = array of `{x,y,w,h}` label hit-boxes recomputed each `drawMarks`, used by `checkEditable` for click-to-edit and by an overlap-avoidance loop that pushes labels down 5px until they stop intersecting (`intersectRect`).

---

## 10. TOCO / contraction display area & colour-zone overlays

The TOCO pane is the bottom 1/3 of the graph (`TOCOHeight`, below `RCFHeight + RCFTOCOSpace`), scale 0–100, drawn black. The acc/dec/contraction overlays already exist via `drawPeriods()` + `fillSurface()` (called by `redraw` before the signal curves), gated by `this.displayMorpho` (the `.btn-morpho` toggle).

### `drawPeriods()` (fhrgraphplot 416–471) iterates `$`-prefixed Marks and shades:
| `$ TYPE` | colour (RGBA, ~20% alpha) | region filled |
|---|---|---|
| `CON` contraction | `#99990033` | between TOCO curve and 0 baseline, in the TOCO pane (`fillSurface(TOCO, zeros, …, isRCF=0)`). |
| `ACC` acceleration | `#00FF0033` (green) | between RCFi and baselineRCF in the FHR pane (`fillSurface(RCFi, baselineRCF, …, isRCF=1)`). |
| `DEC` deceleration | `#FF000033` (red) | same RCFi↔baseline band, FHR pane. |
| `NTA` | `#55555533` (grey) | flat `fillRect` over full RCFHeight for the period span. |
| `URS` | `#55555533` (grey) | flat `fillRect` over full RCFHeight. |

### `fillSurface(Top,Bottom,S,E,isRCF)` (474–510)
Builds a closed polygon: forward along `Top[d+i]` from sample S→E, back along `Bottom[d+i]` E→S, then `fill()`. For RCF it uses `maxRCF/minRCF/RCFHeight` at `BorderTop`; for TOCO it uses `maxTOCO/minTOCO/TOCOHeight` at `BorderTop+RCFHeight+RCFTOCOSpace`. Clipped to the visible window (`E>d && S<d+winlength*srate`) and to array bounds.

The legend in `style.css` 470–497 confirms the colour codes (`.UC #99990033`, `.Acc #00FF0033`, `.Dec #FF000033`, `.Uperiod #55555533`, raw/preprocessed/baseline FHR strike-through legend items).

For new overlays (host-computed acc/dec/contraction zones from Python), the clean integration point is to push `$`-typed entries into `signals.Marks` (or a dedicated `signals.periods` array) and let `drawPeriods` shade them — no other change needed. The contraction zone overlay specifically targets the TOCO pane (`isRCF=0`), the acc/dec overlays target the FHR pane between the (cleaned) FHR `RCFi` and its `baselineRCF` — both only available with 12-byte `.rcfa` files (RCFi/baseline channels). For 6/8-byte files those channels are empty, so period shading for ACC/DEC needs a baseline supplied by the host.

---

## Re-implementation cheat-sheet (clean vanilla ES module, Python-driven)
- Real `customElements.define('fhr-viewer', …)` / `'fhr-viewer-scrollbar'`; move attrs to `observedAttributes` (`data-file`, `data-3cm`, `data-mode`, `data-pageratio`, `data-interpolate`).
- Replace XHR chain (GetBinaryFile/jdataview) with `fetch().arrayBuffer()` + native `DataView` little-endian. Header `[u32 magic=1234555][u32 startEpoch]`, then `[u32 code]` + N×{6|8|12}-byte samples @4 Hz; scale FHR/MHR `/4`, TOCO `/2`.
- Keep GraphPlot maths verbatim (geometry, `winlength`, grid, vertical mappings, `drawSigFast`, `drawPeriods`/`fillSurface`, measurer, marks). Drop jQuery for native DOM/`CustomEvent`.
- Delete all realtime/PHP CRUD/`stateChanged` form code; expose markers + periods as host-injected arrays and emit `CustomEvent`s for scroll/page/marker/question/scale/morpho/resize so Python can listen and persist.
