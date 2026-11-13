import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from synth import pulse_blocks
from gs64.capture import TPS_FAST, TPS_SLOW
from gs64.analysis import creep, scan_rate, steady

PERIOD, NF = 18747, 3
C = NF * PERIOD


def cycle_pulses(ncyc, phase0, slide):
    """One pulse per cycle at (phase0 + k*slide) frames into the cycle, wrapping within frame 1."""
    k = np.arange(ncyc)
    pos = 1.0 + ((phase0 - 1.0 + k * slide) % 1.0)        # stays inside the lit frame [1, 2)
    return k * C + pos * PERIOD


class Creep(unittest.TestCase):
    def test_creep_zero_for_locked_pulse(self):
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, cycle_pulses(ncyc, 1.38, 0.0))
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertLess(abs(r['creep']), 1e-4)
        self.assertEqual(r['jumps'], 0)
        self.assertGreater(r["steps"], 200)          # block pairs in a 255-block capture

    def test_creep_measures_known_slide(self):
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, cycle_pulses(ncyc, 1.1, 0.0175))
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertAlmostEqual(r['creep'], 0.0175, delta=0.001)
        self.assertGreaterEqual(r['jumps'], 1)


def loaded_pulses(ncyc, marker_phase, load_cols, slide=0.0, load_weight=1, period=PERIOD):
    """Marker: column 0 lit in frame 1 of each cycle. Load: columns 1..load_cols lit in every frame.

    Digit slot d sits at (marker_phase + d/8 * 0.965) frames into its frame (the scan is
    0.965 of the frame; the rest is the halt), so the load pulses repeat every frame."""
    out = []
    for k in range(ncyc):
        m = marker_phase + k * slide
        for f in range(NF):
            base = (k * NF + f) * period
            if f == 1:
                out.append(base + ((m - 1.0) % 1.0) * period)
            for d in range(1, load_cols + 1):
                out += [base + (((m - 1.0) + d / 8 * 0.965) % 1.0) * period] * load_weight
    return np.sort(np.array(out))


class CreepUnderLoad(unittest.TestCase):
    def test_creep_zero_with_heavy_uniform_load(self):
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, loaded_pulses(ncyc, 1.38, 6), keep=lambda i: i % 7 != 3)
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertEqual(r['jumps'], 0)
        self.assertLess(abs(r['creep']), 1e-4)

    def test_creep_slide_with_heavy_uniform_load(self):
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, loaded_pulses(ncyc, 1.38, 6, slide=0.002), keep=lambda i: i % 7 != 3)
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertAlmostEqual(r['creep'], 0.002, delta=0.0003)


    def test_creep_zero_with_dominant_frame_rate_line(self):
        # on the real unit the every-frame load line is about 13x the marker line
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, loaded_pulses(ncyc, 1.38, 3, load_weight=5), keep=lambda i: i % 2 == 0)
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertEqual(r['jumps'], 0)
        self.assertLess(abs(r['creep']), 1e-4)


    def test_creep_zero_with_frame_locked_shutdown_dip(self):
        # the firmware's shutdown bracket dips the supply at every frame tick, tied to the
        # timer and not to the scan; it must not leak into the position estimate
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, loaded_pulses(ncyc, 1.38, 3))
        ticks_dip = np.arange(ncyc * NF) * PERIOD
        dip = pulse_blocks(TPS_SLOW, nblk, ticks_dip, base=0.0, amp=-400.0, width=1500.0, seed=2)   # frame line ~17x the marker, as measured
        blocks = [(i, a + b) for (i, a), (_, b) in zip(blocks, dip)]
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertEqual(r['jumps'], 0)
        self.assertLess(abs(r['creep']), 1e-4)

    def test_creep_zero_with_narrow_frame_locked_spike(self):
        # a timer-locked feature narrower than the 1664-tick sample spacing is sampled at a
        # different offset in each frame of the cycle; at period 18821 that pattern beats
        # over ~15 cycles (2 blocks) and must not show up as a moving position
        p = 18821
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / (NF * p)) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, loaded_pulses(ncyc, 1.38, 3, period=p))
        spike = pulse_blocks(TPS_SLOW, nblk, np.arange(ncyc * NF) * p, base=0.0, amp=-60.0, width=300.0, seed=2)
        blocks = [(i, a + b) for (i, a), (_, b) in zip(blocks, spike)]
        r = creep(blocks, TPS_SLOW, NF * p, NF)
        self.assertEqual(r['jumps'], 0)
        self.assertLess(abs(r['creep']), 1e-4)


class ScanRate(unittest.TestCase):
    def test_scan_rate_finds_884_52(self):
        fs = 884.52
        nblk = 255
        T = 16e6 / fs
        n = int(nblk * 256 * TPS_FAST / T) + 2
        blocks = pulse_blocks(TPS_FAST, nblk, np.arange(n) * T, width=1200.0, keep=lambda i: i % 4 != 1)
        self.assertAlmostEqual(scan_rate(blocks, TPS_FAST), fs, delta=0.01)


class Steady(unittest.TestCase):
    def test_steady(self):
        self.assertTrue(steady({'creep': 0.0004, 'jumps': 0}))
        self.assertFalse(steady({'creep': 0.0006, 'jumps': 0}))
        self.assertFalse(steady({'creep': 0.0, 'jumps': 1}))


if __name__ == '__main__':
    unittest.main()
