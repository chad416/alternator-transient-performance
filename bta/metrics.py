"""ISO 8528-5 style transient metrics from simulated RMS voltage and frequency.

Definitions follow ISO 8528-5 (see DOSSIER.md §5.1 for the clause references):
- transient voltage deviation  dU_dyn = (U_extreme - U_r) / U_r * 100  (U_r = rated voltage)
- voltage recovery time t_U    = time from the load change until U re-enters, and stays in, the
                                  tolerance band around the new steady-state voltage
- transient frequency deviation and frequency recovery time t_f: same, on frequency.
"""
from __future__ import annotations

import numpy as np


def recovery_time(t: np.ndarray, x: np.ndarray, t_event: float, band: float, x_final: float | None = None) -> float:
    """Time after t_event until x stays within +-band (absolute) of x_final. inf if it never settles."""
    m = t >= t_event
    tt, xx = t[m], x[m]
    xf = xx[-1] if x_final is None else x_final
    outside = np.abs(xx - xf) > band
    if not outside.any():
        return 0.0
    k = np.nonzero(outside)[0][-1]
    if k == len(tt) - 1:
        return float("inf")
    return float(tt[k + 1] - t_event)


def transient_metrics(res: dict, t_event: float, u_r: float = 1.0, f_r: float = 50.0,
                      du_band_pct: float = 1.0, df_band_pct: float = 0.5, window: float | None = None) -> dict:
    t, u, f = res["t"], res["vt"], res["f"]
    m = t >= t_event
    if window:
        m &= t <= t_event + window
    u_min, u_max = float(u[m].min()), float(u[m].max())
    f_min, f_max = float(f[m].min()), float(f[m].max())
    t_u = recovery_time(t, u, t_event, du_band_pct / 100 * u_r)
    t_f = recovery_time(t, f, t_event, df_band_pct / 100 * f_r)
    return {
        "du_dyn_minus_pct": (u_min - u_r) / u_r * 100,
        "du_dyn_plus_pct": (u_max - u_r) / u_r * 100,
        "t_u_s": t_u,
        "df_dyn_minus_pct": (f_min - f_r) / f_r * 100,
        "df_dyn_plus_pct": (f_max - f_r) / f_r * 100,
        "t_f_s": t_f,
        "u_final": float(u[-1]),
        "f_final": float(f[-1]),
        "t_u_min_s": float(t[m][np.argmin(u[m])] - t_event),
    }


def margins(met: dict, lim: dict, kind: str) -> dict:
    """Margins (positive = inside the limit) in the same units as the limit."""
    out = {}
    if kind in ("load_on", "motor"):
        out["dip_margin_pct"] = met["du_dyn_minus_pct"] - lim["du_dyn_minus_pct"]
    if kind == "load_off":
        out["rise_margin_pct"] = lim["du_dyn_plus_pct"] - met["du_dyn_plus_pct"]
    out["t_u_margin_s"] = lim["t_u_rec_s"] - met["t_u_s"]
    return out
