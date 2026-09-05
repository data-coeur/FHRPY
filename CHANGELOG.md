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
  `header` lines and `footer` as real PDF text with `page i/n`, `fillLastPage`.
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

### Tests

- `npm test` → `node --test 'tests/js/*.test.mjs'`: browser-free unit tests of the viewer
  with a small DOM stub (no dependency). (#25)
- `e2e/viewer_options.spec.ts`: Playwright checks built from the current source
  (header detection in a real browser, paper and label pixels, follow control,
  MHR button, resize handle, labels).
- `tests/test_viewer_options.py`: the Python wrapper's new options and methods.
