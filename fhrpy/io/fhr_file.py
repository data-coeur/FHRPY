"""Readers and writers for FHRMA binary FHR files (``.fhr`` / ``.fhrm`` /
``.rcf`` / ``.rcfm`` / ``.dat``).

This is a faithful Python port of the MATLAB ``fhropen.m`` / ``fhrsave.m``
routines from the FHRMA toolbox, kept numerically identical so that outputs can
be checked for parity against MATLAB/Octave.

File layout (little-endian), all signals sampled at **4 Hz**:

``.dat`` (PhysioNet CTU-UHB)
    No header. Interleaved ``uint16`` pairs ``[FHR1, TOCO] / 100``.

``.fhr`` / ``.rcf`` (6 bytes/sample)
    Header then, per sample: ``FHR1`` ``uint16``/4, ``FHR2`` ``uint16``/4,
    ``TOCO`` ``uint8``/2, ``Q`` ``uint8`` (quality/sensor flags).

``.fhrm`` / ``.rcfm`` (8 bytes/sample)
    As above plus ``MHR`` ``uint16``/4 inserted after ``FHR2``.

Analysed variants append ``FHRi`` ``uint16``/4 and ``baseline`` ``uint16``/4
(adding 4 bytes/sample), as written by ``fhrsave`` with the optional arguments.

Header size
    The MATLAB toolbox dataset files store a **4-byte** header (a single
    ``uint32`` Unix timestamp). The hospital *recorder* files (``.rcfm``) store
    an **8-byte** header (a ``uint32`` magic followed by the ``uint32``
    timestamp). ``read_fhr`` auto-detects the header size by default.

The quality byte ``Q`` packs 7 flags (bit 0 = LSB), matching ``fhrsave``:
``Q1 | isECG1<<1 | Q2<<2 | isECG2<<3 | Qm<<4 | isTOCOMHR<<5 | isIUP<<6``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

__all__ = ["FHRRecord", "read_fhr", "write_fhr", "encode_fhr"]

# Bit layout of the quality/sensor byte (matches fhrsave.m).
_Q_FLAGS = (
    ("Q1", 0),
    ("isECG1", 1),
    ("Q2", 2),
    ("isECG2", 3),
    ("Qm", 4),
    ("isTOCOMHR", 5),
    ("isIUP", 6),
)


@dataclass
class FHRRecord:
    """A decoded FHR recording. All signals are 1-D ``float64`` arrays at 4 Hz."""

    fhr1: np.ndarray
    fhr2: np.ndarray
    mhr: np.ndarray
    toco: np.ndarray
    timestamp: int = 0
    fs: float = 4.0
    fhri: np.ndarray | None = None
    baseline: np.ndarray | None = None
    infos: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.fhr1)

    @property
    def duration_s(self) -> float:
        return len(self.fhr1) / self.fs


def _decode_quality(q: np.ndarray) -> dict:
    """Decode the per-sample quality byte into boolean flag arrays."""
    q = q.astype(np.uint8)
    return {name: ((q >> bit) & 1).astype(bool) for name, bit in _Q_FLAGS}


def _sample_layout(ext: str) -> tuple[int, bool]:
    """Return ``(n_u16_channels, has_mhr)`` for the base (non-analysed) stride."""
    ext = ext.lower()
    if ext in (".fhrm", ".rcfm"):
        return 3, True  # FHR1, FHR2, MHR + (TOCO u8, Q u8)
    if ext in (".fhr", ".rcf"):
        return 2, False  # FHR1, FHR2 + (TOCO u8, Q u8)
    raise ValueError(f"unsupported extension for layout: {ext!r}")


def _detect_header(size: int, stride: int, prefer: int) -> int:
    """Pick the header size (in bytes) for which the body divides evenly.

    ``prefer`` is tried first; falls back to the other common header size.
    """
    candidates = [prefer] + [h for h in (4, 8) if h != prefer]
    for h in candidates:
        if size >= h and (size - h) % stride == 0:
            return h
    # No clean fit: default to the preferred one (caller may truncate).
    return prefer


def read_fhr(filename: str | os.PathLike, header: str | int = "auto") -> FHRRecord:
    """Read a FHRMA binary FHR file into an :class:`FHRRecord`.

    Parameters
    ----------
    filename:
        Path to a ``.fhr`` / ``.fhrm`` / ``.rcf`` / ``.rcfm`` / ``.dat`` file.
    header:
        Header size in bytes (``4`` or ``8``), or ``"auto"`` (default) to detect
        it. ``.dat`` files have no header and ignore this argument.
    """
    filename = os.fspath(filename)
    ext = os.path.splitext(filename)[1].lower()
    with open(filename, "rb") as f:
        raw = f.read()

    if ext == ".dat":
        data = np.frombuffer(raw, dtype="<u2")
        data = data[: (len(data) // 2) * 2].reshape(-1, 2).astype(np.float64) / 100.0
        n = data.shape[0]
        return FHRRecord(
            fhr1=data[:, 0].copy(),
            fhr2=np.zeros(n),
            mhr=np.zeros(n),
            toco=data[:, 1].copy(),
            timestamp=0,
        )

    n_u16, has_mhr = _sample_layout(ext)
    stride = n_u16 * 2 + 2  # + TOCO(u8) + Q(u8)

    if header == "auto":
        prefer = 8 if ext in (".rcfm", ".rcf") else 4
        hdr = _detect_header(len(raw), stride, prefer)
    else:
        hdr = int(header)

    # Timestamp is the last uint32 of the header (offset hdr-4).
    timestamp = int(np.frombuffer(raw, dtype="<u4", count=1, offset=max(0, hdr - 4))[0]) if hdr >= 4 else 0

    body = raw[hdr:]
    nsamp = len(body) // stride
    body = body[: nsamp * stride]
    rows = np.frombuffer(body, dtype=np.uint8).reshape(nsamp, stride)

    u16 = rows[:, : n_u16 * 2].view("<u2").astype(np.float64) / 4.0
    fhr1 = u16[:, 0].copy()
    fhr2 = u16[:, 1].copy()
    mhr = u16[:, 2].copy() if has_mhr else np.zeros(nsamp)
    toco = rows[:, n_u16 * 2].astype(np.float64) / 2.0
    q = rows[:, n_u16 * 2 + 1]
    infos = _decode_quality(q) if has_mhr else {}

    return FHRRecord(
        fhr1=fhr1, fhr2=fhr2, mhr=mhr, toco=toco, timestamp=timestamp, infos=infos
    )


def encode_fhr(
    record: FHRRecord,
    *,
    with_mhr: bool | None = None,
    with_analysis: bool = False,
    header_bytes: int = 4,
) -> bytes:
    """Encode an :class:`FHRRecord` to FHRMA binary bytes (mirrors ``fhrsave.m``).

    With ``header_bytes=8`` a recorder-style header (zero ``magic`` +
    ``timestamp``) is written; the analysed ``.rcfa`` layout (12 bytes/sample,
    FHRi @8, baseline @10) is produced by ``with_mhr=True, with_analysis=True``.
    """
    if with_mhr is None:
        with_mhr = bool(np.any(record.mhr))

    n = len(record.fhr1)
    # Rebuild the quality byte from flag arrays if present.
    q = np.zeros(n, dtype=np.uint8)
    for name, bit in _Q_FLAGS:
        flag = record.infos.get(name)
        if flag is not None:
            q |= (np.asarray(flag, dtype=np.uint8) & 1) << bit

    out = bytearray()
    if header_bytes == 8:
        out += np.uint32(0).tobytes()  # magic placeholder (recorder format)
    out += np.uint32(record.timestamp).tobytes()

    def u16(x):
        return np.clip(np.round(np.asarray(x) * 4.0), 0, 65535).astype("<u2")

    fhr1 = u16(record.fhr1)
    fhr2 = u16(record.fhr2)
    mhr = u16(record.mhr) if with_mhr else None
    toco = np.clip(np.round(record.toco * 2.0), 0, 255).astype(np.uint8)
    if with_analysis:
        fhri = u16(record.fhri if record.fhri is not None else np.zeros(n))
        base = u16(record.baseline if record.baseline is not None else np.zeros(n))

    for i in range(n):
        out += fhr1[i].tobytes() + fhr2[i].tobytes()
        if with_mhr:
            out += mhr[i].tobytes()
        out += bytes((int(toco[i]), int(q[i])))
        if with_analysis:
            out += fhri[i].tobytes() + base[i].tobytes()

    return bytes(out)


def write_fhr(
    filename: str | os.PathLike,
    record: FHRRecord,
    *,
    with_mhr: bool | None = None,
    with_analysis: bool = False,
    header_bytes: int = 4,
) -> None:
    """Write an :class:`FHRRecord` to a FHRMA binary file (mirrors ``fhrsave.m``).

    By default writes a 4-byte (timestamp-only) header, matching the MATLAB
    toolbox. Set ``with_mhr`` to force/skip the MHR channel (defaults to whether
    the record carries a non-empty MHR). Set ``with_analysis`` to append the
    ``fhri``/``baseline`` channels.
    """
    filename = os.fspath(filename)
    data = encode_fhr(
        record, with_mhr=with_mhr, with_analysis=with_analysis, header_bytes=header_bytes
    )
    with open(filename, "wb") as f:
        f.write(data)


