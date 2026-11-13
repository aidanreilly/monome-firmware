# gs64rec10 varibright (64vb.c, revision 3)

A mext firmware for the gs64rec10 monome 64 (ATmega325 @ 16 MHz, one MAX7219). Stock
serialosc / libmonome drive it as an 8x8 varibright grid.

**Status: validated by inspection and in simulation only (simavr, atmega1281 core, and a
behavioural MAX7219 model). Nothing here has run on real hardware.** The design rests on
undocumented MAX7219 behaviour. Run the probes in section 5 before you trust it.

| file | what |
|---|---|
| `64vb.c` | the varibright mext firmware |
| `64.c` | legacy series-protocol firmware (unchanged) |
| `64int.c` | the original unfinished mext attempt (unchanged, not built) |
| `button.c/h`, `types.h` | debouncer shared by both builds (unchanged) |

Revision 2 (plain "FLIP" bit planes, intensity register changed every frame) was refuted in
simulation. The chip shows a mixed state during the register burst, which gives 23..100 % FS
errors (`../sim/README.md` section 1). Revision 3 replaces it.

## 1. How it works

The MAX7219 multiplexes its digits from its own RC oscillator (f_s 500..1300 Hz, about 800 Hz
typical) and has no sync output. A Timer1 CTC interrupt fires once per scan frame with
period T_u, which is calibrated by the user (section 4). Each tick writes one burst of 11
words with the chip in shutdown:

    0x0C=0, 0x0A=code[f], digits 1..8 = frame f, 0x0C=1

* **Shutdown bracket:** the datasheet says the scan oscillator halts in shutdown, so the chip
  never displays a half-written state.
* **Cycle-exact tick:** inside the ISR, `tick_align()` spins until TCNT1 reaches 160 and pads
  the 0..4-cycle poll overshoot. The data shifter is constant-time inline asm, and the digit
  writes are unrolled with constant addresses. Every burst therefore starts at the same timer
  count and lasts exactly 687 cycles between the two shutdown LOAD edges, whatever the data
  or the interrupt latency (measured in simavr). The simulation shows that about 1 us of
  jitter costs about 0.7 % p-p of flicker.

Two display modes use the same burst, so one calibration serves both:

| | **T-SD** (default) | **SD** (opt-in) |
|---|---|---|
| principle | constant intensity (LED_INT); level step s of P lit in s of P frames, spread evenly | intensity-weighted frames |
| frames | P = 4 if f_s >= 750 Hz, else P = 3 (can be forced, section 6) | 15/15/6/15/11/15 if f_s >= 600 Hz, else 15/15/7/15/3 |
| brightness steps | 5 (P = 4) or 4 (P = 3), linear | 16 |
| level 15 vs stock | 97.9 / 96.7 / 94.7 % at 500 / 800 / 1300 Hz | 72.6 % (500 Hz, 5-frame) / 83 % (800 Hz) / 81 % (1300 Hz) |
| simulated rate tolerance (frozen wake) | +-1.1 % (500 Hz), +-1.4 % (800), +-1.5..2.2 % (1300) | about +-0.1 % (500 Hz) to +-0.3 % |

Host level to T-SD step (0 stays off, any nonzero level is at least the dimmest step, 15 is full):

| host level | 0 | 1..5 | 6..9 | 10..13 | 14..15 |
|---|---|---|---|---|---|
| P = 4 (f_s >= 750 Hz): step / brightness | 0 | 1 = 25 % | 2 = 50 % | 3 = 75 % | 4 = 100 % |

| host level | 0 | 1..7 | 8..12 | 13..15 |
|---|---|---|---|---|
| P = 3 (f_s < 750 Hz): step / brightness | 0 | 1 = 33 % | 2 = 67 % | 3 = 100 % |

**Mono fallback:** with no valid calibration record in EEPROM, the frame timer is off and the
main loop writes the MAX7219 directly. Host levels > 7 are on, at full stock brightness.

**LED_INT (0x17):** in T-SD, g is the chip intensity code. In the simulation the rate tolerance
shrinks below g = 11: to about +-0.5 % at g = 7, and near the exact rate only for g <= 3. In SD
the frame codes are scaled by (g+1)/16, using the smallest g' >= g that keeps the 16-level ramp
strictly increasing. In mono, g goes straight to the chip.

Why T-SD is the default: in the simulation it tolerates 5..15 times more rate mismatch than SD,
and it is no worse under any other modelled chip behaviour. The RC oscillator will drift by
more than +-0.1 %. Full comparison: `../sim/README.md` section 10.

## 2. Build, size, flash

```
make vb          # 64vb.elf / 64vb.hex for the ATmega325
make sim         # 64vb-sim.elf: -mmcu=atmega1281 -DSIM (register/vector name shim only)
make vb-clean vb VBFLAGS="-DVB_TILT=0"     # options: VB_TILT, VB_USE_TXE, VB_SHIFT_NOPS, VB_ALIGN_T0
make             # legacy series firmware 64.hex (unchanged)
```

Both builds compile without warnings (`-Wall -Wextra`, avr-gcc 7.3.0). Size: flash 9828 B
(30 % of 32 KB), static RAM 661 B (32 % of 2 KB), including the 256-byte output ring.

**No AVR toolchain on the host?** Build in a container instead, so nothing gets installed system-wide.
`../Containerfile` is a Fedora 44 image with avr-gcc, avr-libc, avr-binutils and make (about 535 MB).
Build the image once, from `varibright/`:

```
$ podman build -t gs64-avr .
```

Then build the firmware from this directory:

```
$ podman run --rm -v "$PWD":/src:Z gs64-avr
```

The container runs `make vb-clean vb VBFLAGS="-std=gnu11"`, writes `64vb.hex` (plus `64vb.elf` and `64vb.map`) back into this directory, and removes itself.
To use other options, add your own make command, for example:

```
$ podman run --rm -v "$PWD":/src:Z gs64-avr make vb-clean vb VBFLAGS="-std=gnu11 -DVB_TILT=0"
```

Keep `-std=gnu11` in `VBFLAGS`.
Fedora 44 ships avr-gcc 15.3.0, which defaults to C23.
In C23 `bool` is a keyword, so `types.h` fails with "two or more data types in declaration specifiers" unless you pass `-std=gnu11` (the avr-gcc 7.3 default).
With avr-gcc 15.3.0 the flash size is 9686 B and static RAM is still 661 B.
The image only covers the firmware build.
`make sim` and the `../sim` experiments also need simavr, Python and a libmonome checkout (`../sim/README.md`).

The cycle counts in sections 1 and 7 were measured on the avr-gcc 7.3.0 build.
The burst shifter is inline asm and `tick_align()` pads to a fixed timer count, so the burst timing should hold, but the ISR totals can shift with a different compiler.
Re-run the simavr checks (`make sim`, `../sim/README.md`) if you depend on those numbers.

**Flashing.** The stock gs64rec10 has no USB bootloader: the Makefile fuses are
hfuse 0x99, with BOOTRST unprogrammed. The first flash therefore needs an ISP or JTAG
programmer:

```
make vb-pro      # avrdude -p m325 -c avrispmkII -P usb -e -D -U flash:w:64vb.hex:i (+ fuses as legacy)
```

`bootloader/mk-boot.c` in github.com/monome/mk is an STK500 bootloader for the same MCU and FT245
wiring (text at 0x7C00). It could allow later updates over USB, but it is untested on this
board and is entered only on external reset.

A chip erase (`-e`) also clears the EEPROM with these fuses, so the calibration is lost on
every reflash. Note the period first (`tools/gridtest.py vb get`) and restore it with
`vb set --period N --save`.

Host-side test tool: `tools/gridtest.py` (serial and serialosc modes). First-contact steps:
`BRINGUP.md`.

## 3. FTDI serial string (required; firmware cannot set it)

serialosc's Linux detector accepts any tty with a usb-serial parent, so FTDI qualifies, and
runs `monome_open(devnode)`. libmonome then reads the USB serial (udev `ID_SERIAL_SHORT`, or on
macOS the suffix of `/dev/tty.usbserial-<serial>`) and picks the protocol from
`src/private/devices.h`: `m64-%d` / `m64_%d` gives **series**, plain `m%d` gives **mext**.
Then comes the mext handshake (0x00 / 0x01 / 0x05), then `monome_set_rotation` and
`monome_led_all(0)`. Nothing else is queried: there is no varibright flag, version or VID/PID
check (checked in the serialosc and libmonome sources).

So rewrite the FT245's EEPROM serial to `m` + digits, for example `m0000064`, with FT_Prog or
`ftdi_eeprom`, keeping VID/PID. Avoid serials that start with `m40h`, `mk` or `m64-`. Back up
first with `ftdi_eeprom --read-eeprom`. To return to `64.hex`, restore an `m64-` serial.

## 4. Calibration procedure

Hold key (0,0) (top left) while plugging in. The **calibration band** appears: all LEDs on for
half of T_u, written with the same bracketed burst as a frame, then off for the other half.
About half the rows look lit, and the band rolls at |1/T_u - f_s| Hz. Release all keys; keys
are ignored until everything has been released. Then:

| row y | x0 | x1 | x2 | x3 | x4 | x5 | x6 | x7 |
|---|---|---|---|---|---|---|---|---|
| 0 | -100 ticks | -10 | -1 | +1 | +10 | +100 | exit, no save | **save**, exit (2 blinks) |
| 1 | mode T-SD | mode SD | P auto | P = 3 | P = 4 | erase, mono, exit (1 blink) | | |
| 2 | band | preview ramp | | | probe 1 | probe 2 | probe 3 | probe 4 |

1. Start value: the stored period, or 20687 ticks (800 Hz plus 687 dark).
2. Use +-100 until the band rolls slowly, then +-10 and +-1 until it stands still. A roll of
   less than one row per few seconds is well inside the T-SD window. SD needs about one row
   per 10 s or slower (+-0.1 %). One tick is 0.003..0.008 % of T_u. If a step makes the roll
   faster, go the other way.
3. Optional: pick the mode, then "preview" shows column x at levels 2x / 2x+1. It should show
   steady steps with no flicker or rolling band.
4. Save with (7,0). The record goes to EEPROM 0x10: `B6 cfg lo hi cfg^lo^hi^5A`, where cfg
   bit 0 is the mode and bits 4..7 are the forced P. The revision-2 record (0xB5) is not
   accepted, so re-calibrate after upgrading.

Calibrate warm (after a few minutes on), and re-check if flicker appears later. Oscillator
drift with temperature and supply voltage is the main unknown.

If the band **never rolls** whatever the period, the chip probably restarts its scan at digit 0
on wake (see probe 1). In that case no flicker is expected at any period, and the period only
needs to minimise the first/last-row brightness difference.

## 5. Probe procedure (run on first contact with hardware)

Start from the calibration UI (row 2), or with 0x0B (section 6). **Probe 1 first**: it runs at
intensity 0. In the "restart at 0" case probes 2 and 3 keep one digit driver on far longer
than normal, and the datasheet warns about digit driver overload with short scans. Probes 1..3
light all LEDs and alternate **1 s reference** (chip awake) with **1 s probe**. Predictions
from the firmware traces (model, 800 Hz; % of a stock row, rows = LED x 0..7):

| probe | pattern | restart at digit 0 | frozen (resume) | same digit restarts | next digit |
|---|---|---|---|---|---|
| 1 | int 0, 50 us awake / 50 us shutdown | ref 3 % all rows; probe: x=0 row 40 %, rest dark | ref 3 %; probe 2 % (dimmer) | one random row 40 %, rest dark | ref 3 %; probe 5 % (brighter) |
| 2 | int 15, 50/50 us | x=0 row 413 %, rest dark | 50 % all | one random row 415 % | 52 % all |
| 3 | int 15, 400/100 us | 250 250 145 0 0 0 0 0 | 80 % all | 62 / 99 alternating | 81 % all |
| 4 | T-SD P=4, all LEDs at step 2; 2 s at T_u, 2 s at T_u + 0.5 % | steady both phases | steady (pp about 1 %) | | |

Probe 4 under "frozen, latch held" (the next-slot write model, keeping the value latched
before the halt): visible flicker in the +0.5 % phase (19 % p-p predicted, 12 % already at
T_u if it is a little off).

How to read them:

* **Probe 1, one row bright and the rest dark:** restart at 0 (top row) or same digit (some
  other row). With restart at 0, SD and T-SD self-synchronise and no rate flicker is
  possible; SD (16 levels) then becomes the better choice. Same digit: both modes fail in
  simulation, so use mono.
* **Probe 1, uniform dimmer in the probe second:** frozen. T-SD is the right mode.
* **Probe 1, uniform brighter:** next digit. Both modes fail in simulation, so use mono.
* **Probe 4 flickering in the detuned phase:** the latch is held across the wake. Every
  temporal scheme then fails at any mismatch. T-SD only works while the calibration is
  essentially exact, otherwise use mono.

Leave a probe with (0,2) or (1,2), or by exiting the calibration.

## 6. Protocol

Byte-exact with libmonome `src/proto/mext.c` / `mext.h`. Lengths include the header and equal
1 + libmonome's `outgoing_payload_lengths`. Every header libmonome does not list is consumed as
1 byte. A partial packet is dropped after about 100 ms of real silence; bytes held back by flow
control do not count.

| opcode | len | meaning | reply |
|---|---|---|---|
| 0x00 | 1 | system query | `00 01 01`, `00 02 01`, `00 08 01` (tilt only with VB_TILT) |
| 0x01 | 1 | get id | `01` + 32 bytes `"monome 64"` |
| 0x02 | 33 | set id (RAM) | - |
| 0x03 / 0x05 | 1 | get offsets (ignored) / get grid size | - / `03 08 08` |
| 0x04 / 0x06 / 0x08 | 4 / 3 / 3 | set offset / size / addr (consumed) | - |
| 0x07 / 0x0F | 1 | get addr / version (ignored) | - |
| **0x0A** | 1 | extension: get state | `0A status cfg nframes view per_hi per_lo ee_hi ee_lo` |
| **0x0B** | 6 | extension: `0B A5 per_hi per_lo flags cfg` | same as 0x0A (no reply if the key byte is not 0xA5) |
| 0x10 / 0x11 | 3 | LED off / on `x y` | - |
| 0x12 / 0x13 | 1 | all off / on | - |
| 0x14 / 0x15 / 0x16 | 11 / 4 / 4 | map / row / col (bits) | - |
| 0x17 | 2 | intensity g | - |
| 0x18 / 0x19 | 4 / 2 | level set `x y l` / level all `l` | - |
| 0x1A / 0x1B / 0x1C | 35 / 7 / 7 | level map / row / col, nybbles high = even LED | - |
| 0x80 / 0x81 / 0x82 | 1 / 2 / 2 | tilt state / enable / disable | `80 s` / - / - |
| 0x90..0x94 | 4 / 3 / 34 / 5 / 3 | LED ring (consumed) | - |

Device to host: `21 x y` / `20 x y` key down / up. `81 00 xL xH yL yH 00 00` tilt (int16 LE,
as monome/mk), sent only after 0x81 00. Nothing else is sent unsolicited. Messages are queued
whole. Host bytes stay in the FT245 FIFO while the 255-byte output ring has less than 40
bytes free, so replies are never dropped. Key events go through an ordered 32-entry queue.

Extension fields:

* `status`: bit 0 varibright active, bit 1 EEPROM record valid, bit 2 band showing, bit 3
  probe showing.
* `cfg`: bit 0 mode (0 T-SD, 1 SD), bits 4..7 forced P (0 = auto, 2..8).
* `nframes`: the P or SD frame count (0 in mono). `view`: 0 normal, 1 band, 3..6 probes 1..4.
* `flags` (0x0B): bit 0 also write EEPROM (period 0 erases), bit 1 show the band, bits 4..6
  probe 1..4.
* 0x0B period: 0 = mono, otherwise 12000..34000 ticks; anything else changes nothing.

libmonome never sends 0x0A or 0x0B. Its incoming table does not know the 0x0A reply, so use
these only from your own tool with serialosc stopped.

Coordinates (as 64.c, the physical reference): LED (x, y) = MAX7219 digit x+1, bit 7-y.
Key (x, y) = row select 7-x, shift position 7-y.

## 7. Timing and concurrency

* Frame ISR (T-SD, SD, band, probe 4): at most 987 cycles from the first instruction to after
  `reti`, plus 7 for response and the vector jmp: **62.1 us** (budget 120 us). Probes 1..3:
  18.9 us per 50 us segment. Measured in simavr under host traffic and key scanning. Tick
  spacing was exact to the cycle in every run.
* Alignment margin: about 88 cycles from compare match to the TCNT1 poll, plus up to about 40
  when the key ISR is running, against VB_ALIGN_T0 = 160.
* Only the Timer1 ISR touches PORTE 0..2 while the timer runs. Main uses only sbi/cbi on E3/E4
  and never disables interrupts for more than a few cycles. Only main writes `lvl` and the
  frame buffer; a frame may show a half-applied command for one cycle.
* USB suspend (PWREN high): fade, timer stop, MAX7219 shutdown. Wake: restart, fade-in, and the
  LED state is kept. Sleep is polled every 0.5 s, as in 64.c.

## 8. Known risks and unverified points

* Not run on hardware. Every number comes from a model of the MAX7219 built from the datasheet
  plus assumptions (`../sim/README.md` sections 3, 9 and 10).
* The wake behaviour after shutdown, the write latching and the wake-time repeatability are
  undocumented and decide everything. Run the probes.
* Oscillator drift: T-SD tolerates about +-1.1..2 % in simulation, SD about +-0.1..0.3 %.
* MAX7219 clones may differ in all of the above.
* Phantom-array or stroboscopic visibility of the f_s/P cycle (200 Hz at 800 Hz with P = 4)
  is not covered by the metric.
* The 1-cycle CLK widths are within the datasheet but leave little margin (VB_SHIFT_NOPS=1 adds
  margin). TXE is not checked by default (VB_USE_TXE=1 once the wiring is confirmed).
* Tilt axis orientation was not checked against a unit.
