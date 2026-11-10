"""Reduce FEMM CSV results (femm/out) to machine parameters -> results/params_femm.json.

Pure Python (numpy/scipy), so CI re-runs this reduction on the cached CSVs without FEMM.
"""
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bta.design import Design, load_machine  # noqa: E402

OUT = ROOT / "femm" / "out"


def read(name):
    with open(OUT / name, newline="") as fh:
        r = list(csv.reader(fh))
    head, rows = r[0], r[1:]
    cols = {h: [] for h in head}
    for row in rows:
        for h, v in zip(head, row):
            try:
                cols[h].append(float(v))
            except ValueError:
                cols[h].append(v)
    return {h: (np.array(v) if not isinstance(v[0], str) else v) for h, v in cols.items()}


def waveform(d, o):
    """EMF harmonics from the flux-linkage waveform over half a period (anti-periodic extension)."""
    th = np.radians(d["theta_e"])
    psi = np.vstack([d["psi_a"], d["psi_b"], d["psi_c"]])
    n = len(th)
    psi_full = np.hstack([psi, -psi])                     # 0..360 deg electrical
    w = o["omega"]
    dth = th[1] - th[0]
    # EMF = d psi / dt = w d psi / d theta (spectral derivative)
    P = np.fft.rfft(psi_full, axis=1)
    k = np.arange(P.shape[1])
    E = 1j * k * P * w
    amp = np.abs(E) * 2 / psi_full.shape[1]
    e_ph = amp[0]
    line = np.fft.rfft(psi_full[0] - psi_full[1])
    e_ll = np.abs(1j * k * line * w) * 2 / psi_full.shape[1]
    h = list(range(1, min(60, len(k))))
    thd_ph = math.sqrt(sum(e_ph[i] ** 2 for i in h[1:])) / e_ph[1]
    thd_ll = math.sqrt(sum(e_ll[i] ** 2 for i in h[1:])) / e_ll[1]
    return {"e1_ph_peak": float(e_ph[1]), "thd_phase": thd_ph, "thd_line": thd_ll,
            "harm_line_pct": {int(i): float(e_ll[i] / e_ll[1] * 100) for i in h if e_ll[i] / e_ll[1] > 0.002},
            "psi1_over_psi_peak": float(np.abs(P[0, 1]) * 2 / psi_full.shape[1] / np.max(np.abs(psi_full[0]))),
            "theta": np.degrees(np.r_[th, th + math.pi]).tolist(), "e_line_t": None}


def fit_ssfr(f, L, L0_guess, axis):
    """Least-squares fit of the standard operational inductance; the DC value L0 is fitted too."""
    s = 2j * np.pi * f
    if axis == "d":
        def model(p):
            l0, t1, t2, t3, t4 = np.exp(p)
            return l0 * (1 + s * t1) * (1 + s * t2) / ((1 + s * t3) * (1 + s * t4))
        p0 = np.log([L0_guess, 0.2, 0.012, 2.0, 0.02])
    else:
        def model(p):
            l0, t1, t3 = np.exp(p)
            return l0 * (1 + s * t1) / (1 + s * t3)
        p0 = np.log([L0_guess, 0.02, 0.1])
    res = least_squares(lambda p: np.r_[(model(p) - L).real, (model(p) - L).imag] / L0_guess, p0)
    pe = np.exp(res.x)
    return pe[0], pe[1:], model(res.x), float(np.sqrt(np.mean(res.fun ** 2)))


def main():
    m = load_machine()
    des = Design(m)
    o = des.run()
    zb, w, a = o["z_base"], o["omega"], m["stator"]["parallel_paths"]
    out = {"source": "FEMM 4.2 (22Oct2023) 2-D, reduced by femm/reduce.py", "notes": []}
    l_end = o["l_end"]                                    # analytic end-winding leakage (not in 2-D)
    # ---- waveform
    wv = waveform(read("wave_if1.00.csv"), o)
    out["waveform"] = {k: v for k, v in wv.items() if k not in ("theta", "e_line_t")}
    k1 = wv["psi1_over_psi_peak"]
    # ---- OCC
    oc = read("occ.csv")
    psi1 = oc["psi_a"] * k1
    e_pu = w * psi1 / math.sqrt(2) / o["u_ph"]
    slope = e_pu[0] / oc["i_f"][0]                        # air-gap line from the lowest (linear) point
    if_ag = 1.0 / slope
    out["if_airgap_A"] = float(if_ag)
    out["occ_e"] = [float(x) for x in e_pu]
    out["occ_ifd_pu"] = [float(x / if_ag) for x in oc["i_f"]]
    out["if0_A"] = float(np.interp(1.0, e_pu, oc["i_f"]))
    # ---- Ld, Lq (unsaturated, field unexcited)
    dq = read("ldq.csv")
    ax = np.array(dq["axis"])
    i = np.array(dq["i_peak"], float)
    psi_a = np.array(dq["psi_a"], float)
    ld2 = float(np.mean(np.abs(psi_a[ax == "d"]) / i[ax == "d"]))
    lq2 = float(np.mean(np.abs(psi_a[ax == "q"]) / i[ax == "q"]))
    ld, lq = ld2 + l_end, lq2 + l_end
    # ---- field
    fd = read("field.csv")
    lafd = float(np.mean(np.abs(fd["psi_a"]) / fd["i_f"]))
    lff = float(np.mean(m["rating"]["poles"] * np.abs(fd["psi_f_model"]) / fd["i_f"]))
    rf = o["rf"]
    ldp = ld - 1.5 * lafd ** 2 / lff
    tdo_p = lff / rf
    out["static"] = {"ld": ld, "lq": lq, "lafd": lafd, "lff": lff, "rf": rf, "ldp": ldp, "tdo_p": tdo_p,
                     "l_end_analytic": l_end}
    # leakage: slot leakage is inside the 2-D model; Xl for the dynamic model = analytic slot+tip+diff+end
    xl = w * o["l_sigma"] / zb
    pu = {"xd": w * ld / zb, "xq": w * lq / zb, "xl": xl, "xdp": w * ldp / zb, "ra": o["ra"] / zb,
          "tdo_p": tdo_p}
    # ---- SSFR
    sf = read("ssfr.csv")
    axs = np.array(sf["axis"])
    fr = np.array(sf["f"], float)
    L = (np.array(sf["psi_re"], float) + 1j * np.array(sf["psi_im"], float)) / np.array(sf["i_peak"], float) + l_end
    for axis_name in ("d", "q"):                         # flux sign convention: positive inductance at DC
        mk = axs == axis_name
        if mk.any() and L[mk][0].real < 0:
            L[mk] = -(L[mk] - l_end) + l_end
    md = axs == "d"
    # field-open d-axis response = damper only: L(s) = L0 (1 + s Ta) / (1 + s Tb)
    ld0, (ta, tb), Ld_fit, rms_d = fit_ssfr(fr[md], L[md], ld, "q")
    ll = o["l_sigma"]                                     # stator leakage (analytic; slot part is inside 2-D L0)
    lad = ld - ll
    ldpp_open = ld0 * ta / tb
    l1d = lad * (ldpp_open - ll) / (lad - (ldpp_open - ll))
    r1d = (lad + l1d) / tb
    lfd = lad * (ldp - ll) / (lad - (ldp - ll))
    rfd = (lad + lfd) / tdo_p
    ldpp = ll + 1 / (1 / lad + 1 / lfd + 1 / l1d)
    tdo_pp = (l1d + lad * lfd / (lad + lfd)) / r1d
    td_pp = tdo_pp * ldpp / ldp
    td_p = tdo_p * ldp / ld
    # combined operational inductance (field + damper), for the figure
    sj = 2j * np.pi * fr[md]
    zf = rfd / sj + lfd
    zd = r1d / sj + l1d
    L_comb = ll + 1 / (1 / lad + 1 / zf + 1 / zd)
    mq = axs == "q"
    lq0, (tqa, tqb), Lq_fit, rms_q = fit_ssfr(fr[mq], L[mq], lq, "q")
    lqpp = lq0 * tqa / tqb
    out["ssfr"] = {"d_field_open": {"L0": ld0, "Ta": ta, "Tb": tb, "ldpp_open": ldpp_open, "fit_rms": rms_d},
                   "q": {"L0": lq0, "Ta": tqa, "Tb": tqb, "lqpp": lqpp, "fit_rms": rms_q},
                   "circuit_d": {"lad": lad, "ll": ll, "lfd": lfd, "rfd": rfd, "l1d": l1d, "r1d": r1d},
                   "f": fr[md].tolist(), "Ld_re": L[md].real.tolist(), "Ld_im": L[md].imag.tolist(),
                   "Ldfit_re": Ld_fit.real.tolist(), "Ldfit_im": Ld_fit.imag.tolist(),
                   "Lcomb_re": L_comb.real.tolist(), "Lcomb_im": L_comb.imag.tolist(),
                   "fq": fr[mq].tolist(), "Lq_re": L[mq].real.tolist(), "Lq_im": L[mq].imag.tolist()}
    pu.update({"xdpp": w * ldpp / zb, "xqpp": w * lqpp / zb, "td_p": td_p, "td_pp": td_pp,
               "tdo_pp": tdo_pp, "tqo_pp": float(tqb), "xdpp_field_open": w * ldpp_open / zb})
    out["pu"] = pu
    out["analytic_pu"] = o["pu"]
    (ROOT / "results" / "params_femm.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({k: round(v, 4) for k, v in pu.items()}, indent=1))
    print("THD line %.2f %%" % (100 * wv["thd_line"]))


if __name__ == "__main__":
    main()
