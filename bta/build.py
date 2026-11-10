"""Assemble the generating-set model from the machine design (analytic or FEMM) and config/plant.yaml."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from .design import Design, load_machine
from .dynamics import ExcParams, GenParams, GenSet, GovParams, MotorParams

ROOT = Path(__file__).resolve().parents[1]


def load_plant(path: Path | None = None) -> dict:
    with open(path or ROOT / "config" / "plant.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def gen_params(source: str = "auto", machine: dict | None = None, femm_file: Path | None = None) -> tuple[GenParams, dict]:
    """Alternator parameters. source: 'analytic', 'femm' (results/params_femm.json, or femm_file) or 'auto'
    (FEMM if present)."""
    m = machine or load_machine()
    femm_file = femm_file or ROOT / "results" / "params_femm.json"
    if source == "femm" or (source == "auto" and femm_file.exists()):
        d = json.loads(femm_file.read_text())
        pu = d["pu"]
        occ_e, occ_i = d["occ_e"], d["occ_ifd_pu"]
        src = "femm"
    else:
        des = Design(m)
        o = des.run()
        pu = o["pu"]
        occ_e = o["occ_e"]
        occ_i = [x / o["if_airgap"] for x in o["occ_if"]]
        src = "analytic"
    # add the origin so the saturation table starts on the air-gap line
    occ_e = [0.0] + list(occ_e)
    occ_i = [0.0] + list(occ_i)
    g = GenParams(xd=pu["xd"], xq=pu["xq"], xl=pu["xl"], xdp=pu["xdp"], xdpp=pu["xdpp"], xqpp=pu["xqpp"],
                  tdo_p=pu["tdo_p"], tdo_pp=pu["tdo_pp"], tqo_pp=pu["tqo_pp"], ra=pu["ra"],
                  h=m["mech"]["h_set_s"], occ_e=tuple(occ_e[1:]), occ_ifd=tuple(occ_i[1:]))
    return g, {"source": src, "pu": pu}


def build(gen: GenParams | None = None, exc_over: dict | None = None, gov_over: dict | None = None,
          motor_kva: float | None = None, motor_over: dict | None = None, plant: dict | None = None,
          s_gen_kva: float | None = None) -> GenSet:
    pl = plant or load_plant()
    if gen is None:
        gen, _ = gen_params()
    ex = {k: v for k, v in pl["excitation"].items() if k != "model"}
    ex.update(exc_over or {})
    gv = dict(pl["governor"])
    gv.update(gov_over or {})
    mo = None
    if motor_kva:
        md = {k: v for k, v in pl["motor"].items() if k != "load_type"}
        md.update(motor_over or {})
        mo = MotorParams(s_kva=motor_kva, **md)
    s_gen = s_gen_kva or load_machine()["rating"]["s_kva"]
    return GenSet(gen, ExcParams(**ex), GovParams(**gv), mo, s_gen)
