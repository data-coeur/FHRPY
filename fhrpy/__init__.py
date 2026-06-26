"""FHRPY — Python toolbox for Fetal Heart Rate (FHR / cardiotocography) analysis.

A focused Python port of the MATLAB FHRMA toolbox providing:
  * the WMFB baseline method + morphological analysis (accelerations,
    decelerations, contractions);
  * the false-signal detection method (``fhrma-fs``);
  * I/O for ``.fhr`` / ``.rcf`` / ``.rcfm`` files and the reference datasets;
  * a clean, PHP-free, Python-controllable web CTG viewer.

See https://github.com/data-coeur/FHRPY
"""

__version__ = "0.0.1"

__all__ = ["__version__"]
