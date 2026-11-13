"""Helpers for the firmware integration tests: run 64vb-sim.elf in the gs64sim harness,
parse what comes back, and mirror the firmware's level mapping.  Simulation only."""
import os
import subprocess
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
BUILD = os.path.join(SIM, "build")
FW = os.path.join(SIM, "..", "gs64rec10-vb", "64vb-sim.elf")
GS64SIM = os.path.join(BUILD, "gs64sim")
F_CPU = 16e6
DARK = 687                      # measured: 0x0C=0 .. 0x0C=1 LOAD edges, constant (test_fw (e))
STOCK_FULL = 31.0 / 32.0 / 8.0

SD6_CODE = [15, 15, 6, 15, 11, 15]
SD6_MASK = [0x00, 0x04, 0x10, 0x01, 0x05, 0x11, 0x09, 0x0d, 0x19, 0x1d, 0x0f, 0x1b, 0x1f, 0x2f, 0x3b, 0x3f]
SD5_CODE = [15, 15, 7, 15, 3]
SD5_MASK = [0x00, 0x10, 0x04, 0x14, 0x01, 0x11, 0x05, 0x15, 0x09, 0x19, 0x0d, 0x1d, 0x0b, 0x1b, 0x0f, 0x1f]

# libmonome incoming payload lengths (device -> host), plus our 0x0A reply (9 bytes total)
IN_LEN = {0x00: 3, 0x01: 33, 0x02: 4, 0x03: 3, 0x04: 3, 0x0F: 9, 0x20: 3, 0x21: 3,
          0x80: 2, 0x81: 8, 0x0A: 9}


def ee_image(period=None, cfg=0, size=4096):
    ee = bytearray([0xFF] * size)
    if period:
        lo, hi = period & 0xFF, period >> 8
        ee[0x10:0x15] = bytes([0xB6, cfg, lo, hi, cfg ^ lo ^ hi ^ 0x5A])
    return bytes(ee)


def period_for(fs):
    return int(round(F_CPU / fs)) + DARK


def isr_range(elf=FW, name="__vector_17"):
    out = subprocess.run(["avr-nm", "-S", elf], capture_output=True, text=True).stdout
    for line in out.splitlines():
        p = line.split()
        if len(p) == 4 and p[3] == name:
            lo = int(p[0], 16)
            return lo, lo + int(p[1], 16)
    raise RuntimeError(name)


def hexb(bs):
    return " ".join(f"{b:02x}" for b in bs)


class Run:
    """Result of one harness run."""

    def __init__(self, d):
        self.__dict__.update(d)

    def words(self, t0=0.0, t1=1e9):
        tr = self.trace
        sel = (tr[:, 0] >= t0 * F_CPU) & (tr[:, 0] < t1 * F_CPU)
        return tr[sel]


def run(script, T_ms, ee=None, elf=FW, isr=True, keep=None):
    """script: list of (t_ms, command string) or lines.  Returns Run with
    .bytes [(cycle, byte)], .marks {text: cycle}, .trace ndarray [cycle, addr, data,
    start, nbits], .isr ndarray [entry, exit], .ee bytes, .stderr"""
    d = keep or tempfile.mkdtemp(prefix="fwt", dir=os.environ.get("FWT_TMP"))
    sp = os.path.join(d, "s.script")
    with open(sp, "w") as f:
        for item in script:
            if isinstance(item, str):
                f.write(item.rstrip() + "\n")
            else:
                f.write(f"@{item[0]:.3f} {item[1]}\n")
    cmd = [GS64SIM, "-T", str(T_ms), "-s", sp, "-t", os.path.join(d, "t.txt"),
           "-o", os.path.join(d, "o.txt"), "-E", os.path.join(d, "eeo.bin")]
    if ee is not None:
        with open(os.path.join(d, "ee.bin"), "wb") as f:
            f.write(ee)
        cmd += ["-e", os.path.join(d, "ee.bin")]
    if isr:
        lo, hi = isr_range(elf)
        cmd += ["-i", f"{lo:x}:{hi:x}:{os.path.join(d, 'isr.txt')}"]
    cmd.append(elf)
    r = subprocess.run(cmd, capture_output=True, text=True)
    by, marks = [], {}
    for line in open(os.path.join(d, "o.txt")):
        p = line.split()
        if len(p) > 1 and p[1] == "#":
            marks[" ".join(p[2:])] = int(p[0])
        elif len(p) == 2:
            by.append((int(p[0]), int(p[1], 16)))
    tr = np.loadtxt(os.path.join(d, "t.txt"), dtype=np.int64, ndmin=2)
    isrs = np.zeros((0, 2), np.int64)
    if isr and os.path.getsize(os.path.join(d, "isr.txt")):
        isrs = np.loadtxt(os.path.join(d, "isr.txt"), dtype=np.int64, ndmin=2)
    ee_out = open(os.path.join(d, "eeo.bin"), "rb").read()
    return Run(dict(bytes=by, marks=marks, trace=tr, isr=isrs, ee=ee_out, stderr=r.stderr,
                    rc=r.returncode, dir=d))


def parse_msgs(bs):
    """split device bytes into messages by header; returns (msgs, ok) where ok is False if
    an unknown header or a truncated message is found"""
    msgs, i, ok = [], 0, True
    while i < len(bs):
        n = IN_LEN.get(bs[i])
        if n is None or i + n > len(bs):
            return msgs, False
        msgs.append(tuple(bs[i:i + n]))
        i += n
    return msgs, ok


# --------------------------------------------------------------------------- level mirror
def spread(s, P):
    acc, m = 0, 0
    for k in range(P):
        acc += s
        if acc >= P:
            acc -= P
            m |= 1 << k
    return m


def tsd_P(period, forcep=0):
    return forcep or (4 if period <= 21333 + DARK else 3)


def frames_for(mode, period, g=15, forcep=0):
    """(codes per frame, mask per host level) exactly as 64vb.c computes them"""
    if mode == "sd":
        codes0, masks = (SD6_CODE, SD6_MASK) if period <= 26700 else (SD5_CODE, SD5_MASK)
        while True:
            c = [((2 * x + 1) * (g + 1)) >> 5 for x in codes0]
            sums = [sum(2 * c[f] + 1 for f in range(len(c)) if masks[L] >> f & 1) for L in range(16)]
            if g >= 15 or all(sums[L] > sums[L - 1] for L in range(2, 16)):
                return c, masks
            g += 1
    P = tsd_P(period, forcep)
    masks = []
    for L in range(16):
        s = 0 if L == 0 else max(1, (L * P * 2 + 15) // 30)
        masks.append(spread(s, P))
    return [g] * P, masks


def rel_level(mode, period, L, g=15):
    """expected brightness of host level L relative to a stock LED at intensity 15,
    shutdown dark time excluded"""
    if mode == "mono":
        return (2 * g + 1) / 31.0 if L > 7 else 0.0
    c, m = frames_for(mode, period, g)
    return sum((2 * c[f] + 1) / 31.0 for f in range(len(c)) if m[L] >> f & 1) / len(c)


def level_pattern(name):
    """host levels [x][y] covering all 16 levels in every column (= MAX7219 digit)"""
    x = np.arange(8)[:, None]
    y = np.arange(8)[None, :]
    if name == "lo":
        return (x + y) % 8
    if name == "hi":
        return 8 + (x + y) % 8
    if name == "mixed":
        return (y + 3 * x) % 16
    raise ValueError(name)


def mapx_cmd(lv):
    """0x1A level map command for host levels lv[x][y] (libmonome pack_nybbles order)"""
    out = [0x1A, 0, 0]
    for y in range(8):
        for i in range(4):
            out.append((int(lv[2 * i][y]) << 4) | int(lv[2 * i + 1][y]))
    return "host " + hexb(out)


def key_rc(x, y):
    """harness (row, col) for device key (x, y)"""
    return 7 - x, 7 - y
