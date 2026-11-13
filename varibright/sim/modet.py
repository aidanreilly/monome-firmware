"""Mode T (PLAN.md section 8): constant intensity, frame-locked temporal dither.
Level step s of P = s on-frames spread evenly over a P-frame cycle."""
import sys, time, json
import numpy as np
import evalflip

def spread_mask(s, P):
    m = 0
    acc = 0
    for k in range(P):
        acc += s
        if acc >= P:
            acc -= P
            m |= 1 << k
    return m

def lut_T(P):
    lut = []
    for L in range(16):
        s = 0 if L == 0 else max(1, int(round(L * P / 15.0)))
        lut.append(spread_mask(s, P))
    return lut

def run(P, fs, ratio, digit_effect=0, code=15, jitter=0.0, phase=0.3, burst=50e-6):
    codes = [code] * P
    return evalflip.run_flip(codes, lut_T(P), fs, ratio, phase=phase, burst=burst,
                             order="int_none", digit_effect=digit_effect, int_effect=digit_effect,
                             jitter=jitter)

if __name__ == "__main__":
    t0 = time.time()
    r = run(4, 800.0, 1.0)
    print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()}, round(time.time() - t0, 2), "s")
