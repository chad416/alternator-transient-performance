"""Run the trade study: tune + evaluate every alternative, score, gates, weight sensitivity -> results/aoa.json."""
import json
import sys
import time
from pathlib import Path

from bta.aoa import gates, load_alternatives, run_all, scores, weight_sensitivity
from bta.build import load_plant

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    quick = "--quick" in sys.argv
    src = "femm" if "--femm" in sys.argv else "analytic"
    t0 = time.time()
    alts = load_alternatives()
    lim = load_plant()["limits"]
    res = run_all(source=src, quick=quick)
    for k, r in res.items():
        r.update(cost=alts[k]["cost"], risk=alts[k]["risk"], integration=alts[k]["integration"])
        r["gates"] = gates(r, lim)
        print(k, r["name"], json.dumps({g: bool(v) for g, v in r["gates"].items()}), flush=True)
    sc = scores(res)
    sens = weight_sensitivity(res)
    eligible = {k: v for k, v in sc.items() if all(res[k]["gates"].values())}
    out = {"source": src, "quick": quick, "results": res, "scores": sc, "eligible": list(eligible),
           "weight_sensitivity_win_share": sens, "runtime_s": time.time() - t0}
    name = "aoa_quick.json" if quick else f"aoa_{src}.json"
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / name).write_text(json.dumps(out, indent=1, default=float))
    print("scores", {k: round(v, 1) for k, v in sc.items()}, "eligible", list(eligible), "win share", sens, flush=True)
