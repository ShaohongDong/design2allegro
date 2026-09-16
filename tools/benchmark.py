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
parts = {f"R{i}": {"component": "RESISTOR"} for i in range(count // 2)}
nets = {
    "N"
    + str(i): {
        "endpoints": [
            {"part": "R" + str(i), "pin": "B"},
            {"part": "R" + str((i + 1) % (count // 2)), "pin": "A"},
        ]
    }
    for i in range(count // 2)
}
library = {
    "version": 1,
    "components": {
        "RESISTOR": {
            "package": "R0805",
            "pins": {
                "1": {"name": "A", "type": "PASSIVE"},
                "2": {"name": "B", "type": "PASSIVE"},
            },
        }
    },
}
document = {
    "version": 1,
    "libraries": ["parts.yaml"],
    "top": "board",
    "references": {k: k for k in parts},
    "modules": {"board": {"parts": parts, "nets": nets}},
}
(root / "parts.yaml").write_text(yaml.safe_dump(library))
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
