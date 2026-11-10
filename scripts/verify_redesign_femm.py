"""FEMM verification of the one base-frame redesign that passed the L1 screen (DOSSIER §8.6, decision D21).

The variant (8 mm air gap, 50 mm slots of the same area) was solved in FEMM with the same five studies as the base
design:  BTA_VARIANT=8,50 python femm/femm_model.py occ wave ldq field ssfr ; BTA_VARIANT=8,50 python femm/reduce.py
This script runs its FEMM parameters, with no calibration factor, through SR-01 (100 % block load) and SR-05 (132 kW
DOL start) with the tuned A1 (shunt) and A3 (PMG) gains, and compares the field current with the base FEMM model.

    python -m scripts.verify_redesign_femm
"""
import json
from pathlib import Path

from bta.aoa import load_alternatives
from bta.build import gen_params, load_plant
from bta.design import machine_variant
from scripts.run_studies import cfg_of, run_metrics

ROOT = Path(__file__).resolve().parents[1]
VARIANT = (8.0, 50.0)


def rated_field_current(pu: dict, if0: float, if_ag: float) -> float:
    """Rated-load field current [A]: two-reaction phasor on the air-gap line + no-load saturation increment
    (the same rule as scripts/screen_redesign.py)."""
    import math
    phi = math.acos(0.8)
    e_q = complex(1.0, 0) + 1j * pu["xq"] * complex(math.cos(-phi), math.sin(-phi))
    delta = math.atan2(e_q.imag, e_q.real)
    i_d = math.sin(phi + delta)
    eq = abs(e_q) + (pu["xd"] - pu["xq"]) * i_d
    return eq * if_ag + (if0 - if_ag)


def main():
    aoa = json.loads((ROOT / "results" / "aoa_femm.json").read_text())
    alts = load_alternatives()
    lim = load_plant()["limits"]
    f_var = ROOT / "results" / "params_femm_redesign_g8_s50.json"
    base = json.loads((ROOT / "results" / "params_femm.json").read_text())
    var = json.loads(f_var.read_text())
    g, _ = gen_params("femm", machine_variant(*VARIANT), femm_file=f_var)
    screen = json.loads((ROOT / "results" / "redesign_screen_femm.json").read_text())
    srow = next(r for r in screen["rows"] if r["air_gap_mm"] == VARIANT[0] and abs(r["slot_depth_mm"] - VARIANT[1]) < 0.1)
    if_b = rated_field_current(base["pu"], base["if0_A"], base["if_airgap_A"])
    if_v = rated_field_current(var["pu"], var["if0_A"], var["if_airgap_A"])
    out = {"variant": {"air_gap_mm": VARIANT[0], "slot_depth_mm": VARIANT[1]},
           "pu_femm": var["pu"], "pu_base_femm": base["pu"],
           "screen_estimate": {k: srow[k] for k in ("xd", "xdp", "xdpp", "if_rated_rel")},
           "thd_line": var["waveform"]["thd_line"], "thd_line_base": base["waveform"]["thd_line"],
           "if0_A": var["if0_A"], "if0_base_A": base["if0_A"],
           "if_rated_A": if_v, "if_rated_base_A": if_b, "if_rated_rel": if_v / if_b,
           "field_loss_rel": (if_v / if_b) ** 2, "limits": {"sr01": lim["du_dyn_minus_pct"], "sr05": lim["du_motor_start_pct"]}}
    for key in ("A1", "A3"):
        out[key] = run_metrics(cfg_of(key, aoa, alts, gen=g), lim)
    (ROOT / "results" / "redesign_femm_verify.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k not in ("pu_base_femm",)}, indent=1))


if __name__ == "__main__":
    main()
