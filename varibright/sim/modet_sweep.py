import json, sys
import numpy as np
from multiprocessing import Pool
import modet

FS = [500.0, 800.0, 1300.0]
PS = [3, 4, 5, 6, 8, 10, 12, 15]
FINE = [round(1 + x / 400.0, 5) for x in range(-20, 21)]          # +-5 % in 0.25 % steps
COARSE = [round(x, 3) for x in np.arange(0.6, 1.61, 0.05) if abs(x - 1) > 0.051]

def job(a):
    P, fs, ratio, eff = a
    r = modet.run(P, fs, ratio, digit_effect=eff)
    return dict(P=P, fs=fs, ratio=ratio, eff=eff, pp=r["pp_max"], rms=r["rms_max"],
                band=r["band_max"], ok=bool(r["pass_plan"]), strict=bool(r["pass_strict"]))

if __name__ == "__main__":
    jobs = [(P, fs, ra, eff) for P in PS for fs in FS for eff in (0, 1) for ra in FINE + COARSE]
    with Pool(2) as p:
        res = p.map(job, jobs, chunksize=8)
    json.dump(res, open("results/modet.json", "w"))
    print("| P | f_s | cycle Hz | write model | exact: pp % / band %FS | worst pp % within +-1 % | +-3 % | +-5 % | passes in +-5 % | passes 0.6..1.6 coarse |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for P in PS:
        for fs in FS:
            for eff in (0, 1):
                rs = [r for r in res if r["P"] == P and r["fs"] == fs and r["eff"] == eff]
                ex = [r for r in rs if r["ratio"] == 1.0][0]
                def w(lim):
                    return max(r["pp"] for r in rs if abs(r["ratio"] - 1) <= lim + 1e-9) * 100
                fine = [r for r in rs if abs(r["ratio"] - 1) <= 0.0501]
                co = [r for r in rs if abs(r["ratio"] - 1) > 0.0501]
                print(f"| {P} | {fs:.0f} | {fs/P:.0f} | {'immediate' if eff == 0 else 'next slot'} | "
                      f"{ex['pp']*100:.2f} / {ex['band']*100:.2f} | {w(0.01):.2f} | {w(0.03):.2f} | {w(0.05):.2f} | "
                      f"{sum(r['ok'] for r in fine)}/{len(fine)} | {sum(r['ok'] for r in co)}/{len(co)} |")
