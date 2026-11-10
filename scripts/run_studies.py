"""Dip budget (DOSSIER §6.2), parameter sensitivity (§8.4), diode-fault FMEA quantification (§9).

Reads the tuned gains from results/aoa_<source>.json and writes results/studies_<source>.json.
"""
import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

from bta.aoa import base_exc, gen_for, load_alternatives
from bta.build import load_plant
from bta.dynamics import GenParams
from bta.rectifier import RectParams, signature, simulate
from bta.scenarios import Config, block_load, metrics, motor_start, T_EV

ROOT = Path(__file__).resolve().parents[1]

# Public data-sheet-class machine: midpoints of three public LV data sheets 310-1150 kVA (ref [S7],
# docs/sources_datasheets.md): Xd 2.44-2.94, Xq 1.90-2.48, X'd 0.146-0.19, X''d 0.11-0.13, X''q 0.24-0.37,
# T'do 1.7-4.09 s, T''d 0.012-0.019 s. Xl and T''qo are not on the sheets [A].
DS_CLASS = dict(xd=2.7, xq=2.2, xl=0.08, xdp=0.17, xdpp=0.12, xqpp=0.29, tdo_p=2.8, tdo_pp=0.016 * 0.17 / 0.12,
                tqo_pp=0.05, ra=0.01)


def cfg_of(key, aoa, alts, gen=None, exc_over=None):
    a = alts[key]
    g = gen or gen_for(a["machine"], alts, aoa["source"])
    exc = base_exc(a["exc"])
    exc.update({k: aoa["results"][key]["exc"][k] for k in ("kp", "ki", "kd")})
    exc.update(exc_over or {})
    return Config(key, g, exc, load_plant()["governor"])


def run_metrics(cfg, lim, motor_kw=132.0):
    bl = metrics(block_load(cfg, 0.8, 0.6), lim)
    ms = metrics(motor_start(cfg, motor_kw, t_end=6.0), lim)
    return {"bl_dip": bl["du_dyn_minus_pct"], "bl_tu": bl["t_u_s"], "ms_dip": ms["du_dyn_minus_pct"]}


def dip_budget(cfg, lim):
    """Split the SR-01 dip into causes by switching parts of the model to ideal."""
    out = {}
    r = block_load(cfg, 0.8, 0.6, t_end=2.0)
    t, v = r["t"], r["vt"]
    out["v_0plus"] = float(v[np.searchsorted(t, T_EV + 1e-4)])
    out["actual_min"] = float(v[t > T_EV].min())
    frozen = replace(cfg, exc=dict(cfg.exc, kp=0.0, ki=0.0, kd=0.0))
    rf = block_load(frozen, 0.8, 0.6, t_end=2.0)
    out["frozen_min_2s"] = float(rf["vt"][rf["t"] > T_EV].min())
    ideal = replace(cfg, exc=dict(cfg.exc, supply="pmg", vrmax=500.0, te=0.005, kc=0.0, kdx=0.0, tr=0.001,
                                  kp=400.0, ki=400.0, kd=0.0))
    ri = block_load(ideal, 0.8, 0.6, t_end=2.0)
    out["ideal_exc_min"] = float(ri["vt"][ri["t"] > T_EV].min())
    # engine speed contribution at a step the engine can take (50 %), gen set vs constant speed
    g50 = metrics(block_load(cfg, 0.4, 0.3, ideal=False), lim)
    c50 = metrics(block_load(cfg, 0.4, 0.3, ideal=True), lim)
    out["dip50_genset"] = g50["du_dyn_minus_pct"]
    out["dip50_const_speed"] = c50["du_dyn_minus_pct"]
    out["df50_genset"] = g50["df_dyn_minus_pct"]
    out["tf50_genset"] = g50["t_f_s"]
    # budget lines in percent of rated voltage
    out["budget"] = {
        "reactance_step_pct": (1 - out["v_0plus"]) * 100,
        "flux_decay_unavoidable_pct": (out["v_0plus"] - out["ideal_exc_min"]) * 100,
        "excitation_limitation_pct": (out["ideal_exc_min"] - out["actual_min"]) * 100,
        "total_dip_pct": (1 - out["actual_min"]) * 100,
        "margin_to_limit_pct": -lim["du_dyn_minus_pct"] - (1 - out["actual_min"]) * 100,
        "engine_speed_extra_at_50pct_step_pct": out["dip50_const_speed"] - out["dip50_genset"],
    }
    return out


def sensitivity(cfg, lim):
    base = run_metrics(cfg, lim)
    g = cfg.gen
    cases = {
        "H 0.5/1.2 s (gen set)": ("gen", "h", 0.5, 1.2),
        "X'd -/+20 %": ("genk", "xdp", 0.8, 1.2),
        "X''d -/+20 %": ("genk", "xdpp", 0.8, 1.2),
        "T'do -/+20 %": ("genk", "tdo_p", 0.8, 1.2),
        # FEMM end rings are ideal; real ring resistance only shortens the damper time constants (lo = half)
        "T''do, T''qo x0.5/x1 (end-ring R)": ("genks", ("tdo_pp", "tqo_pp"), 0.5, 1.0),
        "Exciter TE 0.15/0.40 s": ("exc", "te", 0.15, 0.40),
        "Rectifier KC 0.08/0.25": ("exc", "kc", 0.08, 0.25),
        "Ceiling VRMAX 10/18": ("exc", "vrmax", 10.0, 18.0),
        "Sensing TR 5/30 ms": ("exc", "tr", 0.005, 0.03),
    }
    out = {"base": base, "cases": {}}
    for name, (kind, key, lo, hi) in cases.items():
        row = {}
        for tag, val in (("lo", lo), ("hi", hi)):
            if kind == "gen":
                c = replace(cfg, gen=replace(g, **{key: val}))
            elif kind == "genk":
                kw = {key: getattr(g, key) * val}
                if key == "xdp" and kw[key] <= g.xdpp:
                    kw[key] = g.xdpp * 1.05
                if key == "xdpp" and kw[key] >= g.xdp:
                    kw[key] = g.xdp * 0.95
                c = replace(cfg, gen=replace(g, **kw))
            elif kind == "genks":
                c = replace(cfg, gen=replace(g, **{k_: getattr(g, k_) * val for k_ in key}))
            else:
                c = replace(cfg, exc=dict(cfg.exc, **{key: val}))
            row[tag] = run_metrics(c, lim)
        out["cases"][name] = row
    # motor deep-bar resistance (motor model, affects starting PF)
    row = {}
    for tag, val in (("lo", 0.035), ("hi", 0.07)):
        bl = metrics(block_load(cfg, 0.8, 0.6), lim)
        ms = metrics(motor_start(cfg, 132.0, t_end=6.0, motor_over={"rr_lr": val}), lim)
        row[tag] = {"bl_dip": bl["du_dyn_minus_pct"], "bl_tu": bl["t_u_s"], "ms_dip": ms["du_dyn_minus_pct"]}
    out["cases"]["Motor Rr locked 0.035/0.070"] = row
    return out


def xd_sweep(cfgs: dict, lim, xdp_values=None):
    """SR-01 dip and SR-05 motor dip versus X'd (X''d/X'd and X'd/T'd ratios kept), per excitation option.

    Gives the derived requirement DR-01: the largest X'd that still meets the limits with each excitation.
    """
    xdp_values = xdp_values or [0.14, 0.17, 0.20, 0.23, 0.26, 0.29, 0.32]
    out = {}
    for name, cfg in cfgs.items():
        g = cfg.gen
        rows = []
        for x in xdp_values:
            k = x / g.xdp
            gg = replace(g, xdp=x, xdpp=g.xdpp * k, xqpp=g.xqpp * k, xl=min(g.xl, 0.9 * g.xdpp * k))
            rows.append({"xdp": x, **run_metrics(replace(cfg, gen=gg), lim)})
        def cross(key, limv):
            xs = [r["xdp"] for r in rows]
            ys = [r[key] for r in rows]
            for j in range(1, len(xs)):
                if (ys[j - 1] - limv) * (ys[j] - limv) <= 0:
                    return xs[j - 1] + (limv - ys[j - 1]) * (xs[j] - xs[j - 1]) / (ys[j] - ys[j - 1])
            return None
        out[name] = {"rows": rows, "xdp_max_sr01": cross("bl_dip", lim["du_dyn_minus_pct"]),
                     "xdp_max_sr05": cross("ms_dip", lim["du_motor_start_pct"])}
    return out


def diode_fmea(cfg, lim):
    p = RectParams()
    res = {}
    for fault in ("none", "open", "short"):
        sig = signature(simulate(p, fault, periods=30, steps_per_period=1500), 20)
        res[fault] = sig
    h = res["none"]["v_dc_mean"]
    for fault in ("open", "short"):
        k = res[fault]["v_dc_mean"] / h
        c = replace(cfg, exc=dict(cfg.exc, k_rect=k))
        try:
            m = run_metrics(c, lim)
        except Exception as ex:    # e.g. steady state no longer reachable below the ceiling
            m = {"error": str(ex)}
        res[fault]["k_rect"] = k
        res[fault]["g3_effect"] = m
        res[fault]["arm_current_ratio"] = max(res[fault]["i_phase_rms"]) / max(res["none"]["i_phase_rms"])
    res["none"]["g3_effect"] = run_metrics(cfg, lim)
    return res


if __name__ == "__main__":
    src = "femm" if "--femm" in sys.argv else "analytic"
    aoa = json.loads((ROOT / "results" / f"aoa_{src}.json").read_text())
    alts = load_alternatives()
    lim = load_plant()["limits"]
    out = {"source": src, "budget": {}}
    for key in aoa["results"]:
        out["budget"][key] = dip_budget(cfg_of(key, aoa, alts), lim)
        print("budget", key, {k: round(v, 2) for k, v in out["budget"][key]["budget"].items()}, flush=True)
    a1 = cfg_of("A1", aoa, alts)
    out["sensitivity_A1"] = sensitivity(a1, lim)
    print("sensitivity done", flush=True)
    # data-sheet-class machine with the A1 excitation, retuned gains kept: robustness of the conclusion
    occ = a1.gen
    ds = GenParams(h=occ.h, occ_e=occ.occ_e, occ_ifd=occ.occ_ifd, **DS_CLASS)
    out["ds_class"] = {"params": DS_CLASS, "A1_exc": run_metrics(replace(a1, gen=ds), lim),
                       "A3_exc": run_metrics(replace(cfg_of("A3", aoa, alts), gen=ds), lim)}
    print("ds-class", out["ds_class"], flush=True)
    out["xd_sweep"] = xd_sweep({"A1 shunt": a1, "A3 PMG": cfg_of("A3", aoa, alts)}, lim)
    print("xd sweep", {k: (v["xdp_max_sr01"], v["xdp_max_sr05"]) for k, v in out["xd_sweep"].items()}, flush=True)
    out["diode"] = diode_fmea(a1, lim)
    print("diode", {k: (v["v_dc_mean"], v.get("k_rect"), v["g3_effect"]) for k, v in out["diode"].items()}, flush=True)
    (ROOT / "results" / f"studies_{src}.json").write_text(json.dumps(out, indent=1, default=float))
