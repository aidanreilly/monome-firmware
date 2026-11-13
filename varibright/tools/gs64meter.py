#!/usr/bin/env python3
"""gs64meter: measure the gs64rec10 varibright display through its supply ripple.

usage:
  gs64meter.py state
  gs64meter.py fs [--cols N]                       free-running scan rate, N full columns lit
  gs64meter.py creep PERIOD CFG LEVEL              scan creep and wraps, column 0 at LEVEL
  gs64meter.py position PERIOD CFG LEVEL           scan position within the frame cycle
  gs64meter.py sweep START STOP STEP CFG LEVEL     creep at each period, then the zero crossing
CFG: 0x30 = T-SD P=3, 0x20 = P=2, 0x40 = P=4, 0x01 = SD.
"""
import sys
import numpy as np
from gs64.link import Grid, ADC_LIVE, ADC_SLOW
from gs64.capture import parse_blocks, TPS_FAST, TPS_SLOW
from gs64 import analysis


def column(level, col=0):
    return [[level if x == col else 0 for _ in range(8)] for x in range(8)]


def live(g, period, cfg, level):
    r = g.vbset(period, 0, cfg)
    g.intensity(15)
    g.pattern(column(level))
    blocks = parse_blocks(g.capture(255, ADC_LIVE | ADC_SLOW))
    return blocks, r['nframes'] * period, r['nframes']


def main(a):
    g = Grid()
    if a[0] == 'state':
        print(g.state())
        for name, r in zip(('0x00', '0x01', '0x05'), g.query()):
            print(name, r.hex(' '))
    elif a[0] == 'fs':
        n = int(a[2]) if len(a) > 2 and a[1] == '--cols' else 1
        g.vbset(0, 0, 0)
        g.intensity(15)
        blocks = parse_blocks(g.capture(255, 0, cols=(1 << n) - 1))
        print(f"scan rate {analysis.scan_rate(blocks, TPS_FAST, digit=(n == 8)):.3f} Hz with {n} columns lit")
    elif a[0] in ('creep', 'position'):
        p, cfg, lv = int(a[1]), int(a[2], 0), int(a[3])
        blocks, C, nf = live(g, p, cfg, lv)
        r = (analysis.creep if a[0] == 'creep' else analysis.position)(blocks, TPS_SLOW, C, nf)
        print(f"period {p} cfg {cfg:#04x}: {r}" + (f"  steady={analysis.steady(r)}" if a[0] == 'creep' else ''))
    elif a[0] == 'sweep':
        lo, hi, st = int(a[1]), int(a[2]), int(a[3])
        cfg, lv = int(a[4], 0), int(a[5])
        ps, cs = [], []
        for p in range(lo, hi + 1, st):
            blocks, C, nf = live(g, p, cfg, lv)
            r = analysis.creep(blocks, TPS_SLOW, C, nf)
            print(f"period {p}: {r}", flush=True)
            ps.append(p)
            cs.append(r['creep'])
        k, b = np.polyfit(ps, cs, 1)
        print(f"zero creep at {-b / k:.1f} (slope {k:.3e} frames/cycle per tick)")
    else:
        print(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:] or ['help'])
