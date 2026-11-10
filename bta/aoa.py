"""Analysis of alternatives (Wasson ch. 32, normalized weighted-sum method with sensitivity analysis)."""
from __future__ import annotations

import copy
import itertools
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml

from .build import gen_params, load_plant
from .design import load_machine
from .dynamics import GenParams
from .scenarios import (Config, avr_pole_cancel, block_load, load_rejection, max_motor_kw, metrics, motor_start, oc_step,
                        short_circuit, T_EV)

ROOT = Path(__file__).resolve().parents[1]

# OC set-point step acceptance used as the tuning constraint (IEEE 421.2 small-signal performance indices;
# 10 % overshoot is the study's own design rule [A], not a standard limit).
OC_OVERSHOOT_MAX = 10.0
BASE_TAU = 0.10          # baseline: textbook pole-cancellation PID with 0.1 s closed-loop time constant


def load_alternatives() -> dict:
    with open(ROOT / "config" / "alternatives.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def machine_for(key: str, alts: dict) -> tuple[dict, float, float]:
    """Machine dict, kVA ratio (own base -> 800 kVA base) and extra inertia."""
    m = load_machine()
    if key == "base":
        return m, 1.0, 0.0
    ov = alts["machines"][key]
    m = copy.deepcopy(m)
    for sect in ("rating", "stator", "rotor"):
        m[sect].update(ov.get(sect, {}))
    return m, 800.0 / m["rating"]["s_kva"], ov.get("h_extra_s", 0.0)


def gen_for(key: str, alts: dict, source: str = "analytic", gen_override: GenParams | None = None) -> GenParams:
    if gen_override is not None and key == "base":
        return gen_override
    m, k, dh = machine_for(key, alts)
    g, _ = gen_params(source if key == "base" else "analytic", m)
    if source == "femm" and key != "base":
        # same design method, so the FEMM/analytic correction of the base design is carried over (calibration)
        gf, _ = gen_params("femm")
        ga, _ = gen_params("analytic")
        names = ("xd", "xq", "xl", "xdp", "xdpp", "xqpp", "tdo_p", "tdo_pp", "tqo_pp")
        g = replace(g, **{n: getattr(g, n) * getattr(gf, n) / getattr(ga, n) for n in names})
    return replace(g, xd=g.xd * k, xq=g.xq * k, xl=g.xl * k, xdp=g.xdp * k, xdpp=g.xdpp * k, xqpp=g.xqpp * k,
                   ra=g.ra * k, h=g.h + dh)


def base_exc(over: dict) -> dict:
    pl = load_plant()
    e = {k: v for k, v in pl["excitation"].items() if k != "model"}
    e.update(over)
    return e


def tune(gen: GenParams, exc: dict, gov: dict, lim: dict, coarse: bool = False) -> tuple[dict, dict]:
    """Retune KP/KI/KD for the shortest recovery after the 100 % block load, subject to OC overshoot <= 10 %.

    Grid search (deterministic and auditable) over KP, KI, KD; TD fixed. Returns the best gains and a log.
    """
    kps = [15, 30, 50] if not coarse else [15, 30]      # coarse keeps KP = 15: the larger exciter (A2) needs it for DR-03
    kis = [15, 30, 60, 90] if not coarse else [30, 60]
    kds = [2.0, 8.0, 15.0] if not coarse else [8.0]
    best, log = None, []
    for kp, ki, kd in itertools.product(kps, kis, kds):
        e = dict(exc, kp=kp, ki=ki, kd=kd)
        cfg = Config("tune", gen, e, gov)
        try:
            s = oc_step(cfg)
            if s["overshoot_pct"] > OC_OVERSHOOT_MAX:
                log.append(dict(kp=kp, ki=ki, kd=kd, over=s["overshoot_pct"], ok=False))
                continue
            m = metrics(block_load(cfg, 0.8, 0.6), lim)
        except Exception as ex:      # numerical failure = reject
            log.append(dict(kp=kp, ki=ki, kd=kd, err=str(ex), ok=False))
            continue
        score = m["t_u_s"] + 0.05 * abs(m["du_dyn_minus_pct"])
        log.append(dict(kp=kp, ki=ki, kd=kd, over=s["overshoot_pct"], t_u=m["t_u_s"], dip=m["du_dyn_minus_pct"], ok=True))
        if best is None or score < best[0]:
            best = (score, dict(kp=kp, ki=ki, kd=kd))
    if best is None:
        raise ValueError(f"no gain set in the grid meets the {OC_OVERSHOOT_MAX} % open-circuit overshoot rule (DR-03)")
    return best[1], {"grid": log}


def evaluate(cfg: Config, lim: dict, motor_kw: float = 132.0, quick: bool = False) -> dict:
    out = {"exc": {k: cfg.exc[k] for k in ("supply", "kp", "ki", "kd", "vrmax", "te", "kc")}}
    s = oc_step(cfg)
    out["oc_step"] = {k: s[k] for k in ("overshoot_pct", "rise_s", "settle_s")}
    out["bl100"] = metrics(block_load(cfg, 0.8, 0.6), lim)
    out["lr100"] = metrics(load_rejection(cfg, 0.8, 0.6), lim)
    rm = motor_start(cfg, motor_kw)
    mm = metrics(rm, lim)
    mm["motor_kva"] = rm["motor_kva"]
    mm["start_time_s"] = float(rm["t"][np.nanargmax(rm["wm"] > 0.95)] - T_EV) if np.nanmax(rm["wm"]) > 0.95 else float("inf")
    out["motor"] = mm
    sc = short_circuit(cfg, t_fault=10.0 if not quick else 3.0)
    t, i = sc["t"], sc["it"]
    out["sc"] = {"i_peak_rms_pu": float(i[t > T_EV].max()),
                 "i_at_1s_pu": float(np.interp(T_EV + 1.0, t, i)),
                 "i_end_pu": float(i[-1]),
                 "t_end_s": float(t[-1] - T_EV)}
    if not quick:
        out["max_motor_kw_20pct"] = max_motor_kw(cfg, lim["du_motor_start_pct"])
        out["max_motor_kw_15pct"] = max_motor_kw(cfg, lim["du_dyn_minus_pct"])
        # generating-set level (engine model active): 100 % step is beyond turbo-engine acceptance; use 50 %
        gs = metrics(block_load(cfg, 0.4, 0.3, ideal=False), lim)
        out["genset_bl50"] = gs
    return out


def run_all(source: str = "analytic", quick: bool = False, gen_override: GenParams | None = None,
            keys: list[str] | None = None) -> dict:
    alts = load_alternatives()
    pl = load_plant()
    lim, gov = pl["limits"], pl["governor"]
    res = {}
    for key in keys or [k for k in alts if k.startswith("A")]:
        a = alts[key]
        gen = gen_for(a["machine"], alts, source, gen_override)
        exc = base_exc(a["exc"])
        exc.update(avr_pole_cancel(gen.tdo_p, exc["te"], BASE_TAU))
        tune_log = None
        if a["tune"]:
            gains, tune_log = tune(gen, exc, gov, lim, coarse=quick)
            exc.update(gains)
        cfg = Config(key, gen, exc, gov)
        r = evaluate(cfg, lim, quick=quick)
        r["name"] = a["name"]
        r["gen"] = {k: getattr(gen, k) for k in ("xd", "xq", "xl", "xdp", "xdpp", "xqpp", "tdo_p", "tdo_pp", "tqo_pp", "ra", "h")}
        if tune_log:
            r["tune_grid"] = tune_log["grid"]
        res[key] = r
        print(f"  {key} done: dip {r['bl100']['du_dyn_minus_pct']:.2f} % tU {r['bl100']['t_u_s']:.2f} s "
              f"gains {r['exc']['kp']}/{r['exc']['ki']}/{r['exc']['kd']}", flush=True)
    return res


# --------------------------------------------------------------------------- scoring
CRITERIA = {
    # factor: (weight points, {criterion: (sub-weight, value-getter, better)})
    "performance": (50, {
        "bl_dip": (15, lambda r: r["bl100"]["du_dyn_minus_pct"], "high"),
        "bl_recovery": (10, lambda r: r["bl100"]["t_u_s"], "low"),
        "motor_capability": (15, lambda r: r.get("max_motor_kw_20pct", 0.0), "high"),
        "sustained_sc": (10, lambda r: r["sc"]["i_at_1s_pu"], "high"),
    }),
    "cost": (25, {"cost_index": (25, lambda r: r["cost"], "low")}),
    "risk": (15, {"risk_score": (15, lambda r: r["risk"], "high")}),
    "integration": (10, {"integration_score": (10, lambda r: r["integration"], "high")}),
}


def utilities(res: dict) -> dict:
    """Linear utility 0..1 between the worst and best alternative for each criterion."""
    keys = list(res)
    u = {k: {} for k in keys}
    for fac, (_, crits) in CRITERIA.items():
        for name, (_, get, better) in crits.items():
            vals = np.array([get(res[k]) for k in keys], float)
            vals = np.where(np.isfinite(vals), vals, np.nanmax(vals[np.isfinite(vals)]) * 2 if better == "low" else 0)
            lo, hi = vals.min(), vals.max()
            for k, v in zip(keys, vals):
                x = 0.5 if hi == lo else (v - lo) / (hi - lo)
                u[k][name] = float(x if better == "high" else 1 - x)
    return u


def scores(res: dict, weights: dict | None = None) -> dict:
    u = utilities(res)
    out = {}
    for k in res:
        tot = 0.0
        for fac, (fw, crits) in CRITERIA.items():
            sw_sum = sum(c[0] for c in crits.values())
            for name, (sw, _, _) in crits.items():
                w = (weights or {}).get(name, fw * sw / sw_sum)
                tot += w * u[k][name]
        out[k] = tot
    return out


def gates(r: dict, lim: dict) -> dict:
    """Mandatory requirements (pass/fail) used before scoring: an alternative that fails a 'shall' is not eligible."""
    return {
        "SR-01 dip": r["bl100"]["du_dyn_minus_pct"] >= lim["du_dyn_minus_pct"],
        "SR-02 recovery": r["bl100"]["t_u_s"] <= lim["t_u_rec_s"],
        "SR-03 rise": r["lr100"]["du_dyn_plus_pct"] <= lim["du_dyn_plus_pct"],
        "SR-04 rejection recovery": r["lr100"]["t_u_s"] <= lim["t_u_rec_s"],
        "SR-05 motor 132 kW": r["motor"]["du_dyn_minus_pct"] >= lim["du_motor_start_pct"],
        "SR-06 sustained SC": r["sc"]["i_at_1s_pu"] >= lim["i_sc_sustained_pu"],
    }


def weight_sensitivity(res: dict, n: int = 5000, spread: float = 0.5, seed: int = 1) -> dict:
    """Monte Carlo on the criterion weights: each weight scaled by U(1-spread, 1+spread), renormalised to 100."""
    rng = np.random.default_rng(seed)
    base = {}
    for fac, (fw, crits) in CRITERIA.items():
        ssum = sum(c[0] for c in crits.values())
        for name, (sw, _, _) in crits.items():
            base[name] = fw * sw / ssum
    names = list(base)
    wins = {k: 0 for k in res}
    for _ in range(n):
        w = np.array([base[x] for x in names]) * rng.uniform(1 - spread, 1 + spread, len(names))
        w = w / w.sum() * 100
        s = scores(res, dict(zip(names, w)))
        wins[max(s, key=s.get)] += 1
    return {k: v / n for k, v in wins.items()}
