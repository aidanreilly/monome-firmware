"""Mode T with a shutdown bracket around each burst (T-SD): constant intensity 15."""
import json
from multiprocessing import Pool
import evalflip, modet

FINE = [round(1 + x / 400.0, 5) for x in range(-20, 21)]
RM = {0: "restart at 0", 1: "frozen", 2: "same digit", 3: "next digit"}

def job(a):
    P, fs, ratio, eff, rm, wd = a
    r = evalflip.run_flip([15] * P, modet.lut_T(P), fs, ratio, phase=0.3, burst=60e-6,
                          order="int_none", digit_effect=eff, int_effect=eff, shutdown=True,
                          restart_mode=rm, wake_delay=wd)
    return dict(P=P, fs=fs, ratio=ratio, eff=eff, rm=rm, wd=wd, pp=r["pp_max"], band=r["band_max"],
                gain=r["gain"], ok=bool(r["pass_plan"]))

if __name__ == "__main__":
    jobs = [(P, fs, ra, eff, rm, wd) for P in (3, 4, 5, 6) for fs in (500.0, 800.0, 1300.0)
            for eff in (0, 1) for rm in (0, 1, 2, 3) for wd in (0.0,) for ra in FINE]
    with Pool(2) as p:
        res = p.map(job, jobs, chunksize=8)
    json.dump(res, open("results/modet_sd.json", "w"))
    print("| P | f_s | wake model | write model | exact pp % / band %FS | gain % | worst pp % within +-0.5 % | +-1 % | +-2 % | +-5 % | passing ratios (%) |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for P in (3, 4, 5, 6):
        for fs in (500.0, 800.0, 1300.0):
            for rm in (0, 1, 2, 3):
                for eff in (0, 1):
                    rs = [r for r in res if (r["P"], r["fs"], r["rm"], r["eff"]) == (P, fs, rm, eff)]
                    ex = [r for r in rs if r["ratio"] == 1.0][0]
                    w = lambda lim: max(r["pp"] for r in rs if abs(r["ratio"] - 1) <= lim + 1e-9) * 100
                    ok = sorted(r["ratio"] for r in rs if r["ok"])
                    span = f"{(ok[0]-1)*100:+.2f}..{(ok[-1]-1)*100:+.2f} ({len(ok)}/41)" if ok else "none"
                    print(f"| {P} | {fs:.0f} | {RM[rm]} | {'imm' if eff == 0 else 'next'} | {ex['pp']*100:.2f} / {ex['band']*100:.2f} | "
                          f"{ex['gain']*100:.0f} | {w(0.005):.2f} | {w(0.01):.2f} | {w(0.02):.2f} | {w(0.05):.2f} | {span} |")
