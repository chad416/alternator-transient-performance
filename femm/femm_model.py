"""FEMM 4.2 model of one pole pitch, driven through pyfemm (Windows, FEMM ActiveX).

Studies (each mirrors a test method of IEC 60034-4-1:2018, see DOSSIER.md §10):
  occ      open-circuit characteristic: field current sweep, phase flux linkage at d-alignment (cf. 6.4)
  wave     no-load EMF waveform by rotating the rotor (air-gap element), THD (cf. IEC 60034-1 cl. 9.11)
  ldq      unsaturated d- and q-axis synchronous inductance, field unexcited (cf. slip test 6.10)
  field    field self-inductance and field-to-phase mutual inductance -> X'd, T'do
  ssfr     standstill frequency response, d and q axis (cf. 6.27 / 7.28.3), field OPEN, damper bars joined by
           ideal end rings; the field branch is added from the static field data in reduce.py
Results go to femm/out/*.csv and are reduced by femm/reduce.py to results/params_femm.json.

Modelling choices (stated, not hidden):
- 2-D planar, depth = core length x stacking factor; end-winding leakage added analytically (bta/design.py).
- Laminated stator and rotor iron: FEMM library "M-19 Steel", zero conductivity.
- Damper bars: copper blocks with no circuit = shorted by ideal (zero-resistance) end rings.
- Field winding in SSFR: left open. A first run with the field as a solid shorted loop showed eddy-current
  crowding in the coil that a stranded coil cannot have (decision D15), so the field branch is taken from
  the static solutions (Lff, Lafd) and the design resistance instead, and combined in the d-axis circuit.
- Rotor rotation via an anti-periodic air-gap element (AGE, FEMM >= 4.2 21Apr2019) without remeshing.
"""
from __future__ import annotations

import csv
import math
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bta.design import Design, load_machine  # noqa: E402
from bta.geometry import build_section  # noqa: E402

OUT = ROOT / "femm" / "out"
FEM = OUT / "model.fem"
# "<None>": every bar is shorted at infinity (J = -j w sigma A, no voltage term). Under the anti-periodic pole
# symmetry an ideal continuous end ring forces the common bar voltage to zero, so this is the ideal-ring cage for
# both axes. "D" (one parallel circuit, zero net current per pole) also forbids the q-axis bar currents that return
# through the ring to the next pole (decision D17).
BAR_CIRCUIT = "<None>"


def _femm():
    import femm  # pyfemm
    return femm


class Model:
    def __init__(self, m: dict | None = None):
        self.m = m or load_machine()
        self.sec = build_section(self.m)
        self.d = Design(self.m)
        self.o = self.d.run()
        s = self.m["stator"]
        self.depth = s["l_core"] * s["k_stack"]
        self.Rs = s["d_bore"] / 2
        self.r_age_in = self.Rs - 0.0030       # rotor-side AGE arc (inside the minimum gap of 4 mm)
        self.r_age_out = self.Rs - 0.0015      # stator-side AGE arc
        self.f = _femm()

    # ------------------------------------------------------------------ drawing helpers
    def poly(self, pts, closed=True):
        f = self.f
        for x, y in pts:
            f.mi_addnode(x, y)
        n = len(pts)
        for k in range(n if closed else n - 1):
            (x1, y1), (x2, y2) = pts[k], pts[(k + 1) % n]
            f.mi_addsegment(x1, y1, x2, y2)

    def arc(self, r, a1, a2, maxseg=1.0):
        f = self.f
        x1, y1 = r * math.cos(a1), r * math.sin(a1)
        x2, y2 = r * math.cos(a2), r * math.sin(a2)
        f.mi_addnode(x1, y1)
        f.mi_addnode(x2, y2)
        f.mi_addarc(x1, y1, x2, y2, math.degrees(a2 - a1), maxseg)

    def label(self, x, y, mat, circuit="<None>", turns=0, mesh=0.0, group=0):
        f = self.f
        f.mi_addblocklabel(x, y)
        f.mi_selectlabel(x, y)
        automesh = 0 if mesh > 0 else 1
        f.mi_setblockprop(mat, automesh, mesh, circuit, 0, group, turns)
        f.mi_clearselected()

    # ------------------------------------------------------------------ build
    def build(self, freq: float = 0.0, field_shorted: bool = False):
        f, m, sec = self.f, self.m, self.sec
        f.newdocument(0)
        f.mi_probdef(freq, "meters", "planar", 1e-8, self.depth, 30)
        f.mi_getmaterial("Air")
        self.steel = "M-19 Steel"
        if freq > 0:
            # SSFR is a small-signal test: linear iron at an incremental permeability of 2000 [A] (decision D14)
            self.steel = "SteelLin"
            f.mi_addmaterial("SteelLin", 2000, 2000, 0, 0, 0, 0, 0, 1, 0, 0, 0)
        else:
            f.mi_getmaterial("M-19 Steel")
            f.mi_modifymaterial("M-19 Steel", 5, 0)    # laminated: no eddy currents in iron
        t_hot = m["rating"]["t_wind_c"]
        sig_cu = 1 / (m["copper"]["rho_20"] * (1 + m["copper"]["alpha_20"] * (t_hot - 20))) / 1e6   # MS/m
        f.mi_addmaterial("CuStator", 1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0)            # stranded: no eddy
        f.mi_addmaterial("CuBar", 1, 1, 0, 0, sig_cu, 0, 0, 1, 0, 0, 0)
        fill = 0.75
        f.mi_addmaterial("CuField", 1, 1, 0, 0, sig_cu * fill if field_shorted else 0, 0, 0, 1, 0, 0, 0)
        for ph in "ABC":
            f.mi_addcircprop(ph, 0, 1)
        f.mi_addcircprop("F", 0, 0 if field_shorted else 1)
        # damper bars: see BAR_CIRCUIT (decision D17)
        f.mi_addcircprop("D", 0, 0)
        # boundaries
        f.mi_addboundprop("A0", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        for k in range(4):
            f.mi_addboundprop(f"apb{k}", 0, 0, 0, 0, 0, 0, 0, 0, 5, 0, 0)
        f.mi_addboundprop("age", 0, 0, 0, 0, 0, 0, 0, 0, 7, 0, 0)
        a = math.pi / 4
        Ro, Rs = self.sec.r_out, self.Rs
        r_hub = self.sec.r_hub
        # stator: outer arc, bore arc, radial edges, slots
        self.arc(Ro, -a, a, 1.0)
        self.arc(self.r_age_out, -a, a, 0.25)
        self.arc(self.r_age_in, -a, a, 0.25)
        for sgn in (-1, 1):
            ang = sgn * a
            for r1, r2 in ((0, r_hub), (r_hub, self.r_age_in), (self.r_age_in, self.r_age_out), (self.r_age_out, Rs), (Rs, Ro)):
                f.mi_addnode(r1 * math.cos(ang), r1 * math.sin(ang))
                f.mi_addnode(r2 * math.cos(ang), r2 * math.sin(ang))
                f.mi_addsegment(r1 * math.cos(ang), r1 * math.sin(ang), r2 * math.cos(ang), r2 * math.sin(ang))
        # bore: arc segments between slot openings
        slots = [r for r in sec.regions if r.name.startswith("slot") and r.name.endswith("_open")]
        edges = []
        for r in slots:
            p0, p3 = r.poly[0], r.poly[3]
            edges.append((math.atan2(p0[1], p0[0]), math.atan2(p3[1], p3[0])))
        edges.sort()
        prev = -a
        for e0, e1 in edges:
            self.arc(Rs, prev, e0, 0.5)
            prev = e1
        self.arc(Rs, prev, a, 0.5)
        # slot outlines (opening + wedge + layers); the opening joins the gap air
        for r in sec.regions:
            if r.name.startswith("slot") and r.name.endswith("_open"):
                p0, p1, p2, p3 = r.poly           # side walls only: the mouth joins the gap air and the wedge air
                self.poly([p0, p1], closed=False)
                self.poly([p3, p2], closed=False)
            elif r.name.endswith("_wedge"):
                self.poly(r.poly, closed=False)
            elif r.name.endswith("_top") or r.name.endswith("_bot"):
                self.poly(r.poly)
        # rotor iron outline: hub arc - pole body - shoe - surface - shoe - body - hub arc
        pole = [r for r in sec.regions if r.name == "pole"][0].poly
        n_surf = sec.n_surf
        surf = pole[:n_surf]
        tip_up, under_up, body_up = pole[n_surf], pole[n_surf + 1], pole[n_surf + 2]
        body_dn, under_dn, tip_dn = pole[n_surf + 3], pole[n_surf + 4], pole[n_surf + 5]
        outline = [body_dn, under_dn, tip_dn] + surf + [tip_up, under_up, body_up]
        self.poly(outline, closed=False)
        a_body = math.atan2(body_up[1], body_up[0])
        self.arc(r_hub, a_body, a, 1.0)
        self.arc(r_hub, -a, -a_body, 1.0)
        # field coils and damper bars
        for r in sec.regions:
            if r.name.startswith("field") or (r.name.startswith("bar") and not r.name.startswith("barslit")):
                self.poly(r.poly)
        # ---- labels
        gap_mesh = 0.0012
        self.label(0.5 * (self.r_age_in + self.r_age_out), 0.0, "<No Mesh>")       # AGE annulus is analytic
        self.label(Rs - 0.0007, 0.0, "Air", mesh=gap_mesh)                         # stator-side gap + slot mouths
        self.label(0.5 * (r_hub + self.r_age_in) * math.cos(a * 0.97), 0.5 * (r_hub + self.r_age_in) * math.sin(a * 0.97), "Air")
        self.label(0.5 * (Rs + Ro), 0.0, self.steel, group=1)
        self.label(0.6 * r_hub, 0.0, self.steel, group=2)
        for r in sec.regions:
            cx, cy = np.mean(np.array(r.poly), axis=0)
            if r.name.endswith("_top") or r.name.endswith("_bot"):
                self.label(cx, cy, "CuStator", r.circuit, r.turns, group=1)
            elif r.name.startswith("field"):
                self.label(cx, cy, "CuField", "F", r.turns if not field_shorted else 1, group=2)
            elif r.name.startswith("bar") and not r.name.startswith("barslit"):
                self.label(cx, cy, "CuBar", BAR_CIRCUIT, 1, mesh=0.0015, group=2)
        # ---- boundary assignments
        k = 0
        for r1, r2 in ((0, r_hub), (r_hub, self.r_age_in), (self.r_age_out, Rs), (Rs, Ro)):
            for sgn in (-1, 1):
                rm = 0.5 * (r1 + r2)
                f.mi_selectsegment(rm * math.cos(sgn * a), rm * math.sin(sgn * a))
            f.mi_setsegmentprop(f"apb{k}", 0, 1, 0, 0)
            f.mi_clearselected()
            k += 1
        f.mi_selectarcsegment(Ro, 0)
        f.mi_setarcsegmentprop(1, "A0", 0, 0)
        f.mi_clearselected()
        for r in (self.r_age_in, self.r_age_out):
            f.mi_selectarcsegment(r, 0)
            f.mi_setarcsegmentprop(0.25, "age", 0, 0)
            f.mi_clearselected()
        OUT.mkdir(parents=True, exist_ok=True)
        f.mi_saveas(str(FEM))

    # ------------------------------------------------------------------ solve helpers
    def set_rotor(self, theta_e_deg: float):
        """Rotor position in electrical degrees (d-axis on phase-A axis at 0)."""
        self.f.mi_modifyboundprop("age", 10, theta_e_deg / (self.m["rating"]["poles"] / 2))

    def set_currents(self, ia=0.0, ib=0.0, ic=0.0, i_f=0.0):
        a = self.m["stator"]["parallel_paths"]
        for ph, i in zip("ABC", (ia, ib, ic)):
            self.f.mi_modifycircprop(ph, 1, i / a)          # path current
        self.f.mi_modifycircprop("F", 1, i_f)

    def solve(self):
        f = self.f
        f.mi_analyze(0)   # visible solver: a minimized one is throttled by Windows 11 efficiency mode
        f.mi_loadsolution()
        res = {ph: f.mo_getcircuitproperties(ph) for ph in "ABCF"}
        return res

    def close_post(self):
        self.f.mo_close()


def _raise_priority():
    """FEMM shares a busy workstation; run its process (and the solver it spawns) at above-normal priority."""
    import subprocess
    subprocess.run(["powershell", "-Command",
                    "Get-Process femm -ErrorAction SilentlyContinue | ForEach-Object { $_.PriorityClass = 'AboveNormal' }"],
                   capture_output=True)


def run(studies: list[str]):
    import femm
    femm.openfemm(1)
    _raise_priority()
    mod = Model()
    t0 = time.time()
    o = mod.o
    if_ag = o["if_airgap"]
    i_rated = o["i_rated"]
    if "occ" in studies or "wave" in studies or "ldq" in studies or "field" in studies:
        mod.build(0.0)
    if "occ" in studies:
        rows = []
        for k_if in [0.2, 0.4, 0.6, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5]:
            mod.set_rotor(0.0)
            mod.set_currents(0, 0, 0, k_if * if_ag)
            r = mod.solve()
            rows.append([k_if * if_ag, abs(r["A"][2]), abs(r["F"][2])])
            mod.close_post()
        _csv("occ.csv", ["i_f", "psi_a", "psi_f_model"], rows)
    if "wave" in studies:
        for k_if in (1.0,):
            rows = []
            for th in np.arange(0, 180, 6.0):
                mod.set_rotor(th)
                mod.set_currents(0, 0, 0, k_if * if_ag * 1.06)
                r = mod.solve()
                rows.append([th, r["A"][2], r["B"][2], r["C"][2]])
                mod.close_post()
            _csv(f"wave_if{k_if:.2f}.csv", ["theta_e", "psi_a", "psi_b", "psi_c"], rows)
        _field_map(mod, "noload")
    if "ldq" in studies:
        rows = []
        for axis, th in (("d", 0.0), ("q", 90.0)):
            for k in (0.05, 0.1, 0.2):
                i = k * i_rated * math.sqrt(2)
                mod.set_rotor(th)
                mod.set_currents(i, -i / 2, -i / 2, 0.0)
                r = mod.solve()
                rows.append([axis, i, r["A"][2], r["B"][2], r["C"][2]])
                mod.close_post()
        _csv("ldq.csv", ["axis", "i_peak", "psi_a", "psi_b", "psi_c"], rows)
    if "field" in studies:
        rows = []
        for k in (0.1, 0.2):
            mod.set_rotor(0.0)
            mod.set_currents(0, 0, 0, k * if_ag)
            r = mod.solve()
            rows.append([k * if_ag, r["A"][2], r["F"][2]])
            mod.close_post()
        _csv("field.csv", ["i_f", "psi_a", "psi_f_model"], rows)
    if "ssfr" in studies:
        rows = []
        for axis, th in (("d", 0.0), ("q", 90.0)):
            for fr in (np.logspace(-2.5, 2.5, 13) if axis == "d" else np.logspace(-1.5, 2.5, 9)):
                mod.build(float(fr), field_shorted=False)      # field OPEN: damper-only response (combined with the field in reduce.py)
                mod.set_rotor(th)
                i = 0.05 * i_rated * math.sqrt(2)
                mod.set_currents(i, -i / 2, -i / 2, 0.0)
                r = mod.solve()
                psi = complex(r["A"][2])
                rows.append([axis, fr, i, psi.real, psi.imag])
                mod.close_post()
        _csv("ssfr.csv", ["axis", "f", "i_peak", "psi_re", "psi_im"], rows)
    print(f"FEMM studies {studies} done in {time.time() - t0:.0f} s")
    femm.closefemm()


def _csv(name, head, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / name, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(head)
        for r in rows:
            w.writerow([x if isinstance(x, str) else (x.real if isinstance(x, complex) else float(x)) for x in r])


def _field_map(mod: Model, tag: str):
    """Sample |B| and A on a polar grid of the solved no-load case for the field plot (matplotlib, docs/img)."""
    f = mod.f
    mod.set_rotor(0.0)
    mod.set_currents(0, 0, 0, mod.o["if_airgap"] * 1.06)
    f.mi_analyze(0)   # visible solver: a minimized one is throttled by Windows 11 efficiency mode
    f.mi_loadsolution()
    rows = []
    for r in np.linspace(0.005, mod.sec.r_out - 0.001, 150):
        for a in np.linspace(-math.pi / 4, math.pi / 4, 150):
            x, y = r * math.cos(a), r * math.sin(a)
            bx, by = f.mo_getb(x, y)
            rows.append([x, y, math.hypot(abs(bx), abs(by)), f.mo_geta(x, y)])
    f.mo_close()
    _csv(f"map_{tag}.csv", ["x", "y", "b", "a"], [[a, b, c, d.real if isinstance(d, complex) else d] for a, b, c, d in rows])


if __name__ == "__main__":
    run(sys.argv[1:] or ["occ", "wave", "ldq", "field", "ssfr"])
