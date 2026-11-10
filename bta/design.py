"""Analytic design model of the reference salient-pole alternator.

Classical design-office method (magnetic circuit + permeance-based reactances), the same route as the
textbook design procedures of Pyrhönen et al. (Design of Rotating Electrical Machines, 2nd ed., ch. 3-4, 7)
and Boldea (Synchronous Generators, 2nd ed., chapters on design and parameters). Equations are written
out in docs/design_notes.md with their derivation, because the textbooks were not available to re-check
equation numbers (see DOSSIER.md §11, 'assumed vs sourced').

Everything is SI unless the name ends in _pu (per unit on the machine's own rating).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

MU0 = 4e-7 * math.pi
ROOT = Path(__file__).resolve().parents[1]


def load_machine(path: Path | None = None) -> dict:
    with open(path or ROOT / "config" / "machine.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- winding
def winding_factor(nu: int, q: int, pitch_ratio: float, skew_slot_frac: float = 0.0, slots_per_pole: int = 12):
    """Distribution, pitch and skew factor of harmonic nu (electrical order)."""
    a_slot = math.pi / (slots_per_pole)            # slot angle in electrical rad (pi per pole pitch)
    kd = math.sin(nu * q * a_slot / 2) / (q * math.sin(nu * a_slot / 2))
    kp = math.sin(nu * pitch_ratio * math.pi / 2)
    if skew_slot_frac:
        s = nu * skew_slot_frac * a_slot / 2
        ksq = math.sin(s) / s
    else:
        ksq = 1.0
    return kd * kp * ksq, kd, kp, ksq


def carter(slot_open: float, gap: float, slot_pitch: float) -> float:
    """Carter coefficient (Carter's conformal-mapping result, as in Pyrhönen ch. 3)."""
    k = (2 / math.pi) * (math.atan(slot_open / (2 * gap))
                         - (gap / slot_open) * math.log(1 + (slot_open / (2 * gap)) ** 2))
    return slot_pitch / (slot_pitch - k * slot_open)


def bh_h(b: float, table) -> float:
    """H for a given B by linear interpolation; beyond the table, extends with mu0 slope."""
    bs, hs = np.array(table).T
    b = abs(b)
    if b <= bs[-1]:
        return float(np.interp(b, bs, hs))
    return float(hs[-1] + (b - bs[-1]) / MU0)


@dataclass
class Design:
    m: dict
    out: dict = field(default_factory=dict)

    # ------------------------------------------------------------ basics
    def basics(self):
        r, s, ro = self.m["rating"], self.m["stator"], self.m["rotor"]
        o = self.out
        p = r["poles"] // 2
        o["p"] = p
        o["u_ph"] = r["u_ll"] / math.sqrt(3)
        o["i_rated"] = r["s_kva"] * 1e3 / (math.sqrt(3) * r["u_ll"])
        o["z_base"] = r["u_ll"] ** 2 / (r["s_kva"] * 1e3)
        o["omega"] = 2 * math.pi * r["f_hz"]
        o["tau_p"] = math.pi * s["d_bore"] / r["poles"]
        o["slot_pitch"] = math.pi * s["d_bore"] / s["slots"]
        o["q"] = s["slots"] // (r["poles"] * 3)
        o["slots_per_pole"] = s["slots"] // r["poles"]
        o["pitch_ratio"] = s["coil_pitch_slots"] / o["slots_per_pole"]
        coils = s["slots"] * s["layers"] // 2
        o["n_series"] = coils // 3 * s["turns_per_coil"] // s["parallel_paths"]
        kw, kd, kp, _ = winding_factor(1, o["q"], o["pitch_ratio"], s["skew_slots"] / o["slots_per_pole"] if s["skew_slots"] else 0.0,
                                       o["slots_per_pole"])
        o["kw1"], o["kd1"], o["kp1"] = kw, kd, kp
        o["l_ef"] = s["l_core"] + 2 * ro["air_gap_min"]
        o["kc"] = carter(s["slot_open"], ro["air_gap_min"], o["slot_pitch"])
        o["delta_ef"] = o["kc"] * ro["air_gap_min"]
        o["theta_p"] = ro["pole_arc_ratio"] * math.pi / 2       # half pole arc, electrical rad
        o["a_lin"] = 2 * 3 * o["n_series"] * o["i_rated"] / (math.pi * s["d_bore"])
        o["r_gap"] = s["d_bore"] / 2 - ro["air_gap_min"] / 2

    # ------------------------------------------------------- gap field shape
    def gap_shape(self):
        """Fundamental factors for the cosine-shaped pole, delta = delta0/cos(theta) under the pole.

        Field:  B(theta) = B0 cos(theta) under the pole, 0 outside   -> B1/B0 = kf
        d-axis armature MMF F1 cos(theta): B = (mu0 F1/delta_ef) cos^2  -> kd
        q-axis armature MMF F1 sin(theta): B = (mu0 F1/delta_ef) sin cos -> kq (pole part only)
        The interpolar gap is wide; its contribution is estimated with an equivalent gap of
        g_ip = pole body clearance (see docs/design_notes.md) and is the weakest part of the analytic model.
        """
        o, ro = self.out, self.m["rotor"]
        tp = o["theta_p"]
        o["kf"] = (4 / math.pi) * (tp / 2 + math.sin(2 * tp) / 4)
        o["kd_pole"] = (4 / math.pi) * (math.sin(tp) - math.sin(tp) ** 3 / 3)
        o["kq_pole"] = (4 / math.pi) * (math.sin(tp) ** 3 / 3)
        # interpolar region: equivalent gap ~ 8x the minimum gap (flux path to pole sides and shoe flanks)
        g_ip = 8.0
        ip = (4 / math.pi)
        o["kd_ip"] = ip * (1 / g_ip) * ((math.pi / 2 - tp) / 2 - math.sin(math.pi - 2 * tp) / 4)
        o["kq_ip"] = ip * (1 / g_ip) * ((math.pi / 2 - tp) / 2 + math.sin(math.pi - 2 * tp) / 4)
        o["kd"] = o["kd_pole"] + o["kd_ip"]
        o["kq"] = o["kq_pole"] + o["kq_ip"]

    # ------------------------------------------------------- inductances
    def reactances(self):
        r, s, ro = self.m["rating"], self.m["stator"], self.m["rotor"]
        o = self.out
        N, kw, p = o["n_series"], o["kw1"], o["p"]
        # magnetizing inductance of a 3-phase winding over a uniform gap delta_ef (derived in design_notes §2)
        lm_uniform = 2 * 3 * MU0 * o["tau_p"] * o["l_ef"] * (N * kw) ** 2 / (math.pi ** 2 * p * o["delta_ef"])
        o["lm_uniform"] = lm_uniform
        o["lmd"] = o["kd"] * lm_uniform
        o["lmq"] = o["kq"] * lm_uniform
        # slot leakage, semi-closed parallel-sided slot, double layer, short pitch (Pyrhönen ch. 4 form)
        eps = 1 - o["pitch_ratio"]
        k2 = 1 - 3 * eps / 4
        k1 = (1 + 3 * k2) / 4
        h_cond = s["slot_depth"] - s["tip_height"] - s["wedge_height"]
        lam_u = (k1 * h_cond / (3 * s["slot_width"])
                 + k2 * (s["tip_height"] / s["slot_open"]
                         + 2 * s["wedge_height"] / (s["slot_width"] + s["slot_open"])))
        o["lambda_slot"] = lam_u
        coef = 4 * 3 / s["slots"] * MU0 * N ** 2
        o["l_slot"] = coef * o["l_ef"] * lam_u
        o["l_end"] = coef * o["q"] * s["end_turn_length"] * s["lambda_end"]
        # tooth-tip leakage (Pyrhönen form, k2 * 5(delta/b1)/(5+4 delta/b1))
        g = ro["air_gap_min"] / s["slot_open"]
        o["l_tip"] = coef * o["l_ef"] * k2 * 5 * g / (5 + 4 * g)
        # differential (harmonic) leakage from the winding harmonics up to order 199
        sig = 0.0
        for nu in range(5, 200, 2):
            if nu % 3 == 0:
                continue
            kwn, *_ = winding_factor(nu, o["q"], o["pitch_ratio"], 0.0, o["slots_per_pole"])
            sig += (kwn / (nu * kw)) ** 2
        o["sigma_diff"] = sig
        o["l_diff"] = sig * o["lmd"]
        o["l_sigma"] = o["l_slot"] + o["l_end"] + o["l_tip"] + o["l_diff"]
        o["ld"] = o["l_sigma"] + o["lmd"]
        o["lq"] = o["l_sigma"] + o["lmq"]
        # stator resistance at reference temperature
        cu = self.m["copper"]
        rho = cu["rho_20"] * (1 + cu["alpha_20"] * (r["t_wind_c"] - 20))
        cu_area_turn = (s["slot_width"] * (h_cond) * s["fill_factor"]) / (s["layers"] * s["turns_per_coil"])
        l_turn = 2 * s["l_core"] + 2 * s["end_turn_length"] + 2 * 0.025     # + straight extensions
        turns_per_path = (s["slots"] * s["layers"] // 2) // 3 * s["turns_per_coil"] // s["parallel_paths"]
        r_path = rho * turns_per_path * l_turn / cu_area_turn
        o["ra"] = r_path / s["parallel_paths"]
        o["cu_area_turn_mm2"] = cu_area_turn * 1e6
        o["j_stator"] = o["i_rated"] / s["parallel_paths"] / (cu_area_turn * 1e6)

    # ---------------------------------------------------------- field side
    def field(self):
        r, s, ro = self.m["rating"], self.m["stator"], self.m["rotor"]
        o = self.out
        p, Nf = o["p"], ro["field_turns_per_pole"]
        r_g, L = o["r_gap"], o["l_ef"]
        # gap flux per pole per ampere of field (cosine-shaped field, linear iron)
        phi_g_per_a = 2 * MU0 * Nf * L * r_g * math.sin(o["theta_p"]) / (p * o["delta_ef"])
        # leakage permeance between adjacent poles: shoe-to-shoe and body-to-body (both sides of the pole)
        r_shoe = r_g - ro["air_gap_min"] / 2 - ro["pole_shoe_height_edge"] / 2
        shoe_gap = 2 * math.pi * r_shoe / (2 * p) * (1 - ro["pole_arc_ratio"])
        r_body = ro["hub_radius"] + ro["pole_body_height"] / 2
        body_gap = 2 * math.pi * r_body / (2 * p) - ro["pole_body_width"]
        # adjacent poles have opposite MMF: 2F across the shoe gap, 2F*(x/h) linearly along the body
        perm = MU0 * L * (ro["pole_shoe_height_edge"] / shoe_gap + ro["pole_body_height"] / (2 * body_gap))
        # end-region leakage, ~ 30 % of the side leakage (assumed, typical order; see design_notes)
        perm *= 1.3
        phi_s_per_a = 2 * 2 * Nf * perm      # two sides, MMF difference 2F
        o["field_leak_factor"] = phi_s_per_a / phi_g_per_a
        o["lff"] = 2 * p * Nf * (phi_g_per_a + phi_s_per_a)
        # mutual: phase flux linkage in d-alignment per field ampere
        b0_per_a = MU0 * Nf / o["delta_ef"]
        phi1_per_a = (2 / math.pi) * o["kf"] * b0_per_a * o["tau_p"] * L
        o["lafd"] = o["n_series"] * o["kw1"] * phi1_per_a
        cu = self.m["copper"]
        rho = cu["rho_20"] * (1 + cu["alpha_20"] * (r["t_wind_c"] - 20))
        l_turn = 2 * (s["l_core"] + ro["pole_body_width"]) + math.pi * ro["field_coil_width"]
        o["rf"] = rho * 2 * p * Nf * l_turn / (ro["field_conductor_area_mm2"] * 1e-6)
        o["ldp"] = o["ld"] - 1.5 * o["lafd"] ** 2 / o["lff"]
        o["tdo_p"] = o["lff"] / o["rf"]
        o["td_p"] = o["tdo_p"] * o["ldp"] / o["ld"]

    # ---------------------------------------------------------- damper
    def damper(self):
        """Damper referred to the stator like an induction-machine cage (approximate; FEMM SSFR is the reference)."""
        r, s, ro = self.m["rating"], self.m["stator"], self.m["rotor"]
        o = self.out
        dmp = ro["damper"]
        p, L = o["p"], o["l_ef"]
        nb = dmp["bars_per_pole"] * 2 * p
        q_eq = nb / ro["pole_arc_ratio"]          # bar density as if the cage were continuous
        ref = 4 * 3 * (o["n_series"] * o["kw1"]) ** 2 / q_eq
        rho_cu = self.m["copper"]["rho_20"] * (1 + self.m["copper"]["alpha_20"] * (r["t_wind_c"] - 20))
        a_bar = math.pi * dmp["bar_diameter"] ** 2 / 4
        r_bar = rho_cu * L / a_bar
        # end-ring segment referred to a bar (cage formula, ring between bars over the pole)
        d_ring = 2 * (o["r_gap"] - 0.01)
        seg = math.pi * d_ring / q_eq
        r_ring = rho_cu * seg / (dmp["end_ring_area_mm2"] * 1e-6)
        r_bar_eq = r_bar + r_ring / (2 * math.sin(math.pi * p / q_eq) ** 2)
        lam_bar = 0.623 + dmp["bar_depth"] / dmp["bar_slot_open"]   # round bar + slot bridge (Pyrhönen ch. 4)
        l_bar = MU0 * L * lam_bar
        o["rD_d"] = ref * r_bar_eq * o["kd"]
        o["lDs_d"] = ref * l_bar * o["kd"]
        o["rD_q"] = ref * r_bar_eq * o["kq"]
        o["lDs_q"] = ref * l_bar * o["kq"]
        # field leakage referred to the stator d axis (from L'd)
        lad = o["lmd"]
        lfs = lad * (o["ldp"] - o["l_sigma"]) / (lad - (o["ldp"] - o["l_sigma"]))
        o["lfs_ref"] = lfs
        par = 1 / (1 / lad + 1 / lfs + 1 / o["lDs_d"])
        o["ldpp"] = o["l_sigma"] + par
        o["tdo_pp"] = (o["lDs_d"] + 1 / (1 / lad + 1 / lfs)) / o["rD_d"]
        o["td_pp"] = o["tdo_pp"] * o["ldpp"] / o["ldp"]
        o["lqpp"] = o["l_sigma"] + 1 / (1 / o["lmq"] + 1 / o["lDs_q"])
        o["tqo_pp"] = (o["lDs_q"] + o["lmq"]) / o["rD_q"]

    # ------------------------------------------------- open-circuit curve
    def occ(self, e_pu: np.ndarray) -> np.ndarray:
        """Field current [A] for open-circuit phase voltage e_pu (magnetic circuit with saturation)."""
        r, s, ro, st = self.m["rating"], self.m["stator"], self.m["rotor"], self.m["steel"]
        o = self.out
        bh = st["bh"]
        kfe = s["k_stack"]
        out = []
        for e in np.atleast_1d(e_pu):
            e_ph = e * o["u_ph"]
            phi1 = e_ph / (4.44 * r["f_hz"] * o["n_series"] * o["kw1"])          # fundamental flux per pole
            b1 = phi1 * math.pi / (2 * o["tau_p"] * o["l_ef"])
            b0 = b1 / o["kf"]
            f_gap = b0 * o["delta_ef"] / MU0
            # stator tooth at pole centre (parallel-sided slot -> tooth widens; use 1/3 depth width)
            h_s = s["slot_depth"]
            t_w = math.pi * (s["d_bore"] + 2 * h_s / 3) / s["slots"] - s["slot_width"]
            b_t = b0 * o["slot_pitch"] * o["l_ef"] / (t_w * s["l_core"] * kfe)
            f_teeth = bh_h(b_t, bh) * h_s
            # stator yoke: half the total flux per pole
            phi_pole = 2 * b0 * o["r_gap"] * o["l_ef"] * math.sin(o["theta_p"]) / o["p"]
            h_y = (s["d_out"] - s["d_bore"]) / 2 - h_s
            b_y = phi_pole / 2 / (h_y * s["l_core"] * kfe)
            l_y = math.pi * (s["d_out"] - h_y) / (2 * r["poles"])        # half of a pole pair path, per pole
            f_yoke = bh_h(b_y, bh) * l_y
            # pole body with leakage flux, rotor hub
            phi_p = phi_pole * (1 + o["field_leak_factor"])
            b_p = phi_p / (ro["pole_body_width"] * s["l_core"] * kfe)
            f_pole = bh_h(b_p, bh) * (ro["pole_body_height"] + ro["pole_shoe_height_edge"])
            b_h = phi_p / 2 / (ro["hub_radius"] * 0.8 * s["l_core"])      # solid magnetic hub/shaft
            f_hub = bh_h(b_h, bh) * math.pi * ro["hub_radius"] * 0.6 / r["poles"]
            f_tot = f_gap + f_teeth + f_yoke + f_pole + f_hub
            out.append(f_tot / ro["field_turns_per_pole"])
        return np.array(out)

    def run(self) -> dict:
        self.basics()
        self.gap_shape()
        self.reactances()
        self.field()
        self.damper()
        o = self.out
        w, zb = o["omega"], o["z_base"]
        pu = {
            "xd": w * o["ld"] / zb, "xq": w * o["lq"] / zb, "xl": w * o["l_sigma"] / zb,
            "xmd": w * o["lmd"] / zb, "xmq": w * o["lmq"] / zb,
            "xdp": w * o["ldp"] / zb, "xdpp": w * o["ldpp"] / zb, "xqpp": w * o["lqpp"] / zb,
            "ra": o["ra"] / zb,
            "tdo_p": o["tdo_p"], "td_p": o["td_p"], "tdo_pp": o["tdo_pp"], "td_pp": o["td_pp"],
            "tqo_pp": o["tqo_pp"],
        }
        o["pu"] = pu
        if0 = float(self.occ(np.array([1.0]))[0])
        # air-gap line field current at 1 pu: gap MMF only
        o["if0"] = if0
        o["if_airgap"] = float(self.occ_airgap(1.0))
        o["occ_e"] = [0.2, 0.4, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        o["occ_if"] = [float(x) for x in self.occ(np.array(o["occ_e"]))]
        return o

    def occ_airgap(self, e_pu: float) -> float:
        o, r = self.out, self.m["rating"]
        phi1 = e_pu * o["u_ph"] / (4.44 * r["f_hz"] * o["n_series"] * o["kw1"])
        b0 = phi1 * math.pi / (2 * o["tau_p"] * o["l_ef"]) / o["kf"]
        return b0 * o["delta_ef"] / MU0 / self.m["rotor"]["field_turns_per_pole"]


def emf_harmonics(d: Design, n_max: int = 49) -> dict:
    """No-load EMF harmonics from the analytic gap field (truncated cosine) and winding factors.

    Ignores slot ripple (stator slotting modulation), which FEMM captures; used only as a cross-check.
    """
    o = d.out
    tp = o["theta_p"]
    th = np.linspace(-np.pi / 2, np.pi / 2, 20001)
    b = np.where(np.abs(th) < tp, np.cos(th), 0.0)
    res = {}
    kw1 = o["kw1"]
    for nu in range(1, n_max + 1, 2):
        bn = (2 / np.pi) * np.trapezoid(b * np.cos(nu * th), th)
        kwn, *_ = winding_factor(nu, o["q"], o["pitch_ratio"], 0.0, o["slots_per_pole"])
        res[nu] = abs(bn * kwn) / nu * nu  # EMF ~ nu*f * (B_nu/nu flux) -> flux_nu ~ B_nu/nu, emf ~ nu*flux_nu
    e1 = res[1]
    rel = {k: v / e1 for k, v in res.items()}
    thd_ph = math.sqrt(sum(v ** 2 for k, v in rel.items() if k > 1))
    thd_ll = math.sqrt(sum(v ** 2 for k, v in rel.items() if k > 1 and k % 3 != 0))
    return {"rel": rel, "thd_phase": thd_ph, "thd_line": thd_ll}


if __name__ == "__main__":
    d = Design(load_machine())
    o = d.run()
    import json
    print(json.dumps({k: (round(v, 6) if isinstance(v, float) else v) for k, v in o.items() if k != "pu"}, indent=1))
    print(json.dumps({k: round(v, 4) for k, v in o["pu"].items()}, indent=1))
    h = emf_harmonics(d)
    print("THD phase %.3f line %.3f" % (h["thd_phase"], h["thd_line"]))
