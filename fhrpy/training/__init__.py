"""FHRPY training subpackage.

Preserved TensorFlow/Keras training sources for the false-signal (FS) models,
copied verbatim (with minimal renaming) from the FHRMA toolbox so the models can
be retrained later. See ``README.md`` in this directory.

These scripts require **TensorFlow 2** (and a TPU/GPU for any realistic run) and
are *not* imported here — importing :mod:`fhrpy` or :mod:`fhrpy.training` does
**not** pull in TensorFlow. Run the notebooks / ``4_FSScalp.py`` directly to
retrain. Inference (:mod:`fhrpy.falsesignal`) needs only NumPy/SciPy.
"""
