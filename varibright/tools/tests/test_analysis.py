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
        self.assertGreater(r['steps'], 1000)

    def test_creep_measures_known_slide(self):
        nblk = 255
        ncyc = int(nblk * 256 * TPS_SLOW / C) + 2
        blocks = pulse_blocks(TPS_SLOW, nblk, cycle_pulses(ncyc, 1.1, 0.0175))
        r = creep(blocks, TPS_SLOW, C, NF)
        self.assertAlmostEqual(r['creep'], 0.0175, delta=0.001)
        self.assertGreaterEqual(r['jumps'], 1)


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
