---
name: matlab-parity
description: FHRPY signal functions must numerically match MATLAB; verify via Octave docker
metadata: 
  node_type: memory
  type: feedback
  originSessionId: d8b83999-ee33-49fe-9957-39a4696ba63e
---

Every signal-processing function ported from FHRMA must produce **exactly the
same output as MATLAB**. Verify numerical parity using an **Octave docker**
(set one up). If a function can't run in Octave, the human can run short MATLAB
snippets, or (heavier) provide a MATLAB license so the MATLAB docker can be
pulled — ask which they prefer (issue #8).

**Why:** the port must be a faithful, citable reimplementation of validated methods.

**How to apply:** write parity tests comparing NumPy output to MATLAB/Octave
reference output on the reference datasets. Note the gotcha: in FHRMA, srate=240
means cutoffs are in cycles/min (Hz = f/60); FHRMA annotations are in minutes,
FS annotations in 4 Hz samples. See [[ci-badge-tests]], [[fhrpy-project]].
