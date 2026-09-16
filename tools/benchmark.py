"""10,000 physical pins through real Circuit loading, checking and delivery."""

import json
import resource
import time
from pathlib import Path

from design2allegro import check_design, compile_design, export_design, load_design
from design2allegro.verify import verify_package

root = Path(__file__).resolve().parents[1] / "build/parser/benchmark/circuit2"
root.mkdir(parents=True, exist_ok=True)
count = 10000
(root / "cell.circuit").write_text(
    'circuit 2;\nconst DEFAULT_R: resistance = 10 kohm;\ntemplate resistor {\n    device = "generic.resistor"; package = "resistor_0603"; assembly = fitted;\n    properties { tolerance = 1 %; power_rating = 0.1 W; }\n}\nmodule cell(r: resistance = $DEFAULT_R) {\n    ports A, B;\n    part resistor using resistor { id = "resistor"; properties { resistance = $r; } }\n    net A = port.A, resistor.A;\n    net B = port.B, resistor.B;\n}\n'
)
lines = [
    'circuit 2; include "cell.circuit";',
    'board benchmark { id = "benchmark-circuit2"; library = "standard@1"; top = board; }',
    "module board {",
]
for i in range(count // 2):
    lines.append(f'instance cell_{i}: cell(r = $DEFAULT_R * 2) {{ id = "cell-{i}"; }}')
for i in range(count // 2):
    lines.append(f"net N{i} = cell_{i}.B, cell_{(i + 1) % (count // 2)}.A;")
lines.append("}")
(root / "board.circuit").write_text("\n".join(lines) + "\n")
t0 = time.perf_counter()
loaded = load_design(root / "board.circuit")
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
