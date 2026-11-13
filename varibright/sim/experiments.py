#!/usr/bin/env python3
"""Synthetic-write experiments (a)..(g) for the MAX7219 varibright study.

usage: experiments.py [--quick] [--jobs N] [--out DIR] exp [exp ...]
exps: naive exact sweep burst tables calib probe intensity all
Results are written to results/<exp>.md (markdown tables) and results/<exp>.json.
Everything here is simulation of a behavioural model; nothing is measured on hardware.
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
import schemes as S  # noqa: E402

RES = os.path.join(HERE, "results")
QUICK = False
JOBS = 2

FS_ALL = [500, 650, 800, 1000, 1300]
BURST = 50e-6          # default: unrolled shifter, ~5.5 us per 16-bit word, 9 words

T4 = [15, 7, 3, 1]
T5 = [15, 15, 15, 7, 3]

# write strategies.  'sd' = shutdown bracket 0x0C=0 ... 0x0C=1 around every burst
VARIANTS = {
    "FLIP/int_first": dict(order="int_first"),
    "FLIP/int_mid": dict(order="int_mid"),
    "FLIP/int_last": dict(order="int_last"),
    "FLIP/dark": dict(order="dark"),
    "FLIP/bridge": dict(order="bridge"),
    "SD/frozen": dict(order="int_first", shutdown=True, restart_mode=1),
    "SD/restart0": dict(order="int_first", shutdown=True, restart_mode=0),
    "SD/same-digit": dict(order="int_first", shutdown=True, restart_mode=2),
    "SD/next-digit": dict(order="int_first", shutdown=True, restart_mode=3),
}
EFFECTS = {"imm": dict(digit_effect=0, int_effect=0), "lat": dict(digit_effect=1, int_effect=1)}


def phases_n(n):
    """scan phases spread over both the frame and the slot (golden-ratio sequence; equally
    spaced multiples of 1/8 would all sit at the same position inside a digit slot)"""
    return [float((0.03 + k * 0.6180339887) % 1.0) for k in range(n)]


def pct(v, nd=1):
    return f"{100 * v:.{nd}f}"


def save(name, md, data):
    os.makedirs(RES, exist_ok=True)
    with open(os.path.join(RES, name + ".md"), "w") as f:
        f.write(md)
    with open(os.path.join(RES, name + ".json"), "w") as f:
        json.dump(data, f, indent=1, default=float)
    print(md)


def table(headers, rows):
    out = "| " + " | ".join(headers) + " |\n|" + "|".join("---" for _ in headers) + "|\n"
    for r in rows:
        out += "| " + " | ".join(str(x) for x in r) + " |\n"
    return out


def _job(args):
    codes, lut, fs, ratio, kw = args
    try:
        return E.run_flip(codes, lut, fs, ratio, **kw)
    except Exception as ex:  # pragma: no cover
        return dict(error=repr(ex))


def pmap(jobs):
    if JOBS <= 1 or len(jobs) < 4:
        return [_job(j) for j in jobs]
    with Pool(JOBS) as p:
        return p.map(_job, jobs, chunksize=max(1, len(jobs) // (JOBS * 8)))


def worst(results, keys=("pp_max", "rms_max", "pp_abs_fs", "band_max", "row_band",
                         "rel_err_max")):
    w = {k: max(r[k] for r in results) for k in keys}
    w["gain"] = min(r["gain"] for r in results)
    w["pass_plan"] = all(r["pass_plan"] for r in results)
    w["pass_strict"] = all(r["pass_strict"] for r in results)
    return w


# ----------------------------------------------------------------------------- (a)
def exp_naive():
    """naive time-domain BCM / PWM at achievable update rates vs stock static display"""
    fss = [500, 800, 1300]
    phases = phases_n(3) if not QUICK else phases_n(1)
    taus_bcm = [100e-6, 200e-6, 500e-6, 1e-3]
    taus_pwm = [100e-6, 200e-6, 500e-6]
    rows = []
    data = []
    for kind, taus in (("BCM", taus_bcm), ("PWM", taus_pwm), ("static", [None])):
        for tau in taus:
            for fs in fss:
                res = []
                for ph in phases:
                    for pn in ("lo", "hi"):
                        lv = gen.pattern(pn)
                        t1 = 1.25
                        if kind == "BCM":
                            t, a, d = gen.bcm_time(lv, tau, t1 + 0.01, burst=BURST)
                        elif kind == "PWM":
                            t, a, d = gen.pwm_time(lv, tau, t1 + 0.01, burst=BURST)
                        else:
                            # stock firmware: binary on/off, levels > 7 on
                            rws = [sum(1 << c for c in range(8) if lv[r, c] > 7) for r in range(8)]
                            t, a, d = _static_writes(rws)
                        lum, _ = M.simulate(t, a, d, fs=fs, phase=ph, t0=0, t1=t1, dt=E.DT)
                        if kind == "static":
                            nom = np.where(lv > 7, 31 / 32 / 8, 0.0)
                        else:
                            nom = gen.naive_nominal(lv)
                        st, sm = E.stats_for(lum, nom, lv)
                        res.append(sm)
                w = worst(res)
                period = "" if tau is None else (f"{15 * tau * 1e3:.2f} ms")
                rows.append([kind, "" if tau is None else f"{tau * 1e6:.0f}", period, fs,
                             pct(w["rms_max"]), pct(w["pp_max"]), pct(w["pp_abs_fs"]),
                             pct(w["band_max"]), "pass" if w["pass_plan"] else "FAIL"])
                data.append(dict(kind=kind, tau=tau, fs=fs, **w))
    md = "## (a) Naive time-domain modulation (intensity fixed at 15)\n\n"
    md += ("Patterns lo+hi (levels 0..15 in every row), phases " + str(phases) +
           f", burst {BURST * 1e6:.0f} us per 9 words, unchanged rows skipped. "
           "pp/rms relative to each LED's own mean, worst LED; pp_abs and band in % of "
           "full scale.\n\n")
    md += table(["scheme", "tau us", "period", "f_s", "rms %", "pp %", "pp_abs %FS",
                 "band %FS", "PLAN"], rows)
    save("naive", md, data)


def _static_writes(rows):
    T = [1e-6 * (i + 1) for i in range(9)]
    A = [10] + list(range(1, 9))
    D = [15] + list(rows)
    return np.array(T), np.array(A), np.array(D)



# ----------------------------------------------------------------------------- (b)
def exp_exact():
    """T_u exactly calibrated: all 16 levels, several phases, both write-effect models"""
    fss = [500, 800, 1300]
    phases = phases_n(12) if not QUICK else phases_n(4)
    names = ["FLIP/int_first", "FLIP/int_mid", "FLIP/int_last", "SD/frozen", "SD/restart0"]
    lut4 = S.design_lut(T4)
    jobs, keys = [], []
    for vn in names:
        for en, ekw in EFFECTS.items():
            for fs in fss:
                for ph in phases:
                    kw = dict(VARIANTS[vn], **ekw, phase=ph, burst=BURST, want_levels=True)
                    jobs.append((T4, lut4, fs, 1.0, kw))
                    keys.append((vn, en, fs, ph))
    out = pmap(jobs)
    rows, data = [], []
    for vn in names:
        for en in EFFECTS:
            for fs in fss:
                rs = [o for k, o in zip(keys, out) if k[:3] == (vn, en, fs)]
                w = worst(rs)
                lvl_err = max(max(v["err"] for v in r["levels"].values()) for r in rs)
                rows.append([vn, en, fs, pct(w["rms_max"], 2), pct(w["pp_max"], 2),
                             pct(w["band_max"]), pct(lvl_err), pct(w["gain"]),
                             "pass" if w["pass_plan"] else "FAIL",
                             "pass" if w["pass_strict"] else "fail"])
                data.append(dict(variant=vn, effect=en, fs=fs, level_err=lvl_err, **w))
    md = "## (b) FLIP at exactly calibrated rate, table 15/7/3/1\n\n"
    md += (f"{len(phases)} scan phases, patterns lo+hi (all 16 levels in every row), burst "
           f"{BURST * 1e6:.0f} us. 'level err' = worst LED mean error relative to its own "
           "commanded level; 'gain' = global brightness factor (shutdown dark time).\n\n")
    md += table(["variant", "effect", "f_s", "rms %", "pp %", "band %FS", "level err %",
                 "gain %", "PLAN", "strict"], rows)
    save("exact", md, data)


# ----------------------------------------------------------------------------- (c)
def ratio_grid():
    if QUICK:
        g = list(np.round(np.arange(0.995, 1.00501, 0.0005), 6))
        g += [0.6, 0.8, 0.89, 0.92, 0.94, 0.97, 0.99, 1.01, 1.03, 1.07, 1.09, 1.14, 1.33, 1.6]
    else:
        g = list(np.round(np.arange(0.60, 1.6001, 0.01), 6))
        g += list(np.round(np.arange(0.95, 1.0501, 0.001), 6))
        g += list(np.round(np.arange(0.995, 1.00501, 0.0001), 6))
        g += [0.8, 0.8889, 0.9231, 0.9412, 1.0667, 1.0909, 1.1429, 1.3333]
    return sorted(set(float(x) for x in g))


def window(ratios, ok):
    """contiguous passing interval containing ratio 1.0 -> (lo, hi) or None"""
    r = np.array(ratios)
    ok = np.array(ok)
    i = int(np.argmin(np.abs(r - 1.0)))
    if not ok[i]:
        return None
    lo = i
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    hi = i
    while hi < len(r) - 1 and ok[hi + 1]:
        hi += 1
    return float(r[lo]), float(r[hi])


def longest_run(ratios, ok, lo=0.99, hi=1.01):
    """longest contiguous passing interval inside [lo, hi] -> (a, b) or None"""
    best, cur = None, None
    for r, k in zip(ratios, ok):
        if r < lo or r > hi:
            continue
        if k:
            cur = (cur[0], r) if cur else (r, r)
            if best is None or cur[1] - cur[0] > best[1] - best[0]:
                best = cur
        else:
            cur = None
    return best


def exp_sweep():
    fss = FS_ALL if not QUICK else [800]
    grid = ratio_grid()
    names = ["FLIP/int_first", "FLIP/int_mid", "SD/frozen", "SD/restart0", "SD/same-digit",
             "SD/next-digit"]
    effs = {"FLIP/int_first": ["imm", "lat"], "FLIP/int_mid": ["imm"],
            "SD/frozen": ["imm"], "SD/restart0": ["imm"], "SD/same-digit": ["imm"],
            "SD/next-digit": ["imm"]}
    fs_of = {vn: (fss if vn in ("FLIP/int_first", "SD/frozen", "SD/restart0") else
                  [f for f in fss if f == 800]) for vn in names}
    lut4 = S.design_lut(T4)
    jobs, keys = [], []
    for vn in names:
        for en in effs[vn]:
            for fs in fs_of[vn]:
                for r in grid:
                    kw = dict(VARIANTS[vn], **EFFECTS[en], phase=0.3, burst=BURST,
                              patterns=("mixed",), duration=(None if not QUICK else None))
                    if QUICK:
                        kw["duration"] = E.auto_duration(fs, r, 0.5, 1.5)
                    jobs.append((T4, lut4, fs, r, kw))
                    keys.append((vn, en, fs, r))
    t0 = time.time()
    out = pmap(jobs)
    print(f"sweep: {len(jobs)} runs in {time.time() - t0:.0f} s", file=sys.stderr)
    data = [dict(variant=k[0], effect=k[1], fs=k[2], ratio=k[3], **o) for k, o in zip(keys, out)]
    md = "## (c) Rate-ratio sweep, table 15/7/3/1, pattern 'mixed', scan phase 0.3\n\n"
    md += (f"ratio = T_u / T_cal ({len(grid)} ratios from {grid[0]} to {grid[-1]}, finest step "
           f"{'0.0005' if QUICK else '0.0001'} within +-0.5 %). Window = contiguous passing "
           "interval around 1.0, given as percent deviation.\n\n")
    rows = []
    for vn in names:
        for en in effs[vn]:
            for fs in fs_of[vn]:
                sel = [d for d in data if (d["variant"], d["effect"], d["fs"]) == (vn, en, fs)]
                sel.sort(key=lambda d: d["ratio"])
                rr = [d["ratio"] for d in sel]
                wp = window(rr, [d["pass_plan"] for d in sel])
                ws = window(rr, [d["pass_strict"] for d in sel])
                outside = [d for d in sel if abs(d["ratio"] - 1) > 0.05]
                far = ""
                if outside:
                    far = f"{sum(d['pass_plan'] for d in outside)}/{len(outside)}"

                lr = longest_run(rr, [d["pass_plan"] for d in sel])

                def f(w):
                    return "none" if w is None else f"{100 * (w[0] - 1):+.2f} .. {100 * (w[1] - 1):+.2f}"
                rows.append([vn, en, fs, f(wp), f(ws), f(lr), far])
    md += table(["variant", "effect", "f_s", "PLAN window %", "strict window %",
                 "longest PLAN run within +-1 %", "passing outside +-5 %"], rows)
    # detail near 1 at 800 Hz
    md += "\n### Detail at f_s = 800 Hz (worst-LED pp % of own mean / pp % of full scale / band % FS)\n\n"
    pick = [0.99, 0.995, 0.998, 0.999, 0.9995, 0.9998, 1.0, 1.0002, 1.0005, 1.001, 1.002,
            1.005, 1.01]
    hdr = ["ratio"] + [f"{vn} {en}" for vn in names for en in effs[vn]]
    rows = []
    for r in pick:
        row = [f"{r:.4f}"]
        for vn in names:
            for en in effs[vn]:
                m = [d for d in data if (d["variant"], d["effect"], d["fs"]) == (vn, en, 800)
                     and abs(d["ratio"] - r) < 1e-9]
                row.append("-" if not m else f"{pct(m[0]['pp_max'])} / {pct(m[0]['pp_abs_fs'])} / {pct(m[0]['band_max'])}")
        rows.append(row)
    md += table(hdr, rows)
    # predicted bad ratios
    md += "\n### PLAN.md predicted bad ratios vs neighbours, SD/frozen and FLIP/int_first imm, 800 Hz (pp % FS)\n\n"
    rows = []
    for r in [0.8, 0.8889, 0.89, 0.92, 0.9231, 0.94, 0.9412, 1.0667, 1.07, 1.09, 1.0909, 1.14,
              1.1429, 1.33, 1.3333]:
        row = [f"{r:.4f}"]
        for vn, en in (("SD/frozen", "imm"), ("FLIP/int_first", "imm")):
            m = [d for d in data if (d["variant"], d["effect"], d["fs"]) == (vn, en, 800)]
            m.sort(key=lambda d: abs(d["ratio"] - r))
            if m and abs(m[0]["ratio"] - r) < 0.006:
                near = [d for d in m[1:6] if abs(d["ratio"] - r) <= 0.02]
                nb = np.median([d["pp_abs_fs"] for d in near]) if near else float("nan")
                row.append(f"{pct(m[0]['pp_abs_fs'])} @{m[0]['ratio']:.4f} (nbr median {pct(nb)})")
            else:
                row.append("-")
        rows.append(row)
    md += table(["ratio", "SD/frozen", "FLIP/int_first imm"], rows)
    save("sweep", md, data)


# ----------------------------------------------------------------------------- (d)
def exp_burst():
    fs = 800
    bursts = [5e-6, 20e-6, 50e-6, 100e-6, 200e-6, 350e-6] if not QUICK else [50e-6, 200e-6, 350e-6]
    ratios = [1.0, 0.9995, 1.0005]
    phases = phases_n(8) if not QUICK else phases_n(3)
    lut4 = S.design_lut(T4)
    strategies = []
    for o in ("int_first", "int_last", "int_mid", "dark", "bridge"):
        for sk in (False, True):
            strategies.append((f"FLIP/{o}{'+skip' if sk else ''}", dict(order=o, skip=sk)))
    strategies.append(("SD/frozen", dict(VARIANTS["SD/frozen"])))
    strategies.append(("SD/frozen+skip", dict(VARIANTS["SD/frozen"], skip=True)))
    strategies.append(("SD/restart0", dict(VARIANTS["SD/restart0"])))
    jobs, keys = [], []
    for sn, skw in strategies:
        for en, ekw in EFFECTS.items():
            for b in bursts:
                for r in ratios:
                    for ph in (phases if r == 1.0 else [0.3]):
                        kw = dict(skw, **ekw, phase=ph, burst=b)
                        jobs.append((T4, lut4, fs, r, kw))
                        keys.append((sn, en, b, r, ph))
    # jitter
    jit = [0, 1e-6, 2e-6, 5e-6, 20e-6, 50e-6, 100e-6] if not QUICK else [0, 2e-6, 20e-6, 100e-6]
    for sn, skw in (("FLIP/int_mid", dict(order="int_mid")), ("SD/frozen", VARIANTS["SD/frozen"]),
                    ("SD/restart0", VARIANTS["SD/restart0"])):
        for en, ekw in EFFECTS.items():
            for j in jit:
                for mode in ("uniform", "late"):
                    kw = dict(skw, **ekw, phase=0.3, burst=BURST, jitter=j, jitter_mode=mode)
                    jobs.append((T4, lut4, fs, 1.0, kw))
                    keys.append(("J:" + sn, en, mode, j, 0))
    # shutdown wake delay / wake jitter
    for wd in (0, 50e-6, 250e-6):
        for wj in (0, 2e-6, 10e-6):
            for sn in ("SD/frozen", "SD/restart0"):
                kw = dict(VARIANTS[sn], phase=0.3, burst=BURST, wake_delay=wd, wake_jitter=wj)
                for r in (1.0, 1.0005):
                    jobs.append((T4, lut4, fs, r, kw))
                    keys.append(("W:" + sn, wd, wj, r, 0))
    t0 = time.time()
    out = pmap(jobs)
    print(f"burst: {len(jobs)} runs in {time.time() - t0:.0f} s", file=sys.stderr)
    md = f"## (d) Burst length, write order, write-effect model, ISR jitter (f_s = {fs} Hz, 15/7/3/1)\n\n"
    md += ("Each cell: worst pp % of full scale (filtered) / band % FS. Ratio 1.0 = worst of "
           f"{len(phases)} phases; 0.9995 / 1.0005 = calibration off by -0.05 % / +0.05 %.\n\n")
    hdr = ["strategy", "effect"] + [f"{b * 1e6:.0f}us r={r}" for b in bursts for r in ratios]
    rows, data = [], []
    for sn, _ in strategies:
        for en in EFFECTS:
            row = [sn, en]
            for b in bursts:
                for r in ratios:
                    rs = [o for k, o in zip(keys, out) if k[:4] == (sn, en, b, r)]
                    w = worst(rs)
                    row.append(f"{pct(w['pp_abs_fs'])} / {pct(w['band_max'])}")
                    data.append(dict(strategy=sn, effect=en, burst=b, ratio=r, **w))
            rows.append(row)
    md += table(hdr, rows)
    md += ("\n### ISR timing jitter at ratio 1.0, burst 50 us (pp % FS / band % FS); "
           "'uniform' = +-j around the nominal tick, 'late' = 0..j delay\n\n")
    hdr = ["strategy", "effect", "mode"] + [f"+-{j * 1e6:.0f}us" for j in jit]
    rows = []
    for sn in ("FLIP/int_mid", "SD/frozen", "SD/restart0"):
        for en in EFFECTS:
            for mode in ("uniform", "late"):
                row = [sn, en, mode]
                for j in jit:
                    o = [o for k, o in zip(keys, out) if k == ("J:" + sn, en, mode, j, 0)][0]
                    row.append(f"{pct(o['pp_abs_fs'])} / {pct(o['band_max'])}")
                    data.append(dict(strategy="J:" + sn, effect=en, mode=mode, jitter=j, **o))
                rows.append(row)
    md += table(hdr, rows)
    md += ("\n### Shutdown wake behaviour (datasheet: leaving shutdown typically takes < 250 us)\n\n"
           "Cells: pp % FS / band % FS / global gain %. Ratio is relative to the calibrated "
           "period, which includes the mean wake delay.\n\n")
    hdr = ["variant", "wake delay us", "wake jitter us", "r=1.0", "r=1.0005"]
    rows = []
    for sn in ("SD/frozen", "SD/restart0"):
        for wd in (0, 50e-6, 250e-6):
            for wj in (0, 2e-6, 10e-6):
                row = [sn, f"{wd * 1e6:.0f}", f"+-{wj * 1e6:.0f}"]
                for r in (1.0, 1.0005):
                    o = [o for k, o in zip(keys, out) if k == ("W:" + sn, wd, wj, r, 0)][0]
                    row.append(f"{pct(o['pp_abs_fs'])} / {pct(o['band_max'])} / {pct(o['gain'], 0)}")
                    data.append(dict(strategy="W:" + sn, wake_delay=wd, wake_jitter=wj, ratio=r, **o))
                rows.append(row)
    md += table(hdr, rows)
    save("burst", md, data)


# ----------------------------------------------------------------------------- (e)
def candidate_tables():
    c = {
        "4p 15/7/3/1 (PLAN default)": [15, 7, 3, 1],
        "5p 15/15/7/3/1 (PLAN)": [15, 15, 7, 3, 1],
        "6p 15/15/15/7/3/1 (PLAN)": [15, 15, 15, 7, 3, 1],
        "5p 15/15/15/7/3 (new)": [15, 15, 15, 7, 3],
        "6p 15/15/15/15/11/6 (new)": [15, 15, 15, 15, 11, 6],
    }
    out = {}
    gain = lambda f: float(F.filter_gain([f])[0])  # noqa: E731
    for name, codes in c.items():
        lut = S.design_lut(codes)
        out[name] = (codes, lut)
        # spread variant: best frame order for the worst f_s (500 Hz)
        sc, order = S.best_order(codes, lut, 500, gain)
        if order != list(range(len(codes))):
            nc, nl = S.permute(codes, lut, order)
            out[name.split(" (")[0] + " spread-order"] = (nc, nl)
    return out


def exp_tables():
    tabs = candidate_tables()
    fss = [500, 800, 1300]
    phases = phases_n(6) if not QUICK else phases_n(2)
    eps_list = [0.0005, 0.001, 0.002] if not QUICK else [0.001]
    rows_r, data = [], []
    for name, (codes, lut) in tabs.items():
        st = S.ramp_stats(codes, lut)
        rows_r.append([name, "/".join(map(str, codes)), pct(st["peak_stock"]), pct(st["peak_plan"]),
                       "yes" if st["monotonic"] else "NO", pct(st["lin_err_max"], 2),
                       f"{st['step_ratio']:.2f}", f"{st['A_max']:.1f}",
                       " ".join(str(v) for v in st["sums"][1:]),
                       " ".join(f"{m:0{len(codes)}b}"[::-1] for m in lut[1:])])
        data.append(dict(table=name, codes=codes, lut=lut, **st))
    md = "## (e) Plane tables\n\n### Static properties (exact, no simulation)\n\n"
    md += ("peak = level 15 relative to the stock display at intensity 15 (and the PLAN.md "
           "normalisation /32). lin err = worst deviation of the 16-level ramp from a straight "
           "line, % of full scale. step ratio = largest / smallest step (1 = perfectly even). "
           "A = worst excess of one repeated or dropped frame, in units of the LED's mean frame "
           "(drives slip flicker). Masks: frame 0 first.\n\n")
    md += table(["table", "codes (frame order)", "peak % stock", "peak % /32", "monotonic",
                 "lin err %FS", "step ratio", "A", "weights L1..15", "lookup masks L1..15"], rows_r)
    # simulated
    jobs, keys = [], []
    for name, (codes, lut) in tabs.items():
        for fs in fss:
            for ph in phases:
                for vn in ("SD/frozen", "FLIP/int_first"):
                    for en in (["imm"] if vn == "SD/frozen" else ["lat"]):
                        kw = dict(VARIANTS[vn], **EFFECTS[en], phase=ph, burst=BURST, want_levels=True)
                        jobs.append((codes, lut, fs, 1.0, kw))
                        keys.append((name, fs, vn, en, 1.0, ph))
            for eps in eps_list:
                for sgn in (-1, 1):
                    r = 1 + sgn * eps
                    kw = dict(VARIANTS["SD/frozen"], phase=0.3, burst=BURST)
                    jobs.append((codes, lut, fs, r, kw))
                    keys.append((name, fs, "SD/frozen", "imm", r, 0.3))
    t0 = time.time()
    out = pmap(jobs)
    print(f"tables: {len(jobs)} runs in {time.time() - t0:.0f} s", file=sys.stderr)
    md += ("\n### Simulated flicker, burst 50 us\n\n'exact' = worst over phases at T_u = T_cal "
           "(SD/frozen, and plain FLIP/int_first under the latched write model for comparison; "
           "plain FLIP depends on where the burst falls in a slot, see (b)). '+-e' = SD/frozen "
           "with the rate off by e, worst "
           "of both signs. Cells: worst pp % of own mean / pp % FS. Measured peak = simulated "
           "level-15 mean relative to stock.\n\n")
    hdr = ["table", "f_s", "SD exact", "FLIP-lat exact"] + [f"SD +-{100 * e:.2f}%" for e in eps_list] + ["measured peak % stock", "ramp err %FS (sim)"]
    rows = []
    for name, (codes, lut) in tabs.items():
        for fs in fss:
            row = [name, fs]
            for vn, en in (("SD/frozen", "imm"), ("FLIP/int_first", "lat")):
                rs = [o for k, o in zip(keys, out) if k[:5] == (name, fs, vn, en, 1.0)]
                w = worst(rs)
                row.append(f"{pct(w['pp_max'], 2)} / {pct(w['pp_abs_fs'], 2)}")
                data.append(dict(table=name, fs=fs, variant=vn, effect=en, ratio=1.0, **w))
            for eps in eps_list:
                rs = [o for k, o in zip(keys, out) if k[:4] == (name, fs, "SD/frozen", "imm")
                      and abs(abs(k[4] - 1) - eps) < 1e-9]
                w = worst(rs)
                row.append(f"{pct(w['pp_max'], 1)} / {pct(w['pp_abs_fs'], 2)}")
                data.append(dict(table=name, fs=fs, variant="SD/frozen", eps=eps, **w))
            rs = [o for k, o in zip(keys, out) if k[:5] == (name, fs, "SD/frozen", "imm", 1.0)]
            lv = rs[0]["levels"]
            means = np.array([lv[L]["mean"] for L in range(1, 16)])
            stock = 31 / 32 / 8
            row.append(pct(means[-1] / stock))
            lin = means[-1] * np.arange(1, 16) / 15
            row.append(pct(np.abs(means - lin).max() / means[-1], 2))
            rows.append(row)
    md += table(hdr, rows)
    # exact-rate flicker of the two recommended tables between 500 and 800 Hz
    rec = [n for n in tabs if n.startswith("5p 15/15/15/7/3 spread") or n.startswith("6p 15/15/15/15/11/6 spread")]
    mfs = [500, 575, 650, 725, 800] if not QUICK else [500, 650]
    jobs, keys = [], []
    for name in rec:
        codes, lut = tabs[name]
        for fs in mfs:
            for ph in phases:
                jobs.append((codes, lut, fs, 1.0, dict(VARIANTS["SD/frozen"], phase=ph, burst=BURST)))
                keys.append((name, fs))
    out = pmap(jobs)
    md += "\n### Recommended tables at the exact rate between 500 and 800 Hz (SD/frozen, worst of phases)\n\n"
    rows = []
    for name in rec:
        for fs in mfs:
            w = worst([o for k, o in zip(keys, out) if k == (name, fs)])
            rows.append([name, fs, pct(w["pp_max"], 2), pct(w["rms_max"], 2), pct(w["pp_abs_fs"], 2),
                         "pass" if w["pass_strict"] else "fail"])
            data.append(dict(table=name, fs=fs, variant="SD/frozen", ratio=1.0, mid=True, **w))
    md += table(["table", "f_s", "pp % own", "rms % own", "pp % FS", "strict"], rows)
    # tolerance window per table (SD/frozen), fine scan
    fine = list(np.round(np.arange(0.997, 1.00301, 0.0002 if not QUICK else 0.0005), 6))
    wfs = [500, 650, 800, 1300] if not QUICK else [800]
    jobs, keys = [], []
    for name, (codes, lut) in tabs.items():
        for fs in wfs:
            for r in fine:
                kw = dict(VARIANTS["SD/frozen"], phase=0.3, burst=BURST, patterns=("mixed",))
                if QUICK:
                    kw["duration"] = E.auto_duration(fs, r, 0.5, 1.5)
                jobs.append((codes, lut, fs, r, kw))
                keys.append((name, fs, r))
    out = pmap(jobs)
    md += ("\n### Rate tolerance per table (SD/frozen, pattern 'mixed', burst 50 us)\n\n"
           "Contiguous passing window around ratio 1, percent deviation (scan step "
           f"{'0.02' if not QUICK else '0.05'} %, range +-0.3 %).\n\n")
    rows = []
    for name in tabs:
        row = [name]
        for fs in wfs:
            sel = sorted([(k[2], o) for k, o in zip(keys, out) if k[:2] == (name, fs)])
            rr = [x[0] for x in sel]
            for crit in ("pass_plan", "pass_strict"):
                w = window(rr, [x[1][crit] for x in sel])
                row.append("none" if w is None else f"{100 * (w[0] - 1):+.2f} .. {100 * (w[1] - 1):+.2f}")
            data.append(dict(table=name, fs=fs, scan=[(x[0], x[1]["pp_max"], x[1]["pp_abs_fs"],
                                                       x[1]["band_max"]) for x in sel]))
        rows.append(row)
    md += table(["table"] + [f"{fs} Hz {c}" for fs in wfs for c in ("PLAN", "strict")], rows)
    save("tables", md, data)


# ----------------------------------------------------------------------------- (f)
def calib_trace(fs, ratio, sd, phase=0.3, burst=BURST, duration=4.0):
    """Calibration pattern.  Plain (PLAN.md section 3): writes at 2/T_u alternating all
    rows on/off.  With sd=True, the 'on' write of each period is shutdown-bracketed exactly
    like a FLIP burst (so the chip's awake time per period equals FLIP's) and the 'off'
    write mid-period is plain (rows only, no intensity change)."""
    t_word = burst / 9
    T, A, D = [-1e-6], [10], [15]
    words_on = [(12, 0), (10, 15)] + [(r + 1, 0xFF) for r in range(8)] + [(12, 1)] if sd else \
        [(r + 1, 0xFF) for r in range(8)]
    dark = (len(words_on) - 1) * t_word if sd else 0.0
    T_cal = 1 / fs + dark
    T_u = ratio * T_cal
    n = int(duration / T_u) + 2
    for k in range(n):
        t0 = k * T_u
        for i, (a, d) in enumerate(words_on):
            T.append(t0 + (i + 1) * t_word); A.append(a); D.append(d)
        for i in range(8):
            T.append(t0 + T_u / 2 + (i + 1) * t_word); A.append(i + 1); D.append(0)
    return np.array(T), np.array(A), np.array(D), T_u


def exp_calib():
    fs_list = [500, 800, 1300] if not QUICK else [800]
    eps_list = [0.0, 0.0001, 0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05]
    rows, data = [], []
    for fs in fs_list:
        for sd, rmode in ((False, 1), (True, 1), (True, 0)):
            for eps in eps_list:
                t, a, d, T_u = calib_trace(fs, 1 + eps, sd, duration=4.25 if not QUICK else 2.25)
                t1 = t[-1]
                lum, _ = M.simulate(t, a, d, fs=fs, phase=0.3, restart_mode=rmode, t0=0, t1=min(t1, 4.25 if not QUICK else 2.25), dt=E.DT)
                # per-row filtered luminance
                rowl = lum.sum(axis=2) / 8.0
                y = F.sosfilt(F.sos_for(E.DT), rowl, axis=0)[int(0.25 / E.DT):]
                full = 31 / 32 / 8
                # band contrast: max over time of (brightest row - darkest row) / full
                contrast = float((y.max(axis=1) - y.min(axis=1)).max() / full)
                # how far a given row's filtered brightness swings
                swing = float((y.max(axis=0) - y.min(axis=0)).max() / full)
                roll_hz = fs * eps / (1 + eps)
                pname = "plain" if not sd else ("SD frozen" if rmode == 1 else "SD restart0")
                rows.append([fs, pname, f"{100 * eps:.2f}", f"{roll_hz:.3f}",
                             f"{1 / roll_hz:.2f}" if roll_hz > 0 else "inf",
                             pct(contrast, 0), pct(swing, 0)])
                data.append(dict(fs=fs, sd=sd, restart_mode=rmode, eps=eps, roll_hz=roll_hz,
                                 contrast=contrast, swing=swing))
    md = "## (f) Calibration pattern (all rows on for half a period, off for the other half)\n\n"
    md += ("SD variants: the 'on' write is shutdown-bracketed like a FLIP burst, under the "
           "frozen and the restart-at-digit-0 wake models. contrast = largest "
           "difference between the brightest and darkest row after the flicker filter, % of "
           "full scale; swing = largest change of one row's filtered brightness over the run. "
           "Roll period = time for the lit band to travel one full frame (all 8 rows).\n\n")
    md += table(["f_s", "pattern", "mismatch %", "roll Hz", "roll period s", "row contrast %",
                 "row swing %"], rows)
    # what if the calibration ISR brackets both writes (PLAN.md: ISR at 2/T_u)?  The roll
    # nulls when T_u - 2*dark = 1/fs; the display (one bracket per tick) then runs at
    # ratio (1/fs + 2 dark) / (1/fs + dark).
    lut4 = S.design_lut(T4)
    t_word = BURST / 9
    dark = 10 * t_word
    rr = []
    for fs in (500, 800, 1300):
        ratio = (1 / fs + 2 * dark) / (1 / fs + dark)
        o = E.run_flip(T4, lut4, fs, ratio, phase=0.3, burst=BURST, **VARIANTS["SD/frozen"],
                       patterns=("mixed",))
        rr.append([fs, f"{100 * (ratio - 1):+.2f}", pct(o["pp_max"]), pct(o["pp_abs_fs"]),
                   "pass" if o["pass_plan"] else "FAIL"])
        data.append(dict(double_bracket=True, fs=fs, ratio=ratio, **o))
    md += ("\n### Calibrating with a shutdown bracket on both half-period writes, then "
           "displaying with one bracket per tick (SD/frozen, 15/7/3/1)\n\n")
    md += table(["f_s", "resulting T_u error %", "pp % own", "pp % FS", "PLAN"], rr)
    # T_u resolution
    md += "\n### Timer resolution\n\n"
    rr = []
    for fs in (500, 800, 1300):
        ticks = 16e6 / fs
        rr.append([fs, f"{ticks:.0f}", f"{100 / ticks:.4f}", f"{fs / ticks:.4f}"])
    md += table(["f_s", "T_u ticks (62.5 ns)", "1 tick = % of T_u", "roll Hz per tick"], rr)
    save("calib", md, data)


# ----------------------------------------------------------------------------- (g)
def exp_probe():
    """Hardware probe patterns to identify the chip's shutdown/wake behaviour: what each
    model variant predicts the eye would see."""
    fs = 800
    probes = {
        "P1: awake 50 us / shutdown 50 us, all on, int 15": (50e-6, 50e-6, 15),
        "P2: awake 400 us / shutdown 100 us, all on, int 15": (400e-6, 100e-6, 15),
        "P3: awake 50 us / shutdown 50 us, all on, int 0": (50e-6, 50e-6, 0),
    }
    rows, data = [], []
    for pn, (awake, dark, code) in probes.items():
        T, A, D = [-2e-6, -1e-6], [10, 15], [code, 0]
        for r in range(8):
            T.append(-0.5e-6 + r * 1e-8); A.append(r + 1); D.append(0xFF)
        t = 0.0
        while t < 1.0:
            T.append(t); A.append(12); D.append(1)
            T.append(t + awake); A.append(12); D.append(0)
            t += awake + dark
        T, A, D = np.array(T), np.array(A), np.array(D)
        for mode, mname in ((0, "restart at digit 0"), (1, "frozen, resume"),
                            (2, "same digit, slot restarts"), (3, "next digit")):
            for wd in (0.0, 20e-6):
                lum, _ = M.simulate(T, A, D, fs=fs, phase=0.3, restart_mode=mode, wake_delay=wd,
                                    t0=0, t1=1.0, dt=E.DT, regs=[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, code, 7, 0, 0, 0, 0])
                m = lum[int(0.1 / E.DT):].mean(axis=0).mean(axis=1) / (31 / 32 / 8)
                rows.append([pn, mname, f"{wd * 1e6:.0f}", " ".join(f"{100 * v:.0f}" for v in m)])
                data.append(dict(probe=pn, mode=mode, wake_delay=wd, rows=list(m)))
    md = "## (g) Hardware probes for the shutdown/wake behaviour (model predictions)\n\n"
    md += ("Row brightness (% of a stock row at intensity 15) for rows 1..8 that each wake "
           "model predicts. Different predictions mean the probe can tell the models apart "
           "by eye.\n\n")
    md += table(["probe", "wake model", "wake delay us", "rows 1..8 %"], rows)
    save("probe", md, data)


# ----------------------------------------------------------------------------- (h)
def exp_intensity():
    """global intensity (mext 0x17): scale every frame's code so its weight 2c+1 is
    multiplied by (g+1)/16, keep the lookup, check the ramp (static analysis)"""
    rows, data = [], []
    for name, codes in (("5p 15/15/15/7/3", T5), ("4p 15/7/3/1", T4)):
        lut = S.design_lut(codes)
        for g in range(15, -1, -1):
            sc = (g + 1) / 16.0
            cg = [int(max(0, min(15, round(((2 * c + 1) * sc - 1) / 2)))) for c in codes]
            st = S.ramp_stats(cg, lut)
            rows.append([name, g, "/".join(map(str, cg)), pct(st["peak_stock"]),
                         "yes" if st["monotonic"] else "NO", pct(st["lin_err_max"], 1),
                         f"{st['step_ratio']:.2f}" if st["monotonic"] else "-"])
            data.append(dict(table=name, g=g, codes=cg, **st))
    md = "## (h) Global intensity g (0x17) by scaling the frame codes\n\n"
    md += ("code' = round(((2c+1)(g+1)/16 - 1)/2), lookup unchanged. Static analysis only.\n\n")
    md += table(["table", "g", "codes", "peak % stock", "monotonic", "lin err %FS", "step ratio"], rows)
    save("intensity", md, data)


EXPS = dict(intensity=exp_intensity, naive=exp_naive, exact=exp_exact, sweep=exp_sweep, burst=exp_burst,
            tables=exp_tables, calib=exp_calib, probe=exp_probe)


def main():
    global QUICK, JOBS
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", default=None, help="results directory (default results/)")
    ap.add_argument("exps", nargs="+")
    a = ap.parse_args()
    QUICK, JOBS = a.quick, a.jobs
    global RES
    if a.out:
        RES = a.out
    names = list(EXPS) if a.exps == ["all"] else a.exps
    for n in names:
        t0 = time.time()
        EXPS[n]()
        print(f"[{n}: {time.time() - t0:.0f} s]", file=sys.stderr)


if __name__ == "__main__":
    main()
