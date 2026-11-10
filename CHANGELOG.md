# Changelog

## 1.0.0 (2026-11-10)
- Systems-engineering dossier (Wasson spine): need, ConOps, modes, requirements, architecture, budgets, trade study, M&S, FMEA, V&V. Exported to PDF.
- Analytic design of the 800 kVA reference machine (`bta/design.py`) and its 2-D section (`bta/geometry.py`).
- FEMM 4.2 model of one pole pitch with an anti-periodic air-gap element. Studies: OCC, EMF waveform and THD, Ld/Lq, field inductances, SSFR. The CSV results are cached for CI.
- RMS dq dynamic model with OCC saturation, IEEE 421.5 AC8B/AC8C-type excitation (shunt or PMG supply), diesel engine and deep-bar induction motor.
- ISO 8528-5 metrics, six-alternative trade study with per-alternative AVR tuning, requirement gates, weight Monte Carlo.
- Dip budget by cause, parameter tornado, X'd threshold sweep, data-sheet-class robustness check.
- Damper of 9 bars per pole with ideal continuous end rings (decision D17), after a 6-bar FEMM run showed X''d ≈ X'd. The earlier runs are kept in `femm/out/prelim_*`.
- AVR ceiling needed by the PMG alternative for the 3 pu fault-current requirement (`scripts/check_a3_ceiling.py`).
- Detailed rotating-rectifier model: open-diode and short-diode signatures and their effect on the G3 margin.
- End-ring resistance referred to the FEMM damper with the analytic cage formula, k_ring = 1.49 (decision D18). T''d moves from 29.7 ms to 19.9 ms, and the SR-01 margin from 0.32 to 0.05 points. All studies were rerun.
- Stator-skew what-if on the FEMM harmonics (D19): THD 2.27 % unskewed, 2.02 % with a one-slot-pitch skew.
- Base-frame redesign screen for a lower X'd (`scripts/screen_redesign.py`, DOSSIER §8.6, D20).
- THF item closed: IEC 60034-1 clause 9.11 now specifies THD (D13).
- PDF fixes: nested lists, cross-section title (9 bars), legend placement in the score and motor-start figures.
- 14 model-verification tests; CI re-reduces the cached FEMM results and re-runs the dynamics.
