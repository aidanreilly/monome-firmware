"""Test helpers: encode capture streams and synthesise ADC signals (no hardware)."""
import numpy as np


def encode(blocks, decimated=False, end=True):
    """blocks: list of (index, values). Returns the byte stream the firmware sends."""
    out = bytearray()
    for i, vals in blocks:
        out.append(0xC0 | (i & 0x1F))
        for v in vals:
            if decimated:
                out += bytes([0x80 | (v >> 7), v & 0x7F])
            else:
                out += bytes([0x80 | (v >> 5), v & 0x1F])
    if end:
        out.append(0xFE)
    return bytes(out)


def pulse_blocks(tps, nblk, pulse_ticks, base=215.0, amp=14.0, width=2400.0, keep=None, seed=1):
    """Sampled signal with Gaussian pulses centred at the tick times in pulse_ticks.

    Returns [(index, values)] for blocks of 256 samples; keep(i) selects blocks (gaps)."""
    rng = np.random.default_rng(seed)
    pt = np.asarray(pulse_ticks, float)
    res = []
    for i in range(nblk):
        if keep is not None and not keep(i):
            continue
        t = (i * 256 + np.arange(256)) * float(tps)
        k = np.searchsorted(pt, t)
        y = np.zeros(256)
        for j in (k - 1, k):
            ok = (j >= 0) & (j < len(pt))
            d = np.where(ok, t - pt[np.clip(j, 0, len(pt) - 1)], 1e12)
            y += amp * np.exp(-(d / width) ** 2)
        y += base + rng.normal(0, 0.2, 256)
        res.append((i, np.round(y)))
    return res
