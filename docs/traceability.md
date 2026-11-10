# Traceability: requirement → model → evidence → test

| Requirement | Allocated to | Model / analysis | Evidence (generated) | Verification test in this repo |
|---|---|---|---|---|
| SR-01 block-load dip ≥ −15 % | Main machine, exciter, AVR | `bta/scenarios.block_load` → `bta/metrics.transient_metrics` | DOSSIER §8.1, §6.2; `results/aoa_femm.json` | `test_initial_dip_matches_subtransient_closed_form`, `test_steady_state_is_steady` |
| SR-02 recovery ≤ 4 s to ±1 % | AVR, exciter | same + `recovery_time` | DOSSIER §8.1 | `test_recovery_time_on_synthetic_signal` |
| SR-03 rejection rise ≤ +20 % | AVR, exciter | `load_rejection` | DOSSIER §8.1 | CI quick-AoA run |
| SR-04 rejection recovery ≤ 4 s | AVR | `load_rejection` | DOSSIER §8.1 | CI quick-AoA run |
| SR-05 132 kW DOL start dip ≥ −20 % | Main machine, excitation | `motor_start`, `max_motor_kw` | DOSSIER §8.1, §6.3 | `test_motor_model_matches_equivalent_circuit` |
| SR-06 sustained fault current ≥ 3 pu at 1 s | Excitation source | `short_circuit`; ceiling needed: `scripts/check_a3_ceiling.py` | DOSSIER §8.1, §0 finding 6; `results/a3_ceiling_femm.json` | `test_shunt_collapses_and_pmg_sustains_short_circuit`, CI check |
| SR-07 no-load THD ≤ 5 % | Winding, pole shape | FEMM `wave` → `femm/reduce.waveform` | DOSSIER §6.1 | `test_winding_factor_two_thirds_pitch`; CI re-reduction |
| SR-08 steady state ±1 % | AVR | not analysed (steady state) | — | bench regulation test (sister project) |
| DR-01 X'd limit | Main machine | `scripts/run_studies.xd_sweep` | DOSSIER §6.3 | — |
| DR-02 excitation ranges | Exciter | `scripts/run_studies.sensitivity` | DOSSIER §8.4 | `test_fex_continuity_and_values`, `test_exciter_saturation_passes_through_points` |
| DR-03 OC overshoot ≤ 10 % | AVR | `bta/scenarios.oc_step`, `bta/aoa.tune` | DOSSIER §8.1 (OC overshoot column) | CI quick-AoA run |
| FM-01/02 diode faults | Rectifier | `bta/rectifier.py` | DOSSIER §9 | `test_healthy_bridge_dc_voltage_matches_commutation_formula`, `test_diode_faults_reduce_capability_and_raise_fundamental` |
