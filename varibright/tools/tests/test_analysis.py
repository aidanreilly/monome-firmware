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


def loaded_pulses(ncyc, marker_phase, load_cols, slide=0.0):
    """Marker: column 0 lit in frame 1 of each cycle. Load: columns 1..load_cols lit in every frame.

    Digit slot d sits at (marker_phase + d/8 * 0.965) frames into its frame (the scan is
    0.965 of the frame; the rest is the halt), so the load pulses repeat every frame."""
    out = []
    for k in range(ncyc):
        m = marker_phase + k * slide
        for f in range(NF):
            base = k * C + f * PERIOD
            if f == 1:
                out.append(base + ((m - 1.0) % 1.0) * PERIOD)
            for d in range(1, load_cols + 1):
                out.append(base + (((m - 1.0) + d / 8 * 0.965) % 1.0) * PERIOD)
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
