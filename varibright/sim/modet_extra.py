#!/usr/bin/env python3
"""Mode T-SD follow-up experiments (simulation only; workstream C, step 1).

T-SD = constant intensity, one shutdown-bracketed burst per tick (0x0C=0, digits 1..8,
0x0C=1), level step s of P shown as s on-frames spread evenly over a P-frame cycle.

  windows   contiguous passing window vs rate mismatch (fine grid), P 3..6, 5 scan rates,
            wake models restart-at-0 / frozen (immediate) / frozen with the latch held
            across the wake (next-slot model, see max7219.c hold_latch); worst of 2 phases
  holdsd    same latch-hold question for Mode SD (FLIP-SD 15/15/6/15/11/15) for comparison
  jitter    ISR entry jitter
  wake      wake delay and wake jitter
  intensity lower global intensity codes (shorter pulse)
  offsets   per-row / per-LED phase offsets of the dither pattern
  mapping   host level 0..15 -> step mapping (static)
usage: modet_extra.py [--jobs N] exp [exp ...] | all      -> results/modet_extra_<exp>.md/.json
"""
import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import evalflip as E  # noqa: E402
import flicker as F  # noqa: E402
import gen  # noqa: E402
import maxmodel as M  # noqa: E402
import modet  # noqa: E402
import schemes as S  # noqa: E402

RES = os.path.join(HERE, "results")
JOBS = 2
BURST = 50e-6            # 9 word slots of 5.6 us; the bracket spans 9 words (firmware: 10 words, ~5.6 us each)
FS5 = [500.0, 650.0, 800.0, 1000.0, 1300.0]
WAKE = {"restart0": dict(restart_mode=0, digit_effect=0, int_effect=0),
        "frozen-imm": dict(restart_mode=1, digit_effect=0, int_effect=0),
        "frozen-hold": dict(restart_mode=1, digit_effect=1, int_effect=1, hold_latch=1)}
PHASES = [0.3, 0.3 + 0.6180339887 % 1.0]


def regs_with(code):
    r = list(M.RUNNING_REGS)
    r[10] = code
    return r


def tsd(P, fs, ratio, wake, phase=0.3, code=15, **kw):
    k = dict(WAKE[wake])
    k.update(kw)
    return E.run_flip([code] * P, modet.lut_T(P), fs, ratio, phase=phase, burst=BURST,
                      order="int_none", shutdown=True, regs=regs_with(code), **k)


def _job(a):
    fn, args, kw = a
    try:
        o = fn(*args, **kw)
    except Exception as ex:  # pragma: no cover
        return dict(error=repr(ex))
    return {k: v for k, v in o.items() if k != "levels"}


def pmap(jobs):
    with Pool(JOBS) as p:
        return p.map(_job, jobs, chunksize=max(1, len(jobs) // (JOBS * 16)))


def table(h, rows):
    s = "| " + " | ".join(h) + " |\n|" + "|".join("---" for _ in h) + "|\n"
    return s + "".join("| " + " | ".join(str(x) for x in r) + " |\n" for r in rows)


def save(name, md, data):
    with open(os.path.join(RES, f"modet_extra_{name}.md"), "w") as f:
        f.write(md)
    with open(os.path.join(RES, f"modet_extra_{name}.json"), "w") as f:
        json.dump(data, f, default=float)
    print(md)


def window(pts):
    """pts: list of (ratio, ok) -> contiguous passing interval around 1.0 in % or None"""
    pts = sorted(pts)
    i = int(np.argmin([abs(r - 1) for r, _ in pts]))
    if not pts[i][1]:
        return None
    lo = hi = i
    while lo > 0 and pts[lo - 1][1]:
        lo -= 1
    while hi < len(pts) - 1 and pts[hi + 1][1]:
        hi += 1
    return 100 * (pts[lo][0] - 1), 100 * (pts[hi][0] - 1)


def fw(w):
    return "none" if w is None else f"{w[0]:+.2f}..{w[1]:+.2f}"


def grid():
    g = set(round(1 + x / 2000, 6) for x in range(-10, 11))         # +-0.5 % in 0.05 %
    g |= set(round(1 + x / 1000, 6) for x in range(-50, 51))        # +-5 % in 0.1 %
    return sorted(g)


# --------------------------------------------------------------------------- windows
def exp_windows():
    g = grid()
    jobs, keys = [], []
    for P in (3, 4, 5, 6):
        for fs in FS5:
            for w in WAKE:
                rr = g if w != "frozen-hold" else [r for r in g if abs(r - 1) <= 0.005]
                for r in rr:
                    for ph in PHASES:
                        jobs.append((tsd, (P, fs, r, w), dict(phase=ph)))
                        keys.append((P, fs, w, r, ph))
    t0 = time.time()
    out = pmap(jobs)
    print(f"windows: {len(jobs)} runs {time.time() - t0:.0f} s", file=sys.stderr)
    agg = {}
    for k, o in zip(keys, out):
        a = agg.setdefault(k[:4], dict(pp=0, band=0, ok=True, strict=True, gain=1))
        a["pp"] = max(a["pp"], o["pp_max"]); a["band"] = max(a["band"], o["band_max"])
        a["ok"] &= o["pass_plan"]; a["strict"] &= o["pass_strict"]; a["gain"] = min(a["gain"], o["gain"])
    data = [dict(P=k[0], fs=k[1], wake=k[2], ratio=k[3], **v) for k, v in agg.items()]
    md = ("## T-SD rate windows (contiguous, worst of 2 scan phases)\n\n"
          "Grid: 0.05 % steps within +-0.5 %, 0.1 % steps to +-5 %. PLAN = rms < 1 %, pp < 3 %, "
          "band < 3 % FS; strict = rms < 0.35 %, pp < 1 %. frozen-hold = frozen wake with the "
          "next-slot write model when the resumed partial slot keeps the pre-halt latch "
          "(only +-0.5 % scanned). Cells: PLAN window % / strict window %; exact = pp % own / "
          "band % FS at ratio 1.\n\n")
    rows = []
    for P in (3, 4, 5, 6):
        for fs in FS5:
            row = [P, int(fs), f"{fs / P:.0f}"]
            for w in WAKE:
                pts = [(d["ratio"], d) for d in data if (d["P"], d["fs"], d["wake"]) == (P, fs, w)]
                ex = [d for r, d in pts if r == 1.0][0]
                row.append(f"{fw(window([(r, d['ok']) for r, d in pts]))} / "
                           f"{fw(window([(r, d['strict']) for r, d in pts]))} "
                           f"(exact {100 * ex['pp']:.2f} / {100 * ex['band']:.2f})")
            row.append(f"{100 * min(d['gain'] for d in data if d['P'] == P and d['fs'] == fs):.0f}")
            rows.append(row)
    md += table(["P", "f_s", "cycle Hz", "restart at 0", "frozen, immediate", "frozen, latch held",
                 "gain %"], rows)
    save("windows", md, data)


def exp_holdsd():
    codes, lut = [15, 15, 6, 15, 11, 15], [0x00, 0x04, 0x10, 0x01, 0x05, 0x11, 0x09, 0x0d, 0x19,
                                            0x1d, 0x0f, 0x1b, 0x1f, 0x2f, 0x3b, 0x3f]
    rr = [0.995, 0.999, 0.9995, 0.9999, 1.0, 1.0001, 1.0005, 1.001, 1.005]
    jobs, keys = [], []
    for w in ("frozen-imm", "frozen-hold"):
        for r in rr:
            jobs.append((E.run_flip, (codes, lut, 800.0, r), dict(WAKE[w], phase=0.3, burst=BURST,
                                                                    order="int_first", shutdown=True)))
            keys.append((w, r))
            jobs.append((tsd, (4, 800.0, r, w), {}))
            keys.append(("T-SD P4 " + w, r))
    out = pmap(jobs)
    rows = []
    for name in ("frozen-imm", "frozen-hold", "T-SD P4 frozen-imm", "T-SD P4 frozen-hold"):
        rows.append([("SD 15/15/6/15/11/15 " + name) if not name.startswith("T") else name] +
                    [f"{100 * o['pp_max']:.1f}" + ("" if o["pass_plan"] else "*")
                     for k, o in zip(keys, out) if k[0] == name])
    md = ("## Latch held across a frozen wake: Mode SD vs T-SD, 800 Hz\n\n"
          "pp % of own mean (worst LED) at each ratio; * = fails PLAN thresholds.\n\n")
    md += table(["scheme / wake"] + [f"{100 * (r - 1):+.2f} %" for r in rr], rows)
    save("holdsd", md, [dict(k=list(k), **o) for k, o in zip(keys, out)])


# --------------------------------------------------------------------------- jitter / wake
def exp_jitter():
    js = [0, 1e-6, 2e-6, 5e-6, 10e-6, 20e-6, 50e-6]
    jobs, keys = [], []
    for P in (3, 4):
        for w in ("restart0", "frozen-imm"):
            for mode in ("late", "uniform"):
                for j in js:
                    for r in (1.0, 1.005):
                        jobs.append((tsd, (P, 800.0, r, w), dict(jitter=j, jitter_mode=mode, seed=3)))
                        keys.append((P, w, mode, j, r))
    out = pmap(jobs)
    rows = []
    for P in (3, 4):
        for w in ("restart0", "frozen-imm"):
            for mode in ("late", "uniform"):
                row = [P, w, mode]
                for j in js:
                    c = []
                    for r in (1.0, 1.005):
                        o = out[keys.index((P, w, mode, j, r))]
                        c.append(f"{100 * o['pp_max']:.2f}/{100 * o['band_max']:.2f}")
                    row.append(" ; ".join(c))
                rows.append(row)
    md = ("## T-SD: ISR entry jitter, 800 Hz\n\n'late' = 0..j delay, 'uniform' = +-j. Cells: "
          "pp % own / band % FS at ratio 1.0 ; at +0.5 %. Mode SD reference (sim/README 5d, "
          "frozen, 'late'): 1 us 0.9, 2 us 1.8, 5 us 4.4, 20 us 8.6 % FS.\n\n")
    md += table(["P", "wake", "mode"] + [f"j={j * 1e6:.0f} us" for j in js], rows)
    save("jitter", md, [dict(k=list(k), **o) for k, o in zip(keys, out)])


def exp_wake():
    jobs, keys = [], []
    for P in (3, 4):
        for w in ("restart0", "frozen-imm"):
            for wd in (0, 20e-6, 50e-6, 250e-6):
                for wj in (0, 2e-6, 10e-6, 50e-6):
                    for r in (1.0, 1.005):
                        jobs.append((tsd, (P, 800.0, r, w), dict(wake_delay=wd, wake_jitter=wj, seed=5)))
                        keys.append((P, w, wd, wj, r))
    out = pmap(jobs)
    rows = []
    for k, o in zip(keys, out):
        if k[4] != 1.0:
            continue
        o2 = out[keys.index(k[:4] + (1.005,))]
        rows.append([k[0], k[1], f"{k[2] * 1e6:.0f}", f"+-{k[3] * 1e6:.0f}",
                     f"{100 * o['pp_max']:.2f} / {100 * o['band_max']:.2f} / {100 * o['gain']:.0f}",
                     f"{100 * o2['pp_max']:.2f} / {100 * o2['band_max']:.2f}",
                     "pass" if (o["pass_plan"] and o2["pass_plan"]) else "FAIL"])
    md = ("## T-SD: wake delay and wake jitter, 800 Hz\n\nThe calibrated period includes the mean "
          "wake delay (the roll is nulled with it). Cells: pp % own / band % FS / gain %.\n"
          "Mode SD reference (sim/README 5d): +-2 us wake jitter 1.2..2.9 % FS, +-10 us 12..16 % FS.\n\n")
    md += table(["P", "wake", "delay us", "jitter us", "ratio 1.0", "ratio +0.5 %", "PLAN"], rows)
    save("wake", md, [dict(k=list(k), **o) for k, o in zip(keys, out)])


# --------------------------------------------------------------------------- intensity
RR_INT = {"frozen-imm": [0.99, 0.995, 1.0, 1.005, 1.01],
          "restart0": [0.995, 0.9975, 1.0, 1.001, 1.0025]}


def exp_intensity():
    codes = [15, 11, 7, 3, 1, 0]
    jobs, keys = [], []
    for P in (3, 4):
        for fs in (500.0, 800.0, 1300.0):
            for w in ("restart0", "frozen-imm"):
                for c in codes:
                    for r in RR_INT[w]:
                        jobs.append((tsd, (P, fs, r, w), dict(code=c)))
                        keys.append((P, fs, w, c, r))
    out = pmap(jobs)
    rows = []
    for P in (3, 4):
        for fs in (500.0, 800.0, 1300.0):
            for w in ("restart0", "frozen-imm"):
                row = [P, int(fs), w]
                for c in codes:
                    os_ = [out[keys.index((P, fs, w, c, r))] for r in RR_INT[w]]
                    ok = all(o["pass_plan"] for o in os_)
                    row.append(f"{100 * max(o['pp_max'] for o in os_):.2f} / "
                               f"{100 * max(o['band_max'] for o in os_):.2f} {'' if ok else 'FAIL'}")
                rows.append(row)
    md = ("## T-SD at lower global intensity codes (0x17 / MAX7219 0x0A)\n\nWorst over ratios "
          "-1, -0.5, 0, +0.5, +1 % (frozen) or -0.5, -0.25, 0, +0.1, +0.25 % (restart at 0, inside "
          "its static-band window at code 15): pp % own / band % FS. Code c lights (2c+1)/32 of each slot.\n\n")
    md += table(["P", "f_s", "wake"] + [f"code {c}" for c in codes], rows)
    save("intensity", md, [dict(k=list(k), **o) for k, o in zip(keys, out)])


# --------------------------------------------------------------------------- offsets
def offs(kind, P):
    r = np.arange(8)[:, None]
    c = np.arange(8)[None, :]
    if kind == "none":
        return np.zeros((8, 8), int)
    if kind == "row":
        return np.broadcast_to(r % P, (8, 8)).copy()
    if kind == "led":
        return (r + 2 * c) % P
    raise ValueError(kind)


def tsd_offsets(P, fs, ratio, wake, kind, pattern="lo", phase=0.3):
    lv = gen.pattern(pattern)
    lut = modet.lut_T(P)
    o = offs(kind, P)
    rows = []
    for f in range(P):
        rr = []
        for d in range(8):
            v = 0
            for s in range(8):
                if (lut[lv[d, s]] >> ((f + o[d, s]) % P)) & 1:
                    v |= 1 << s
            rr.append(v)
        rows.append(rr)
    tw = BURST / 9
    dark = 9 * tw
    T_cal = 1 / fs + dark
    T_u = ratio * T_cal
    dur = E.auto_duration(fs, ratio)
    t1 = E.SETTLE + dur
    T, A, D = [], [], []
    for k in range(int((t1 + 0.01) / T_u) + 1):
        words = [(12, 0)] + [(d + 1, rows[k % P][d]) for d in range(8)] + [(12, 1)]
        for i, (a, x) in enumerate(words):
            T.append(k * T_u + (i + 1) * tw); A.append(a); D.append(x)
    kw = dict(WAKE[wake])
    lum, _ = M.simulate(np.array(T), np.array(A), np.array(D), fs=fs, phase=phase, t0=0, t1=t1,
                        dt=E.DT, **kw)
    nom = gen.nominal_lum(lv, [15] * P, lut)
    st, sm = E.stats_for(lum, nom, lv)
    # large-area flicker: average over all LEDs of one level, then filter
    y = F.sosfilt(F.sos_for(E.DT), lum.reshape(lum.shape[0], 64), axis=0)[int(E.SETTLE / E.DT):]
    area = 0.0
    for L in range(1, 16):
        sel = (lv.reshape(64) == L)
        if sel.any():
            m = y[:, sel].mean(axis=1)
            area = max(area, (m.max() - m.min()) / lum.reshape(lum.shape[0], 64)[:, sel].mean())
    allm = y.mean(axis=1)
    sm["area_pp"] = float(area)
    sm["grid_pp"] = float((allm.max() - allm.min()) / allm.mean())
    return sm


def exp_offsets():
    rr = [0.98, 0.99, 0.995, 1.0, 1.005, 1.01, 1.015, 1.02]
    jobs, keys = [], []
    for P in (3, 4):
        for fs in (500.0, 800.0):
            for w in ("frozen-imm", "restart0"):
                for kind in ("none", "row", "led"):
                    for r in rr:
                        for pat in ("lo", "hi"):
                            jobs.append((tsd_offsets, (P, fs, r, w, kind), dict(pattern=pat)))
                            keys.append((P, fs, w, kind, r, pat))
    out = pmap(jobs)
    rows = []
    for P in (3, 4):
        for fs in (500.0, 800.0):
            for w in ("frozen-imm", "restart0"):
                for kind in ("none", "row", "led"):
                    row = [P, int(fs), w, kind]
                    for r in rr:
                        os_ = [out[keys.index((P, fs, w, kind, r, p))] for p in ("lo", "hi")]
                        row.append(f"{100 * max(o['pp_max'] for o in os_):.1f} / "
                                   f"{100 * max(o['area_pp'] for o in os_):.1f} / "
                                   f"{100 * max(o['grid_pp'] for o in os_):.2f}")
                    rows.append(row)
    md = ("## T-SD: phase offsets of the dither pattern\n\nnone = all LEDs in phase; row = offset "
          "= row mod P; led = (row + 2 col) mod P. Cells: worst single-LED pp % / pp % of the "
          "average over all LEDs of one level / pp % of the whole-grid average (patterns lo+hi).\n\n")
    md += table(["P", "f_s", "wake", "offsets"] + [f"{100 * (r - 1):+.1f} %" for r in rr], rows)
    save("offsets", md, [dict(k=list(k), **o) for k, o in zip(keys, out)])


# --------------------------------------------------------------------------- mapping
def exp_mapping():
    rows = []
    for P in (3, 4, 5, 6):
        st = [0 if L == 0 else max(1, int(round(L * P / 15.0))) for L in range(16)]
        err = max(abs(st[L] / P - L / 15) for L in range(16))
        rows.append([P, " ".join(map(str, st)), f"{100 * err:.1f}",
                     " ".join(str(sum(1 for s in st if s == k)) for k in range(P + 1))])
    md = ("## Host level -> step mapping\n\nstep(L) = 0 for L = 0, else max(1, round(L P / 15)). "
          "It is the minimax-optimal monotonic map to a linear ramp with 0 -> off, 15 -> full and "
          "every nonzero level lit; max err = worst |step/P - L/15| in % of full scale. The last "
          "column counts host levels per step 0..P.\n\n")
    md += table(["P", "steps for host levels 0..15", "max err % FS", "levels per step"], rows)
    save("mapping", md, rows)


EXPS = dict(windows=exp_windows, holdsd=exp_holdsd, jitter=exp_jitter, wake=exp_wake,
            intensity=exp_intensity, offsets=exp_offsets, mapping=exp_mapping)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("exps", nargs="+")
    a = ap.parse_args()
    JOBS = a.jobs
    for n in (list(EXPS) if a.exps == ["all"] else a.exps):
        t0 = time.time()
        EXPS[n]()
        print(f"[{n}: {time.time() - t0:.0f} s]", file=sys.stderr)
