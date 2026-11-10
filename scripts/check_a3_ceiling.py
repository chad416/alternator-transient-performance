"""How much AVR ceiling the PMG alternative A3 needs to meet SR-06 (sustained short-circuit current >= 3.0 pu at 1 s).

Uses the tuned A3 gains from results/aoa_femm.json and bisects VRMAX. Writes results/a3_ceiling_femm.json.

    python -m scripts.check_a3_ceiling
"""
import json
from pathlib import Path

import numpy as np

from bta.aoa import gen_for, load_alternatives
from bta.build import load_plant
from bta.scenarios import T_EV, Config, short_circuit

ROOT = Path(__file__).resolve().parents[1]


def i_at_1s(gen, exc, gov):
    r = short_circuit(Config("A3", gen, exc, gov), t_fault=3.0)     # same definition as bta/aoa.py evaluate()
    return float(np.interp(T_EV + 1.0, r["t"], r["it"]))


def main():
    aoa = json.loads((ROOT / "results" / "aoa_femm.json").read_text())
    pl = load_plant()
    need = pl["limits"]["i_sc_sustained_pu"]
    exc = aoa["results"]["A3"]["exc"]
    gen = gen_for("base", load_alternatives(), "femm")
    gov = pl["governor"]
    lo, hi = exc["vrmax"], exc["vrmax"] * 1.3
    i_lo = i_at_1s(gen, exc, gov)
    for _ in range(12):
        mid = 0.5 * (lo + hi)
        if i_at_1s(gen, dict(exc, vrmax=mid), gov) >= need:
            hi = mid
        else:
            lo = mid
    out = {"vrmax_assumed": exc["vrmax"], "i_at_1s_assumed_pu": i_lo, "i_sc_required_pu": need,
           "vrmax_needed": hi, "increase_pct": 100 * (hi / exc["vrmax"] - 1)}
    (ROOT / "results" / "a3_ceiling_femm.json").write_text(json.dumps(out, indent=1))
    print(out)


if __name__ == "__main__":
    main()
