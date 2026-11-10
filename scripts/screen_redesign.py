"""Screening of a base-frame redesign for a lower X'd (DOSSIER §8.6, decision D20).

Recommendation 3 of the trade study asks whether the base frame can reach X'd <= ~0.21 pu without the next frame.
This script varies the two geometry levers that the analytic design (L1) shows to act on X'd at a fixed rating and
frame: the air gap, and a shallower and wider stator slot of the same copper area. Each variant is
- computed with the analytic design (bta/design.py),
- calibrated to FEMM by the base design's FEMM/analytic ratios (the same rule as the next-frame alternatives,
  bta/aoa.py gen_for), and
- run through SR-01 (100 % block load) and SR-05 (132 kW DOL start) with the tuned A1 (shunt) and A3 (PMG) gains
  from results/aoa_femm.json.

The price of a larger air gap is field current. The rated-load field current is estimated with the classical
two-reaction phasor (unsaturated Xd, Xq on the air-gap line) plus the no-load saturation increment, and is given
relative to the base design. The field copper loss scales with its square, with the same coil (D8).
This is an L1 screen, not a FEMM-verified design.

    python -m scripts.screen_redesign
"""
import copy
import json
import math
from dataclasses import replace
from pathlib import Path

from bta.aoa import load_alternatives
from bta.build import gen_params, load_plant
from bta.design import Design, load_machine
from scripts.run_studies import cfg_of, run_metrics

ROOT = Path(__file__).resolve().parents[1]
CAL = ("xd", "xq", "xl", "xdp", "xdpp", "xqpp", "tdo_p", "tdo_pp", "tqo_pp")


def variant(gap_mm: float, slot_depth_mm: float | None = None) -> dict:
    m = copy.deepcopy(load_machine())
    m["rotor"]["air_gap_min"] = gap_mm / 1000
    if slot_depth_mm is not None:
        s = m["stator"]
        area = s["slot_width"] * s["slot_depth"]
        s["slot_depth"] = slot_depth_mm / 1000
        s["slot_width"] = area / s["slot_depth"]          # same slot area, so the same copper and current density
    return m


def field_current_rated(o: dict) -> float:
    """Rated-load field current [A]: two-reaction phasor on the air-gap line + no-load saturation increment."""
    pu = o["pu"]
    pf = 0.8
    phi = math.acos(pf)
    v, i = 1.0, 1.0
    e_q = complex(v, 0) + 1j * pu["xq"] * i * complex(math.cos(-phi), math.sin(-phi))
    delta = math.atan2(e_q.imag, e_q.real)
    i_d = i * math.sin(phi + delta)
    eq = abs(e_q) + (pu["xd"] - pu["xq"]) * i_d
    return eq * o["if_airgap"] + (o["if0"] - o["if_airgap"])


def main():
    aoa = json.loads((ROOT / "results" / "aoa_femm.json").read_text())
    alts = load_alternatives()
    lim = load_plant()["limits"]
    gf, _ = gen_params("femm")
    ga, _ = gen_params("analytic")
    base_o = Design(load_machine()).run()
    if_base = field_current_rated(base_o)
    cases = [(4.0, None), (5.0, None), (6.0, None), (7.0, None), (8.0, None), (6.0, 50.0), (7.0, 50.0), (8.0, 50.0)]
    rows = []
    for gap, depth in cases:
        m = variant(gap, depth)
        o = Design(m).run()
        g, _ = gen_params("analytic", m)
        g = replace(g, **{n: getattr(g, n) * getattr(gf, n) / getattr(ga, n) for n in CAL})
        ifr = field_current_rated(o)
        row = {"air_gap_mm": gap, "slot_depth_mm": depth or 1000 * load_machine()["stator"]["slot_depth"],
               "slot_width_mm": 1000 * m["stator"]["slot_width"],
               "xd": g.xd, "xdp": g.xdp, "xdpp": g.xdpp, "tdo_p": g.tdo_p,
               "if_rated_rel": ifr / if_base, "field_loss_rel": (ifr / if_base) ** 2}
        for key in ("A1", "A3"):
            r = run_metrics(cfg_of(key, aoa, alts, gen=g), lim)
            row[key] = r
        rows.append(row)
        print(f"gap {gap} depth {row['slot_depth_mm']:.0f}: X'd {g.xdp:.3f} if x{row['if_rated_rel']:.2f} "
              f"A1 {row['A1']['bl_dip']:.2f}/{row['A1']['ms_dip']:.2f}  A3 {row['A3']['bl_dip']:.2f}/{row['A3']['ms_dip']:.2f}")
    out = {"method": __doc__.strip().splitlines()[0], "limits": {"sr01": lim["du_dyn_minus_pct"],
           "sr05": lim["du_motor_start_pct"]}, "rows": rows}
    (ROOT / "results" / "redesign_screen_femm.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
