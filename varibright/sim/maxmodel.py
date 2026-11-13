"""ctypes wrapper around max7219.c (MAX7219 behavioural model)."""
import ctypes
import os
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "build", "libmax7219.so")
SRC = os.path.join(HERE, "max7219.c")


def _build():
    os.makedirs(os.path.dirname(LIB), exist_ok=True)
    if (not os.path.exists(LIB)) or os.path.getmtime(LIB) < os.path.getmtime(SRC):
        subprocess.check_call(["gcc", "-O2", "-shared", "-fPIC", "-o", LIB, SRC, "-lm"])


class MaxParams(ctypes.Structure):
    _fields_ = [
        ("fs", ctypes.c_double),
        ("phase", ctypes.c_double),
        ("blank", ctypes.c_double),
        ("pwm_pos", ctypes.c_double),
        ("digit_effect", ctypes.c_int),
        ("int_effect", ctypes.c_int),
        ("osc_jitter", ctypes.c_double),
        ("drift", ctypes.c_double),
        ("seed", ctypes.c_uint32),
        ("restart_digit", ctypes.c_int),
        ("restart_mode", ctypes.c_int),
        ("wake_delay", ctypes.c_double),
        ("wake_jitter", ctypes.c_double),
        ("tstart", ctypes.c_double),
        ("regs", ctypes.c_uint8 * 16),
        ("hold_latch", ctypes.c_int),
    ]


_build()
_lib = ctypes.CDLL(LIB)
_dp = ctypes.POINTER(ctypes.c_double)
_u8p = ctypes.POINTER(ctypes.c_uint8)
_lib.max_simulate.restype = ctypes.c_long
_lib.max_simulate.argtypes = [ctypes.POINTER(MaxParams), ctypes.c_long, _dp, _u8p, _u8p,
                              ctypes.c_double, ctypes.c_double, ctypes.c_long, _dp,
                              ctypes.c_double, _dp, ctypes.c_long,
                              ctypes.POINTER(ctypes.c_long)]

# register file of a chip that has been initialised like the stock firmware:
# no decode, intensity 15, scan limit 7, running, test off.
RUNNING_REGS = [0] * 16
RUNNING_REGS[9] = 0
RUNNING_REGS[10] = 15
RUNNING_REGS[11] = 7
RUNNING_REGS[12] = 1
RUNNING_REGS[15] = 0
# datasheet power-up: all control registers reset, shutdown mode
POWERUP_REGS = [0] * 16

# full-scale reference: one LED of a stock display at intensity 15 (duty 31/32 of 1/8)
STOCK_FULL = 31.0 / 32.0 / 8.0


def simulate(t, addr, data, fs=800.0, phase=0.0, blank=0.0, pwm_pos=0.0,
             digit_effect=0, int_effect=0, osc_jitter=0.0, drift=0.0, seed=1,
             restart_digit=0, restart_mode=0, wake_delay=0.0, wake_jitter=0.0, tstart=0.0, regs=None, t0=0.0, t1=1.0, dt=50e-6, hold_latch=0,
             tend=None, want_frames=False):
    """Run the model. Returns (lum[nbins, 8 digits, 8 segs], bin_times) where lum is the
    fraction of each bin the LED is lit. Optionally also returns digit-0 slot start times."""
    t = np.ascontiguousarray(t, dtype=np.float64)
    addr = np.ascontiguousarray(addr, dtype=np.uint8)
    data = np.ascontiguousarray(data, dtype=np.uint8)
    order = np.argsort(t, kind="stable")
    t, addr, data = t[order], addr[order], data[order]
    p = MaxParams()
    p.fs, p.phase, p.blank, p.pwm_pos = fs, phase, blank, pwm_pos
    p.digit_effect, p.int_effect = int(digit_effect), int(int_effect)
    p.osc_jitter, p.drift, p.seed = osc_jitter, drift, seed
    p.restart_digit, p.restart_mode, p.tstart = restart_digit, restart_mode, tstart
    p.wake_delay, p.wake_jitter = wake_delay, wake_jitter
    p.hold_latch = int(hold_latch)
    rr = RUNNING_REGS if regs is None else regs
    for i in range(16):
        p.regs[i] = rr[i]
    nb = int(round((t1 - t0) / dt))
    out = np.zeros(nb * 64)
    if tend is None:
        tend = t1
    nmax = int((tend - tstart) * fs * 2) + 16
    fl = np.zeros(nmax)
    nl = ctypes.c_long(0)
    _lib.max_simulate(ctypes.byref(p), len(t), t.ctypes.data_as(_dp), addr.ctypes.data_as(_u8p),
                      data.ctypes.data_as(_u8p), t0, dt, nb, out.ctypes.data_as(_dp), tend,
                      fl.ctypes.data_as(_dp), nmax, ctypes.byref(nl))
    lum = out.reshape(nb, 8, 8)
    times = t0 + (np.arange(nb) + 0.5) * dt
    if want_frames:
        return lum, times, fl[:nl.value]
    return lum, times


def read_trace(path, f_cpu=16e6):
    """Read a harness trace: lines 'cycle addr data' (decimal or 0x hex). Returns t, addr, data."""
    cyc, a, d = [], [], []
    with open(path) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if not line:
                continue
            parts = line.split()
            cyc.append(int(parts[0], 0))
            a.append(int(parts[1], 0) & 0x0F)
            d.append(int(parts[2], 0) & 0xFF)
    return np.array(cyc, dtype=np.float64) / f_cpu, np.array(a), np.array(d)
