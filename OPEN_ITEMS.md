# Open items

## Publishing (needs the user's approval)

The repository is complete and committed locally as one commit on `main`. It was deliberately not published overnight and waits for the owner's approval. The CI steps were run locally from a fresh clone: 14 tests passed, the FEMM re-reduction reproduced `results/params_femm.json`, and the quick trade-study checks passed. To publish, run from this folder:

```bash
gh repo create chad416/alternator-transient-performance --public --description "Brushless LV alternator transient performance vs ISO 8528-5 G3: FEMM field model, dq dynamics with IEEE 421.5 AC8-type excitation, trade study, FMEA (systems-engineering dossier)" --source . --remote origin
```

```bash
git push -u origin main
```

```bash
gh repo edit chad416/alternator-transient-performance --add-topic synchronous-generator,femm,iso-8528,ieee-421-5,systems-engineering,power-systems,python
```

```bash
gh run watch --repo chad416/alternator-transient-performance
```

## Engineering items still open
- **THF / TIF not computed.** The weighting tables could not be verified (DOSSIER D13). THD is computed.
- **No skew in the 2-D FEMM model.** The slot harmonics (23rd/25th) are therefore conservative.
- **End-ring resistance.** Damper end rings are ideal in FEMM. Halving T''do and T''qo, as a stand-in for real ring resistance, moves the SR-01 dip from −14.68 % to −15.05 %. The next model step is the end-ring impedance in FEMM (or a measured T''d).
- **No base-frame redesign for lower X'd yet.** It is recommended as an extra alternative (DOSSIER §8.5, item 3) but not modelled.
- **ISO 8528-5 and IEC 60034-1/-4-1 values were read through public previews and manufacturer white papers.** Check them against purchased copies before any external use.
- **Engine model is generic.** The engine-speed column of the dip budget is a sensitivity, not a validated prediction.
