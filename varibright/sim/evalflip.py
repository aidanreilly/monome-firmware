"""Glue: generate writes, run the MAX7219 model, apply the flicker metric."""
import numpy as np

import flicker
import gen
import maxmodel

DT = 50e-6
SETTLE = 0.25


def auto_duration(fs, ratio, tmin=0.75, tmax=3.0):
    """long enough to see 1.5 slip periods (burst crossing a whole frame), clipped"""
    eps = abs(1.0 - 1.0 / ratio)
    if eps < 1e-9:
        return tmin
    return float(min(tmax, max(tmin, 1.5 / (fs * eps))))


def stats_for(lum, nominal, levels, settle=SETTLE, dt=DT):
    st = flicker.led_stats(lum, dt, settle)
    full = nominal.max() if nominal.max() > 0 else 1.0
    return st, flicker.summarise(st, nominal, full, levels)


def per_level(st, nominal, levels):
    """worst-LED figures per level 1..15: pp, rms, mean error (fraction of own mean)"""
    out = {}
    lit = nominal > 0
    g = st["mean"][lit].sum() / nominal[lit].sum()
    for L in range(1, 16):
        sel = levels == L
        if not sel.any():
            continue
        out[L] = dict(pp=float(st["pp"][sel].max()), rms=float(st["rms"][sel].max()),
                      err=float(np.abs(st["mean"][sel] / (g * nominal[sel]) - 1).max()),
                      dc=float(st["mean"][sel].mean() / nominal[sel].mean()),
                      mean=float(st["mean"][sel].mean()))
    return out


def run_flip(codes, lut, fs, ratio, phase=0.0, burst=100e-6, order="int_first",
             skip=False, jitter=0.0, jitter_mode="uniform", digit_effect=0, int_effect=0,
             pwm_pos=0.0, blank=0.0, patterns=("lo", "hi"), duration=None, shutdown=False,
             restart_mode=0, wake_delay=0.0, wake_jitter=0.0, seed=0, row_order=None, want_levels=False, osc_jitter=0.0,
             drift=0.0, hold_latch=0, regs=None):
    """Returns the worst-case summary over the patterns (and optionally per-level data).
    ratio is T_u / T_cal, where T_cal is the tick period at which the chip's mean awake
    time per tick equals one scan frame: 1/fs without shutdown bracket, 1/fs + mean dark
    time (burst between the two 0x0C writes + wake_delay) with it."""
    T_cal = 1.0 / fs
    if shutdown:
        lv0 = gen.pattern(patterns[0])
        t, a, d = gen.flip(lv0, codes, lut, T_cal, 0.05, burst=burst, order=order,
                           skip_unchanged=skip, shutdown=True, row_order=row_order)
        on = t[(a == 12) & (d == 0)]
        off = t[(a == 12) & (d == 1)]
        n = min(len(on), len(off))
        T_cal += float(np.mean(off[:n] - on[:n])) + wake_delay
    T_u = ratio * T_cal
    if duration is None:
        duration = auto_duration(fs, ratio)
    t1 = SETTLE + duration
    worst = None
    lvl = {}
    for pname in patterns:
        levels = gen.pattern(pname)
        t, a, d = gen.flip(levels, codes, lut, T_u, t1 + 0.01, burst=burst, order=order,
                           skip_unchanged=skip, jitter=jitter, jitter_mode=jitter_mode,
                           seed=seed, shutdown=shutdown, row_order=row_order)
        lum, _ = maxmodel.simulate(t, a, d, fs=fs, phase=phase, blank=blank, pwm_pos=pwm_pos,
                                   digit_effect=digit_effect, int_effect=int_effect,
                                   restart_mode=restart_mode, wake_delay=wake_delay, wake_jitter=wake_jitter, osc_jitter=osc_jitter,
                                   drift=drift, seed=seed + 1, t0=0.0, t1=t1, dt=DT,
                                   hold_latch=hold_latch, regs=regs)
        nom = gen.nominal_lum(levels, codes, lut, blank)
        st, sm = stats_for(lum, nom, levels)
        if want_levels:
            lvl.update(per_level(st, nom, levels))
        if worst is None:
            worst = sm
        else:
            for k in ("rms_max", "pp_max", "pp_abs_fs", "band_max", "row_band", "rel_err_max"):
                worst[k] = max(worst[k], sm[k])
            worst["gain"] = min(worst["gain"], sm["gain"])
            worst["pass_plan"] = worst["pass_plan"] and sm["pass_plan"]
            worst["pass_strict"] = worst["pass_strict"] and sm["pass_strict"]
        # brightness relative to stock (intensity 15, full on)
    worst["duration"] = duration
    worst["T_u"] = T_u
    if want_levels:
        worst["levels"] = lvl
    return worst


def fmt(v, pct=True, nd=2):
    if pct:
        return f"{100 * v:.{nd}f}"
    return f"{v:.{nd}f}"
