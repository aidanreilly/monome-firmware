"""Synthetic MAX7219 write generators (stand-ins for firmware; simulation only).

All generators return (t, addr, data) numpy arrays; t is the time (s) at which each
16-bit word is latched (LOAD rising edge).  A burst of n words starting at t0 latches
word i at t0 + (i+1)*t_word.
"""
import numpy as np


def pattern(name):
    """8x8 level patterns, [row=digit 0..7][col=segment bit 0..7].
    'lo': level = (r+c) % 8      -> levels 0..7, each level once in every row
    'hi': level = 8 + (r+c) % 8  -> levels 8..15, each level once in every row
    'mixed': (c + 3r) % 16, 'full': all 15, 'one': single LED at 15, rest 0"""
    r = np.arange(8)[:, None]
    c = np.arange(8)[None, :]
    if name == "lo":
        return (r + c) % 8
    if name == "hi":
        return 8 + (r + c) % 8
    if name == "mixed":
        return (c + 3 * r) % 16
    if name == "full":
        return np.full((8, 8), 15)
    if name == "one":
        p = np.zeros((8, 8), dtype=int)
        p[3, 4] = 15
        return p
    if name.startswith("level"):
        return np.full((8, 8), int(name[5:]))
    raise ValueError(name)


def frame_rows(levels, lut, k):
    """row bytes of frame k: bit c of row r set if lut[level[r][c]] has bit k"""
    lv = np.asarray(levels)
    rows = []
    for r in range(8):
        v = 0
        for c in range(8):
            if (lut[lv[r, c]] >> k) & 1:
                v |= 1 << c
        rows.append(v)
    return rows


def nominal_lum(levels, codes, lut, blank=0.0):
    """expected mean luminance in model units (fraction of time lit) per LED"""
    w = np.array([2 * c + 1 for c in codes], float)
    lv = np.asarray(levels)
    out = np.zeros(lv.shape)
    for k in range(len(codes)):
        bit = np.vectorize(lambda L: (lut[L] >> k) & 1)(lv)
        out += bit * w[k]
    return out / (32.0 * len(codes) * 8.0) * (1 - blank)


def flip(levels, codes, lut, T_u, duration, t_begin=0.0, burst=100e-6, order="int_first",
         skip_unchanged=False, jitter=0.0, jitter_mode="uniform", seed=0, row_order=None,
         shutdown=False, words_per_burst=9):
    """FLIP: one burst per tick of period T_u, tick k shows frame k mod P.
    burst: duration of a full 9-word burst (t_word = burst / words_per_burst); skipped
           words shorten the burst, extra words (shutdown bracket) lengthen it.
    order: int_first | int_last | int_mid | int_none | dark (int first when the code
           drops, last when it rises) | bridge (rows to old AND new, int, rows to new)
    shutdown: bracket the burst with 0x0C=0 ... 0x0C=1 (display dark during the burst)"""
    rng = np.random.default_rng(seed)
    P = len(codes)
    rows = [frame_rows(levels, lut, k) for k in range(P)]
    t_word = burst / words_per_burst
    if row_order is None:
        row_order = list(range(8))
    n_ticks = int(duration / T_u) + 1
    T, A, D = [], [], []
    cur_rows = [None] * 8
    cur_int = None
    for k in range(n_ticks):
        f = k % P
        code = codes[f]
        tk = t_begin + k * T_u
        if jitter > 0:
            if jitter_mode == "uniform":
                tk += rng.uniform(-jitter, jitter)
            else:  # 'late': ISR latency only delays
                tk += rng.uniform(0, jitter)
        prev_int = cur_int
        if order == "bridge":
            # rows -> (old AND new), intensity, rows -> new: every mixed state is a
            # partial time shift of each LED's own transition, never a wrong pairing
            pre, post = [], []
            for r in row_order:
                v = rows[f][r]
                old = cur_rows[r]
                mid = v if old is None else (old & v)
                if old is None or mid != old or not skip_unchanged:
                    pre.append((r + 1, mid))
                if mid != v or not skip_unchanged:
                    post.append((r + 1, v))
                cur_rows[r] = v
            iw = [] if (skip_unchanged and cur_int == code) else [(10, code)]
            cur_int = code
            words = pre + iw + post
            if shutdown:
                words = [(12, 0)] + words + [(12, 1)]
            for i, (a, d) in enumerate(words):
                T.append(tk + (i + 1) * t_word); A.append(a); D.append(d)
            continue
        wr = []
        for r in row_order:
            v = rows[f][r]
            if skip_unchanged and cur_rows[r] == v:
                continue
            wr.append((r + 1, v))
            cur_rows[r] = v
        iw = []
        if order != "int_none" and not (skip_unchanged and cur_int == code):
            iw = [(10, code)]
            cur_int = code
        if order == "dark":
            # mixed state = brighter-code rows at the dimmer code (a deficit, never an excess)
            order_now = "int_last" if (prev_int is not None and code > prev_int) else "int_first"
        else:
            order_now = order
        if order_now == "int_first":
            words = iw + wr
        elif order_now == "int_last":
            words = wr + iw
        elif order_now == "int_mid":
            h = len(wr) // 2
            words = wr[:h] + iw + wr[h:]
        else:
            words = wr
        if shutdown:
            words = [(12, 0)] + words + [(12, 1)]
        for i, (a, d) in enumerate(words):
            T.append(tk + (i + 1) * t_word)
            A.append(a)
            D.append(d)
    return np.array(T), np.array(A), np.array(D)


def bcm_time(levels, tau, duration, burst=100e-6, t_begin=0.0, weights=(8, 4, 2, 1)):
    """Naive time-domain binary code modulation: bit planes 3..0 held for 8,4,2,1 x tau,
    intensity fixed at 15, unchanged rows skipped."""
    lv = np.asarray(levels)
    T, A, D = [t_begin - 1e-6], [10], [15]
    t_word = burst / 9
    t = t_begin
    cur = [None] * 8
    while t < t_begin + duration:
        for b, w in zip((3, 2, 1, 0), weights):
            i = 0
            for r in range(8):
                v = 0
                for c in range(8):
                    if (lv[r, c] >> b) & 1:
                        v |= 1 << c
                if cur[r] == v:
                    continue
                cur[r] = v
                i += 1
                T.append(t + i * t_word); A.append(r + 1); D.append(v)
            t += w * tau
    return np.array(T), np.array(A), np.array(D)


def pwm_time(levels, tau, duration, burst=100e-6, t_begin=0.0, steps=15):
    """Naive time-domain PWM: 15 ticks of tau per period, LED on while tick < level."""
    lv = np.asarray(levels)
    T, A, D = [t_begin - 1e-6], [10], [15]
    t_word = burst / 9
    t = t_begin
    cur = [None] * 8
    k = 0
    while t < t_begin + duration:
        ph = k % steps
        i = 0
        for r in range(8):
            v = 0
            for c in range(8):
                if lv[r, c] > ph:
                    v |= 1 << c
            if cur[r] != v:
                cur[r] = v
                i += 1
                T.append(t + i * t_word); A.append(r + 1); D.append(v)
        t += tau
        k += 1
    return np.array(T), np.array(A), np.array(D)


def naive_nominal(levels):
    """expected luminance of the naive schemes (level/15 of stock, model units)"""
    return np.asarray(levels) / 15.0 * (31 / 32) / 8.0


def calib(T_u, duration, burst=100e-6, t_begin=0.0, intensity=15):
    """Calibration pattern (PLAN.md section 3): ISR at 2/T_u alternates all rows 0xFF / 0x00."""
    T, A, D = [t_begin - 1e-6], [10], [intensity]
    t_word = burst / 9
    n = int(duration / (T_u / 2)) + 1
    for k in range(n):
        v = 0xFF if k % 2 == 0 else 0x00
        for i in range(8):
            T.append(t_begin + k * T_u / 2 + (i + 1) * t_word)
            A.append(i + 1)
            D.append(v)
    return np.array(T), np.array(A), np.array(D)
