# Changelog

All notable changes to FHRPY. The project is pre-release: entries accumulate
under *Unreleased* until the first validated release is tagged.

## Unreleased (branch `dev`)

### Viewer — `fhrpy/viewer/web/fhrviewer.js`, `fhrviewer.css`

Ported from OpenCTG's vendored copy (data-coeur/OpenCTG#175) as **options with
unchanged defaults**, plus the new requests of the same issue:

- **Header length auto-detection** (4 / 8 / 8 + legacy code word) by divisibility
  of the body, the rule of `fhrpy.io.read_fhr`; new options `headerBytes` (4 | 8)
  and `bytesPerSample` (6 | 8 | 12), also per call as
  `loadBuffer(buffer, ext, {bytesPerSample, headerBytes})`. Fixes the decoding
  of 4-byte-header files such as `examples/example_recording.fhr`, previously
  read from the wrong offset. `Signals` is exported for tests. (#14)
- **`labels`** option: translated tooltips and captions of the toolbar. (#15)
- **`delays`** option, `setDelays()` / `getDelays()`, event `delaysChange`:
  per-sensor estimation delays compensated at display time from each sample's
  Q byte; the printed strip follows; the file is never modified. (#16)
- **`timeZone`** option and `setTimezone('Europe/Paris')`: IANA zone for the
  time axis, DST-aware; `setTimezone(seconds)` unchanged. Python: `timezone=`
  and `set_timezone()` accept a name. (#17)
- **Marker conventions**: `£!…` drawn in red (protected alert), `§…` never drawn
  nor editable (protected metadata); both kept by `markersText()` / `save_markers()`. (#18)
- **`print()` options**: `cmPerMin` (1 | 3), `paper` (A4 | letter | legal),
  `header` lines and `footer` as real PDF text, `fillLastPage`. `page i/n` comes
  with the header block and `pageNumbers` forces it either way, so a `print()`
  with no options still produces the PDF this viewer always made.
  Python: `print(cm_per_min=…, **options)`. (#19)
- **Marker editing**: Enter validates, Escape cancels (`cancelMark()`), leaving
  the field validates; a typed line break is stored as the format's `\r`; the
  reference cursor is cleared when the pointer leaves the graph. (#20)
- **Resize handle**: uniform light-grey bar with a centred grip and a 6 px margin
  above it (the striped gradient read as transparent). (#21)
- **Follow live**: `follow` option, `setFollow()` / `getFollow()`, event
  `followChange`, a ⇥ toggle at the right end of the scrollbar row
  (`.fhr-viewer-scrollbar` now holds `.scrollbarTrack` + `.btn-follow`); while
  on, every `loadBuffer()` keeps the live end in view. Python: `set_follow()`. (#22)
- **MHR toggle** drawn in the MHR curve colour with a `−` / `+` prefix. (#23)
- **White paper** on screen and print; the FHR label chips take the colour of
  what they cover, so the label on the 160 line is white above the safe band and
  grey inside it. (#24)
- **Printed strip at screen size**: `GraphPlot.uiScale` (1 = screen) multiplies
  every screen-pixel size — fonts, the chips the figures sit in, line widths and
  the band that carries the time axis — and `print()` sets it to its own
  oversampling ratio, so a printed text measures the millimetres the screen
  shows instead of half of them. (#27)
- **`printGeometry({paper, cmPerMin, bpmPerCm})`**: the vertical geometry of the
  printed strip in centimetres (`bpmPerCm`, `cmPerMin`, `fhrHeightCm`,
  `tocoHeightCm`, `tocoRange`, `tocoPerCm`, `graphHeightCm`, `stripHeightCm`),
  derived from the ratios `resize()` uses instead of a hard-coded 12.63 cm that
  forgot the time-axis band and shrank every scale by ~3 %. `print()` takes the
  strip height from it; an FHR range too wide for the sheet clamps the strip and
  the returned scales follow, the paper speed included. (#27)
- **`print()` header block**: a line may be a list of `{text, bold}` runs (bold
  key label, plain value — chained `Tj` in one `BT`/`ET`, `/F2` Helvetica-Bold
  added to the page resources), and `logo` (`{jpeg, width, height, heightPt}`)
  opens the block with a rasterised mark. Objects 1-5 are now fixed (`null` for
  the logo when there is none, so the numbering never moves). A bare string line
  and a `print()` with no options behave exactly as before. (#27)
- **`pdfText()` encodes the whole of WinAnsi**: the 0x80-0x9F block (`€`, `œ`,
  `Œ`, `Ÿ`, `“ ”`, `•`, `–`, `—`) was sent to `?` — "Maternité du Cœur" printed
  as "Maternité du C?ur" — and a control character (a newline typed in a form
  value) reached a PDF literal string raw, swallowing the rest of the line; it
  becomes a space. (#27)

### Tests

- `npm test` → `node --test 'tests/js/*.test.mjs'`: browser-free unit tests of the viewer
  with a small DOM stub (no dependency). (#25) The stub's canvas context also
  records `font` and `lineWidth` assignments, so what the strip measures on
  paper can be asserted against what it measures on screen. (#27)
- `e2e/viewer_options.spec.ts`: Playwright checks built from the current source
  (header detection in a real browser, paper and label pixels, follow control,
  MHR button, resize handle, labels).
- `tests/test_viewer_options.py`: the Python wrapper's new options and methods.

### Also

- `examples/viewer_demo.html` rebuilt: it inlines the viewer, so the committed
  demo — and `e2e/viewer.spec.ts`, which runs against it — were still exercising
  the pre-port code. The analysed payload and markers are untouched; only the
  inlined CSS and JS were refreshed.
- `docs/screenshots/issue175-viewer-options.png`: one frame with the white paper,
  the `£!` alert in red, the `£` sensor marker in blue (a `§` line loaded and
  never drawn), the MHR toggle in its curve's colour, the follow control lit at
  the right end of the scrollbar, and the resize handle set apart.
