#!/usr/bin/env python3
"""Measurement campaign for the scan tracking design (plan Task 2).

usage:
  campaign.py load        free-running scan rate against LED load (mono)
  campaign.py wake        per-wake loss D at several loads (T-SD zero-creep sweeps)
  campaign.py response    frames with different loads: does the cycle average decide the lock?
  campaign.py step        scan rate right after a load change and later (electrical vs thermal)
  campaign.py range       capture range: sweep the period up and down through the lock at 3 loads
  campaign.py target      hold the scan at 8 positions across a digit slot
  campaign.py thermal M   log the scan rate for M minutes under fixed load, then dark, then load
Results go to varibright/sim/results/hw-2026-11-13/<name>.json.
"""
import json, os, sys, time
import numpy as np
from gs64.link import Grid, ADC_LIVE, ADC_SLOW
from gs64.capture import parse_blocks, TPS_FAST, TPS_SLOW
from gs64 import analysis

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'sim', 'results', 'hw-2026-11-13')
D_GUESS = 659


def save(name, data):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name + '.json'), 'w') as f:
        json.dump(data, f, indent=1)


def grid_from(cells):
    """cells: set of (x, y) lit at level 15."""
    return [[15 if (x, y) in cells else 0 for y in range(8)] for x in range(8)]


def cols(n):
    return {(x, y) for x in range(n) for y in range(8)}


def rows(n):
    return {(x, y) for x in range(8) for y in range(n)}


def spread(per_col):
    return {(x, (x + k * (8 // per_col)) % 8) for x in range(8) for k in range(per_col)}


def mono_rate(g, cells):
    g.vbset(0, 0, 0)
    g.intensity(15)
    g.pattern(grid_from(cells))
    time.sleep(0.3)
    counts = [sum((x, y) in cells for y in range(8)) for x in range(8)]
    blocks = parse_blocks(g.capture(255, ADC_LIVE))
    return analysis.scan_rate(blocks, TPS_FAST, lo=860, hi=900, digit=len(set(counts)) == 1)


def tsd_creep(g, period, cfg, levels, nf_cycle=None):
    r = g.vbset(period, 0, cfg)
    g.intensity(15)
    g.pattern(levels)
    time.sleep(0.3)
    blocks = parse_blocks(g.capture(255, ADC_LIVE | ADC_SLOW))
    nf = nf_cycle or r['nframes']
    return analysis.creep(blocks, TPS_SLOW, nf * period, nf)


SLOPE = -1.7e-4          # creep per tick of period error (frames per cycle), measured


def zero_sweep(g, centre, cfg, levels, nf_cycle=None, half=10, step=10, prehold=60, tries=8):
    """Lock period for this content: hold it prehold seconds (self-heating settles), step
    towards zero creep using the known slope until a capture is steady, then fit a line
    through steady points at +-half ticks around it. Returns (zero, slope, points)."""
    g.vbset(centre, 0, cfg)
    g.pattern(levels)
    time.sleep(prehold)
    pts = []

    def meas(p):
        c = tsd_creep(g, p, cfg, levels, nf_cycle)
        pts.append((p, c['creep'], c['jumps']))
        print(f"    period {p}: creep {c['creep']:+.5f} jumps {c['jumps']}", flush=True)
        return c

    p = centre
    for _ in range(tries):
        c = meas(p)
        if analysis.steady(c):
            break
        p += int(np.clip(round(c['creep'] / -SLOPE), -40, 40)) or (1 if c['creep'] > 0 else -1)
    for q in range(p - half, p + half + 1, step):
        if q != p:
            meas(q)
    good = [(q, c) for q, c, j in pts if j == 0 and abs(q - p) <= 2 * half]
    if len(good) >= 2 and len({q for q, _ in good}) >= 2:
        k, b = np.polyfit([q for q, _ in good], [c for _, c in good], 1)
    else:
        k, b = SLOPE, -SLOPE * p
    return -b / k, k, pts


def cmd_load(g):
    res = []
    ref = lambda: mono_rate(g, cols(1))
    cases = [(f"cols{n}", cols(n)) for n in range(1, 8)] + [(f"rows{n}", rows(n)) for n in range(1, 9)] \
        + [(f"spread{k}x8", spread(k)) for k in (1, 2, 4)]
    for name, cells in cases:
        r0 = ref()
        r = mono_rate(g, cells)
        leds = len(cells)
        per_col = [sum((x, y) in cells for y in range(8)) for x in range(8)]
        res.append({'name': name, 'leds': leds, 'lit_cols': sum(c > 0 for c in per_col),
                    'max_per_col': max(per_col), 'sum_sq': sum(c * c for c in per_col),
                    'rate': r, 'ref_1col': r0, 'delta': r - r0})
        print(f"  {name:10s} leds {leds:2d} rate {r:8.3f}  ref {r0:8.3f}  delta {r - r0:+7.3f} Hz", flush=True)
    save('load', res)
    y = np.array([c['delta'] for c in res])
    for key in ('leds', 'lit_cols', 'max_per_col', 'sum_sq'):
        x = np.array([c[key] for c in res], float)
        k, b = np.polyfit(x, y, 1)
        print(f"  fit delta ~ {key}: {k:+.4f} Hz per unit, residual rms {np.std(y - (k * x + b)):.3f} Hz")


def marker_load(n):
    """Column 0 at step 1 (frame 0 only, the position marker) plus columns 1..n at full step (every frame)."""
    return [[1] * 8 if x == 0 else ([15] * 8 if x <= n else [0] * 8) for x in range(8)]


def cmd_wake(g):
    """Lock period against average load, measured directly in T-SD P=3 with a clean marker."""
    res = []
    for n in (0, 3, 6):
        avg_leds = 8 * n + 8 / 3
        guess = int(round(18776 + 3.5 * (avg_leds - 8 / 3)))
        print(f"  {n} load columns (average {avg_leds:.1f} LEDs), sweep around {guess}", flush=True)
        z, k, pts = zero_sweep(g, guess, 0x30, marker_load(n))
        fs = mono_rate(g, cols(n + 1))
        res.append({'load_cols': n, 'avg_leds': avg_leds, 'zero': z, 'slope': k, 'points': pts,
                    'fs_after_mono_cols': fs, 'D_vs_mono': z - 16e6 / fs})
        print(f"  {n} load columns: zero creep at {z:.1f} (slope {k:.3e}); mono {n + 1} cols after: {fs:.3f} Hz",
              flush=True)
    save('wake', res)
    x = np.array([r['avg_leds'] for r in res]); y = np.array([r['zero'] for r in res])
    k, b = np.polyfit(x, y, 1)
    print(f"  lock period ~ {b:.1f} + {k:.3f} * average lit LEDs (residual {np.std(y - (k * x + b)):.1f} ticks)")


def range_scan(g, name, lv, centre, half=40, step=8, prehold=60):
    """Sweep the period up then down through centre; each point records creep, jumps, position."""
    g.vbset(centre - half, 0, 0x30)
    g.intensity(15)
    g.pattern(lv)
    time.sleep(prehold)
    sweep = list(range(centre - half, centre + half + 1, step))
    res = []
    for direction, ps in (('up', sweep), ('down', sweep[::-1])):
        for q in ps:
            g.vbset(q, 0, 0x30)
            g.pattern(lv)
            time.sleep(0.3)
            blocks = parse_blocks(g.capture(255, ADC_LIVE | ADC_SLOW))
            c = analysis.creep(blocks, TPS_SLOW, 3 * q, 3)
            pos = analysis.position(blocks, TPS_SLOW, 3 * q, 3)
            held = analysis.steady(c) and pos['spread'] < 0.06
            res.append({'case': name, 'dir': direction, 'period': q, 'creep': c['creep'], 'jumps': c['jumps'],
                        'pos': pos['mean'], 'spread': pos['spread'], 'held': held})
            print(f"  {name} {direction:4s} period {q}: creep {c['creep']:+.5f} jumps {c['jumps']:3d} "
                  f"pos {pos['mean']:.3f} spread {pos['spread']:.3f}{'  HELD' if held else ''}", flush=True)
    held = [r['period'] for r in res if r['held']]
    print(f"  {name}: held at {sorted(set(held))}", flush=True)
    return res


def cmd_range(g):
    """Is there a window of periods where the scan holds still (pull-in), and how wide?"""
    res = []
    for n, centre in ((0, 18781), (3, 18830), (6, 18903)):
        res += range_scan(g, f"load{n}", marker_load(n), centre)
        save('range', res)


def cmd_response(g):
    """Same 18.7-LED cycle average, spread differently: does the window follow the average or each frame?"""
    heavy_frame = [[1] * 8 if x < 7 else [0] * 8 for x in range(8)]     # 56 LEDs in frame 0, none in 1 and 2
    uniform = marker_load(2)                                             # 16 LEDs every frame plus marker
    res = range_scan(g, 'frame0_heavy', heavy_frame, 18820, half=48, step=6)
    save('response', res)
    res += range_scan(g, 'uniform', uniform, 18820, half=48, step=6)
    save('response', res)


def cmd_step(g):
    heavy, light = cols(7), cols(1)
    res = {}
    for name, a, b in (('heavy_to_light', heavy, light), ('light_to_heavy', light, heavy)):
        mono_rate(g, a)
        print(f"  {name}: holding first load 60 s", flush=True)
        time.sleep(60)
        seq = []
        t0 = time.time()
        for _ in range(6):
            seq.append((time.time() - t0, mono_rate(g, b)))
            print(f"    t {seq[-1][0]:5.1f} s: {seq[-1][1]:.3f} Hz", flush=True)
            time.sleep(5)
        res[name] = seq
    save('step', res)


def cmd_target(g):
    lv = [[1] * 8 if x == 0 else [0] * 8 for x in range(8)]
    fs = mono_rate(g, cols(1))
    p0 = int(round(16e6 / fs + D_GUESS))
    z, k, _ = zero_sweep(g, p0, 0x30, lv)
    p = int(round(z))
    slot = 1 / 8 * (p - D_GUESS) / p            # one digit slot, in frames
    res = []
    for i in range(8):
        g.vbset(p, 0, 0x30)
        g.pattern(lv)
        blocks = parse_blocks(g.capture(255, ADC_LIVE | ADC_SLOW))
        pos = analysis.position(blocks, TPS_SLOW, 3 * p, 3)
        c = analysis.creep(blocks, TPS_SLOW, 3 * p, 3)
        res.append({'step': i, 'pos': pos, 'creep': c})
        print(f"  step {i}: position {pos['mean']:.3f} frames spread {pos['spread']:.4f}  creep {c['creep']:+.5f} "
              f"jumps {c['jumps']}", flush=True)
        # shift by about 1/8 slot: run 40 ticks long for the time it takes to move slot/8 frames
        shift_cycles = (slot / 8) / (40 * 1.635e-4)
        g.vbset(p + 40, 0, 0x30)
        time.sleep(shift_cycles * 3 * (p + 40) / 16e6)
    save('target', {'period': p, 'slot_frames': slot, 'steps': res})


def cmd_thermal(g, minutes):
    load = cols(4)
    log = []
    t0 = time.time()

    def mark(phase):
        r = mono_rate(g, cols(1))
        log.append({'t': time.time() - t0, 'phase': phase, 'rate_1col': r})
        print(f"  t {log[-1]['t'] / 60:6.2f} min  {phase:5s} 1-col rate {r:.3f} Hz", flush=True)

    def hold(cells, seconds):
        g.vbset(0, 0, 0)
        g.intensity(15)
        g.pattern(grid_from(cells))
        time.sleep(seconds)

    end_load = t0 + minutes * 60
    while time.time() < end_load:
        mark('load')
        hold(load, 30)
    for _ in range(10):
        mark('dark')
        hold(set(), 60)
    for _ in range(10):
        mark('load2')
        hold(load, 30)
    save('thermal', log)


if __name__ == '__main__':
    a = sys.argv[1:]
    g = Grid()
    {'load': cmd_load, 'wake': cmd_wake, 'range': cmd_range, 'response': cmd_response, 'step': cmd_step,
     'target': cmd_target}.get(a[0] if a else '', lambda g: None)(g) if a and a[0] != 'thermal' \
        else (cmd_thermal(g, float(a[1])) if a else print(__doc__))
