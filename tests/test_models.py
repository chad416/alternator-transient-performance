"""Model verification tests: each checks a model against an independent closed-form result or a source."""
import math

import numpy as np
import pytest

from bta.build import build, gen_params
from bta.design import Design, carter, load_machine, winding_factor
from bta.dynamics import ExcParams, MotorParams, Segment, W0, fex
from bta.metrics import recovery_time
from bta.rectifier import RectParams, signature, simulate


# ---------------------------------------------------------------- design
def test_winding_factor_two_thirds_pitch():
    kw1, kd1, kp1, _ = winding_factor(1, 4, 2 / 3)
    assert kp1 == pytest.approx(math.sin(math.pi / 3))
    assert kd1 == pytest.approx(0.5 / (4 * math.sin(math.pi / 24)))
    kw3, *_ = winding_factor(3, 4, 2 / 3)
    assert abs(kw3) < 1e-12          # 2/3 pitch removes the 3rd harmonic


def test_carter_limits():
    assert carter(1e-9, 0.004, 0.035) == pytest.approx(1.0, abs=1e-6)
    assert 1.0 < carter(0.004, 0.004, 0.035) < 1.1


def test_design_parameters_plausible():
    """Per-unit parameters must fall in a broad plausibility envelope around public LV data sheets [S7]."""
    o = Design(load_machine()).run()
    pu = o["pu"]
    assert 2.0 < pu["xd"] < 4.0
    assert 0.12 < pu["xdp"] < 0.35       # data sheets 0.15-0.19; the design is knowingly high (DOSSIER §6.1)
    assert 0.09 < pu["xdpp"] < 0.20
    assert 1.5 < pu["tdo_p"] < 4.5
    assert pu["xdpp"] < pu["xdp"] < pu["xd"]
    # OCC monotonic and saturating
    i = np.array(o["occ_if"])
    assert np.all(np.diff(i) > 0)
    assert np.all(np.diff(np.diff(i) / np.diff(o["occ_e"]))[3:] > -1e-9)


# ---------------------------------------------------------------- excitation functions
def test_fex_continuity_and_values():
    assert fex(0) == 1.0
    assert fex(0.433) == pytest.approx(1 - 0.577 * 0.433, abs=1e-6)
    assert fex(0.4331) == pytest.approx(math.sqrt(0.75 - 0.4331 ** 2), abs=2e-3)
    assert fex(0.75) == pytest.approx(1.732 * 0.25, abs=2e-3)
    assert fex(1.0) == 0.0


def test_exciter_saturation_passes_through_points():
    e = ExcParams()
    assert e.se(e.ve1) == pytest.approx(e.se1, rel=1e-9)
    assert e.se(e.ve2) == pytest.approx(e.se2, rel=1e-9)


# ---------------------------------------------------------------- dynamics
def _settled(gs, y0, seg, t=1.0):
    r = gs.simulate(y0, [seg], dt_out=0.01) if False else gs.simulate(y0, [Segment(t, **seg)], dt_out=0.01)
    return r


@pytest.mark.parametrize("p,q", [(0.0, 0.0), (0.8, 0.6), (0.5, 0.0)])
def test_steady_state_is_steady(p, q):
    gs = build(gov_over={"ideal": True})
    y0 = gs.steady_state(p, q)
    r = gs.simulate(y0, [Segment(1.0, p_load=p, q_load=q)], dt_out=0.01)
    assert r["vt"].max() - r["vt"].min() < 1e-4
    assert r["vt"][-1] == pytest.approx(1.0, abs=1e-4)


def test_initial_dip_matches_subtransient_closed_form():
    """At t=0+ the rotor fluxes are frozen: V = |E'' - jX'' I| with I = Y V (closed form, isotropic X'')."""
    g, _ = gen_params("analytic")
    gs = build(gen=g, gov_over={"ideal": True})
    y0 = gs.steady_state(0.0, 0.0)
    r = gs.simulate(y0, [Segment(0.1), Segment(0.1 + 1e-3, p_load=0.8, q_load=0.6)], dt_out=1e-4)
    v0p = r["vt"][r["t"] > 0.1][0]
    xpp = 0.5 * (gs.c["ll"] + 1 / (1 / gs.c["lad"] + 1 / gs.c["lfd"] + 1 / gs.c["l1d"])
                 + gs.c["ll"] + 1 / (1 / gs.c["laq"] + 1 / gs.c["l1q"]))
    yl = complex(0.8, -0.6)
    v_cf = abs(1.0 / (1 + complex(gs.c["ra"], xpp) * yl))
    assert v0p == pytest.approx(v_cf, abs=0.01)


def test_motor_model_matches_equivalent_circuit():
    m = MotorParams(s_kva=200.0)
    for s in (1.0, 0.3, 0.05, 0.012):
        rr = m.rr(s)
        zr = complex(rr / s, m.xr)
        z_eq = complex(m.rs, m.xs) + 1j * m.xm * zr / (1j * m.xm + zr)
        t0 = (m.xm + m.xr) / (W0 * rr)
        z_dyn = complex(m.rs, m.xp) + 1j * (m.x - m.xp) / (1 + 1j * s * W0 * t0)
        assert abs(z_dyn - z_eq) < 1e-9


def test_shunt_collapses_and_pmg_sustains_short_circuit():
    """Known behaviour [S7]: a self-excited (shunt) alternator does not sustain short-circuit current; PMG does."""
    out = {}
    for supply in ("shunt", "pmg"):
        gs = build(exc_over={"supply": supply, "kp": 50, "ki": 45, "kd": 3}, gov_over={"ideal": True})
        y0 = gs.steady_state(0, 0)
        r = gs.simulate(y0, [Segment(0.1), Segment(1.6, fault_z=complex(0, 1e-3))], dt_out=0.005)
        out[supply] = r["it"][-1]
    assert out["shunt"] < 1.0
    assert out["pmg"] > 2.5


# ---------------------------------------------------------------- metrics
def test_recovery_time_on_synthetic_signal():
    t = np.linspace(0, 10, 10001)
    x = 1 - 0.2 * np.exp(-(t - 1).clip(0) / 0.5) * (t >= 1)
    tr = recovery_time(t, x, 1.0, 0.01, 1.0)
    assert tr == pytest.approx(0.5 * math.log(20), abs=2e-3)


# ---------------------------------------------------------------- rectifier
def test_healthy_bridge_dc_voltage_matches_commutation_formula():
    """With negligible armature resistance the classical six-pulse result is exact: V = 1.3505 V_LL - (3/pi) X_c I."""
    p = RectParams(r_x=1e-4)
    s = signature(simulate(p, "none", periods=10, steps_per_period=600), 6)
    x_c = 2 * math.pi * p.f_ex * p.l_c
    v_expected = 3 * math.sqrt(2) / math.pi * p.e_ll_rms - 3 / math.pi * x_c * s["i_f_mean"]
    assert s["v_dc_mean"] == pytest.approx(v_expected, rel=0.01)
    assert s["mmf_1fex"] < 0.01 * s["mmf_dc"]


def test_diode_faults_reduce_capability_and_raise_fundamental():
    p = RectParams()
    h = signature(simulate(p, "none", periods=10, steps_per_period=600), 6)
    o = signature(simulate(p, "open", periods=10, steps_per_period=600), 6)
    sh = signature(simulate(p, "short", periods=10, steps_per_period=600), 6)
    assert sh["v_dc_mean"] < o["v_dc_mean"] < h["v_dc_mean"]
    assert o["mmf_1fex"] > 10 * h["mmf_1fex"] + 1
    # fundamental / 6th-harmonic ratio rises with the fault (detection ratio, cf. ref [S12])
    assert sh["mmf_1fex"] / sh["mmf_6fex"] > o["mmf_1fex"] / o["mmf_6fex"] > h["mmf_1fex"] / h["mmf_6fex"]
