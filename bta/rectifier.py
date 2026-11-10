"""Detailed rotating-rectifier model for the rotating-diode failure signature (FMEA item FM-01/FM-02).

Circuit: exciter armature (3 phases, star, EMF e_k, resistance r_x, commutating inductance l_c), six diodes
(piecewise-linear: g_on / g_off), main field (R_f, L_f). Backward-Euler + nodal analysis with diode-state
iteration (the SPICE companion-model approach). Faults: one diode open, one diode shorted.

Signature: the armature MMF space vector, computed in the rotor frame from the phase currents and moved to
the stationary exciter-field frame. A healthy six-pulse bridge gives DC + 6k x f_ex there; a missing or
shorted diode adds components at f_ex and 2 f_ex, which induce ripple in the stationary exciter field
current -- the quantity an AVR can measure without access to the rotor. The amplitude reaching the field
current also depends on the field circuit and the AVR, so only frequencies and relative changes are claimed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class RectParams:
    f_ex: float = 150.0        # exciter armature frequency: 12-pole exciter at 1500 r/min [A]
    e_ll_rms: float = 54.0     # exciter line EMF (V rms) for full-load field current [D from VE at full load]
    r_x: float = 0.10          # armature resistance per phase, ohm [A]
    l_c: float = 143e-6        # commutating inductance per phase, H [D from KC = 0.15]
    r_f: float = 0.86          # main field resistance, ohm [D, design]
    l_f: float = 1.91          # main field inductance, H [D, design]
    i_f0: float = 77.7         # initial field current, A [D, full-load field current]
    g_on: float = 1e3          # 1 mOhm forward
    g_off: float = 1e-6        # 1 MOhm reverse


def simulate(p: RectParams, fault: str = "none", periods: int = 30, steps_per_period: int = 1500) -> dict:
    """fault: 'none' | 'open' (upper diode of phase a missing) | 'short' (upper diode of phase a shorted)."""
    h = 1.0 / (p.f_ex * steps_per_period)
    n = periods * steps_per_period
    e_pk = p.e_ll_rms * math.sqrt(2) / math.sqrt(3)
    w = 2 * math.pi * p.f_ex
    kL, kF = p.l_c / h, p.l_f / h
    i_ph = np.zeros(3)
    i_f = p.i_f0
    state = np.ones(6, dtype=bool)      # diode conducting guesses: upper a,b,c then lower a,b,c
    rec_t = np.empty(n)
    rec_i = np.empty((n, 3))
    rec_if = np.empty(n)
    rec_vd = np.empty(n)
    gx = 1.0 / (p.r_x + kL)
    for s in range(n):
        t = (s + 1) * h
        e = e_pk * np.sin(w * t - np.array([0.0, 2 * math.pi / 3, 4 * math.pi / 3]))
        for _ in range(20):
            g = np.where(state, p.g_on, p.g_off)
            if fault == "open":
                g[0] = 0.0
            elif fault == "short":
                g[0] = p.g_on
            gu, gl = g[:3], g[3:]
            # unknowns: v_a, v_b, v_c, v_s, v_P   (v_N = 0)
            A = np.zeros((5, 5))
            b = np.zeros(5)
            for k in range(3):
                # winding current i_k = gx*(e_k + v_s - v_k + kL*i_old)
                # KCL at k: i_k - gu(v_k - v_P) - gl(v_k - 0) = 0
                A[k, k] += -gx - gu[k] - gl[k]
                A[k, 3] += gx
                A[k, 4] += gu[k]
                b[k] -= gx * (e[k] + kL * i_ph[k])
                # star point: sum of i_k = 0
                A[3, k] += -gx
                A[3, 3] += gx
                b[3] -= gx * (e[k] + kL * i_ph[k])
                # KCL at P: sum gu(v_k - v_P) - i_f = 0
                A[4, k] += gu[k]
                A[4, 4] += -gu[k]
            gf = 1.0 / (p.r_f + kF)
            A[4, 4] += -gf
            b[4] += gf * kF * i_f
            v = np.linalg.solve(A, b)
            vk, vs, vp = v[:3], v[3], v[4]
            new = np.concatenate([vk - vp > 0, -vk > 0])
            if (new == state).all():
                break
            state = new
        i_ph = gx * (e + vs - vk + kL * i_ph)
        i_f = gf * (vp + kF * i_f)
        rec_t[s], rec_i[s], rec_if[s], rec_vd[s] = t, i_ph, i_f, vp
    return {"t": rec_t, "i_ph": rec_i, "i_f": rec_if, "v_dc": rec_vd, "f_ex": p.f_ex, "h": h}


def mmf_stator_frame(res: dict) -> np.ndarray:
    """Armature MMF space vector moved from the rotor frame to the stationary field frame."""
    a = np.exp(2j * math.pi / 3)
    i = res["i_ph"]
    f_r = (2 / 3) * (i[:, 0] + a * i[:, 1] + a * a * i[:, 2])
    th = 2 * math.pi * res["f_ex"] * res["t"]
    # rotor rotates so that positive-sequence fundamental is stationary in the field frame
    return f_r * np.exp(-1j * (th - math.pi / 2))


def spectrum(x: np.ndarray, h: float, last_periods: int, f_ex: float) -> tuple[np.ndarray, np.ndarray]:
    n = int(round(last_periods / (f_ex * h)))
    seg = x[-n:]
    seg = seg - seg.mean() if np.isrealobj(seg) else seg
    X = np.fft.rfft(seg) if np.isrealobj(seg) else np.fft.fft(seg)
    f = np.fft.rfftfreq(n, h) if np.isrealobj(seg) else np.fft.fftfreq(n, h)
    return f, np.abs(X) * 2 / n


def signature(res: dict, last_periods: int = 20) -> dict:
    """Key numbers: mean DC voltage, field ripple, and field-frame MMF harmonics at k x f_ex (k=1,2,6)."""
    fx, h = res["f_ex"], res["h"]
    n = int(round(last_periods / (fx * h)))
    fs = mmf_stator_frame(res)
    d_axis = fs.real            # component that links the exciter field winding
    f, a = spectrum(d_axis, h, last_periods, fx)
    def at(k):
        j = np.argmin(np.abs(f - k * fx))
        return float(a[j])
    i_f = res["i_f"][-n:]
    vd = res["v_dc"][-n:]
    return {
        "v_dc_mean": float(vd.mean()),
        "i_f_mean": float(i_f.mean()),
        "i_f_ripple_pp": float(i_f.max() - i_f.min()),
        "mmf_dc": float(abs(d_axis[-n:].mean())),
        "mmf_1fex": at(1), "mmf_2fex": at(2), "mmf_6fex": at(6),
        "i_phase_rms": [float(np.sqrt(np.mean(res["i_ph"][-n:, k] ** 2))) for k in range(3)],
        "i_phase_dc": [float(res["i_ph"][-n:, k].mean()) for k in range(3)],
    }
