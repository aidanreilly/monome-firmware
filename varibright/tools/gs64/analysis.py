"""Analysis of ADC captures: scan rate, scan creep and scan position.

Blocks are [(block_index, values)] from gs64.capture.parse_blocks; sample n of
block i was taken at timer tick (i * 256 + n) * tps (ADC and Timer1 share the crystal)."""
import numpy as np

CREEP_LIMIT = 0.0005        # frames per cycle, the spec's steadiness bound
JUMP = 0.25                 # a block step this far (frames) from the median step is a wrap-around


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


def _block_positions(blocks, tps, cycle_ticks, nf):
    """Per block: phase of the frame-cycle fundamental, as a position in frames.

    Linear (no clipping) and over the whole block, so content lit equally in every
    frame cancels and only frame-to-frame differences (the marker) remain.
    Returns arrays (index, position_frames, weight)."""
    idx, pos, wt = [], [], []
    for i, b in blocks:
        tick = (i * 256 + np.arange(256)) * float(tps)
        z = ((b - b.mean()) * np.exp(2j * np.pi * (tick % cycle_ticks) / cycle_ticks)).sum()
        idx.append(i)
        pos.append(np.angle(z) / (2 * np.pi) % 1 * nf)
        wt.append(abs(z))
    order = np.argsort(idx)
    return np.array(idx)[order], np.array(pos)[order], np.array(wt)[order]


def creep(blocks, tps, cycle_ticks, nf):
    """Scan creep in frames per cycle. Returns {'creep', 'jumps', 'steps'}.

    Steps are taken between consecutive captured blocks. A step that differs from
    the median step by JUMP frames or more is a wrap-around. With no wraps the creep is the slope of a line
    through every block position (resolution far below CREEP_LIMIT); with wraps it
    is the mean of the steps not next to a wrap (a wrap blurs the blocks around it)."""
    idx, pos, _ = _block_positions(blocks, tps, cycle_ticks, nf)
    cpb = 256 * float(tps) / cycle_ticks                 # cycles per block
    dn = np.diff(idx)
    d = (np.diff(pos) + nf / 2) % nf - nf / 2
    per_block = d / dn
    big = np.abs(per_block - np.median(per_block)) >= JUMP if len(per_block) else per_block > 0
    jumps = int(big.sum())
    if jumps == 0 and len(pos) > 3:
        un = np.r_[pos[0], pos[0] + np.cumsum(d)]
        c = float(np.polyfit(idx * cpb, un, 1)[0])
    else:
        near = big | np.r_[big[1:], False] | np.r_[False, big[:-1]]   # wraps blur their neighbours
        small = per_block[~near]
        c = float(small.mean() / cpb) if len(small) else float("nan")
    return {'creep': c, 'jumps': jumps, 'steps': int(len(d))}


def position(blocks, tps, cycle_ticks, nf):
    """Scan position (frame-cycle fundamental phase, in frames). Returns {'mean', 'spread', 'drift'}."""
    idx, pos, _ = _block_positions(blocks, tps, cycle_ticks, nf)
    t = (idx * 256 + 128) * float(tps) / 16e6
    un = np.unwrap(pos * 2 * np.pi / nf) * nf / (2 * np.pi)
    fit = np.polyfit(t, un, 1)
    return {'mean': float(un.mean() % nf), 'spread': float(np.std(un - np.polyval(fit, t))),
            'drift': float(fit[0])}


def steady(c):
    """The spec's pass criterion for one capture."""
    return abs(c['creep']) <= CREEP_LIMIT and c['jumps'] == 0
