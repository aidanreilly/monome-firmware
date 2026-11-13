#!/usr/bin/env python3
"""End-to-end harness test: run the self-test firmware in gs64sim with a script, check the
device bytes, the decoded MAX7219 writes, EEPROM preload/readback, and feed the trace into
the MAX7219 model.  Usage: test_harness.py BUILD_DIR"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import maxmodel as M  # noqa: E402

B = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "build")
FAILS = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


with open(os.path.join(B, "ee_in.bin"), "wb") as f:
    f.write(bytes([0x5A, 0x11, 0x22, 0x33]))
cmd = [os.path.join(B, "gs64sim"), "-T", "60", "-s", os.path.join(HERE, "harness_test.script"),
       "-t", os.path.join(B, "trace.txt"), "-o", os.path.join(B, "out.txt"),
       "-e", os.path.join(B, "ee_in.bin"), "-E", os.path.join(B, "ee_out.bin"),
       os.path.join(B, "testfw.elf")]
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stderr.strip())
check(r.returncode == 0, "gs64sim exit status 0")
check("0 warnings" in r.stderr, "no protocol warnings")

out = []
marks = {}
for line in open(os.path.join(B, "out.txt")):
    p = line.split()
    if p[1] == "#":
        marks[" ".join(p[2:])] = int(p[0])
    else:
        out.append((int(p[0]), int(p[1], 16)))
bytes_ = [b for _, b in out]
check(bytes_[:4] == [1, 2, 3, 0xFE], "host bytes 01 02 03 fe echoed")
check(out[0][0] > 5e-3 * 16e6 and out[0][0] < 6e-3 * 16e6, "echo arrives within 1 ms of the script time")
check(bytes_[4:7] == [0x21, 5, 2], "key row 2 col 5 down -> 21 05 02")
check(bytes_[7:10] == [0x20, 5, 2], "key up -> 20 05 02")
check(bytes_[10:15] == [0x5A, 0x11, 0x22, 0x33, 0x00], "EEPROM preload visible to firmware; boot counter 0xff+1")
check(any(k.startswith("eeprom 0: 5a 11 22 33 00") for k in marks), "eedump script command")
ee = open(os.path.join(B, "ee_out.bin"), "rb").read()
check(len(ee) == 4096 and ee[:5] == bytes([0x5A, 0x11, 0x22, 0x33, 0x00]), "EEPROM readback file (4 KB)")

rows = [list(map(int, l.split())) for l in open(os.path.join(B, "trace.txt")) if not l.startswith("#")]
check(all(r[4] == 16 for r in rows), "every MAX7219 word has 16 clock edges")
init = [(r[1], r[2]) for r in rows[:13]]
check(init[:4] == [(11, 7), (10, 15), (9, 0), (1, 0x5A)] and init[-2:] == [(12, 1), (15, 0)],
      "init sequence decoded in order (scan limit, intensity, decode, digit 1 = EEPROM byte 0)")
isr = [r for r in rows[13:] if r[1] == 10]
per = np.diff([r[0] for r in isr])
check(len(isr) > 40 and abs(np.median(per) - 20000) <= 2, f"ISR intensity writes every {np.median(per):.0f} cycles (20000 = 1.25 ms)")
check(per.max() - per.min() < 400, f"ISR write period spread {per.max() - per.min()} cycles (key scan / FIFO code running)")
wl = [(r[0] - r[3]) / 16 for r in rows]
check(max(wl) < 20, f"word duration {min(wl):.1f}..{max(wl):.1f} us")

# trace -> model
t, a, d = M.read_trace(os.path.join(B, "trace.txt"))
lum, tt = M.simulate(t, a, d, fs=800, regs=M.POWERUP_REGS, t0=0, t1=0.06, dt=50e-6)
seg = lum[tt > 0.01].mean(axis=0)
check(seg[0].sum() > 0 and (seg[0] > 0).sum() == 4, "model: digit 0 shows 0x5A (4 segments)")
check(all((seg[k] > 0).sum() == 1 and seg[k][k] > 0 for k in range(1, 8)), "model: digits 1..7 show one segment each")

print("HARNESS TESTS " + ("FAILED: %d" % len(FAILS) if FAILS else "PASSED"))
sys.exit(1 if FAILS else 0)
