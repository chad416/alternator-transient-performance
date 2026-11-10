"""Write the result tables into DOSSIER.md and README.md between <!-- TABLE:name --> ... <!-- /TABLE --> markers.

The tables are generated from results/*.json, so no number in the documents is typed by hand.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def f(x, nd=2):
    if x is None:
        return "—"
    if isinstance(x, float) and x == float("inf"):
        return "∞"
    return f"{x:.{nd}f}"


def t_params(pf, an):
    keys = [("xd", "Xd"), ("xq", "Xq"), ("xl", "Xl"), ("xdp", "X'd"), ("xdpp", "X''d"), ("xqpp", "X''q"),
            ("tdo_p", "T'do (s)"), ("td_p", "T'd (s)"), ("tdo_pp", "T''do (s)"), ("td_pp", "T''d (s)"), ("tqo_pp", "T''qo (s)"), ("ra", "Ra")]
    ds = {"xd": "2.44–2.94", "xq": "1.90–2.48", "xdp": "0.146–0.19", "xdpp": "0.11–0.13", "xqpp": "0.24–0.37",
          "tdo_p": "1.7–4.09", "td_p": "0.08–0.097", "td_pp": "0.012–0.019"}
    rows = ["| Parameter (pu on 800 kVA) | Analytic (L1) | FEMM (L2) | Public data sheets 310–1150 kVA [S7] |", "|---|---|---|---|"]
    for k, n in keys:
        rows.append(f"| {n} | {f(an.get(k), 3)} | {f(pf.get(k) if pf else None, 3)} | {ds.get(k, '—')} |")
    return "\n".join(rows)


def t_aoa(aoa):
    r = aoa["results"]
    rows = ["| | Alternative | KP/KI/KD | OC overshoot | SR-01 dip | SR-02 t_U | SR-03 rise | SR-04 t_U | SR-05 132 kW dip | Max motor @20 % | SR-06 I_sc at 1 s | Gates |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in r.items():
        e = v["exc"]
        g = v["gates"]
        ok = sum(bool(x) for x in g.values())
        rows.append(f"| {k} | {v['name']} | {f(e['kp'],1)}/{f(e['ki'],1)}/{f(e['kd'],1)} | {f(v['oc_step']['overshoot_pct'],1)} % | "
                    f"{f(v['bl100']['du_dyn_minus_pct'])} % | {f(v['bl100']['t_u_s'])} s | +{f(v['lr100']['du_dyn_plus_pct'],1)} % | "
                    f"{f(v['lr100']['t_u_s'])} s | {f(v['motor']['du_dyn_minus_pct'],1)} % | {f(v['max_motor_kw_20pct'],0)} kW | "
                    f"{f(v['sc']['i_at_1s_pu'])} pu | {ok}/6 |")
    return "\n".join(rows)


def t_gates(aoa):
    r = aoa["results"]
    names = list(next(iter(r.values()))["gates"])
    rows = ["| Requirement | " + " | ".join(r) + " |", "|---|" + "---|" * len(r)]
    for n in names:
        rows.append(f"| {n} | " + " | ".join("pass" if r[k]["gates"][n] else "**fail**" for k in r) + " |")
    return "\n".join(rows)


def t_scores(aoa):
    r = aoa["results"]
    s = aoa["scores"]
    w = aoa["weight_sensitivity_win_share"]
    rows = ["| | Cost index [A/D] | Risk [A] | Integration [A] | Weighted score | Won (weights ±50 %) | Meets every shall |", "|---|---|---|---|---|---|---|"]
    for k in r:
        rows.append(f"| {k} | {f(r[k]['cost'])} | {r[k]['risk']} | {r[k]['integration']} | {f(s[k],1)} | {f(100*w[k],1)} % | "
                    f"{'yes' if all(r[k]['gates'].values()) else 'no'} |")
    return "\n".join(rows)


def t_budget(st):
    rows = ["| | Reactance step t=0⁺ | Flux decay (ideal excitation) | Real excitation | Total dip | Margin to −15 % | Extra dip from engine speed (50 % step) |",
            "|---|---|---|---|---|---|---|"]
    for k, v in st["budget"].items():
        b = v["budget"]
        rows.append(f"| {k} | {f(b['reactance_step_pct'])} | {f(b['flux_decay_unavoidable_pct'])} | {f(b['excitation_limitation_pct'])} | "
                    f"{f(b['total_dip_pct'])} | {f(b['margin_to_limit_pct'])} | {f(b['engine_speed_extra_at_50pct_step_pct'])} |")
    return "\n".join(rows)


def t_sens(st):
    s = st["sensitivity_A1"]
    rows = [f"| Parameter [A] (low/high) | SR-01 dip low | high | t_U low | high | 132 kW dip low | high |", "|---|---|---|---|---|---|---|"]
    for n, c in s["cases"].items():
        if n.startswith("H "):
            continue
        rows.append(f"| {n} | {f(c['lo']['bl_dip'])} | {f(c['hi']['bl_dip'])} | {f(c['lo']['bl_tu'])} | {f(c['hi']['bl_tu'])} | "
                    f"{f(c['lo']['ms_dip'],1)} | {f(c['hi']['ms_dip'],1)} |")
    b = s["base"]
    rows.append(f"| *A1 base* | {f(b['bl_dip'])} | | {f(b['bl_tu'])} | | {f(b['ms_dip'],1)} | |")
    return "\n".join(rows)


def t_xd(st):
    rows = ["| Excitation | Largest X'd meeting SR-01 (−15 %) | Largest X'd meeting SR-05 (132 kW, −20 %) |", "|---|---|---|"]
    for k, v in st["xd_sweep"].items():
        rows.append(f"| {k} | {f(v['xdp_max_sr01'],3)} | {f(v['xdp_max_sr05'],3)} |")
    return "\n".join(rows)


def t_diode(st):
    d = st["diode"]
    lab = {"none": "Healthy", "open": "One diode open", "short": "One diode shorted"}
    rows = ["| Rectifier state | Mean DC voltage (V) | Capability factor | Max armature current vs healthy | Field-frame MMF at f_ex (A) | at 6 f_ex (A) | ratio 1/6 | SR-01 dip | SR-02 t_U | 132 kW dip |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for k in ("none", "open", "short"):
        v = d[k]
        g = v["g3_effect"]
        rows.append(f"| {lab[k]} | {f(v['v_dc_mean'],1)} | {f(v.get('k_rect', 1.0),3)} | {f(v.get('arm_current_ratio', 1.0))} | "
                    f"{f(v['mmf_1fex'],2)} | {f(v['mmf_6fex'],2)} | {f(v['mmf_1fex']/v['mmf_6fex'],3)} | {f(g.get('bl_dip'))} % | {f(g.get('bl_tu'))} s | {f(g.get('ms_dip'),1)} % |")
    return "\n".join(rows)


def t_ds(st):
    d = st["ds_class"]
    return ("| Machine | Excitation | SR-01 dip | SR-02 t_U | 132 kW dip |\n|---|---|---|---|---|\n"
            f"| Data-sheet class (X'd {d['params']['xdp']}) | A1 shunt retuned | {f(d['A1_exc']['bl_dip'])} % | {f(d['A1_exc']['bl_tu'])} s | {f(d['A1_exc']['ms_dip'],1)} % |\n"
            f"| Data-sheet class | A3 PMG retuned | {f(d['A3_exc']['bl_dip'])} % | {f(d['A3_exc']['bl_tu'])} s | {f(d['A3_exc']['ms_dip'],1)} % |")


def t_femm(pf):
    if not pf:
        return "_FEMM results not available._"
    w = pf["waveform"]
    h = ", ".join(f"{k}: {v:.2f} %" for k, v in list(w["harm_line_pct"].items())[1:8])
    s = pf["static"]
    return (f"| Quantity | Value |\n|---|---|\n| No-load field current for 1 pu (FEMM) | {f(pf['if0_A'],1)} A |\n"
            f"| Air-gap-line field current at 1 pu | {f(pf['if_airgap_A'],1)} A |\n"
            f"| Line-to-line THD, no load, unskewed | {f(100*w['thd_line'])} % |\n| Phase THD (incl. triplen) | {f(100*w['thd_phase'])} % |\n"
            f"| Largest line harmonics (% of fundamental) | {h} |\n| Field self-inductance Lff (4 poles) | {f(s['lff'],3)} H |\n"
            f"| Field–phase mutual Lafd | {f(s['lafd']*1e3,2)} mH |\n"
            f"| SSFR fit RMS error, d (field open) / q | {f(100*pf['ssfr']['d_field_open']['fit_rms'],2)} % / {f(100*pf['ssfr']['q']['fit_rms'],2)} % |\n"
            f"| SSFR low-frequency limit vs static solve (linear μr 2000 vs M-19 B-H), d / q | "
            f"{f(100*(pf['ssfr']['d_field_open']['L0']/s['ld']-1),1)} % / {f(100*(pf['ssfr']['q']['L0']/s['lq']-1),1)} % |\n"
            f"| X''d: damper only (field open) / with field branch | {f(pf['pu']['xdpp_field_open'],3)} / {f(pf['pu']['xdpp'],3)} |\n"
            f"| End-ring factor k_ring on the damper resistance (D18, ring {f(pf['end_ring']['end_ring_area_mm2'],0)} mm²) | {f(pf['end_ring']['k_ring'],3)} |\n"
            f"| T''d / T''do: ideal FEMM ring → with end ring | {f(pf['end_ring']['ideal_ring']['td_pp']*1e3,1)} / {f(pf['end_ring']['ideal_ring']['tdo_pp']*1e3,1)} ms → "
            f"{f(pf['pu']['td_pp']*1e3,1)} / {f(pf['pu']['tdo_pp']*1e3,1)} ms |\n"
            f"| T''qo: ideal ring → with end ring | {f(pf['end_ring']['ideal_ring']['tqo_pp']*1e3,1)} ms → {f(pf['pu']['tqo_pp']*1e3,1)} ms |\n"
            f"| What-if: stator skewed one slot pitch (D19): line THD / fundamental factor | "
            f"{f(100*w['skew_one_slot']['thd_line'])} % / {f(w['skew_one_slot']['k_sk1'],4)} |")


def t_redesign(rd):
    if not rd:
        return "_Redesign screen not run._"
    rows = ["| Air gap (mm) | Slot depth × width (mm) | Xd | X'd | X''d | Rated field current vs base | Field Cu loss vs base | "
            "SR-01 dip A1 / A3 | SR-05 132 kW dip A1 / A3 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rd["rows"]:
        rows.append(f"| {f(r['air_gap_mm'],0)} | {f(r['slot_depth_mm'],0)} × {f(r['slot_width_mm'],1)} | {f(r['xd'])} | {f(r['xdp'],3)} | "
                    f"{f(r['xdpp'],3)} | ×{f(r['if_rated_rel'])} | ×{f(r['field_loss_rel'])} | "
                    f"{f(r['A1']['bl_dip'])} / {f(r['A3']['bl_dip'])} % | {f(r['A1']['ms_dip'],1)} / {f(r['A3']['ms_dip'],1)} % |")
    return "\n".join(rows)


def fill(path: Path, tables: dict):
    txt = path.read_text(encoding="utf-8")
    for name, body in tables.items():
        txt = re.sub(rf"(<!-- TABLE:{name} -->)(.*?)(<!-- /TABLE -->)", lambda m: f"{m.group(1)}\n{body}\n{m.group(3)}", txt, flags=re.S)
    path.write_text(txt, encoding="utf-8")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "femm"
    aoa = json.loads((ROOT / "results" / f"aoa_{src}.json").read_text())
    st = json.loads((ROOT / "results" / f"studies_{src}.json").read_text())
    pff = ROOT / "results" / "params_femm.json"
    pf = json.loads(pff.read_text()) if pff.exists() else None
    rdf = ROOT / "results" / f"redesign_screen_{src}.json"
    rd = json.loads(rdf.read_text()) if rdf.exists() else None
    from bta.design import Design, load_machine
    an = Design(load_machine()).run()["pu"]
    tables = {"params": t_params(pf["pu"] if pf else None, an), "aoa": t_aoa(aoa), "gates": t_gates(aoa),
              "scores": t_scores(aoa), "budget": t_budget(st), "sens": t_sens(st), "xd": t_xd(st),
              "diode": t_diode(st), "ds": t_ds(st), "femm": t_femm(pf), "redesign": t_redesign(rd)}
    for doc in ("DOSSIER.md", "README.md"):
        p = ROOT / doc
        if p.exists():
            fill(p, tables)
    print("tables:", ", ".join(tables))
