import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from synth import encode
from gs64.capture import parse_blocks


class ParseBlocks(unittest.TestCase):
    def test_parse_roundtrip(self):
        blocks = [(i, [(i * 37 + j) % 1024 for j in range(256)]) for i in range(3)]
        got = parse_blocks(encode(blocks))
        self.assertEqual([i for i, _ in got], [0, 1, 2])
        for (i, v), (_, w) in zip(blocks, got):
            self.assertEqual(list(w), v)

    def test_parse_drops_incomplete_and_keeps_index(self):
        blocks = [(i, [(i + j) % 1024 for j in range(256)]) for i in range(5)]
        raw = bytearray(encode(blocks))
        blen = 1 + 512
        del raw[1 * blen + 100:1 * blen + 102]          # block 1 short by one sample
        start3 = 3 * blen - 2
        del raw[start3]                                 # block 3 loses its marker
        got = parse_blocks(bytes(raw))
        self.assertEqual([i for i, _ in got], [0, 4])
        self.assertEqual(list(got[1][1]), blocks[4][1])

    def test_parse_decimated(self):
        blocks = [(0, [0, 1, 127, 128, 8184] + [4000] * 251)]
        got = parse_blocks(encode(blocks, decimated=True), decimated=True)
        self.assertEqual(list(got[0][1][:5]), [0, 1, 127, 128, 8184])


if __name__ == '__main__':
    unittest.main()
