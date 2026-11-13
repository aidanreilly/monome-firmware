"""Serial link to the gs64rec10 varibright firmware (mext plus the 0x0A/0x0B/0x0C extensions)."""
import time
import serial

ADC_LIVE, ADC_SLOW, ADC_DEC8 = 0x80, 0x40, 0x20
FS_FAST = 16e6 / (64 * 13)


def _report(r):
    if len(r) < 9 or r[0] != 0x0A:
        raise RuntimeError(f"bad 0x0A report: {r.hex(' ')}")
    st, cfg, nf, view, ph, pl, eh, el = r[1:9]
    return {'status': st, 'cfg': cfg, 'nframes': nf, 'view': view,
            'period': ph << 8 | pl, 'ee_period': eh << 8 | el}


class Grid:
    def __init__(self, port='/dev/ttyUSB0'):
        self.s = serial.Serial(port, 115200, timeout=0.3)
        time.sleep(0.3)
        self.s.reset_input_buffer()

    def _ask(self, cmd, wait=0.25):
        self.s.reset_input_buffer()
        self.s.write(bytes(cmd))
        time.sleep(wait)
        return self.s.read(256)

    def vbset(self, period, flags, cfg):
        """0x0B: set period (0 = mono), flags (bit 0 save, bit 1 band, bits 4..6 probe), cfg."""
        return _report(self._ask([0x0B, 0xA5, period >> 8, period & 0xFF, flags, cfg]))

    def state(self):
        return _report(self._ask([0x0A]))

    def query(self):
        """Raw replies to 0x00, 0x01 and 0x05."""
        return self._ask([0x00]), self._ask([0x01]), self._ask([0x05])

    def level(self, x, y, l):
        self.s.write(bytes([0x18, x, y, l]))

    def level_all(self, l):
        self.s.write(bytes([0x19, l]))

    def intensity(self, g):
        self.s.write(bytes([0x17, g]))

    def pattern(self, levels):
        """levels[x][y], 8x8 host levels 0..15."""
        for x in range(8):
            for y in range(8):
                self.level(x, y, levels[x][y])
        time.sleep(0.1)

    def capture(self, nblk, flags, mux=0x1E, cols=0):
        """0x0C capture. Returns the raw stream up to and including the 0xFE end marker."""
        rate = FS_FAST / (2 if flags & ADC_SLOW else 1) / (8 if flags & ADC_DEC8 else 1)
        self.s.reset_input_buffer()
        self.s.write(bytes([0x0C, 0xA5, cols, flags | (mux & 0x1F), nblk]))
        raw = bytearray()
        t0 = time.time()
        while time.time() - t0 < nblk * 256 / rate + 5:
            raw += self.s.read(65536)
            if raw and raw[-1] == 0xFE:
                break
        return bytes(raw)
