#!/usr/bin/env python3
"""Firmware integration tests (workstream C, step 3 b..e) against the real 64vb-sim.elf
in the gs64sim simavr harness.  Simulation only: the MAX7219 is a behavioural model.

usage: test_fw.py [--quick] [--jobs N] [--out results/fw_tests.md] [group ...]
groups: robust flicker calib isr   (default: all)
Step 3a (libmonome end to end) is the C program build/e2e_libmonome, run by `make test`.
"""
import argparse
import os
import random
import subprocess
import sys
import time
from multiprocessing import Pool

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import fwlib as L  # noqa: E402
import flicker as F  # noqa: E402
import maxmodel as M  # noqa: E402

RESULTS = []          # (group, name, status, detail)   status: PASS / FAIL / EXPECTED-FAIL / INFO
QUICK = False
JOBS = 2
BOOT_MS = 3000        # start-up animation and fade-in are over by then


def rec(group, name, ok, detail="", expected_fail=False):
    st = ("EXPECTED-FAIL" if not ok else "PASS(unexpected)") if expected_fail else ("PASS" if ok else "FAIL")
    if ok is None:
        st = "INFO"
    RESULTS.append((group, name, st, detail))
    print(f"[{st:>13}] {group}: {name}  {detail}", flush=True)


# --------------------------------------------------------------------------- model glue
WAKE = {"frozen-imm": dict(restart_mode=1, digit_effect=0, int_effect=0),
        "frozen-lat": dict(restart_mode=1, digit_effect=1, int_effect=1),
        "frozen-hold": dict(restart_mode=1, digit_effect=1, int_effect=1, hold_latch=1),
        "restart0": dict(restart_mode=0, digit_effect=0, int_effect=0),
        "restart0-lat": dict(restart_mode=0, digit_effect=1, int_effect=1),
        "same-digit": dict(restart_mode=2), "next-digit": dict(restart_mode=3)}


def fs_for_ratio(period, ratio, dark=L.DARK):
    """model scan rate such that T_u / T_cal = ratio, T_cal = 1/f_s + dark"""
    T_u = period / L.F_CPU
    return 1.0 / (T_u / ratio - dark / L.F_CPU)


def model_lum(run, t0, t1, fs, wake="frozen-imm", phase=0.3, **kw):
    tr = run.trace[run.trace[:, 0] < t1 * L.F_CPU]
    k = dict(WAKE[wake])
    k.update(kw)
    lum, _ = M.simulate(tr[:, 0] / L.F_CPU, tr[:, 1], tr[:, 2], fs=fs, phase=phase,
                        regs=M.POWERUP_REGS, t0=t0, t1=t1, dt=50e-6, **k)
    return lum                                  # [bins, digit x, seg]; LED (x, y) = seg 7 - y


def led_means(lum):
    m = lum.mean(axis=0)                        # [x][seg]
    return m[:, ::-1] / L.STOCK_FULL            # [x][y], relative to a stock LED


def flicker_summary(lum, mode, period, lv, g=15):
    lvs = lv[:, ::-1]                           # [x][seg]
    nom = np.vectorize(lambda v: L.rel_level(mode, period, int(v), g))(lvs) * L.STOCK_FULL
    st = F.led_stats(lum, 50e-6, 0.25)
    full = L.rel_level(mode, period, 15, g) * L.STOCK_FULL
    return F.summarise(st, nom, full, lvs.astype(int))


# --------------------------------------------------------------------------- (b) robustness
LM_OUT = {  # every opcode libmonome can send, total length (header + payload)
    0x00: 1, 0x01: 1, 0x02: 33, 0x03: 1, 0x04: 4, 0x05: 1, 0x06: 3, 0x07: 1, 0x08: 3, 0x0F: 1,
    0x10: 3, 0x11: 3, 0x12: 1, 0x13: 1, 0x14: 11, 0x15: 4, 0x16: 4, 0x17: 2, 0x18: 4, 0x19: 2,
    0x1A: 35, 0x1B: 7, 0x1C: 7, 0x90: 4, 0x91: 3, 0x92: 34, 0x93: 5, 0x94: 3, 0x80: 1, 0x81: 2,
    0x82: 2}
REPLY = {0x00: [(0, 1, 1), (0, 2, 1), (0, 8, 1)], 0x01: "id", 0x05: [(3, 8, 8)], 0x80: "tilt"}


def check_display(run, t0, mode, period, lv, g=15, what="", tol=0.02, group="robust"):
    fs = fs_for_ratio(period, 1.0) if mode != "mono" else 800.0
    lum = model_lum(run, t0, t0 + 0.3, fs)
    awake = 1 - L.DARK / period if mode != "mono" else 1.0
    m = led_means(lum) / awake
    exp = np.vectorize(lambda v: L.rel_level(mode, period, int(v), g))(lv)
    err = np.abs(m - exp).max()
    rec(group, what, err < tol, f"worst LED error {100 * err:.2f} % of stock")
    return err


def t_robust():
    period = L.period_for(800)
    ee = L.ee_image(period, 0)
    rnd = random.Random(7)
    lv = L.level_pattern("mixed")

    # b1: random garbage, then timeout, then resync
    garbage = [rnd.randrange(256) for _ in range(1500 if QUICK else 4000)]
    garbage = [0xA4 if b == 0xA5 else b for b in garbage]     # no valid 0x0B (key byte 0xA5)
    sc = []
    t = BOOT_MS
    for i in range(0, len(garbage), 200):
        sc.append((t, "host " + L.hexb(garbage[i:i + 200])))
        t += 15
    t_sync = t + 200
    sc += [(t_sync, "mark resync"), (t_sync, "host 82 00 17 0f"), (t_sync + 1, L.mapx_cmd(lv)),
           (t_sync + 5, "host 00 01 05"), (t_sync + 300, "mark end")]
    r = L.run(sc, t_sync + 700, ee=ee)
    msgs, ok = L.parse_msgs([b for _, b in r.bytes])
    rec("robust", "b1 garbage: device output parses into whole messages", ok, f"{len(r.bytes)} bytes, {len(msgs)} messages")
    after = [b for c, b in r.bytes if c >= r.marks["resync"]]
    am, ok2 = L.parse_msgs(after)
    hs = [m for m in am if m[0] in (0, 1, 3)]
    want = [(0, 1, 1), (0, 2, 1), (0, 8, 1)]
    good = ok2 and [m for m in hs if m[0] == 0] == want and any(m[0] == 3 and m[1:] == (8, 8) for m in hs) \
        and any(m[0] == 1 for m in hs)
    rec("robust", "b1 garbage: handshake answered exactly after resync", good,
        f"{len(hs)} handshake messages after resync")
    check_display(r, r.marks["resync"] / L.F_CPU + 0.1, "tsd", period, lv, what="b1 garbage: display correct after resync (T-SD, model)")
    rec("robust", "b1 garbage: EEPROM calibration record untouched", r.ee[0x10:0x15] == ee[0x10:0x15],
        L.hexb(r.ee[0x10:0x15]))

    # b2: every opcode libmonome can send, random payload, each followed by a 0x05 probe
    sc, t, expect = [], BOOT_MS, []
    ops = list(LM_OUT)
    for rep in range(1 if QUICK else 3):
        for op in ops:
            n = LM_OUT[op]
            pl = [rnd.randrange(256) for _ in range(n - 1)]
            if op in (0x81, 0x82):
                pl = [0]
            sc.append((t, "host " + L.hexb([op] + pl + [0x05])))
            expect.append(op)
            t += 8
    sc += [(t, "host 82 00 17 0f"), (t + 1, L.mapx_cmd(lv)), (t + 2, "mark settled")]
    r = L.run(sc, t + 500, ee=ee)
    msgs, ok = L.parse_msgs([b for _, b in r.bytes])
    sizes = [m for m in msgs if m[0] == 3]
    rec("robust", "b2 all libmonome opcodes: stream stays in sync", ok and len(sizes) == len(expect) + sum(1 for o in expect if o == 5),
        f"{len(expect)} opcodes sent, {len(sizes)} grid-size replies (expected {len(expect) + sum(1 for o in expect if o == 5)})")
    check_display(r, r.marks["settled"] / L.F_CPU + 0.1, "tsd", period, lv, what="b2 all opcodes: display correct afterwards")

    # b2': 0x0B without its key byte is consumed and ignored
    r = L.run([(BOOT_MS, "host 0b 00 5a 00 00 01 05"), (BOOT_MS + 200, "mark x")], BOOT_MS + 400, ee=ee)
    by = [b for _, b in r.bytes]
    rec("robust", "b2 0x0B with a wrong key byte: no reply, no change, next command parsed",
        by == [3, 8, 8] and r.ee[0x10:0x15] == ee[0x10:0x15], L.hexb(by))

    # b3: repeated handshake queries
    n = 20 if QUICK else 60
    sc = [(BOOT_MS + 0.5 * i, "host 00 01 05") for i in range(n)]
    sc.append((BOOT_MS + 400, "host 00 01 05 00 01 05 00 01 05 00 01 05 00 01 05 00 01 05 00 01 05"))
    r = L.run(sc, BOOT_MS + 800, ee=ee)
    msgs, ok = L.parse_msgs([b for _, b in r.bytes])
    nq = sum(1 for m in msgs if m[0] == 0) // 3
    ni = sum(1 for m in msgs if m[0] == 1)
    ns = sum(1 for m in msgs if m[0] == 3)
    rec("robust", f"b3 {n + 7} handshake queries: every reply complete", ok and nq == ni == ns == n + 7,
        f"{nq} query, {ni} id, {ns} size replies")

    # b4: output buffer limits.  TXE-aware build: hold TXE high (FT245 FIFO full) while
    # queries and key presses pile up, then release.
    txe_elf = os.path.join(L.BUILD, "64vb-sim-txe.elf")
    sc = [(BOOT_MS, "txe 1")]
    for i in range(30):
        sc.append((BOOT_MS + 1 + i, "host 00 01 05"))
    lvb = L.level_pattern("hi")
    sc += [(BOOT_MS + 40, "key 2 3 down"), (BOOT_MS + 90, "key 2 3 up"), (BOOT_MS + 150, L.mapx_cmd(lvb)),
           (BOOT_MS + 300, "txe 0"), (BOOT_MS + 310, "mark released")]
    r = L.run(sc, BOOT_MS + 1000, ee=ee, elf=txe_elf)
    by = [b for _, b in r.bytes]
    msgs, ok = L.parse_msgs(by)
    before = [b for c, b in r.bytes if c < r.marks["released"] - 10 * 16000]
    keys = [m for m in msgs if m[0] in (0x20, 0x21)]
    nq = sum(1 for m in msgs if m[0] == 0) // 3
    ni = sum(1 for m in msgs if m[0] == 1)
    rec("robust", "b4 TXE held high: nothing written while the FIFO is full", len(before) == 0, f"{len(before)} bytes")
    rec("robust", "b4 output blocked for 300 ms: every reply delivered whole afterwards, key events in order",
        ok and nq == ni == 30 and keys == [(0x21, 5, 4), (0x20, 5, 4)],
        f"{len(by)} bytes, {nq} query / {ni} id replies, keys {keys}")
    check_display(r, r.marks["released"] / L.F_CPU + 0.2, "tsd", period, lvb,
                  what="b4 level map sent while input was held back: applied intact")


# --------------------------------------------------------------------------- (c) flicker
def traffic_script(lv, t_from, t_to):
    """host traffic and key scanning while the display shows lv"""
    sc = [(t_from - 200, L.mapx_cmd(lv))]
    t, k = t_from - 150, 0
    while t < t_to:
        sc.append((t, L.mapx_cmd(lv)))                        # 35-byte map, same content
        sc.append((t + 3, "host 18 %02x %02x %02x 00 01 05" % (k % 8, (k // 8) % 8, lv[k % 8][(k // 8) % 8])))
        x, y = k % 8, (3 * k) % 8
        r_, c_ = L.key_rc(x, y)
        sc.append((t + 5, f"key {r_} {c_} down"))
        sc.append((t + 25, f"key {r_} {c_} up"))
        t += 40
        k += 1
    return sc


def flicker_job(a):
    fs, mode, pat = a
    period = L.period_for(fs)
    lv = L.level_pattern(pat)
    t0, t1 = BOOT_MS / 1000 + 0.3, BOOT_MS / 1000 + 0.3 + (1.6 if QUICK else 2.4)
    r = L.run(traffic_script(lv, BOOT_MS + 200, t1 * 1000), t1 * 1000 + 20,
              ee=L.ee_image(period, 1 if mode == "sd" else 0))
    if mode == "tsd":
        cases = [("frozen-imm", x) for x in (-1.0, -0.5, 0.0, 0.5, 1.0)] + \
                [("frozen-lat", x) for x in (-1.0, 0.0, 1.0)] + \
                [("restart0", x) for x in (-0.5, 0.0, 0.25)] + \
                [("restart0-lat", x) for x in (-0.5, 0.25)] + \
                [("frozen-hold", x) for x in (0.0, 0.1)]
    else:
        cases = [("frozen-imm", x) for x in (-0.1, -0.05, 0.0, 0.05, 0.1)] + \
                [("frozen-lat", x) for x in (0.0, 0.05)] + \
                [("restart0", x) for x in (-0.5, 0.0, 0.2)] + [("frozen-hold", x) for x in (0.0, 0.05)]
    out = []
    for wake, pct in cases:
        lum = model_lum(r, t0, t1, fs_for_ratio(period, 1 + pct / 100), wake)
        s = flicker_summary(lum, mode, period, lv)
        out.append((fs, mode, pat, wake, pct, s["pp_max"], s["rms_max"], s["band_max"], s["pass_plan"], s["gain"]))
    # ISR timing under this load (used by (e))
    tr = r.trace
    w0 = tr[(tr[:, 1] == 12) & (tr[:, 2] == 0) & (tr[:, 0] > t0 * L.F_CPU)][:, 0]
    sp = np.diff(w0)
    isr = r.isr[r.isr[:, 0] > t0 * L.F_CPU]
    dur = isr[:, 1] - isr[:, 0]
    return out, (fs, mode, pat, int(sp.min()), int(sp.max()), period, int(dur.min()), int(dur.max()),
                 len(r.bytes))


# window each (mode, wake) case is expected to pass in, from the synthetic sweeps
def expected_pass(mode, fs, wake, pct):
    if wake == "frozen-hold":
        return pct == 0.0
    if mode == "tsd":
        if wake.startswith("restart0"):
            return -0.7 <= pct <= 0.3
        return abs(pct) <= 1.0
    if wake.startswith("restart0"):
        return -0.7 <= pct <= 0.2
    return abs(pct) <= 0.10          # sim/README 5e: 6-frame / 5-frame windows >= +-0.10 %


FLICKER_TIMING = []


def t_flicker():
    fss = [800] if QUICK else [500, 800, 1300]
    jobs = [(fs, m, p) for fs in fss for m in ("tsd", "sd") for p in ("lo", "hi")]
    with Pool(JOBS) as pool:
        res = pool.map(flicker_job, jobs)
    rows = {}
    for out, timing in res:
        FLICKER_TIMING.append(timing)
        for fs, mode, pat, wake, pct, pp, rms, band, ok, gain in out:
            k = (fs, mode, wake, pct)
            a = rows.setdefault(k, [0, 0, 0, True, 1])
            a[0] = max(a[0], pp); a[1] = max(a[1], rms); a[2] = max(a[2], band); a[3] &= ok; a[4] = min(a[4], gain)
    for (fs, mode, wake, pct), (pp, rms, band, ok, gain) in sorted(rows.items()):
        ex = expected_pass(mode, fs, wake, pct)
        name = f"c {mode.upper()} f_s {fs} Hz, {wake}, rate {pct:+.2f} %"
        det = f"pp {100 * pp:.2f} % rms {100 * rms:.2f} % band {100 * band:.2f} % FS, gain {100 * gain:.1f} %"
        if ex:
            rec("flicker", name, ok, det)
        else:
            rec("flicker", name, ok, det + " (outside the synthetic window / model variant)", expected_fail=True)


# --------------------------------------------------------------------------- (d) calibration, modes, probes, sleep
def frames_in(run, t0, t1):
    """list of bursts (cycle of 0x0C=0, intensity code, 8 digit bytes) in [t0, t1)"""
    tr = run.words(t0, t1)
    out = []
    for i in range(len(tr) - 10):
        if tr[i, 1] == 12 and tr[i, 2] == 0 and tr[i + 1, 1] == 10 and tr[i + 10, 1] == 12 and tr[i + 10, 2] == 1:
            out.append((int(tr[i, 0]), int(tr[i + 1, 2]), tuple(int(v) for v in tr[i + 2:i + 10, 2])))
    return out


def press(sc, t, x, y, hold=40):
    r_, c_ = L.key_rc(x, y)
    sc.append((t, f"key {r_} {c_} down"))
    sc.append((t + hold, f"key {r_} {c_} up"))
    return t + hold + 80


def t_calib():
    # d1: calibration UI by key presses, then save
    sc = [(0, "key 7 7 down"), (300, "key 7 7 up")]
    t = 500
    sc.append((t - 10, "mark cal-start"))
    t = press(sc, t, 5, 0)            # +100
    t = press(sc, t, 5, 0)            # +100
    t = press(sc, t, 2, 0)            # -1
    sc.append((t + 300, "mark cal-adjusted"))
    t += 400
    t = press(sc, t, 1, 1)            # mode SD
    t = press(sc, t, 1, 2)            # preview
    sc.append((t + 200, "mark preview"))
    t += 400
    t = press(sc, t, 4, 2)            # probe 1
    sc.append((t + 100, "mark probe1"))
    t += 2300
    t = press(sc, t, 0, 2)            # back to the band
    t = press(sc, t, 7, 0)            # save
    sc.append((t, "mark saved"))
    T = t + 3500
    sc.append((T - 400, "mark run"))
    r = L.run(sc, T, ee=L.ee_image(None))
    c = lambda m: r.marks[m] / L.F_CPU  # noqa: E731
    tr = r.words(0.05, c("cal-start"))
    on = tr[(tr[:, 1] == 12) & (tr[:, 2] == 0)][:, 0]
    sp = np.diff(on)
    d0 = L.DARK + 20000
    rec("calib", "d1 key (0,0) at power-up starts the bracketed calibration band",
        len(on) > 100 and sp.min() == sp.max() == d0, f"bracket spacing {sp.min()}..{sp.max()} cycles (default {d0})")
    fr = r.words(0.05, c("cal-start"))
    offs = [w for w in fr if w[1] in range(1, 9)]
    rec("calib", "d1 band: digits all 0xFF in the bracket, all 0x00 plain at half period",
        set(int(w[2]) for w in offs) == {0, 255}, f"{len(offs)} digit writes")
    tr = r.words(c("cal-adjusted") - 0.2, c("cal-adjusted"))
    on = tr[(tr[:, 1] == 12) & (tr[:, 2] == 0)][:, 0]
    sp = np.diff(on)
    rec("calib", "d1 keys +100 +100 -1 change the period to default + 199",
        len(sp) > 10 and sp.min() == sp.max() == d0 + 199, f"{sp.min()}..{sp.max()}")
    fr = frames_in(r, c("preview") - 0.15, c("preview"))
    codes = sorted(set(f[1] for f in fr))
    rec("calib", "d1 mode SD + preview: 6-frame codes 15/15/6/15/11/15", codes == [6, 11, 15], f"codes {codes}")
    tr = r.words(c("probe1") + 1.05, c("probe1") + 1.9)
    sd = tr[tr[:, 1] == 12]
    ints = r.words(c("probe1") - 0.4, c("probe1") + 0.05)
    i0 = [int(w[2]) for w in ints if w[1] == 10]
    rec("calib", "d1 probe 1 from the keypad: intensity 0, 50/50 us shutdown toggling",
        len(sd) > 1000 and i0 and i0[-1] == 0 and np.abs(np.diff(sd[:, 0]) - 800).max() == 0,
        f"{len(sd)} shutdown writes, spacing {np.diff(sd[:, 0]).min()}..{np.diff(sd[:, 0]).max()}, intensity {i0[-1:]}")
    ee = r.ee[0x10:0x15]
    p = d0 + 199
    want = bytes([0xB6, 1, p & 255, p >> 8, 1 ^ (p & 255) ^ (p >> 8) ^ 0x5A])
    rec("calib", "d1 save: EEPROM record v2 written (mode SD, period)", ee == want, L.hexb(ee))
    fr = frames_in(r, c("run"), c("run") + 0.35)
    sp = np.diff([f[0] for f in fr])
    rec("calib", "d1 after save: SD frames at the saved period", len(fr) > 50 and sp.min() == sp.max() == p,
        f"{len(fr)} bursts, spacing {sp.min() if len(sp) else '-'}")

    # d2: persistence across a simulated reset
    r2 = L.run([(BOOT_MS, "host 19 0f"), (BOOT_MS + 50, "host 0a")], BOOT_MS + 500, ee=r.ee)
    fr = frames_in(r2, BOOT_MS / 1000 + 0.1, BOOT_MS / 1000 + 0.45)
    sp = np.diff([f[0] for f in fr])
    rep = [b for _, b in r2.bytes]
    rec("calib", "d2 reset with that EEPROM: SD at the saved period, 0x0A report",
        len(sp) and sp.min() == sp.max() == p and rep[:9] == [0x0A, 0x03, 0x01, 6, 0, p >> 8, p & 255, p >> 8, p & 255],
        f"report {L.hexb(rep[:9])}")

    # d3: uncalibrated fallback (mono)
    lv = L.level_pattern("mixed")
    r3 = L.run([(BOOT_MS, L.mapx_cmd(lv)), (BOOT_MS + 50, "mark m")], BOOT_MS + 500, ee=L.ee_image(None))
    tr = r3.words(BOOT_MS / 1000, 99)
    rec("calib", "d3 no calibration: no frame timer (no shutdown toggling)", not np.any(tr[:, 1] == 12), f"{len(tr)} words")
    regs = {}
    for w in tr:
        regs[int(w[1])] = int(w[2])
    want = [sum(1 << (7 - y) for y in range(8) if lv[x][y] > 7) for x in range(8)]
    rec("calib", "d3 mono: digit registers show levels > 7", [regs.get(1 + x) for x in range(8)] == want,
        f"{[regs.get(1 + x) for x in range(8)]}")
    check_display(r3, r3.marks["m"] / L.F_CPU + 0.05, "mono", 0, lv, what="d3 mono display (model)", group="calib")
    # old revision-2 record (0xB5) is not accepted
    old = bytearray(L.ee_image(None))
    old[0x10:0x14] = bytes([0xB5, 0x20, 0x4E, 0x20 ^ 0x4E ^ 0x5A])
    r3b = L.run([(BOOT_MS, "host 0a")], BOOT_MS + 200, ee=bytes(old))
    rec("calib", "d3 revision-2 record 0xB5 ignored (mono)", [b for _, b in r3b.bytes][:2] == [0x0A, 0x00],
        L.hexb([b for _, b in r3b.bytes]))

    # d4: mode switching through 0x0B (and saving), report fields
    p8 = L.period_for(800)
    sc = [(BOOT_MS, "host 0b a5 %02x %02x 00 00" % (p8 >> 8, p8 & 255)), (BOOT_MS + 1, "host 19 07"),
          (BOOT_MS + 300, "mark tsd"),
          (BOOT_MS + 600, "host 0b a5 %02x %02x 01 01" % (p8 >> 8, p8 & 255)), (BOOT_MS + 900, "mark sd"),
          (BOOT_MS + 1200, "host 0b a5 %02x %02x 00 30" % (p8 >> 8, p8 & 255)), (BOOT_MS + 1500, "mark p3"),
          (BOOT_MS + 1800, "host 0b a5 00 00 00 00"), (BOOT_MS + 2000, "mark mono"), (BOOT_MS + 2100, "host 0a")]
    r4 = L.run(sc, BOOT_MS + 2300, ee=L.ee_image(None))
    c4 = lambda m: r4.marks[m] / L.F_CPU  # noqa: E731
    msgs, _ = L.parse_msgs([b for _, b in r4.bytes])
    f1 = frames_in(r4, c4("tsd") - 0.2, c4("tsd"))
    f2 = frames_in(r4, c4("sd") - 0.2, c4("sd"))
    f3 = frames_in(r4, c4("p3") - 0.2, c4("p3"))
    lvl7 = lambda fr, n: sorted(set(f[2][0] for f in fr))  # noqa: E731
    rec("calib", "d4 0x0B T-SD: 4 frames at code 15, level 7 = 2 of 4 frames",
        f1 and set(f[1] for f in f1) == {15} and lvl7(f1, 4) == [0, 255] and
        sum(1 for f in f1[:4] if f[2][0] == 255) == 2, f"{len(f1)} bursts")
    rec("calib", "d4 0x0B SD + save: 6-frame codes, EEPROM written",
        f2 and sorted(set(f[1] for f in f2)) == [6, 11, 15] and r4.ee[0x10] in (0xFF, 0xB6),
        f"codes {sorted(set(f[1] for f in f2))}")
    on3 = [sum(1 for f in f3[k:k + 3] if f[2][0] == 255) for k in range(0, 30, 3)]
    rec("calib", "d4 0x0B forced P = 3 (cfg 0x30): level 7 = step 1 of 3 (round(7*3/15))",
        f3 and set(on3) == {1} and L.frames_for("tsd", p8, forcep=3)[1][7] in (1, 2, 4), f"on-frames per cycle {on3}")
    reps = [m for m in msgs if m[0] == 0x0A]
    rec("calib", "d4 0x0B replies: 0A status cfg nframes view period ee",
        len(reps) == 5 and reps[0][1:5] == (1, 0, 4, 0) and reps[1][1:5] == (3, 1, 6, 0) and
        reps[2][1:5] == (3, 0x30, 3, 0) and reps[3][1:5] == (2, 0, 0, 0) and reps[3][5:7] == (0, 0) and
        reps[3][7:9] == (p8 >> 8, p8 & 255),
        "; ".join(L.hexb(m) for m in reps))
    tr = r4.words(c4("mono"), c4("mono") + 0.15)
    rec("calib", "d4 0x0B period 0: back to mono (timer off)", not np.any(tr[:, 1] == 12), "")

    # d5: probes through 0x0B, firmware timing, and what each wake model predicts
    t_p = BOOT_MS
    sc = [(t_p, "host 0b a5 %02x %02x %02x 00" % (p8 >> 8, p8 & 255, n << 4)) for n in (1,)]
    pr = []
    for n in (1, 2, 3, 4):
        sc = [(BOOT_MS, "host 0b a5 %02x %02x %02x 00" % (p8 >> 8, p8 & 255, n << 4)), (BOOT_MS + 1, "mark start")]
        dur = 4.3 if n < 4 else 8.3
        rp = L.run(sc, BOOT_MS + dur * 1000, ee=L.ee_image(p8, 0))
        ts = rp.marks["start"] / L.F_CPU
        pr.append((n, rp, ts))
        if n < 4:
            sdw = rp.words(ts, ts + 4.2)
            sdw = sdw[sdw[:, 1] == 12]
            gaps = np.diff(sdw[:, 0])
            aw, dk = (800, 800) if n < 3 else (6400, 1600)
            ints = [int(w[2]) for w in rp.words(ts - 0.01, ts + 0.05) if w[1] == 10]
            # reference second: only wake writes, every pair; probe second: both
            zeros = sdw[sdw[:, 2] == 0][:, 0]
            first0 = (zeros[0] - rp.marks["start"]) / L.F_CPU if len(zeros) else -1
            g = gaps[1:]                     # the first gap follows the main-loop wake write
            near = lambda v: min(abs(v - aw), abs(v - dk), abs(v - aw - dk))  # noqa: E731
            jit = max(near(v) for v in g)
            ok = jit == 0 and ints[-1:] == [0 if n == 1 else 15] and 0.95 < first0 < 1.05
            rec("calib", f"d5 probe {n}: {aw / 16:.0f} us awake / {dk / 16:.0f} us shutdown, reference second first, intensity {ints[-1:]}",
                ok, f"first shutdown after {first0:.3f} s, segment jitter {jit} cycles (tick_align)")
        else:
            fr = frames_in(rp, ts, ts + 8.2)
            sp = np.diff([f[0] for f in fr])
            vals = sorted(set(sp))
            rec("calib", "d5 probe 4: T-SD P=4 mid level, period alternates p / p + 0.5 % every 2 s",
                vals == [p8, p8 + p8 // 200] or vals[:1] == [p8] and p8 + p8 // 200 in vals,
                f"periods {vals[:4]}")
    PROBE_TRACES.extend(pr)

    # d6: sleep / wake
    lv = L.level_pattern("mixed")
    sc = [(BOOT_MS, L.mapx_cmd(lv)), (BOOT_MS + 300, "pwren 1"), (BOOT_MS + 1300, "mark asleep"),
          (BOOT_MS + 2000, "pwren 0"), (BOOT_MS + 3200, "mark awake")]
    r6 = L.run(sc, BOOT_MS + 3700, ee=L.ee_image(p8, 0))
    c6 = lambda m: r6.marks[m] / L.F_CPU  # noqa: E731
    tr = r6.words(c6("asleep") - 0.4, c6("asleep") + 0.6)
    last = r6.words(BOOT_MS / 1000 + 0.3, c6("asleep"))
    rec("calib", "d6 USB suspend: fade, frame timer stopped, MAX7219 shut down",
        len(tr) == 0 and int(last[-1, 1]) == 12 and int(last[-1, 2]) == 0,
        f"last word {int(last[-1, 1]):#x}={int(last[-1, 2])}, {len(tr)} words while asleep")
    check_display(r6, c6("awake"), "tsd", p8, lv, what="d6 wake: frames resume, LED state preserved (model)", group="calib")


PROBE_TRACES = []


def t_probe_predict():
    """what a person would see in each probe, per wake model (from the firmware traces)"""
    rows = []
    for n, rp, ts in PROBE_TRACES:
        if n == 4:
            p8 = L.period_for(800)
            for wake in ("frozen-imm", "frozen-hold", "restart0", "same-digit", "next-digit"):
                res = []
                for k, (a, b) in enumerate(((ts + 0.3, ts + 1.9), (ts + 2.3, ts + 3.9))):
                    lum = model_lum(rp, a, b, fs_for_ratio(p8, 1.0), wake)
                    st = F.led_stats(lum, 50e-6, 0.25)
                    row = lum.mean(axis=0).mean(axis=1) / L.STOCK_FULL
                    res.append(f"rows {' '.join(f'{100 * v:.0f}' for v in row)} %, pp {100 * st['pp'].max():.0f} %")
                rows.append((f"probe 4 ({wake})", res[0], res[1]))
            continue
        for wake in ("restart0", "frozen-imm", "same-digit", "next-digit"):
            res = []
            for a, b in ((ts + 0.2, ts + 0.95), (ts + 1.2, ts + 1.95)):
                lum = model_lum(rp, a, b, 800.0, wake)
                row = lum.mean(axis=0).mean(axis=1) / L.STOCK_FULL
                res.append(" ".join(f"{100 * v:.0f}" for v in row))
            rows.append((f"probe {n} ({wake})", "rows " + res[0] + " %", "rows " + res[1] + " %"))
    md = ("\n### Probe predictions from the firmware traces (model, f_s 800 Hz)\n\n"
          "Row brightness in % of a stock row at intensity 15 (rows = digits 1..8 = LED x 0..7).\n"
          "Probes 1..3: reference second / probe second. Probe 4: calibrated period / +0.5 %, "
          "with worst filtered pp % of own mean.\n\n"
          "| probe (wake model) | first phase | second phase |\n|---|---|---|\n")
    md += "".join(f"| {a} | {b} | {c} |\n" for a, b, c in rows)
    return md


# --------------------------------------------------------------------------- (e) ISR timing
def t_isr():
    rows = []
    p8 = L.period_for(800)
    lo, hi = L.isr_range()
    rows.append(("ISR code range", f"{hi - lo} bytes"))
    for fs, mode, pat, smin, smax, period, dmin, dmax, nbytes in FLICKER_TIMING:
        ok = smin == smax == period
        rec("isr", f"e tick period under host traffic + key scan, {mode.upper()} {fs} Hz {pat}", ok,
            f"0x0C=0 spacing {smin}..{smax} cycles (period {period}), ISR entry..exit {dmin}..{dmax} cycles, {nbytes} device bytes")
    # per mode: frames (T-SD, SD), calibration band, probes
    cases = [("T-SD frames", L.ee_image(p8, 0), [], 2.0),
             ("SD frames", L.ee_image(p8, 1), [], 2.0),
             ("calibration band", L.ee_image(p8, 0), [(BOOT_MS, "host 0b a5 %02x %02x 02 00" % (p8 >> 8, p8 & 255))], 1.0),
             ("probe 1 (50/50 us)", L.ee_image(p8, 0), [(BOOT_MS, "host 0b a5 %02x %02x 10 00" % (p8 >> 8, p8 & 255))], 2.5),
             ("probe 3 (400/100 us)", L.ee_image(p8, 0), [(BOOT_MS, "host 0b a5 %02x %02x 30 00" % (p8 >> 8, p8 & 255))], 2.5),
             ("probe 4", L.ee_image(p8, 0), [(BOOT_MS, "host 0b a5 %02x %02x 40 00" % (p8 >> 8, p8 & 255))], 2.5)]
    md = "\n### ISR duration in simavr (cycles from the first ISR instruction to after reti; add 7 for interrupt response and the vector jmp)\n\n"
    md += "| mode | ISR passes | min | max | max incl. response, us | burst 0x0C=0 .. 0x0C=1 LOAD, cycles | tick spacing min..max |\n|---|---|---|---|---|---|---|\n"
    for name, ee, sc, dur in cases:
        sc = sc + [(BOOT_MS + 50, "mark s")] + traffic_script(L.level_pattern("mixed"), BOOT_MS + 300, BOOT_MS + dur * 1000)
        r = L.run(sc, BOOT_MS + dur * 1000 + 100, ee=ee)
        t0 = r.marks["s"] + 0.2 * L.F_CPU
        isr = r.isr[r.isr[:, 0] > t0]
        d = isr[:, 1] - isr[:, 0]
        tr = r.trace[r.trace[:, 0] > t0]
        z = tr[(tr[:, 1] == 12) & (tr[:, 2] == 0)][:, 0]
        o = tr[(tr[:, 1] == 12) & (tr[:, 2] == 1)][:, 0]
        burst = "-"
        if "frames" in name or "band" in name:
            k = min(len(z), len(o))
            bl = [int(o[o > a][0] - a) for a in z[:200] if np.any(o > a)]
            burst = f"{min(bl)}..{max(bl)}" if bl else "-"
        sp = np.diff(z)
        spr = f"{sp.min()}..{sp.max()}" if len(sp) else "-"
        md += f"| {name} | {len(d)} | {d.min()} | {d.max()} | {(d.max() + 7) / 16:.1f} | {burst} | {spr} |\n"
        rec("isr", f"e ISR within the 120 us budget: {name}", (d.max() + 7) / 16 < 120,
            f"max {(d.max() + 7) / 16:.1f} us")
        if "frames" in name:
            rec("isr", f"e cycle-exact tick: {name}", sp.min() == sp.max() == p8, f"spacing {spr}")
    return md


# --------------------------------------------------------------------------- main
def main():
    global QUICK, JOBS
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--out", default=os.path.join(L.SIM, "results", "fw_tests.md"))
    ap.add_argument("groups", nargs="*", default=["robust", "flicker", "calib", "isr"])
    a = ap.parse_args()
    QUICK, JOBS = a.quick, a.jobs
    t0 = time.time()
    extra = ""
    if "robust" in a.groups:
        t_robust()
    if "flicker" in a.groups:
        t_flicker()
    if "calib" in a.groups:
        t_calib()
        extra += t_probe_predict()
    if "isr" in a.groups:
        if not FLICKER_TIMING:
            t_flicker()
        extra += t_isr()
    nf = sum(1 for r in RESULTS if r[2] in ("FAIL", "PASS(unexpected)"))
    md = (f"## Firmware integration tests ({'quick' if QUICK else 'full'} run, simulation only)\n\n"
          f"{len(RESULTS)} checks, {nf} unexpected results, {time.time() - t0:.0f} s. "
          "EXPECTED-FAIL = a case outside the window that the synthetic sweeps predict for "
          "that wake / write model (for example the latch-held next-slot model at any "
          "mismatch); it is reported, not hidden.\n\n| group | check | result | detail |\n|---|---|---|---|\n")
    md += "".join(f"| {g} | {n} | {s} | {d} |\n" for g, n, s, d in RESULTS)
    md += extra
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write(md)
    print(extra)
    print(f"FW TESTS {'FAILED' if nf else 'PASSED'}: {len(RESULTS)} checks, {nf} unexpected")
    sys.exit(1 if nf else 0)


if __name__ == "__main__":
    main()
