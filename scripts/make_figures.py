"""All dossier figures (PNG, docs/img). Every trace is re-simulated from the saved tuned gains, nothing is drawn by hand."""
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

from bta.aoa import load_alternatives  # noqa: E402
from bta.build import load_plant  # noqa: E402
from bta.design import Design, load_machine  # noqa: E402
from bta.geometry import build_section  # noqa: E402
from bta.rectifier import RectParams, mmf_stator_frame, simulate, spectrum  # noqa: E402
from bta.scenarios import T_EV, block_load, motor_start, short_circuit  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_studies import cfg_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "docs" / "img"
IMG.mkdir(parents=True, exist_ok=True)
# categorical order (validated reference palette, fixed order, never cycled)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
                     "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.6,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "legend.frameon": False})


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=150)
    plt.close(fig)
    print("wrote", name)


def fig_section():
    m = load_machine()
    sec = build_section(m)
    fig, ax = plt.subplots(figsize=(6.2, 6.2))
    col = {"steel": "#b7bec7", "copper": "#d9822b", "air": "#fcfcfb"}
    a = np.linspace(-math.pi / 4, math.pi / 4, 200)
    ring = np.concatenate([np.c_[sec.r_out * np.cos(a), sec.r_out * np.sin(a)],
                           np.c_[sec.r_bore * np.cos(a[::-1]), sec.r_bore * np.sin(a[::-1])]])
    ax.add_patch(Polygon(ring, fc=col["steel"], ec=INK2, lw=0.4))
    for r in sec.regions:
        if r.material == "air":
            ax.add_patch(Polygon(r.poly, fc=col["air"], ec=INK2, lw=0.3))
    hub = [r for r in sec.regions if r.name == "hub"][0]
    pole = [r for r in sec.regions if r.name == "pole"][0]
    ax.add_patch(Polygon(hub.poly, fc=col["steel"], ec=INK2, lw=0.4))
    ax.add_patch(Polygon(pole.poly, fc=col["steel"], ec=INK2, lw=0.4))
    for r in sec.regions:
        if r.material == "copper":
            ax.add_patch(Polygon(r.poly, fc=col["copper"], ec=INK2, lw=0.3))
            if r.circuit in "ABC" and r.circuit and r.name.endswith("_top"):
                cx, cy = np.mean(np.array(r.poly), axis=0)
                ax.text(cx * 1.0, cy, f"{'+' if r.turns > 0 else '−'}{r.circuit}", fontsize=6, ha="center", va="center", color=INK)
    ax.set_aspect("equal")
    ax.set_xlim(0, sec.r_out * 1.02)
    ax.set_ylim(-sec.r_out * 0.75, sec.r_out * 0.75)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.grid(False)
    ax.set_title(f"One pole pitch of the reference machine (4 poles, 48 slots, 2/3 pitch, "
                 f"{m['rotor']['damper']['bars_per_pole']} damper bars)", fontsize=9)
    save(fig, "cross_section.png")


def fig_occ(params_femm=None):
    d = Design(load_machine())
    o = d.run()
    e = np.linspace(0.05, 1.3, 40)
    i = d.occ(e) / o["if_airgap"]
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    ax.plot(i, e, color=C[0], label="Analytic magnetic circuit")
    ax.plot([0, 1.3], [0, 1.3], color=INK2, lw=1, ls="--", label="Air-gap line")
    if params_femm:
        ax.plot(params_femm["occ_ifd_pu"], params_femm["occ_e"], "o", color=C[1], ms=5, label="FEMM 2-D")
    ax.set_xlabel("Field current, pu of air-gap-line value at 1 pu")
    ax.set_ylabel("Open-circuit voltage, pu")
    ax.legend()
    ax.set_title("Open-circuit characteristic", fontsize=9)
    save(fig, "occ.png")


def fig_bl(aoa, alts, lim):
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    for j, key in enumerate(aoa["results"]):
        r = block_load(cfg_of(key, aoa, alts), 0.8, 0.6, t_end=5.0)
        ax.plot(r["t"] - T_EV, r["vt"] * 100, color=C[j], label=f"{key} {aoa['results'][key]['name']}")
    ax.axhline(100 + lim["du_dyn_minus_pct"], color="#e34948", lw=1, ls="--")
    ax.text(0.35, 100 + lim["du_dyn_minus_pct"] - 1.0, "G3 dip limit −15 %", ha="left", fontsize=8, color=INK2)
    ax.axhspan(99, 101, color="#1baf7a", alpha=0.10, lw=0)
    ax.axvline(lim["t_u_rec_s"], color=INK2, lw=0.8, ls=":")
    ax.text(lim["t_u_rec_s"] + 0.05, 101.5, "t_U limit 4 s", fontsize=8, color=INK2)
    ax.set_xlim(-0.2, 5.0)
    ax.set_xlabel("Time after load application (s)")
    ax.set_ylabel("Terminal voltage (% of rated)")
    ax.set_title("SR-01/02: 0→100 % rated kVA at 0.8 PF, constant speed", fontsize=9)
    ax.legend(fontsize=7, loc="lower right", bbox_to_anchor=(1.0, 0.07), frameon=True, facecolor="#fcfcfb", edgecolor="none", framealpha=1)     # above the dip-limit line
    save(fig, "block_load.png")


def fig_motor(aoa, alts, lim):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True)
    for j, key in enumerate(aoa["results"]):
        if key not in ("A1", "A3", "A4"):
            continue
        r = motor_start(cfg_of(key, aoa, alts), 132.0, t_end=4.0)
        jj = list(aoa["results"]).index(key)
        a1.plot(r["t"] - T_EV, r["vt"] * 100, color=C[jj], label=f"{key} {aoa['results'][key]['name']}")
        a2.plot(r["t"] - T_EV, r["wm"], color=C[jj])
    a1.axhline(100 + lim["du_motor_start_pct"], color="#e34948", lw=1, ls="--")
    a1.text(1.0, 100 + lim["du_motor_start_pct"] + 0.8, "practice limit −20 %", ha="left", fontsize=8, color=INK2)
    a1.set_ylabel("Voltage (%)")
    a1.legend(fontsize=7, loc="lower right", bbox_to_anchor=(1.0, 0.15))    # above the limit line
    a2.set_ylabel("Motor speed (pu)")
    a2.set_xlabel("Time after DOL start of 132 kW pump motor (s)")
    a1.set_title("SR-05: direct-on-line motor start", fontsize=9)
    save(fig, "motor_start.png")


def fig_sc(aoa, alts):
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for key in ("A1", "A3"):
        r = short_circuit(cfg_of(key, aoa, alts), t_fault=3.0)
        jj = list(aoa["results"]).index(key)
        ax.plot(r["t"] - T_EV, r["it"], color=C[jj], label=f"{key} {aoa['results'][key]['name']}")
    ax.axhline(3.0, color=INK2, ls="--", lw=1)
    ax.text(2.9, 3.1, "SR-06: 3 pu at 1 s", ha="right", fontsize=8, color=INK2)
    ax.set_xlabel("Time after bolted 3-phase terminal fault (s)")
    ax.set_ylabel("RMS stator current (pu)")
    ax.set_title("Fault current: shunt supply collapses, PMG sustains", fontsize=9)
    ax.legend(fontsize=7)
    save(fig, "short_circuit.png")


def fig_budget(st, lim):
    keys = list(st["budget"])
    parts = [("reactance_step_pct", "Reactance step at t=0⁺ (X''d, X'd)"),
             ("flux_decay_unavoidable_pct", "Flux decay even with ideal excitation"),
             ("excitation_limitation_pct", "Real excitation (ceiling, TE, KC, AVR)")]
    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    x = np.arange(len(keys))
    bottom = np.zeros(len(keys))
    for j, (k, lab) in enumerate(parts):
        v = np.array([st["budget"][kk]["budget"][k] for kk in keys])
        ax.bar(x, v, 0.6, bottom=bottom, color=C[j], label=lab, edgecolor="#fcfcfb", linewidth=1.5)
        bottom += v
    ax.axhline(-lim["du_dyn_minus_pct"], color="#e34948", ls="--", lw=1)
    ax.text(-0.45, -lim["du_dyn_minus_pct"] + 0.9, "G3 limit 15 %", ha="left", fontsize=8, color=INK2)
    for xi, b in zip(x, bottom):
        ax.text(xi, b + 0.2, f"{b:.1f}", ha="center", fontsize=8, color=INK)
    ax.set_xticks(x, keys)
    ax.set_ylabel("Voltage dip (% of rated)")
    ax.set_title("§6.2 dip budget for SR-01, by cause", fontsize=9)
    ax.set_ylim(0, 19)
    ax.legend(fontsize=7, loc="upper right", ncol=1)
    save(fig, "dip_budget.png")


def fig_aoa(aoa):
    from bta.aoa import CRITERIA, utilities
    res = aoa["results"]
    keys = list(res)
    u = utilities(res)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.8), gridspec_kw={"width_ratios": [3, 2]})
    x = np.arange(len(keys))
    bottom = np.zeros(len(keys))
    for j, (fac, (fw, crits)) in enumerate(CRITERIA.items()):
        ssum = sum(c[0] for c in crits.values())
        v = np.array([sum(fw * sw / ssum * u[k][n] for n, (sw, _, _) in crits.items()) for k in keys])
        a1.bar(x, v, 0.6, bottom=bottom, color=C[j], label=f"{fac} ({fw})", edgecolor="#fcfcfb", linewidth=1.5)
        bottom += v
    for xi, k in zip(x, keys):
        ok = all(res[k]["gates"].values())
        a1.text(xi, bottom[xi] + 1, f"{bottom[xi]:.0f}" + ("" if ok else "\nfails a shall"), ha="center", fontsize=7, color=INK)
    a1.set_xticks(x, keys)
    a1.set_ylabel("Weighted score (of 100)")
    a1.set_title("Normalized weighted-sum scores", fontsize=9)
    a1.set_ylim(0, 95)
    a1.legend(fontsize=7, loc="upper left", ncol=2)
    ws = aoa["weight_sensitivity_win_share"]
    a2.barh(keys[::-1], [ws[k] * 100 for k in keys[::-1]], color=C[0])
    a2.set_xlabel("Share of 5000 weight sets won (%)")
    a2.set_title("Weight sensitivity (±50 %)", fontsize=9)
    save(fig, "aoa_scores.png")


def fig_tornado(st):
    s = st["sensitivity_A1"]
    base = s["base"]["bl_dip"]
    rows = []
    for name, c in s["cases"].items():
        if name.startswith("H "):        # inertia has no effect at constant speed (by construction); see the budget
            continue
        rows.append((name, c["lo"]["bl_dip"] - base, c["hi"]["bl_dip"] - base))
    rows.sort(key=lambda r: max(abs(r[1]), abs(r[2])))
    fig, ax = plt.subplots(figsize=(7.0, 3.8))
    y = np.arange(len(rows))
    ax.barh(y, [r[1] for r in rows], color=C[0], label="low value", height=0.6)
    ax.barh(y, [r[2] for r in rows], color=C[1], label="high value", height=0.6)
    ax.set_yticks(y, [r[0] for r in rows], fontsize=7)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_xlabel(f"Change of SR-01 dip, percentage points (A1 base {base:.1f} %; + = shallower)")
    ax.set_title("Sensitivity of the block-load dip to the [A] parameters", fontsize=9)
    ax.legend(fontsize=7)
    save(fig, "tornado.png")


def fig_diode():
    p = RectParams()
    fig, axs = plt.subplots(2, 3, figsize=(9.0, 4.8))
    for j, fault in enumerate(("none", "open", "short")):
        r = simulate(p, fault, periods=30, steps_per_period=1500)
        n = int(3 / (p.f_ex * r["h"]))
        t = (r["t"][-n:] - r["t"][-n]) * 1e3
        for k in range(3):
            axs[0, j].plot(t, r["i_ph"][-n:, k], color=C[k], lw=1.0, label=f"phase {'abc'[k]}")
        axs[0, j].set_title({"none": "Healthy bridge", "open": "One diode open", "short": "One diode shorted"}[fault], fontsize=9)
        axs[0, j].set_xlabel("ms")
        f, a = spectrum(mmf_stator_frame(r).real, r["h"], 20, p.f_ex)
        m = f <= 7.5 * p.f_ex
        axs[1, j].bar(f[m] / p.f_ex, a[m], width=0.12, color=C[0])
        axs[1, j].set_xlabel("Frequency / f_ex (field frame)")
    axs[0, 0].set_ylabel("Exciter armature current (A)")
    axs[1, 0].set_ylabel("Armature MMF, d-axis (A)")
    axs[0, 0].legend(fontsize=6)
    save(fig, "diode_signature.png")


def fig_xd(st, lim):
    sw = st["xd_sweep"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.6), sharex=True)
    for j, (name, v) in enumerate(sw.items()):
        x = [r["xdp"] for r in v["rows"]]
        a1.plot(x, [r["bl_dip"] for r in v["rows"]], "o-", color=C[j], ms=4, label=name)
        a2.plot(x, [r["ms_dip"] for r in v["rows"]], "o-", color=C[j], ms=4, label=name)
    a1.axhline(lim["du_dyn_minus_pct"], color="#e34948", ls="--", lw=1)
    a2.axhline(lim["du_motor_start_pct"], color="#e34948", ls="--", lw=1)
    for ax in (a1, a2):
        ax.axvspan(0.15, 0.19, color="#1baf7a", alpha=0.12, lw=0)
        ax.set_xlabel("X'd (pu on 800 kVA)")
    a1.text(0.152, a1.get_ylim()[0] + 0.5, "public data sheets", fontsize=7, color=INK2)
    a1.set_ylabel("SR-01 block-load dip (%)")
    a2.set_ylabel("SR-05 132 kW DOL start dip (%)")
    a1.set_title("Dip vs X'd (X''d/X'd kept)", fontsize=9)
    a2.set_title("Motor-start dip vs X'd", fontsize=9)
    a1.legend(fontsize=7)
    save(fig, "dip_vs_xd.png")


def fig_femm(pf):
    """FEMM no-load field map (|B| and flux lines), EMF harmonics, SSFR fit."""
    import csv as _csv
    from matplotlib.tri import Triangulation
    rows = list(_csv.reader(open(ROOT / "femm" / "out" / "map_noload.csv")))[1:]
    x, y, b, a = (np.array([float(r[k]) for r in rows]) for k in range(4))
    sec = build_section(load_machine())
    fig, ax = plt.subplots(figsize=(6.4, 6.6))
    tri = Triangulation(x, y)
    cf = ax.tricontourf(tri, b, levels=np.linspace(0, 2.0, 21), cmap="Blues")
    ax.tricontour(tri, a, levels=24, colors=INK, linewidths=0.45)
    for r in sec.regions:
        if r.material == "copper":
            ax.add_patch(Polygon(r.poly, fill=False, ec="#d9822b", lw=0.5))
    cb = fig.colorbar(cf, ax=ax, shrink=0.75)
    cb.set_label("|B| (T)")
    ax.set_aspect("equal")
    ax.set_xlim(0, sec.r_out * 1.02)
    ax.set_ylim(-sec.r_out * 0.75, sec.r_out * 0.75)
    ax.grid(False)
    ax.set_title("FEMM no-load field at rated voltage: |B| and flux lines (one pole pitch)", fontsize=9)
    save(fig, "femm_field_noload.png")
    w = pf["waveform"]["harm_line_pct"]
    hk = [int(k) for k in w if int(k) > 1]
    fig, ax = plt.subplots(figsize=(6.4, 3.2))
    ax.bar(hk, [w[str(k)] if str(k) in w else w[k] for k in hk], width=0.8, color=C[0])
    ax.set_xlabel("Harmonic order")
    ax.set_ylabel("Line voltage, % of fundamental")
    ax.set_title(f"FEMM no-load line-voltage harmonics, THD = {100 * pf['waveform']['thd_line']:.2f} %", fontsize=9)
    save(fig, "femm_harmonics.png")
    ss = pf.get("ssfr")
    if ss:
        f = np.array(ss["f"])
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.8, 3.6))
        a1.semilogx(f, np.array(ss["Ld_re"]) * 1e3, "o", color=C[0], ms=4, label="FEMM, field open: Re")
        a1.semilogx(f, -np.array(ss["Ld_im"]) * 1e3, "o", color=C[1], ms=4, label="FEMM, field open: −Im")
        a1.semilogx(f, np.array(ss["Ldfit_re"]) * 1e3, color=C[0], lw=1.2, label="1st-order fit")
        a1.semilogx(f, -np.array(ss["Ldfit_im"]) * 1e3, color=C[1], lw=1.2)
        a1.semilogx(f, np.array(ss["Lcomb_re"]) * 1e3, "--", color=C[2], lw=1.2, label="with field branch (circuit)")
        a1.set_xlabel("Frequency (Hz)")
        a1.set_ylabel("Ld(jω) (mH)")
        a1.set_title("d axis: damper from FEMM + field from static data", fontsize=9)
        a1.legend(fontsize=6)
        fq = np.array(ss["fq"])
        a2.semilogx(fq, np.array(ss["Lq_re"]) * 1e3, "o", color=C[0], ms=4, label="FEMM Re")
        a2.semilogx(fq, -np.array(ss["Lq_im"]) * 1e3, "o", color=C[1], ms=4, label="FEMM −Im")
        a2.set_xlabel("Frequency (Hz)")
        a2.set_ylabel("Lq(jω) (mH)")
        a2.set_title("q axis", fontsize=9)
        a2.legend(fontsize=6)
        save(fig, "femm_ssfr.png")

if __name__ == "__main__":
    src = "femm" if "--femm" in sys.argv else "analytic"
    aoa = json.loads((ROOT / "results" / f"aoa_{src}.json").read_text())
    st_file = ROOT / "results" / f"studies_{src}.json"
    st = json.loads(st_file.read_text()) if st_file.exists() else None
    alts = load_alternatives()
    lim = load_plant()["limits"]
    pf = ROOT / "results" / "params_femm.json"
    fig_section()
    pfd = json.loads(pf.read_text()) if pf.exists() else None
    fig_occ(pfd)
    if pfd:
        fig_femm(pfd)
    fig_bl(aoa, alts, lim)
    fig_motor(aoa, alts, lim)
    fig_sc(aoa, alts)
    fig_aoa(aoa)
    if st:
        fig_budget(st, lim)
        fig_tornado(st)
        if "xd_sweep" in st:
            fig_xd(st, lim)
    fig_diode()
