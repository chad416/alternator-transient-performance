# Design and model notes: the equations, written out

These are the equations the code uses, each derived here or traced to a source. The textbooks [T1]–[T5] were not at
hand, so equation numbers are not cited (DOSSIER §11). Symbols are SI unless stated.

## 1. Winding (bta/design.py `winding_factor`)

For q slots per pole per phase and a slot angle α = π/(slots per pole) in electrical radians, the factors for harmonic ν are:

- **Distribution factor:** k_d,ν = sin(ν q α/2) / (q sin(ν α/2))
- **Pitch factor:** k_p,ν = sin(ν (W/τ_p) π/2)
- **Winding factor:** k_w,ν = k_d,ν · k_p,ν (× skew factor, not used)

With W/τ_p = 2/3, k_p,3 = sin(π) = 0, so the 3rd harmonic EMF vanishes. For q = 4: k_w1 = 0.9577 · 0.8660 = 0.829.

**Series turns.** N = (coils per phase × turns per coil) / parallel paths = (16 × 3)/4 = 12.

## 2. Magnetising inductance over a uniform gap

**Fundamental MMF of one phase.** For a phase with N k_w effective series turns and p pole pairs, the fundamental MMF
amplitude is F₁ = (4/π)·N k_w i / (2p).

**Gap field and flux.** The fundamental gap flux density is B₁ = μ₀F₁/δ_ef, and the flux per pole is Φ = (2/π)·B₁·τ_p·L.

**Phase inductance.** The phase flux linkage is ψ = N k_w Φ, so

L_ph = (4/π²)·μ₀·(N k_w)²·τ_p·L / (p δ_ef)

**Three-phase magnetising inductance (dq).** L_m = (3/2)·L_ph = 6 μ₀ τ_p L (N k_w)² / (π² p δ_ef).

**Effective gap.** δ_ef = k_C·δ, with Carter's coefficient

k_C = τ_s / (τ_s − κ b₀), κ = (2/π)[atan(b₀/2δ) − (δ/b₀) ln(1 + (b₀/2δ)²)]

## 3. Cosine-shaped pole (gap δ(θ) = δ₀/cos θ under the pole, |θ| ≤ θ_p = α_p·π/2)

**Field excitation.** Field MMF F gives B(θ) = (μ₀F/δ_ef) cos θ under the pole. Its fundamental is

B₁ = (4/π)∫₀^θp B₀ cos²θ dθ  →  k_f = B₁/B₀ = (4/π)(θ_p/2 + sin 2θ_p/4)

**d-axis armature MMF.** F₁ cos θ gives B = (μ₀F₁/δ_ef) cos²θ, so the pole part is

k_d,pole = (4/π)(sin θ_p − sin³θ_p/3)

**q-axis armature MMF.** F₁ sin θ gives B = (μ₀F₁/δ_ef) sin θ cos θ, so the pole part is

k_q,pole = (4/π) sin³θ_p/3

**Interpolar region.** An equivalent gap of 8·δ_ef is assumed [A], which gives the small k_d,ip and k_q,ip terms. This
is the weakest part of the analytic model. FEMM (L2) replaces it.

**Result.** L_md = k_d L_m and L_mq = k_q L_m.

## 4. Leakage

**Slot leakage.** L_u = (4m/Q) μ₀ L N² λ_u, for a double-layer, semi-closed, parallel-sided slot. With ε = 1 − W/τ_p:
- k₂ = 1 − 3ε/4
- k₁ = (1 + 3k₂)/4
- λ_u = k₁ h_c/(3b) + k₂ [h_tip/b₀ + 2h_w/(b + b₀)]

**End-winding leakage.** L_w = (4m/Q) q μ₀ N² l_w λ_w. Here l_w is the length of one end connection and λ_w = 0.3 [A].

**Tooth-tip leakage.** L_tip = (4m/Q) μ₀ L N² k₂ · 5(δ/b₀)/(5 + 4δ/b₀).

**Differential leakage.** L_diff = σ_δ L_md, with σ_δ = Σ_{ν≠1, non-triplen} (k_w,ν / (ν k_w1))².

## 5. Field winding, X'd and T'do

**Gap flux per pole per field ampere** (cosine field):

Φ_g/i_f = 2 μ₀ N_f L r sin(θ_p) / (p δ_ef)

**Pole leakage.** Adjacent poles carry opposite MMF, so 2F acts across the shoe-to-shoe gap g_s. Along the body the
MMF difference rises linearly from 0 to 2F, which gives the average F across the body-to-body gap g_b:

P_σ = μ₀ L (h_s/g_s + h_b/(2 g_b)) × 1.3 (end regions [A])

Φ_σ/i_f = 2 · 2 N_f · P_σ (two sides)

**Field self-inductance** (all poles in series): L_ff = 2p N_f (Φ_g + Φ_σ)/i_f.

**Field–phase mutual inductance:** L_afd = N k_w (2/π) k_f (μ₀ N_f/δ_ef) τ_p L.

**Transient inductance.** With the amplitude-invariant Park transform, a short-circuited field reduces the d-axis
inductance by (3/2)·L_afd²/L_ff:

L'_d = L_d − (3/2) L_afd² / L_ff

The 3/2 checks out on the ideal machine (no leakage, uniform gap). There L_ff·L_md = (3/2)·L_afd², so L'_d = L_σ, as
it must.

**Time constants.** T'_do = L_ff / R_f and T'_d = T'_do · L'_d / L_d.

## 6. Damper (approximate, superseded by the FEMM SSFR)

The bars are referred like a cage: factor 4m(N k_w)²/Q_eq, with Q_eq = (bars per pole × 2p)/α_p, scaled by k_d (d axis)
or k_q (q axis). The bar leakage permeance of a round bar under a slot bridge is λ_b = 0.623 + h_bridge/b_open. Then:
- L''_d = L_σ + (1/L_md + 1/L_fσ + 1/L_Dσ)⁻¹
- T''_do = (L_Dσ + L_md ∥ L_fσ)/R_D
- T''_d = T''_do · L''_d / L'_d

## 7. Open-circuit characteristic (magnetic circuit)

For each EMF E:
1. Φ₁ = E_ph/(4.44 f N k_w₁), then B₀ = Φ₁π/(2τ_p L)/k_f.
2. The field MMF per pole is the sum of the gap MMF, B₀δ_ef/μ₀, and the H·l drops in the teeth, yoke, pole body (flux × (1 + leakage)) and hub. The H values come from the B-H table in `config/machine.yaml`.

## 8. Dynamic model (bta/dynamics.py)

**Equivalent circuit from standard parameters.** These are the classical relations that IEEE 1110 and [T4] use for
model 2.1:
- L_ad = X_d − X_l
- L_fd = L_ad(X'_d − X_l)/(L_ad − X'_d + X_l)
- R_fd = (L_ad + L_fd)/(ω₀ T'_do)
- L_1d = L_ad L_fd (X''_d − X_l)/(L_ad L_fd − (X''_d − X_l)(L_ad + L_fd))
- R_1d = (L_1d + L_ad L_fd/(L_ad + L_fd))/(ω₀ T''_do)
- L_1q = L_aq(X''_q − X_l)/(L_aq − X''_q + X_l)
- R_1q = (L_aq + L_1q)/(ω₀ T''_qo)

**Rotor circuits** (per unit, L_ad-reciprocal base):
- dψ_fd/dt = ω₀ (R_fd/L_adu · E_fd − R_fd i_fd)
- dψ_1d/dt = −ω₀ R_1d i_1d
- dψ_1q/dt = −ω₀ R_1q i_1q

E_fd and I_fd are in the IEEE 421.5 base: 1 pu gives 1 pu open-circuit voltage on the air-gap line.

**Stator.** Stator transients are neglected and the speed voltage is kept:
- e_d = −R_a i_d − ω ψ_q
- e_q = −R_a i_q + ω ψ_d
- with ψ_d = −L''_d i_d + ψ''_d and ψ_q = −L''_q i_q + ψ''_q

So the machine is a voltage source behind the salient subtransient impedance [[R_a, −ωX''_q], [ωX''_d, R_a]].

**Saturation.** L_ads = K_sd · L_adu, where K_sd(ψ_ad) is taken from the OCC as the air-gap-line ratio
(K_sd = e/i_fd on the OCC). The loop between K_sd, the network and ψ_ad is solved by fixed-point iteration at every
evaluation.

**Network.** All elements are in the generator dq frame. Loads are constant-impedance, with the reactance proportional
to frequency. The motor is a source E'_m behind R_s + jωX'. KCL gives a 2×2 linear solve.

**Induction motor** (3rd order, stator transients neglected):
- dE'/dt = −(E' − jω(X − X')I)/T'_0 − jω₀(ω − ω_m)E'
- T'_0 = (X_m + X_r)/(ω₀ R_r(s))
- deep-bar effect: R_r(s) = R_r,run + (R_r,lr − R_r,run)√|s| [A]

At steady state this reduces exactly to the textbook equivalent circuit (unit test).

**Excitation (IEEE 421.5 AC8B/AC8C type [S1]).**
- AVR: PID with a derivative filter T_D, then the K_A/(1 + sT_A) power stage, limited to [VRMIN, VRMAX]·(V_t for shunt supply, 1 for PMG). The integrator has anti-windup.
- Exciter: T_E dV_E/dt = V_R − V_FE, with V_FE = (K_E + S_E(V_E))V_E + K_D I_FD.
- Rectifier: E_FD = k_rect · V_E · F_EX(K_C I_FD / V_E). Here k_rect = 1 when healthy, and comes from `bta/rectifier.py` for a failed diode.
- Exciter saturation: S_E is the quadratic through (V_E1, S_E1) and (V_E2, S_E2).

**Engine.**
- PI governor on (ω_ref − ω − R·fuel).
- Actuator lag and combustion lag.
- Fuel limit f_na + (f_max − f_na)·b, where the boost b lags the engine torque by T_boost [A].
- Swing equation: 2H dω/dt = T_m/ω − T_e.

## 9. Rotating rectifier (bta/rectifier.py)

**Solver.** Backward Euler turns each inductor into a conductance plus a history current source. Nodal analysis then
runs over the nodes (a, b, c, star, P), with N grounded. Each diode is a conductance g_on/g_off, and its state is
iterated until it agrees with its voltage.

**Signature.** The armature MMF space vector is f_r = (2/3)(i_a + a i_b + a² i_c), computed in the rotor frame. It is
moved to the stationary field frame by e^(−j(θ − π/2)), so a balanced fundamental appears as DC. The d-axis component
of the result is what couples to the exciter field winding.
