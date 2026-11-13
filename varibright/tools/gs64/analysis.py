"""Analysis of ADC captures: scan rate, scan creep and scan position.

Blocks are [(block_index, values)] from gs64.capture.parse_blocks; sample n of
block i was taken at timer tick (i * 256 + n) * tps (ADC and Timer1 share the crystal)."""
import numpy as np

CREEP_LIMIT = 0.0005        # frames per cycle, the spec's steadiness bound
JUMP = 0.15                 # a step at least this large (frames) is a wrap-around


def _tx(blocks, tps):
    n = np.concatenate([i * 256 + np.arange(256) for i, _ in blocks])
    x = np.concatenate([b for _, b in blocks])
    return n * float(tps), x


def _spec(t_s, x, f):
    out = np.empty(len(f))
    for k in range(0, len(f), 200):
        ff = f[k:k + 200, None]
        out[k:k + 200] = np.abs(np.exp(-2j * np.pi * ff * t_s[None, :]) @ x)
    return out


def scan_rate(blocks, tps, lo=500.0, hi=1300.0, digit=False):
    """Free-running MAX7219 scan rate in Hz from the strongest line in lo..hi.

    digit=True searches the 8x digit-rate line instead (all columns equally lit,
    where the scan fundamental cancels) and divides by 8."""
    t, x = _tx(blocks, tps)
    t = t / 16e6
    x = x - x.mean()
    m = 8.0 if digit else 1.0
    f = np.arange(lo * m, hi * m, 0.25 * m)
    f0 = f[np.argmax(_spec(t, x, f))]
    for half, step in ((m, 0.005 * m), (0.01 * m, 0.0005 * m)):
        f = np.arange(f0 - half, f0 + half, step)
        f0 = f[np.argmax(_spec(t, x, f))]
    return f0 / m


def _cycle_positions(blocks, tps, cycle_ticks, nf):
    """Per whole cycle inside each block: circular centroid (in frames) of the positive pulse lobe."""
    base = np.median(np.concatenate([b for _, b in blocks]))
    per_block = []
    for i, b in blocks:
        tick = (i * 256 + np.arange(256)) * float(tps)
        cyc = np.floor(tick / cycle_ticks).astype(int)
        pos = []
        for c in np.unique(cyc)[1:-1]:
            m = cyc == c
            w = np.clip(b[m] - base, 0, None)
            if w.sum() < 5:
                pos.append(np.nan)
                continue
            ph = (tick[m] - c * cycle_ticks) / cycle_ticks
            pos.append(np.angle((w * np.exp(2j * np.pi * ph)).sum()) / (2 * np.pi) % 1 * nf)
        per_block.append(((i * 256 + 128) * float(tps) / 16e6, np.array(pos)))
    return per_block


def creep(blocks, tps, cycle_ticks, nf):
    """Scan creep in frames per cycle. Returns {'creep', 'jumps', 'steps'}.

    With no wrap-arounds the creep is the slope of a line through every cycle
    position over the whole capture (resolution far below CREEP_LIMIT). With
    wraps it falls back to the mean of the small cycle-to-cycle steps."""
    steps, cyc_t, cyc_p = [], [], []
    cps = 16e6 / cycle_ticks
    for tb, pos in _cycle_positions(blocks, tps, cycle_ticks, nf):
        d = np.diff(pos)
        d = (d + nf / 2) % nf - nf / 2
        steps += list(d[~np.isnan(d)])
        k = np.arange(len(pos))
        ok = ~np.isnan(pos)
        cyc_t += list(tb + (k[ok] - len(pos) / 2) / cps)
        cyc_p += list(pos[ok])
    steps = np.array(steps)
    jumps = int(np.sum(np.abs(steps) >= JUMP))
    if jumps == 0 and len(cyc_p) > 10:
        order = np.argsort(cyc_t)
        t = np.array(cyc_t)[order]
        un = np.unwrap(np.array(cyc_p)[order] * 2 * np.pi / nf) * nf / (2 * np.pi)
        c = float(np.polyfit(t, un, 1)[0] / cps)
    else:
        small = steps[np.abs(steps) < JUMP]
        c = float(small.mean()) if len(small) else float('nan')
    return {'creep': c, 'jumps': jumps, 'steps': int(len(steps))}


def position(blocks, tps, cycle_ticks, nf):
    """Scan position per block (circular mean of cycle positions). Returns {'mean', 'spread', 'drift'}."""
    t, a = [], []
    for tb, pos in _cycle_positions(blocks, tps, cycle_ticks, nf):
        pos = pos[~np.isnan(pos)]
        if len(pos):
            t.append(tb)
            a.append(np.angle(np.exp(2j * np.pi * pos / nf).mean()) / (2 * np.pi) % 1)
    t, a = np.array(t), np.array(a)
    un = np.unwrap(a * 2 * np.pi) / (2 * np.pi)
    fit = np.polyfit(t, un, 1)
    return {'mean': float((un.mean() % 1) * nf), 'spread': float(np.std(un - np.polyval(fit, t)) * nf),
            'drift': float(fit[0] * nf)}


def steady(c):
    """The spec's pass criterion for one capture."""
    return abs(c['creep']) <= CREEP_LIMIT and c['jumps'] == 0
