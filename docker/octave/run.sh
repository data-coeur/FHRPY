#!/usr/bin/env bash
# One-command entry point for the FHRPY <-> MATLAB(Octave) parity harness.
#
#   bash docker/octave/run.sh
#
# Builds the Octave image (first run pulls gnuoctave/octave:9.2.0 and installs
# the signal package -- a few minutes, one-off) and runs run_reference.m over:
#   * examples/example_recording.fhr            (always; = train01.fhr, ~58 min)
#   * a couple of short FHRMAdataset recordings  (if the dataset is present on
#     this machine at the known read-only path -- staged into out/extra_inputs/)
#
# Outputs land in docker/octave/out/ref_<name>.mat (gitignored). Then run:
#   python3 -m pytest -q tests/test_matlab_parity.py
#
# Env overrides:
#   FHRPY_DATASET_DIR  - dir holding extra .fhr files to also process
#   FHRPY_EXTRA_FILES  - explicit space-separated host paths of extra .fhr files
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
OUT="$HERE/out"
EXTRA="$OUT/extra_inputs"
mkdir -p "$OUT" "$EXTRA"

# --- Default dataset location (read-only reference, outside the repo) ---------
DATASET_DIR="${FHRPY_DATASET_DIR:-/home/samuelboudet/Projets/fhr-demo/matlab/src/FHRMA/FHRMAdataset}"

# Stage a couple of SHORT dataset recordings next to the example so the harness
# is self-contained at run time (we copy, never depend on the read-only path
# inside the container). train03 (~40 min) and train19 (~29 min) are small.
EXTRA_SRC=()
if [[ -n "${FHRPY_EXTRA_FILES:-}" ]]; then
  # shellcheck disable=SC2206
  EXTRA_SRC=(${FHRPY_EXTRA_FILES})
else
  for cand in "$DATASET_DIR/traindata/train03.fhr" "$DATASET_DIR/traindata/train19.fhr"; do
    [[ -f "$cand" ]] && EXTRA_SRC+=("$cand")
  done
fi

# Container-side file list (always includes the repo example).
CFILES="/work/repo/examples/example_recording.fhr"
for src in "${EXTRA_SRC[@]:-}"; do
  [[ -z "$src" ]] && continue
  base="$(basename "$src")"
  cp -f "$src" "$EXTRA/$base"
  CFILES="$CFILES /work/out/extra_inputs/$base"
  echo "staged $base"
done
export FHR_FILES="$CFILES"

echo "FHR_FILES (in container): $FHR_FILES"

# --- Build + run via docker-compose v1 ----------------------------------------
cd "$HERE"
echo ">>> docker-compose build (first run installs the signal package; slow once)"
docker-compose build
echo ">>> docker-compose run"
FHR_FILES="$FHR_FILES" docker-compose run --rm octave-reference

echo
echo "References written to: $OUT"
ls -1 "$OUT"/ref_*.mat 2>/dev/null || echo "(no ref_*.mat produced -- check the log above)"
echo
echo "Now compare against FHRPY:"
echo "    python3 -m pytest -q tests/test_matlab_parity.py"
