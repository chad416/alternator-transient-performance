# Alternator transient performance vs ISO 8528-5 G3

**Question.** Can an 800 kVA, 400 V, 4-pole brushless alternator with its exciter and AVR meet the ISO 8528-5
**G3** voltage limits (−15 % dip, 4 s recovery) on a full block load and on a direct-on-line motor start? Which
design or AVR parameter decides it?

The study runs geometry → field solution → machine parameters → dynamics → trade study, following a
systems-engineering spine:
- need, ConOps, modes, requirements, architecture;
- budgets, analysis of alternatives, modeling and simulation, FMEA;
- verification and validation.

The full report is in **[DOSSIER.md](DOSSIER.md)** (also as [DOSSIER.pdf](DOSSIER.pdf)).

**Answer (FEMM-derived parameters).** The machine *just* meets the G3 block-load dip: −14.7 % against −15 %,
with 0.3 points of margin. It meets the 4 s recovery once the AVR is retuned (0.97 s). It fails:
- the 132 kW direct-on-line motor start: −22.9 % against −20 %;
- with shunt excitation, the 3 pu sustained fault current.

The deciding parameter is **X'd**: 0.256 pu, against the 0.214 pu the motor start needs. The AVR, exciter and PMG move
the first dip by at most 0.3 points; 12.6 of the 14.7 points are already there at t = 0⁺. Only the next frame with a
PMG meets every requirement. Before that, the dossier recommends challenging the motor requirement and studying a
lower-X'd redesign of the base frame. One open rotating diode is enough to break the dip limit silently; the study
gives its signature on the stationary side.

![Block load](docs/img/block_load.png)

## What is in it

| Level | What | Where |
|---|---|---|
| Design | Analytic salient-pole design: winding, cosine-shaped pole, magnetic circuit, reactances, time constants | `bta/design.py`, `docs/design_notes.md` |
| Field | FEMM 4.2 2-D model of one pole pitch with an anti-periodic air-gap element: OCC, EMF waveform and THD, Ld/Lq, field inductances, standstill frequency response (SSFR) | `femm/femm_model.py`, `femm/reduce.py` |
| Dynamics | dq machine (IEEE 1110 model 2.1) with saturation, IEEE 421.5 AC8B/AC8C-type brushless excitation (shunt or PMG supply), diesel engine with droop and turbo lag, deep-bar induction motor | `bta/dynamics.py` |
| Metrics | ISO 8528-5 transient voltage/frequency deviation and recovery time | `bta/metrics.py` |
| Trade study | Six alternatives: AVR retune, larger exciter, PMG, next frame, combination. Per-alternative PID tuning, requirement gates, weighted scores, weight Monte Carlo | `bta/aoa.py`, `scripts/run_aoa.py` |
| Budgets and sensitivity | Dip budget by cause, tornado of assumed parameters, X'd threshold sweep | `scripts/run_studies.py` |
| Reliability | Detailed rotating rectifier: open- and short-diode signature and effect on the G3 margin | `bta/rectifier.py` |
| Verification | Each model checked against an independent result (closed forms, the equivalent circuit, the commutation formula, published behaviour) | `tests/test_models.py` |

## Results (generated from `results/*.json`)

<!-- TABLE:aoa -->
| | Alternative | KP/KI/KD | OC overshoot | SR-01 dip | SR-02 t_U | SR-03 rise | SR-04 t_U | SR-05 132 kW dip | Max motor @20 % | SR-06 I_sc at 1 s | Gates |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A0 | Baseline (shunt AVR, textbook PID) | 20.7/10.0/4.6 | 0.0 % | -14.73 % | 5.25 s | +17.0 % | 5.11 s | -23.0 % | 111 kW | 0.04 pu | 2/6 |
| A1 | AVR retuned (shunt) | 30.0/60.0/8.0 | 6.0 % | -14.68 % | 0.97 s | +16.9 % | 1.85 s | -22.9 % | 111 kW | 0.04 pu | 4/6 |
| A2 | Larger exciter + retune | 15.0/60.0/8.0 | 6.5 % | -14.42 % | 2.25 s | +17.3 % | 3.27 s | -22.3 % | 115 kW | 0.04 pu | 4/6 |
| A3 | PMG excitation + retune | 30.0/60.0/8.0 | 8.3 % | -14.49 % | 0.97 s | +16.9 % | 1.85 s | -22.3 % | 115 kW | 2.92 pu | 4/6 |
| A4 | Next frame (oversized) + retune | 30.0/90.0/8.0 | 9.7 % | -10.74 % | 0.72 s | +12.6 % | 1.54 s | -17.4 % | 151 kW | 0.05 pu | 5/6 |
| A5 | Next frame + PMG + retune | 30.0/60.0/8.0 | 8.6 % | -10.64 % | 1.01 s | +12.6 % | 1.73 s | -17.1 % | 156 kW | 3.61 pu | 6/6 |
<!-- /TABLE -->

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q                       # model verification
python -m scripts.run_aoa --femm          # trade study on FEMM parameters
python -m scripts.run_studies --femm      # dip budget, sensitivity, X'd sweep, diode FMEA
python -m scripts.check_a3_ceiling        # AVR ceiling the PMG option needs for 3 pu fault current
python -m scripts.make_figures --femm
python -m scripts.make_tables femm        # writes the tables into DOSSIER.md and README.md
```

**FEMM studies** (Windows, FEMM 4.2 and `pyfemm`): `python femm/femm_model.py occ wave ldq field ssfr`, then
`python femm/reduce.py`. CI does not run FEMM. It re-reduces the cached CSVs in `femm/out/` and re-runs everything
else.

## Assumptions and limits

The machine is a study design, not a product. Every value in the dossier is tagged as sourced, derived or assumed,
and every assumption that can change a conclusion is varied (DOSSIER §8.4, §11). Standards that are behind paywalls
(ISO 8528-5, IEC 60034-1/-4-1, IEEE 421.5) were read through their public previews and public implementations, as
listed in the references.

Sister project: [alternator-routine-test-station](https://github.com/chad416/alternator-routine-test-station).
It is the factory routine-test bench whose checks this model can provide expected values for (DOSSIER §10.3).

MIT licence.
