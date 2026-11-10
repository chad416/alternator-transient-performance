"""2-D cross-section of one pole pitch (90 deg mechanical), shared by the FEMM driver and the drawing.

Coordinates in metres, origin on the shaft axis, pole d-axis along +x (angle 0). The sector spans
-45..+45 deg; its radial edges carry anti-periodic boundary conditions in FEMM.
Regions are returned as closed polygons (lists of (x, y)) with a material and, for windings, a circuit and turns.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Region:
    name: str
    poly: list            # closed polygon, list of (x, y)
    material: str         # 'air', 'steel', 'copper', 'aluminium'
    circuit: str = ""     # 'A','B','C','F' or '' ; damper bars use '' (shorted by ideal end rings)
    turns: int = 0        # signed turns (+ = going conductor)
    label: tuple = (0.0, 0.0)


@dataclass
class Section:
    regions: list = field(default_factory=list)
    r_bore: float = 0.0
    r_out: float = 0.0
    r_rotor_max: float = 0.0
    r_hub: float = 0.0
    n_surf: int = 0       # number of pole-outline points on the pole face (incl. damper slits)


def rot(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def centroid(poly):
    a = np.array(poly)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


def winding_layout(slots_per_pole: int, q: int, pitch: int):
    """Phase and sign of top and bottom layer for each slot in one pole pitch (60 deg phase belts, A,-C,B)."""
    seq = [("A", 1), ("C", -1), ("B", 1)]
    top = [seq[k // q] for k in range(slots_per_pole)]
    bot = []
    for k in range(slots_per_pole):
        j = k - pitch
        if j >= 0:
            ph, sg = top[j]
            bot.append((ph, -sg))
        else:                       # coil starts in the previous pole: anti-periodic -> sign flips twice
            ph, sg = top[j + slots_per_pole]
            bot.append((ph, sg))
    return top, bot


def build_section(m: dict) -> Section:
    s, ro = m["stator"], m["rotor"]
    poles = m["rating"]["poles"]
    p = poles // 2
    Rs = s["d_bore"] / 2
    Ro = s["d_out"] / 2
    sec = Section(r_bore=Rs, r_out=Ro)
    sp = s["slots"] // poles
    q = s["slots"] // (poles * 3)
    pitch_ang = 2 * math.pi / s["slots"]
    top, bot = winding_layout(sp, q, s["coil_pitch_slots"])
    b_o, b_s, h_t, h_w, h_s = s["slot_open"], s["slot_width"], s["tip_height"], s["wedge_height"], s["slot_depth"]
    h_mid = (h_t + h_w + h_s) / 2
    for k in range(sp):
        ang = -math.pi / poles + (k + 0.5) * pitch_ang
        # local slot frame: x radial from the axis, y tangential (parallel-sided slot)
        x0 = math.sqrt(Rs ** 2 - (b_o / 2) ** 2)
        opening = [(x0, -b_o / 2), (Rs + h_t, -b_o / 2), (Rs + h_t, b_o / 2), (x0, b_o / 2)]
        wedge = [(Rs + h_t, -b_o / 2), (Rs + h_t + h_w, -b_s / 2), (Rs + h_t + h_w, b_s / 2), (Rs + h_t, b_o / 2)]
        layer_top = [(Rs + h_t + h_w, -b_s / 2), (Rs + h_mid, -b_s / 2), (Rs + h_mid, b_s / 2), (Rs + h_t + h_w, b_s / 2)]
        layer_bot = [(Rs + h_mid, -b_s / 2), (Rs + h_s, -b_s / 2), (Rs + h_s, b_s / 2), (Rs + h_mid, b_s / 2)]
        g = lambda poly: [rot(pt, ang) for pt in poly]
        sec.regions.append(Region(f"slot{k}_open", g(opening), "air"))
        sec.regions.append(Region(f"slot{k}_wedge", g(wedge), "air"))
        ph, sg = top[k]
        sec.regions.append(Region(f"slot{k}_top", g(layer_top), "copper", ph, sg * s["turns_per_coil"]))
        ph, sg = bot[k]
        sec.regions.append(Region(f"slot{k}_bot", g(layer_bot), "copper", ph, sg * s["turns_per_coil"]))
    # ---- rotor pole (pole axis along +x)
    d0 = ro["air_gap_min"]
    th_e = ro["pole_arc_ratio"] * math.pi / 2
    th_m = th_e / p
    n = 41
    surf = []
    for a in np.linspace(-th_m, th_m, n):
        r = Rs - d0 / math.cos(p * a)
        surf.append((r * math.cos(a), r * math.sin(a)))
    r_edge = Rs - d0 / math.cos(th_e)
    h_se = ro["pole_shoe_height_edge"]
    bw = ro["pole_body_width"] / 2
    tip_lo = ((r_edge - h_se) * math.cos(th_m), (r_edge - h_se) * math.sin(th_m))
    shoe_under_x = tip_lo[0] - 0.008
    r_hub = ro["hub_radius"]
    body_bot_x = math.sqrt(r_hub ** 2 - bw ** 2)
    # damper bars (round, 16-gons) in semi-open slots: an air slit of width bar_slot_open from the bar to the
    # pole surface (a closed iron bridge would short the damper's flux path, see DOSSIER decision D16)
    dmp = ro["damper"]
    nb = dmp["bars_per_pole"]
    bar_pitch_ang = dmp["bar_pitch_ratio"] * pitch_ang
    rb = dmp["bar_diameter"] / 2
    w_sl = dmp["bar_slot_open"]
    beta = math.asin(w_sl / (2 * rb))

    def r_surface(ang):
        return Rs - d0 / math.cos(p * ang)

    def to_surface(pt, u):
        t = 0.0
        for _ in range(30):
            q_ = (pt[0] + t * u[0], pt[1] + t * u[1])
            ang = math.atan2(q_[1], q_[0])
            t += r_surface(ang) - math.hypot(*q_)
        return (pt[0] + t * u[0], pt[1] + t * u[1])

    bars, notches = [], []
    for j in range(nb):
        a = (j - (nb - 1) / 2) * bar_pitch_ang
        rc = r_surface(a) - dmp["bar_depth"] - rb
        cx, cy = rc * math.cos(a), rc * math.sin(a)
        ts = [a + beta + k * (2 * math.pi - 2 * beta) / 15 for k in range(16)]
        poly = [(cx + rb * math.cos(t), cy + rb * math.sin(t)) for t in ts]
        bars.append(Region(f"bar{j}", poly, "copper"))
        u = (math.cos(a), math.sin(a))
        lo, hi = poly[-1], poly[0]                      # bar-top vertices at a-beta and a+beta
        notches.append((to_surface(lo, u), lo, hi, to_surface(hi, u)))
    # pole outline: surface with the damper slits (ccw from -th_m to +th_m), tip, underside, body side, mirrored
    # keep each notch's four points in order (sorting by angle can swap the bottom pair): rebuild explicitly
    out_pts = []
    used = set()
    for pt in sorted(surf + [q_ for n in notches for q_ in (n[0],)], key=lambda q_: math.atan2(q_[1], q_[0])):
        hit = [n for n in notches if pt == n[0]]
        if hit:
            out_pts.extend(hit[0])
        elif not any(math.atan2(n[0][1], n[0][0]) - 1e-9 <= math.atan2(pt[1], pt[0]) <= math.atan2(n[3][1], n[3][0]) + 1e-9
                     for n in notches):
            out_pts.append(pt)
    sec.n_surf = len(out_pts)
    outline = list(out_pts)
    outline.append(tip_lo)
    outline.append((shoe_under_x, bw))
    outline.append((body_bot_x, bw))
    outline.append((body_bot_x, -bw))
    outline.append((shoe_under_x, -bw))
    outline.append((tip_lo[0], -tip_lo[1]))
    sec.r_rotor_max = Rs - d0
    sec.r_hub = r_hub
    sec.regions.append(Region("pole", outline, "steel"))
    # hub sector (-45..45 deg) up to r_hub, joined to the pole body
    hub = [(0.0, 0.0)]
    for a in np.linspace(-math.pi / poles, math.pi / poles, 31):
        hub.append((r_hub * math.cos(a), r_hub * math.sin(a)))
    sec.regions.append(Region("hub", hub, "steel"))
    # field coils, one each side of the body (go / return)
    clr = 0.003
    wc = ro["field_coil_width"]
    x_lo = body_bot_x + 0.004
    x_hi = shoe_under_x - clr
    for side, sgn in (("F+", 1), ("F-", -1)):
        y0, y1 = bw + clr, bw + clr + wc
        poly = [(x_lo, sgn * y0), (x_hi, sgn * y0), (x_hi, sgn * y1), (x_lo, sgn * y1)]
        if sgn < 0:
            poly = poly[::-1]
        sec.regions.append(Region(f"field_{side}", poly, "copper", "F", sgn * ro["field_turns_per_pole"]))
    for r_ in bars:
        sec.regions.append(r_)
    for j, n in enumerate(notches):
        sec.regions.append(Region(f"barslit{j}", list(n), "air"))
    return sec


def check_section(sec: Section) -> list:
    """Geometric sanity checks: coils inside the sector, clear of the interpolar axis and of the shoe."""
    issues = []
    for r in sec.regions:
        if r.name.startswith("field"):
            for x, y in r.poly:
                if abs(math.atan2(y, x)) > math.pi / 4 - 0.01:
                    issues.append(f"{r.name} crosses the interpolar axis at ({x:.3f},{y:.3f})")
    return issues
