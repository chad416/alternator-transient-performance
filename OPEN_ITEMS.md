# Open items

## Publishing

The first version (commit `6570b06`) is public at https://github.com/chad416/alternator-transient-performance, and its GitHub Actions run passed. The next commit (end-ring referral D18, skew D19, redesign screen D20, PDF fixes) passed the same steps from a fresh local clone and is ready to push. The repository topics are not set yet. From this folder:

```bash
git push origin main
```

```bash
gh repo edit chad416/alternator-transient-performance --add-topic synchronous-generator,femm,iso-8528,ieee-421-5,systems-engineering,power-systems,python
```

```bash
gh run watch --repo chad416/alternator-transient-performance
```

## Engineering items still open
- **FEMM run of the redesign variant.** The redesign screen (DOSSIER §8.6) finds that only an 8 mm air gap with 50 mm slots meets SR-05, by 0.1 points. That geometry needs its own FEMM run (about 90 min), a field coil that fits between the poles for 28 % more field current (D8), and a resized exciter. Only then can it be scored against A5.
- **Measured T''d.** The SR-01 pass (0.05 points) depends on the end-ring resistance, which is referred analytically (D18). A sudden-short-circuit test (IEC 60034-4-1) is the first test to run.
- **ISO 8528-5 and IEC 60034-1/-4-1 values were read through public previews and manufacturer white papers.** Check them against purchased copies before any external use.
- **Engine model is generic.** The engine-speed column of the dip budget is a sensitivity, not a validated prediction.

## Closed on 10 Nov 2026
- **End-ring resistance:** referred to the FEMM damper (D18) and now part of every result.
- **Skew:** bounded as a what-if on the FEMM harmonics (D19). A one-slot-pitch skew lowers THD from 2.27 % to 2.02 %, so SR-07 does not need it.
- **THF:** IEC 60034-1 clause 9.11 now specifies THD for synchronous machines [S4]; THD is computed (D13).
- **Base-frame redesign:** screened (DOSSIER §8.6, D20). The FEMM verification of the one passing variant is the open item above.
