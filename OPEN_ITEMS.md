# Open items

## Publishing

Public at https://github.com/chad416/alternator-transient-performance since 10 Nov 2026, with topics set. GitHub Actions passed on both commits: the first version (run 42764971491) and the end-ring, skew and redesign-screen update (run 42767287185).

## Engineering items still open
- **Measured T''d.** The SR-01 pass (0.05 points) depends on the end-ring resistance, which is referred analytically (D18). A sudden-short-circuit test (IEC 60034-4-1) is the first test to run.
- **ISO 8528-5 and IEC 60034-1/-4-1 values were read through public previews and manufacturer white papers.** Check them against purchased copies before any external use.
- **Engine model is generic.** The engine-speed column of the dip budget is a sensitivity, not a validated prediction.

## Closed on 10 Nov 2026
- **FEMM run of the redesign variant (8 mm gap, 50 mm slots):** solved with the full study set (D21). X'd 0.199 pu, 132 kW start −18.7 % (A1), rated field current ×1.31. The verdict of the L1 screen holds with a 1.3-point margin.
- **End-ring resistance:** referred to the FEMM damper (D18) and now part of every result.
- **Skew:** bounded as a what-if on the FEMM harmonics (D19). A one-slot-pitch skew lowers THD from 2.27 % to 2.02 %, so SR-07 does not need it.
- **THF:** IEC 60034-1 clause 9.11 now specifies THD for synchronous machines [S4]; THD is computed (D13).
- **Base-frame redesign:** screened (DOSSIER §8.6, D20), and the one passing variant verified in FEMM (D21, first item of this list).
