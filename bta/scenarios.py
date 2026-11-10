"""Test scenarios (derived from ISO 8528-5 / ISO 8528-3 test types) and one-call runners."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .build import build, gen_params, load_plant
from .dynamics import GenParams, Segment
from .metrics import transient_metrics

T_EV = 0.5   # event time, s


@dataclass
class Config:
    """One design alternative = alternator parameters + excitation + governor settings."""
    name: str
    gen: GenParams
    exc: dict
    gov: dict
    s_gen_kva: float = 800.0


def avr_pole_cancel(tdo_p: float, te: float, tau_cl: float) -> dict:
    """PID by pole-zero cancellation: zeros at 1/T'do and 1/TE, closed loop ~ first order with tau_cl.

    PID(s) = KI (1 + s T1)(1 + s T2) / s, T1 = T'do, T2 = TE  ->  KP = KI (T1 + T2), KD = KI T1 T2.
    Open-circuit loop then reduces to KI / s (exciter KE = 1, unsaturated, small signal).
    """
    ki = 1.0 / tau_cl
    return {"kp": ki * (tdo_p + te), "ki": ki, "kd": ki * tdo_p * te}


def _gs(cfg: Config, motor_kva: float | None = None, ideal: bool = False, motor_over: dict | None = None):
    gov = dict(cfg.gov)
    gov["ideal"] = ideal
    return build(gen=cfg.gen, exc_over=cfg.exc, gov_over=gov, motor_kva=motor_kva, motor_over=motor_over,
                 s_gen_kva=cfg.s_gen_kva)


def oc_step(cfg: Config, step: float = 0.05, t_end: float = 4.0) -> dict:
    """Open-circuit set-point step (IEEE Std 421.2 style small-signal test): overshoot, rise and settling time."""
    gs = _gs(cfg, ideal=True)
    y0 = gs.steady_state(0, 0, vt=1.0 - step)
    r = gs.simulate(y0, [Segment(T_EV), Segment(T_EV + t_end, vref=1.0)], dt_out=0.002)
    t, u = r["t"] - T_EV, r["vt"]
    m = t >= 0
    t, u = t[m], u[m]
    u0, u1 = 1.0 - step, u[-1]
    over = (u.max() - u1) / step * 100
    def first(level):
        k = np.nonzero(u >= u0 + level * (u1 - u0))[0]
        return float(t[k[0]]) if len(k) else float("inf")
    rise = first(0.9) - first(0.1)
    out = np.abs(u - u1) > 0.02 * step
    settle = float(t[np.nonzero(out)[0][-1] + 1]) if out.any() and np.nonzero(out)[0][-1] + 1 < len(t) else 0.0
    return {"overshoot_pct": float(over), "rise_s": rise, "settle_s": settle, "trace": r}


def block_load(cfg: Config, p: float, q: float, ideal: bool = True, t_end: float = 8.0, p0: float = 0.0, q0: float = 0.0):
    gs = _gs(cfg, ideal=ideal)
    y0 = gs.steady_state(p0, q0)
    segs = [Segment(T_EV, p_load=p0, q_load=q0), Segment(T_EV + t_end, p_load=p0 + p, q_load=q0 + q)]
    r = gs.simulate(y0, segs, dt_out=0.002)
    return r


def load_rejection(cfg: Config, p: float, q: float, ideal: bool = True, t_end: float = 8.0):
    gs = _gs(cfg, ideal=ideal)
    y0 = gs.steady_state(p, q)
    r = gs.simulate(y0, [Segment(T_EV, p_load=p, q_load=q), Segment(T_EV + t_end)], dt_out=0.002)
    return r


def motor_start(cfg: Config, motor_kw: float, ideal: bool = True, t_end: float = 10.0, p0: float = 0.0, q0: float = 0.0,
                motor_over: dict | None = None):
    pl = load_plant()["motor"]
    kva = motor_kw / (pl["pf_rated"] * pl["eff_rated"])
    gs = _gs(cfg, motor_kva=kva, ideal=ideal, motor_over=motor_over)
    y0 = gs.steady_state(p0, q0)
    segs = [Segment(T_EV, p_load=p0, q_load=q0), Segment(T_EV + t_end, p_load=p0, q_load=q0, motor_on=True)]
    r = gs.simulate(y0, segs, dt_out=0.002)
    r["motor_kva"] = kva
    return r


def short_circuit(cfg: Config, t_fault: float = 1.0, ideal: bool = True, p0: float = 0.0, q0: float = 0.0):
    """Bolted three-phase short at the terminals for t_fault seconds; returns the RMS current envelope."""
    gs = _gs(cfg, ideal=ideal)
    y0 = gs.steady_state(p0, q0)
    r = gs.simulate(y0, [Segment(T_EV, p_load=p0, q_load=q0),
                         Segment(T_EV + t_fault, p_load=p0, q_load=q0, fault_z=complex(0.0, 1e-3))], dt_out=0.002)
    return r


def metrics(r: dict, lim: dict) -> dict:
    return transient_metrics(r, T_EV, du_band_pct=lim["du_band_pct"], df_band_pct=lim["df_band_pct"])


def max_motor_kw(cfg: Config, dip_limit_pct: float, lo: float = 20.0, hi: float = 600.0, ideal: bool = True,
                 tol: float = 5.0) -> float:
    """Largest DOL motor (kW) whose start keeps the voltage dip within dip_limit_pct (negative number)."""
    def ok(kw):
        try:
            r = motor_start(cfg, kw, ideal=ideal, t_end=6.0)
        except Exception:
            return False
        m = transient_metrics(r, T_EV)
        stalled = np.nanmin(r["wm"][-50:]) < 0.9
        return m["du_dyn_minus_pct"] >= dip_limit_pct and not stalled
    if not ok(lo):
        return 0.0
    if ok(hi):
        return hi
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo
