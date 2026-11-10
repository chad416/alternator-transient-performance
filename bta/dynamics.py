"""Time-domain model of an islanded generating set: alternator + brushless excitation + engine + loads.

Fidelity (Wasson ch. 33, Principle 33.1): RMS / phasor-dynamics ("stability-type") model.
- Alternator: dq model with field, one d-damper and one q-damper (IEEE Std 1110 model 2.1),
  stator transients neglected, speed voltage kept, d-axis magnetising saturation from the OCC
  (Kundur, Power System Stability and Control, §3.8 approach: Lads = Ksd * Ladu).
- Excitation: IEEE Std 421.5-2016 AC8B structure (PID, exciter field lag, KE, SE, KD, rectifier FEX(KC)).
  Shunt supply: regulator ceiling multiplied by terminal voltage. PMG supply: ceiling constant.
- Engine: PI governor with droop, actuator and combustion lags, boost-limited fuel (turbo lag).
- Loads: constant impedance (frequency-dependent reactance) and a deep-bar induction motor
  (3rd-order model, stator transients neglected).
This fidelity resolves the RMS voltage envelope that ISO 8528-5 limits apply to; it does not resolve
the first-cycle DC offset or waveform distortion (those come from FEMM and are out of scope here).
All quantities per unit on the alternator rating unless stated. Time in seconds.
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

W0 = 2 * math.pi * 50.0


# ------------------------------------------------------------------ parameters
@dataclass
class GenParams:
    xd: float
    xq: float
    xl: float
    xdp: float
    xdpp: float
    xqpp: float
    tdo_p: float
    tdo_pp: float
    tqo_pp: float
    ra: float
    h: float
    occ_e: tuple            # OCC: open-circuit voltage pu ...
    occ_ifd: tuple          # ... versus field current in pu of the air-gap-line value at 1 pu (IEEE IFD base)

    def circuit(self) -> dict:
        """Equivalent-circuit parameters from standard parameters (classical relations, Kundur §4.2 / IEEE 1110)."""
        lad = self.xd - self.xl
        laq = self.xq - self.xl
        a = self.xdp - self.xl
        lfd = lad * a / (lad - a)
        rfd = (lad + lfd) / (W0 * self.tdo_p)
        b = self.xdpp - self.xl
        l1d = b * lad * lfd / (lad * lfd - b * (lad + lfd))
        r1d = (l1d + lad * lfd / (lad + lfd)) / (W0 * self.tdo_pp)
        c = self.xqpp - self.xl
        l1q = laq * c / (laq - c)
        r1q = (laq + l1q) / (W0 * self.tqo_pp)
        return dict(lad=lad, laq=laq, lfd=lfd, rfd=rfd, l1d=l1d, r1d=r1d, l1q=l1q, r1q=r1q, ll=self.xl, ra=self.ra)


@dataclass
class ExcParams:
    supply: str = "shunt"
    tr: float = 0.01
    kp: float = 4.0
    ki: float = 4.0
    kd: float = 0.4
    td: float = 0.02
    ka: float = 1.0
    ta: float = 0.005
    vrmax: float = 14.0
    vrmin: float = 0.0
    te: float = 0.25
    ke: float = 1.0
    kc: float = 0.15
    kdx: float = 0.6
    ve1: float = 6.0
    se1: float = 0.30
    ve2: float = 4.5
    se2: float = 0.10
    k_rect: float = 1.0      # rectifier capability factor (1 healthy; <1 with a failed diode, from bta/rectifier.py)

    def se(self, ve: float) -> float:
        """IEEE 421.5 quadratic exciter saturation SE(VE) = B (VE - A)^2 / VE through two points."""
        r = math.sqrt(self.se1 * self.ve1 / (self.se2 * self.ve2))
        a = (self.ve1 - r * self.ve2) / (1 - r)
        b = self.se1 * self.ve1 / (self.ve1 - a) ** 2
        if ve <= a or ve <= 0:
            return 0.0
        return b * (ve - a) ** 2 / ve


def fex(i_n: float) -> float:
    """IEEE 421.5 rectifier regulation function FEX(IN)."""
    if i_n <= 0:
        return 1.0
    if i_n <= 0.433:
        return 1 - 0.577 * i_n
    if i_n <= 0.75:
        return math.sqrt(0.75 - i_n ** 2)
    if i_n <= 1.0:
        return 1.732 * (1 - i_n)
    return 0.0


@dataclass
class GovParams:
    droop: float = 0.03
    kp: float = 12.0
    ki: float = 6.0
    t_act: float = 0.05
    t_eng: float = 0.08
    fuel_max: float = 1.10
    f_na: float = 0.55
    t_boost: float = 1.5
    damping: float = 0.0
    ideal: bool = False      # True: constant speed (alternator-only test, as on a test bed with a stiff drive)


@dataclass
class MotorParams:
    s_kva: float             # motor rating
    rs: float = 0.010
    xs: float = 0.080
    xm: float = 3.000
    xr: float = 0.080
    rr_run: float = 0.012
    rr_lr: float = 0.050
    h: float = 0.6
    t0: float = 0.05
    pf_rated: float = 0.88
    eff_rated: float = 0.95

    @property
    def x(self):
        return self.xs + self.xm

    @property
    def xp(self):
        return self.xs + self.xm * self.xr / (self.xm + self.xr)

    def rr(self, s: float) -> float:
        return self.rr_run + (self.rr_lr - self.rr_run) * math.sqrt(min(abs(s), 1.0))

    @property
    def t_rated(self):
        return self.pf_rated * self.eff_rated   # rated shaft torque in pu of motor kVA base at sync speed

    def load_torque(self, wm: float) -> float:
        return self.t_rated * (self.t0 + (1 - self.t0) * wm * wm) * (1 if wm > 0 else self.t0)


@dataclass
class Segment:
    """One time segment with a fixed set of connected loads."""
    t_end: float
    p_load: float = 0.0          # static load at 1 pu voltage and frequency
    q_load: float = 0.0
    motor_on: bool = False
    fault_z: complex | None = None   # bolted fault impedance at the terminals
    vref: float | None = None        # new AVR set point from the start of this segment


# ------------------------------------------------------------------ the model
class GenSet:
    # state indices
    PSI_FD, PSI_1D, PSI_1Q, WR, VM, XI, XD, VRA, VE, XG, FA, TM, BST, EMD, EMQ, WM = range(16)
    N = 16

    def __init__(self, gen: GenParams, exc: ExcParams, gov: GovParams, motor: MotorParams | None, s_gen_kva: float):
        self.g = gen
        self.c = gen.circuit()
        self.e = exc
        self.gv = gov
        self.mo = motor
        self.s_gen = s_gen_kva
        e = np.asarray(gen.occ_e, float)
        i = np.asarray(gen.occ_ifd, float)
        # saturation ratio K(e) = e / ifd(e) on the OCC (=1 on the air-gap line)
        self._sat_e = e
        self._sat_k = np.where(e > 0, e / np.maximum(i, 1e-9), 1.0)
        self._se_l, self._sk_l = [float(v) for v in self._sat_e], [float(v) for v in self._sat_k]
        self._cf = (self.c["ra"], self.c["ll"], self.c["lfd"], self.c["l1d"], self.c["l1q"])
        self.vref = 1.0
        self.wref = 1.0
        self.seg: Segment | None = None

    # ---- saturation factor Ksd as function of d-axis air-gap flux
    def ksd(self, psi_ad: float) -> float:
        x = abs(psi_ad)
        se, sk = self._se_l, self._sk_l
        if x <= se[0]:
            return sk[0]
        if x <= se[-1]:
            j = bisect.bisect_right(se, x)
            f = (x - se[j - 1]) / (se[j] - se[j - 1])
            return sk[j - 1] + f * (sk[j] - sk[j - 1])
        # beyond the last OCC point: extend the field current linearly with the last slope
        e, k = self._sat_e, self._sat_k
        i1, i0 = e[-1] / k[-1], e[-2] / k[-2]
        i = i1 + (x - e[-1]) * (i1 - i0) / (e[-1] - e[-2])
        return float(x / i)

    # ---- network solution for given states (scalar arithmetic: this is the inner loop)
    def network(self, y, seg: Segment, ksd_guess: float | None = None):
        c = self._cf
        wr = 1.0 if self.gv.ideal else y[self.WR]
        psi_fd, psi_1d, psi_1q = y[self.PSI_FD], y[self.PSI_1D], y[self.PSI_1Q]
        ksd = ksd_guess if ksd_guess is not None else 1.0
        # isotropic admittance of loads, fault and motor (complex), plus motor injection
        yc = 0j
        inj = 0j
        if seg.p_load or seg.q_load:
            yc += complex(seg.p_load, -seg.q_load / wr)
        if seg.fault_z is not None:
            yc += 1 / complex(seg.fault_z.real, seg.fault_z.imag * wr)
        ym = 0j
        em = 0j
        if seg.motor_on and self.mo is not None:
            m = self.mo
            k = self.s_gen / m.s_kva
            ym = 1 / (complex(m.rs, wr * m.xp) * k)
            em = complex(y[self.EMD], y[self.EMQ])
            yc += ym
            inj = ym * em
        ra, ll, lfd, l1d, l1q = c
        laqs = self.c["laq"]
        l_aqs = 1 / (1 / laqs + 1 / l1q)
        xqpp = wr * (ll + l_aqs)
        e_d = -wr * l_aqs * psi_1q / l1q
        for _ in range(8):
            lads = self.c["lad"] * ksd
            l_ads = 1 / (1 / lads + 1 / lfd + 1 / l1d)
            xdpp = wr * (ll + l_ads)
            e_q = wr * l_ads * (psi_fd / lfd + psi_1d / l1d)
            det = ra * ra + xdpp * xqpp
            # Yg = [[ra, xqpp], [-xdpp, ra]] / det
            g11, g12, g21, g22 = ra / det, xqpp / det, -xdpp / det, ra / det
            y11, y12, y21, y22 = g11 + yc.real, g12 - yc.imag, g21 + yc.imag, g22 + yc.real
            r1 = g11 * e_d + g12 * e_q + inj.real
            r2 = g21 * e_d + g22 * e_q + inj.imag
            dt = y11 * y22 - y12 * y21
            vd = (r1 * y22 - y12 * r2) / dt
            vq = (y11 * r2 - y21 * r1) / dt
            idg = g11 * (e_d - vd) + g12 * (e_q - vq)
            iqg = g21 * (e_d - vd) + g22 * (e_q - vq)
            psi_ad = l_ads * (-idg + psi_fd / lfd + psi_1d / l1d)
            k_new = self.ksd(psi_ad)
            if abs(k_new - ksd) < 1e-9:
                break
            ksd = k_new
        im = None
        if seg.motor_on and self.mo is not None:
            ic = ym * (complex(vd, vq) - em)
            im = (ic.real, ic.imag)
        return dict(v=(vd, vq), ig=(idg, iqg), psi_ad=psi_ad, ksd=ksd, l_ads=l_ads, l_aqs=l_aqs, wr=wr, im=im,
                    e_d=e_d, e_q=e_q)

    # ---- right-hand side
    MAX_RHS = 400_000          # evaluation budget per segment: a stalled (chattering) run is reported, not waited for

    def rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        self._nfev += 1
        if self._nfev > self.MAX_RHS:
            raise RuntimeError(f"solver stalled at t={t:.3f} s (more than {self.MAX_RHS} evaluations)")
        seg = self.seg
        c, e, gv = self.c, self.e, self.gv
        n = self.network(y, seg, self._ksd_last)
        self._ksd_last = n["ksd"]
        v, ig, wr = n["v"], n["ig"], n["wr"]
        dy = np.zeros(self.N)
        # rotor circuits
        psi_ad = n["psi_ad"]
        ifd = (y[self.PSI_FD] - psi_ad) / c["lfd"]
        i1d = (y[self.PSI_1D] - psi_ad) / c["l1d"]
        psi_aq = n["l_aqs"] * (-ig[1] + y[self.PSI_1Q] / c["l1q"])
        i1q = (y[self.PSI_1Q] - psi_aq) / c["l1q"]
        ladu = c["lad"]
        ifd_ieee = ladu * ifd                                # IEEE 421.5 IFD (1.0 = air-gap-line no-load field current)
        ve = max(y[self.VE], 1e-6)
        i_n = e.kc * max(ifd_ieee, 0.0) / ve
        efd = e.k_rect * ve * fex(i_n)
        dy[self.PSI_FD] = W0 * (c["rfd"] / ladu * efd - c["rfd"] * ifd)
        dy[self.PSI_1D] = -W0 * c["r1d"] * i1d
        dy[self.PSI_1Q] = -W0 * c["r1q"] * i1q
        # electrical torque
        psi_d = -c["ll"] * ig[0] + psi_ad
        psi_q = -c["ll"] * ig[1] + psi_aq
        te = psi_d * ig[1] - psi_q * ig[0]
        # ---- AVR (AC8B PID) + exciter
        vt = math.hypot(v[0], v[1])
        dy[self.VM] = (vt - y[self.VM]) / e.tr
        err = self.vref - y[self.VM]
        deriv = (err - y[self.XD]) / e.td
        dy[self.XD] = deriv
        vpid = e.kp * err + y[self.XI] + e.kd * deriv
        supply = vt if e.supply == "shunt" else 1.0
        vrmax, vrmin = e.vrmax * supply, e.vrmin * supply
        # integrator with anti-windup (clamp when the regulator output is at a limit and pushing further)
        di = e.ki * err
        if (y[self.VRA] >= vrmax and di > 0) or (y[self.VRA] <= vrmin and di < 0):
            di = 0.0
        dy[self.XI] = di
        vr_cmd = min(max(e.ka * vpid, vrmin), vrmax)
        dy[self.VRA] = (vr_cmd - y[self.VRA]) / e.ta
        vr = min(max(y[self.VRA], vrmin), vrmax)
        vfe = e.ke * ve + e.se(ve) * ve + e.kdx * ifd_ieee
        dve = (vr - vfe) / e.te
        if y[self.VE] <= 1e-6 and dve < 0:
            dve = 0.0
        dy[self.VE] = dve
        # ---- governor and engine
        if gv.ideal:
            dy[self.WR] = 0.0
        else:
            werr = self.wref - y[self.WR] - gv.droop * y[self.FA]
            dxg = gv.ki * werr
            fuel_lim = min(gv.fuel_max, gv.f_na + (gv.fuel_max - gv.f_na) * y[self.BST])
            u = gv.kp * werr + y[self.XG]
            if (u >= fuel_lim and dxg > 0) or (u <= 0 and dxg < 0):
                dxg = 0.0
            dy[self.XG] = dxg
            u = min(max(u, 0.0), fuel_lim)
            dy[self.FA] = (u - y[self.FA]) / gv.t_act
            dy[self.TM] = (y[self.FA] - y[self.TM]) / gv.t_eng
            dy[self.BST] = (y[self.TM] - y[self.BST]) / gv.t_boost
            dy[self.WR] = (y[self.TM] / y[self.WR] - te - gv.damping * (y[self.WR] - 1)) / (2 * self.g.h)
        # ---- motor
        if seg.motor_on and self.mo is not None:
            m = self.mo
            k = self.s_gen / m.s_kva
            im = (n["im"][0] * k, n["im"][1] * k)             # current in motor base
            ep = complex(y[self.EMD], y[self.EMQ])
            i_c = complex(im[0], im[1])
            wm = y[self.WM]
            s = (wr - wm) / wr
            t0p = (m.xm + m.xr) / (W0 * m.rr(s))
            dep = -(ep - 1j * wr * (m.x - m.xp) * i_c) / t0p - 1j * W0 * (wr - wm) * ep
            dy[self.EMD], dy[self.EMQ] = dep.real, dep.imag
            tem = (ep * i_c.conjugate()).real / wr
            dy[self.WM] = (tem - m.load_torque(wm)) / (2 * m.h)
        return dy

    # ---- outputs for logging
    def outputs(self, t: float, y: np.ndarray) -> dict:
        n = self.network(y, self.seg, None)
        c, e = self.c, self.e
        v, ig = n["v"], n["ig"]
        psi_ad = n["psi_ad"]
        ifd = (y[self.PSI_FD] - psi_ad) / c["lfd"]
        ifd_ieee = c["lad"] * ifd
        ve = max(y[self.VE], 1e-6)
        efd = e.k_rect * ve * fex(e.kc * max(ifd_ieee, 0) / ve)
        psi_aq = n["l_aqs"] * (-ig[1] + y[self.PSI_1Q] / c["l1q"])
        te = (-c["ll"] * ig[0] + psi_ad) * ig[1] - (-c["ll"] * ig[1] + psi_aq) * ig[0]
        vt = math.hypot(*v)
        out = dict(t=t, vt=vt, it=math.hypot(*ig), p=v[0] * ig[0] + v[1] * ig[1], q=v[1] * ig[0] - v[0] * ig[1],
                   ifd=ifd_ieee, efd=efd, ve=y[self.VE], vr=y[self.VRA], f=n["wr"] * 50.0, te=te,
                   tm=y[self.TM], ksd=n["ksd"])
        on = self.seg.motor_on and self.mo is not None
        out["wm"] = y[self.WM] if on else float("nan")
        out["im"] = math.hypot(*n["im"]) * self.s_gen / self.mo.s_kva if on else float("nan")
        return out

    # ---------------------------------------------------------- steady state
    def steady_state(self, p: float, q: float, vt: float = 1.0) -> np.ndarray:
        """Steady state with a static load P+jQ (pu, at vt) connected; sets vref and wref."""
        c, e, gv = self.c, self.e, self.gv
        # phasors in an arbitrary frame
        V = complex(vt, 0.0)
        I = complex(p, -q) / V.conjugate() if (p or q) else 0j
        eq_dir = V + complex(c["ra"], self.g.xq) * I
        delta = math.atan2(eq_dir.imag, eq_dir.real)
        rot = complex(math.cos(math.pi / 2 - delta), math.sin(math.pi / 2 - delta))
        vdq, idq = V * rot, I * rot
        vd, vq, i_d, i_q = vdq.real, vdq.imag, idq.real, idq.imag
        psi_ad = vq + c["ra"] * i_q + c["ll"] * i_d
        ksd = self.ksd(psi_ad)
        ifd = psi_ad / (c["lad"] * ksd) + i_d
        y = np.zeros(self.N)
        y[self.PSI_FD] = psi_ad + c["lfd"] * ifd
        y[self.PSI_1D] = psi_ad
        y[self.PSI_1Q] = -c["laq"] * i_q
        y[self.WR] = 1.0
        ifd_ieee = c["lad"] * ifd
        efd = ifd_ieee
        # exciter: EFD = VE * FEX(KC IFD / VE)
        f = lambda ve: e.k_rect * ve * fex(e.kc * ifd_ieee / ve) - efd
        ve = brentq(f, max(efd, 1e-3), 50.0)
        vr = e.ke * ve + e.se(ve) * ve + e.kdx * ifd_ieee
        supply = vt if e.supply == "shunt" else 1.0
        if vr > e.vrmax * supply:
            raise ValueError(f"steady state needs VR={vr:.2f} above the ceiling")
        y[self.VM] = vt
        y[self.XI] = vr / e.ka
        y[self.XD] = 0.0
        y[self.VRA] = vr
        y[self.VE] = ve
        pe = p + c["ra"] * (i_d ** 2 + i_q ** 2)
        y[self.FA] = y[self.TM] = y[self.BST] = pe
        y[self.XG] = pe
        self.vref = vt
        self.wref = 1.0 + gv.droop * pe
        self._ksd_last = ksd
        return y

    # ---------------------------------------------------------------- run
    def simulate(self, y0: np.ndarray, segments: list[Segment], t0: float = 0.0, dt_out: float = 0.002,
                 max_step: float = 0.004) -> dict:
        t, y = t0, y0.copy()
        rec: dict[str, list] = {}
        for seg in segments:
            self.seg = seg
            if seg.vref is not None:
                self.vref = seg.vref
            self._ksd_last = 1.0
            self._nfev = 0
            t_eval = np.linspace(t, seg.t_end, max(2, int(round((seg.t_end - t) / dt_out)) + 1))
            sol = solve_ivp(self.rhs, (t, seg.t_end), y, method="LSODA", t_eval=t_eval, max_step=max_step,
                            rtol=1e-5, atol=1e-7)
            if not sol.success:
                raise RuntimeError(sol.message)
            for k, tk in enumerate(sol.t):
                o = self.outputs(tk, sol.y[:, k])
                for key, val in o.items():
                    rec.setdefault(key, []).append(val)
            t, y = seg.t_end, sol.y[:, -1].copy()
        res = {k: np.asarray(v) for k, v in rec.items()}
        res["y_end"] = y
        return res
