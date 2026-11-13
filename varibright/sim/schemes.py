"""Plane tables ("schemes") for FLIP and the level -> plane-mask lookup.

A scheme is a list of per-frame MAX7219 intensity codes, in the order the frames are
shown, plus a 16-entry lookup `lut[level]` of frame masks (bit k set = LED lit in
frame k).  Frame k contributes weight 2*code_k + 1 (the chip's duty is (2n+1)/32).
Binary tables are just the special case lut[L] = L with one frame per bit.
"""
import itertools

import numpy as np

STOCK_W = 31  # weight of one stock frame at intensity 15 (duty 31/32)


def weights(codes):
    return np.array([2 * c + 1 for c in codes], dtype=float)


def mask_sum(mask, w):
    return sum(w[k] for k in range(len(w)) if (mask >> k) & 1)


def lut_sums(codes, lut):
    w = weights(codes)
    return np.array([mask_sum(m, w) for m in lut])


def spread_A(codes, mask):
    """worst relative excess of one repeated/dropped frame for an LED with this mask:
    max_k |x_k / mean - 1| in 'mean-frames' (see README, slip transients)."""
    w = weights(codes)
    x = np.array([w[k] if (mask >> k) & 1 else 0.0 for k in range(len(w))])
    m = x.mean()
    if m == 0:
        return 0.0
    return float(np.abs(x / m - 1).max())


def design_lut(codes, target="linear"):
    """Monotonic 16-entry lookup minimising the worst deviation from a linear ramp
    (level 15 = all frames on, level 0 = off), then the sum of squared deviations.
    Exact: binary search on the max-error bound, additive DP for the SSE.  Among masks
    with equal sum the one with the smallest slip excess (spread_A) is used."""
    P = len(codes)
    w = weights(codes)
    full = (1 << P) - 1
    W = w.sum()
    by_sum = {}
    for m in range(1, full):
        s = mask_sum(m, w)
        best = by_sum.get(s)
        if best is None or spread_A(codes, m) < spread_A(codes, best):
            by_sum[s] = m
    sums = np.array(sorted(by_sum))
    n = len(sums)
    if n < 14:
        return None
    tgt = W * np.arange(16) / 15.0
    err = np.abs(sums[None, :] - tgt[1:15, None]) / W      # [14 levels, n]

    def dp(bound):
        INF = 1e18
        cost = np.where(err[0] <= bound, err[0] ** 2, INF)
        backs = []
        for L in range(1, 14):
            pm = np.minimum.accumulate(cost)                   # best over indices <= j
            arg = np.zeros(n, dtype=int)
            bi = 0
            for j in range(n):
                if cost[j] < cost[bi]:
                    bi = j
                arg[j] = bi
            prev = np.concatenate(([INF], pm[:-1]))
            parg = np.concatenate(([-1], arg[:-1]))
            c = np.where(err[L] <= bound, prev + err[L] ** 2, INF)
            cost = c
            backs.append(parg)
        j = int(np.argmin(cost))
        if cost[j] >= 1e17:
            return None
        idx = [j]
        for parg in reversed(backs):
            j = int(parg[j])
            idx.append(j)
        return idx[::-1]

    cands = np.unique(err)
    lo, hi = 0, len(cands) - 1
    if dp(cands[hi]) is None:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if dp(cands[mid]) is not None:
            hi = mid
        else:
            lo = mid + 1
    idx = dp(cands[lo])
    lut = [0] + [by_sum[int(sums[j])] for j in idx] + [full]
    return lut


def ramp_stats(codes, lut):
    s = lut_sums(codes, lut)
    W = s[15]
    lin = W * np.arange(16) / 15.0
    steps = np.diff(s)
    return dict(
        peak_stock=float(W / (len(codes) * STOCK_W)),     # vs stock display at intensity 15
        peak_plan=float(W / (len(codes) * 32)),            # PLAN.md normalisation (/32)
        monotonic=bool((steps > 0).all()),
        lin_err_max=float(np.abs(s - lin).max() / W),       # fraction of full scale
        step_ratio=float(steps.max() / steps.min()),        # 1 = perfectly even steps
        min_step=float(steps.min() / W),
        A_max=float(max(spread_A(codes, m) for m in lut[1:])),
        sums=[int(v) for v in s],
    )


def harmonic_score(codes, lut, fs, gain_fn):
    """Sum over levels' worst case of filtered harmonic amplitudes at m*fs/P (steady state,
    exact rate).  gain_fn(f) is the flicker filter gain."""
    return harmonic_scores(codes, lut, fs, gain_fn)[0]


def harmonic_scores(codes, lut, fs, gain_fn):
    """(worst, mean) over levels 1..15 of the filtered steady-state harmonic content"""
    P = len(codes)
    w = weights(codes)
    worst = 0.0
    allv = []
    for L in range(1, 16):
        x = np.array([w[k] if (lut[L] >> k) & 1 else 0.0 for k in range(P)])
        X = np.fft.fft(x)
        tot = 0.0
        for m in range(1, P):
            tot += 2 * abs(X[m]) / abs(X[0]) * gain_fn(m * fs / P) / 2
        worst = max(worst, tot)
        allv.append(tot)
    return worst, float(np.mean(allv))


def permute(codes, lut, order):
    """reorder frames: new frame i = old frame order[i]"""
    nc = [codes[o] for o in order]
    nl = []
    for m in lut:
        v = 0
        for i, o in enumerate(order):
            if (m >> o) & 1:
                v |= 1 << i
        nl.append(v)
    return nc, nl


def best_order(codes, lut, fs, gain_fn):
    """frame order (rotations are equivalent) minimising harmonic_score at fs."""
    P = len(codes)
    best = None
    for perm in itertools.permutations(range(1, P)):
        order = (0,) + perm
        nc, nl = permute(codes, lut, order)
        sc = harmonic_scores(nc, nl, fs, gain_fn)
        sc = (round(sc[0], 9), sc[1])
        if best is None or sc < best[0]:
            best = (sc, list(order))
    return best


def binary(codes):
    """one frame per bit, frame k = bit k"""
    return list(codes), list(range(16))


# tables from PLAN.md, frame order as listed (MSB first), lookups designed by design_lut
PLAN_TABLES = {
    "4p 15/7/3/1": [15, 7, 3, 1],
    "5p 15/15/7/3/1": [15, 15, 7, 3, 1],
    "6p 15/15/15/7/3/1": [15, 15, 15, 7, 3, 1],
}


def search_tables(P, max_lin_err=0.02, top=5):
    """brute-force search over code multisets of length P for the brightest tables whose
    best lookup has a linear-ramp error under max_lin_err.  Returns list of (peak, codes)."""
    res = []
    for codes in itertools.combinations_with_replacement(range(15, -1, -1), P):
        codes = list(codes)
        w = weights(codes)
        # quick reject: need 16 distinct sums
        lut = design_lut(codes)
        if lut is None:
            continue
        st = ramp_stats(codes, lut)
        if st["monotonic"] and st["lin_err_max"] <= max_lin_err:
            res.append((st["peak_stock"], codes, st["lin_err_max"]))
    res.sort(key=lambda r: (-r[0], r[2]))
    return res[:top]
