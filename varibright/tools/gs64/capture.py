"""Parse the 0x0C ADC capture stream (see adc_capture() in 64vb.c)."""
import numpy as np

TPS_FAST = 64 * 13          # timer ticks per sample, ADC clock /64 (19230.77 samples/s)
TPS_SLOW = 128 * 13         # ADC_SLOW, /128 (9615.38 samples/s)
TPS_DEC8 = 128 * 13 * 8     # ADC_SLOW | ADC_DEC8, sums of 8 (1201.92 outputs/s)


def parse_blocks(raw, decimated=False):
    """Split the stream on block markers and return [(block_index, values)] for complete blocks.

    The true index is recovered from the 5-bit counter in each marker, so dropped
    markers do not shift the timing of later blocks."""
    shift, lomask = (7, 0x7F) if decimated else (5, 0x1F)
    blocks, cur, hi, idx, last = [], None, None, None, -1
    for b in raw:
        if b == 0xFE:
            break
        if b >= 0xC0:
            if cur is not None:
                blocks.append((idx, cur))
            k = b & 0x1F
            idx = last + ((k - last) % 32 or 32) if last >= 0 else k
            last = idx
            cur, hi = [], None
        elif cur is None:
            continue
        elif b & 0x80:
            hi = b & 0x3F if decimated else b & 0x1F
        elif hi is not None:
            cur.append(hi << shift | (b & lomask))
            hi = None
    if cur is not None:
        blocks.append((idx, cur))
    return [(i, np.array(v, float)) for i, v in blocks if len(v) == 256]
