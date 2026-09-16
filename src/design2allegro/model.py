"""Independent immutable electrical intermediate representation."""

import hashlib
import json
from dataclasses import dataclass


class ElectricalError(ValueError):
    """Invalid design or blocked electrical delivery."""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class CompiledDesign:
    _json: str
    rules_json: str = '{"version":1,"rules":[]}'
    waivers_json: str = "[]"
    design_path: str = ""

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def digest(self):
        data = self.data
        data.pop("inputs", None)
        for part in data["parts"].values():
            part.pop("source", None)
        return digest(data)

    def check(self, rules=None, waivers=None):
        from .rules import check

        report = check(
            self,
            json.loads(self.rules_json) if rules is None else rules,
            json.loads(self.waivers_json) if waivers is None else waivers,
        )
        from .rules import CheckReport

        data = report.data
        for identity, part in self.data["parts"].items():
            for name in part.get("missing_properties", []):
                data["diagnostics"].append(
                    {
                        "rule": "PROPERTY.REQUIRED",
                        "object": identity,
                        "status": "FAIL",
                        "severity": "ERROR",
                        "message": "missing required property: " + name,
                        "required": True,
                        "evidence": {},
                        "source": part.get("source", []),
                        "path": "/".join(part["hierarchy"]),
                    }
                )
                data["ok"] = False
        from collections import Counter

        data["coverage"]["status_counts"] = dict(
            Counter(d["status"] for d in data["diagnostics"])
        )
        return CheckReport(canonical(data))
