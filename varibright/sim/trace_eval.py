#!/usr/bin/env python3
"""Evaluate a gs64sim MAX7219 trace with the behavioural model and the flicker metric.

usage: trace_eval.py TRACE [--fs 800] [--phase 0.3] [--effect imm|lat] [--restart 1]
                           [--wake-delay US] [--t0 S] [--t1 S] [--settle S] [--json]
By default the chip is taken as running from t = 0 with the given scan phase (the trace's
own init writes are applied on top); --powerup starts it in shutdown instead.
Prints per-LED mean luminance (% of a stock LED at intensity 15), worst filtered pp and
rms modulation (% of the LED's own mean) over [t0 + settle, t1].  Simulation only.
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flicker as F  # noqa: E402
import maxmodel as M  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--fs", type=float, default=800.0)
    ap.add_argument("--phase", type=float, default=0.3)
    ap.add_argument("--effect", choices=("imm", "lat"), default="imm")
    ap.add_argument("--restart", type=int, default=1, help="shutdown wake model 0..3")
    ap.add_argument("--wake-delay", type=float, default=0.0, help="us")
    ap.add_argument("--pwm-pos", type=float, default=0.0)
    ap.add_argument("--blank", type=float, default=0.0)
    ap.add_argument("--fcpu", type=float, default=16e6)
    ap.add_argument("--t0", type=float, default=None, help="start (s), default first write")
    ap.add_argument("--t1", type=float, default=None, help="end (s), default last write")
    ap.add_argument("--settle", type=float, default=0.25)
    ap.add_argument("--powerup", action="store_true",
                    help="start in the datasheet power-up state (shutdown); the scan phase is "
                         "then set by the firmware's first wake write and --phase is ignored")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    t, ad, d = M.read_trace(a.trace, a.fcpu)
    t0 = a.t0 if a.t0 is not None else 0.0
    t1 = a.t1 if a.t1 is not None else float(t[-1])
    eff = 1 if a.effect == "lat" else 0
    lum, _ = M.simulate(t, ad, d, fs=a.fs, phase=a.phase, blank=a.blank, pwm_pos=a.pwm_pos,
                        digit_effect=eff, int_effect=eff, restart_mode=a.restart,
                        wake_delay=a.wake_delay * 1e-6,
                        regs=M.POWERUP_REGS if a.powerup else M.RUNNING_REGS, tstart=0.0,
                        t0=t0, t1=t1, dt=50e-6)
    st = F.led_stats(lum, 50e-6, a.settle)
    rel = st["mean"] / M.STOCK_FULL
    res = dict(mean_pct_stock=(100 * rel).round(2).tolist(),
               pp_pct=(100 * st["pp"]).round(2).tolist(),
               rms_pct=(100 * st["rms"]).round(3).tolist(),
               worst_pp_pct=float(100 * st["pp"].max()),
               worst_rms_pct=float(100 * st["rms"].max()),
               worst_pp_abs_pct_stock=float(100 * st["pp_abs"].max() / M.STOCK_FULL))
    if a.json:
        print(json.dumps(res))
        return
    np.set_printoptions(precision=1, suppress=True, linewidth=120)
    print("mean luminance, % of stock LED (rows = digit 1..8, cols = segment bit 0..7):")
    print(np.array(res["mean_pct_stock"]))
    print("filtered pp modulation, % of own mean:")
    print(np.array(res["pp_pct"]))
    print(f"worst pp {res['worst_pp_pct']:.2f} %, worst rms {res['worst_rms_pct']:.3f} %, "
          f"worst pp {res['worst_pp_abs_pct_stock']:.2f} % of a stock LED")


if __name__ == "__main__":
    main()
