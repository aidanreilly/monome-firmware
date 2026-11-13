#!/usr/bin/env python3
"""Unit tests of the MAX7219 behavioural model and the flicker metric (simulation only)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import flicker as F  # noqa: E402
import gen  # noqa: E402
import maxmodel as M  # noqa: E402
import schemes as S  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def writes(lst):
    t = np.array([w[0] for w in lst], float)
    return t, np.array([w[1] for w in lst]), np.array([w[2] for w in lst])


def static_rows(rows, intensity=15, extra=()):
    lst = [(-1e-6 * (20 - i), i + 1, rows[i]) for i in range(8)]
    lst.append((-1e-7, 10, intensity))
    lst += list(extra)
    return writes(lst)


full = 31 / 32 / 8

# 1. stock static display, intensity 15
t, a, d = static_rows([0xFF] * 8)
lum, _ = M.simulate(t, a, d, fs=800, t1=0.1)
check(np.allclose(lum.mean(axis=0), full, rtol=1e-3), "all-on intensity 15 gives 31/32 x 1/8 per LED")

# 2. intensity table
ok = True
for n in range(16):
    t, a, d = static_rows([0xFF] * 8, intensity=n)
    lum, _ = M.simulate(t, a, d, fs=800, t1=0.05)
    ok &= np.allclose(lum.mean(axis=0), (2 * n + 1) / 32 / 8, rtol=1e-3)
check(ok, "intensity code n gives duty (2n+1)/32 of the slot")

# 3. scan limit
t, a, d = static_rows([0xFF] * 8, extra=[(-5e-8, 11, 3)])
lum, _, fr = M.simulate(t, a, d, fs=800, t1=0.05, want_frames=True)
m = lum.mean(axis=0).mean(axis=1)
check(np.allclose(m[:4], 31 / 32 / 4, rtol=1e-3) and np.allclose(m[4:], 0), "scan limit 3: 4 digits at 1/4 duty")
check(abs(np.median(np.diff(fr)) - 1 / 800 / 2) < 1e-9, "scan limit 3: frame rate 8 fosc / 4")

# 4. frame period
t, a, d = static_rows([0xFF] * 8)
_, _, fr = M.simulate(t, a, d, fs=650, t1=0.05, want_frames=True)
check(abs(np.median(np.diff(fr)) - 1 / 650) < 1e-9, "frame period = 1/fs")

# 5. shutdown
t, a, d = static_rows([0xFF] * 8, extra=[(0.02, 12, 0)])
lum, tt = M.simulate(t, a, d, fs=800, t1=0.04, dt=50e-6)
check(lum[tt > 0.0201].sum() == 0 and lum[tt < 0.0199].sum() > 0, "shutdown blanks the display")

# 6. display test overrides rows and shutdown
t, a, d = static_rows([0x00] * 8, intensity=0, extra=[(-5e-8, 15, 1), (-4e-8, 12, 0)])
lum, _ = M.simulate(t, a, d, fs=800, t1=0.05)
check(np.allclose(lum.mean(axis=0), full, rtol=1e-3), "display test: all LEDs at 31/32 despite rows 0, intensity 0, shutdown")

# 7. decode mode (Code B '8' = 0x7F on digit 0)
t, a, d = static_rows([0x08] + [0] * 7, extra=[(-5e-8, 9, 0x01)])
lum, _ = M.simulate(t, a, d, fs=800, t1=0.02)
lit = (lum.mean(axis=0)[0] > 0).astype(int)
check(list(lit) == [1, 1, 1, 1, 1, 1, 1, 0], "decode mode: digit 0 value 8 lights segments G..A")

# 8. write effect: mid-slot write to digit 0, immediate vs next slot
fs = 1000.0
Td = 1 / fs / 8
for eff, expect in ((0, 31 / 32 - 0.5), (1, 0.0)):
    # rows off, digit 0 slot starts at t=0 (phase 0); write 0xFF to digit 0 at mid-slot of frame 10
    tw = 10 / fs + Td * 0.5
    t, a, d = writes([(-1e-7, 10, 15), (-5e-8, 1, 0), (tw, 1, 0xFF), (tw + Td * 2, 1, 0)])
    lum, tt = M.simulate(t, a, d, fs=fs, phase=0.0, digit_effect=eff, t0=0, t1=0.02, dt=1e-6)
    got = lum[:, 0, 0].sum() * 1e-6 / Td
    check(abs(got - expect) < 0.01,
          f"digit_effect={eff}: mid-slot write lights {got:.3f} of the slot (expect {expect:.3f})")

# 9. PWM position inside the slot
for pos, lo, hi in ((0.0, 0.0, 3 / 32), (1.0, 29 / 32, 1.0)):
    t, a, d = static_rows([0x01] + [0] * 7, intensity=1)
    lum, tt = M.simulate(t, a, d, fs=1000, phase=0.0, pwm_pos=pos, t0=0, t1=0.002, dt=1e-7)
    on = tt[lum[:, 0, 0] > 0]
    frac = (on[0] % (1 / 1000)) / Td, (on[-1] % (1 / 1000)) / Td
    check(abs(frac[0] - lo) < 0.01 and abs(frac[1] - hi) < 0.01,
          f"pwm_pos={pos}: code 1 lit {frac[0]:.3f}..{frac[1]:.3f} of the slot")

# 10. blanking parameter
t, a, d = static_rows([0xFF] * 8)
lum, _ = M.simulate(t, a, d, fs=800, blank=0.1, t1=0.05)
check(np.allclose(lum.mean(axis=0), full * 0.9, rtol=1e-3), "inter-digit blanking 10 % scales light by 0.9")

# 11. frozen restart: oscillator does not advance during shutdown
t, a, d = static_rows([0xFF] * 8, extra=[(0.01 + 1e-4 * k, 12, k % 2) for k in range(0, 40)])
_, _, fr0 = M.simulate(t, a, d, fs=800, restart_mode=1, t1=0.03, want_frames=True)
t, a, d = static_rows([0xFF] * 8)
_, _, frr = M.simulate(t, a, d, fs=800, t1=0.03, want_frames=True)
late = fr0[fr0 > 0.02][0] - frr[frr > 0.018][0]
check(abs(late - 20 * 1e-4) < 1e-9, f"restart_mode 1: scan delayed by the total shutdown time ({late * 1e3:.3f} ms)")

# 12. metric: a 10 Hz 1 % sinusoid passes almost unattenuated, a 100 Hz one is suppressed
dt = 50e-6
tt = np.arange(0, 1.25, dt)
for f, lo, hi in ((10, 0.019, 0.021), (100, 0, 0.0002)):
    x = (1 + 0.01 * np.sin(2 * np.pi * f * tt))[:, None, None] * np.ones((1, 8, 8))
    st = F.led_stats(x, dt)
    check(lo <= st["pp"].max() <= hi, f"metric: 1 % sinusoid at {f} Hz -> pp {100 * st['pp'].max():.3f} %")
check(abs(float(F.filter_gain([32])[0]) - 0.7071) < 0.01, "metric: -3 dB at 32 Hz")

# 13. FLIP at exact rate under the latched model with burst away from slot starts: exact means
codes = [15, 7, 3, 1]
lut = S.design_lut(codes)
lv = gen.pattern("lo")
t, a, d = gen.flip(lv, codes, lut, 1 / 800 + 10 * 20e-6 / 9, 0.6, burst=20e-6, shutdown=True)
lum, _ = M.simulate(t, a, d, fs=800, phase=0.3, restart_mode=1, t1=0.6, dt=dt)
nom = gen.nominal_lum(lv, codes, lut)
st = F.led_stats(lum, dt, 0.2)
g = st["mean"][nom > 0].sum() / nom[nom > 0].sum()
check(np.abs(st["mean"][nom > 0] / (g * nom[nom > 0]) - 1).max() < 0.015,
      "FLIP-SD at the calibrated rate reproduces the lookup weights within 1.5 % (window not a whole number of cycles)")

# 14. lookup design
for codes in ([15, 7, 3, 1], [15, 15, 15, 7, 3], [15, 15, 15, 15, 11, 6]):
    lut = S.design_lut(codes)
    st = S.ramp_stats(codes, lut)
    check(st["monotonic"] and lut[0] == 0 and lut[15] == (1 << len(codes)) - 1,
          f"lookup for {codes} is monotonic, 0 = off, 15 = all frames")
check(S.design_lut([15, 7, 3, 1]) == [0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15],
      "lookup for the binary table is the bit-reversed identity (frame 0 = MSB)")

print("MODEL TESTS " + ("FAILED: %d" % len(FAILS) if FAILS else "PASSED"))
sys.exit(1 if FAILS else 0)
