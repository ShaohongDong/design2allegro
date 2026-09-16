"""10,000 physical pins through real YAML loading, checking and delivery."""

import json
import resource
import time
from pathlib import Path

import yaml

from design2allegro import check_design, compile_design, export_design, load_design
from design2allegro.verify import verify_package

root = Path(__file__).resolve().parents[1] / "build/parser/benchmark"
root.mkdir(parents=True, exist_ok=True)
count = 10000
parts = {
    f"resistor_{i}": {
        "id": f"resistor-{i}",
        "device": "generic.resistor",
        "package": "resistor_0603",
        "assembly": "fitted",
        "properties": {
            "resistance": "10 kohm",
            "tolerance": "1 %",
            "power_rating": "0.1 W",
        },
    }
    for i in range(count // 2)
}
nets = {
    "N"
    + str(i): {
        "endpoints": [
            {"part": "resistor_" + str(i), "pin": "B"},
            {"part": "resistor_" + str((i + 1) % (count // 2)), "pin": "A"},
        ]
    }
    for i in range(count // 2)
}
document = {
    "version": 2,
    "id": "benchmark",
    "name": "benchmark",
    "library": {"name": "standard", "version": "1"},
    "top": "board",
    "modules": {"board": {"parts": parts, "nets": nets}},
}
(root / "board.yaml").write_text(yaml.safe_dump(document))
t0 = time.perf_counter()
loaded = load_design(root / "board.yaml")
t1 = time.perf_counter()
compiled = compile_design(loaded)
t2 = time.perf_counter()
report = check_design(compiled)
t3 = time.perf_counter()
assert report.ok
export_design(compiled, root / "output")
t4 = time.perf_counter()
assert verify_package(root / "output")["pins"] == count
result = {
    "pins": count,
    "load_s": t1 - t0,
    "compile_s": t2 - t1,
    "check_s": t3 - t2,
    "export_including_recheck_s": t4 - t3,
    "total_s": t4 - t0,
    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    "snapshot": compiled.digest,
}
(root / "result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
