"""Perceptual flicker metric (simulation only).

Filter: 6th-order Butterworth low-pass, fc = 32 Hz, applied to each LED's luminance.
Gain: 0.99 @ 20 Hz, 0.83 @ 30 Hz, 0.25 @ 40 Hz, 0.069 @ 50 Hz, 0.023 @ 60 Hz,
0.009 @ 70 Hz, 0.004 @ 80 Hz.  It stands in for the high-frequency flank of the
large-field, high-luminance temporal contrast sensitivity function normalised to
its peak (de Lange 1958, Kelly 1961).  Combined with the thresholds below it
reproduces a critical flicker frequency for 100 % sinusoidal modulation of 64 Hz
(PLAN thresholds) or 77 Hz (strict thresholds), which brackets the CFF of large
bright fields.  Below 30 Hz the gain is kept at ~1 (the real TCSF falls again below
~5 Hz, so treating slow drift and rolling bands as fully visible is conservative).

Reported per LED, over the settled window:
  rms  = std(filtered) / mean(raw)
  pp   = (max - min)(filtered) / mean(raw)
  mean = mean(raw) (exact, no filter)
"""
import numpy as np
from scipy.signal import butter, sosfilt, sosfreqz

FC = 32.0
ORDER = 6

# thresholds
PLAN_RMS, PLAN_PP, PLAN_BAND = 0.01, 0.03, 0.03      # PLAN.md section 6
# strict: Michelson threshold ~0.5 % at the TCSF peak (large bright field) -> pp 1 %,
# rms of a sinusoid at that amplitude 0.35 %
STRICT_RMS, STRICT_PP = 0.0035, 0.01

_sos_cache = {}


def sos_for(dt):
    key = round(1.0 / dt, 6)
    if key not in _sos_cache:
        _sos_cache[key] = butter(ORDER, FC, fs=1.0 / dt, output="sos")
    return _sos_cache[key]


def filter_gain(freqs, dt=50e-6):
    w, h = sosfreqz(sos_for(dt), worN=np.asarray(freqs, float), fs=1.0 / dt)
    return np.abs(h)


def led_stats(lum, dt, settle=0.25):
    """lum: [nbins, 8, 8] fraction-lit. Returns dict of [8,8] arrays."""
    nb = lum.shape[0]
    x = lum.reshape(nb, 64)
    y = sosfilt(sos_for(dt), x, axis=0)
    s = int(round(settle / dt))
    y = y[s:]
    m = x[s:].mean(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        rms = np.where(m > 0, y.std(axis=0) / m, 0.0)
        pp = np.where(m > 0, (y.max(axis=0) - y.min(axis=0)) / m, 0.0)
    return dict(mean=m.reshape(8, 8), rms=rms.reshape(8, 8), pp=pp.reshape(8, 8),
                pp_abs=(y.max(axis=0) - y.min(axis=0)).reshape(8, 8))


def summarise(st, nominal, fullscale, levels=None):
    """nominal: [8,8] expected mean luminance (same units as lum); fullscale: luminance of
    the brightest level.  A global brightness factor g = sum(mean)/sum(nominal) is
    reported separately ('gain') and removed before the banding figures, so a uniform
    loss (for example dark time during a shutdown bracket) is not counted as banding.
    Returns scalar summary (worst cases over LEDs with nominal > 0)."""
    lit = nominal > 0
    g = float(st["mean"][lit].sum() / nominal[lit].sum()) if lit.any() else 1.0
    if g <= 0:
        g = 1e-9
    err = (st["mean"] / g - nominal) / fullscale
    row_err = np.array([err[r][lit[r]].mean() if lit[r].any() else 0.0 for r in range(8)])
    out = dict(
        gain=g,
        rms_max=float(st["rms"][lit].max()) if lit.any() else 0.0,
        pp_max=float(st["pp"][lit].max()) if lit.any() else 0.0,
        pp_abs_fs=float(st["pp_abs"].max() / (g * fullscale)),
        band_max=float(np.abs(err[lit]).max()) if lit.any() else 0.0,   # worst LED, of FS
        row_band=float(row_err.max() - row_err.min()),
        dark_leak=float(st["mean"][~lit].max() / fullscale) if (~lit).any() else 0.0,
    )
    if levels is not None:
        rel = np.zeros(16)
        for L in range(1, 16):
            sel = (levels == L) & lit
            if sel.any():
                rel[L] = np.abs(st["mean"][sel] / (g * nominal[sel]) - 1).max()
        out["rel_err_max"] = float(rel.max())
    out["pass_plan"] = bool(out["rms_max"] < PLAN_RMS and out["pp_max"] < PLAN_PP
                            and out["band_max"] < PLAN_BAND)
    out["pass_strict"] = bool(out["rms_max"] < STRICT_RMS and out["pp_max"] < STRICT_PP
                              and out["band_max"] < PLAN_BAND)
    return out
