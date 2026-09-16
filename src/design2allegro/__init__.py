"""Compile YAML circuit designs to offline-verified Allegro Telesis packages."""

from .compiler import compile_design
from .loader import load_design
from .model import CompiledDesign, ElectricalError

__version__ = "2.0.0"


def check_design(compiled):
    return compiled.check()


def export_design(compiled, output_dir):
    import json

    from .annotation import deliver
    from .telesis import export

    report = compiled.check()
    if not report.ok:
        raise ElectricalError("electrical DRC blocked export: " + report.markdown())

    def writer(annotated, destination):
        mapping = {
            "version": 1,
            "parts": {
                identity: {"package": part["footprint"]}
                for identity, part in annotated.data["parts"].items()
            },
        }
        return export(
            annotated,
            destination,
            mapping,
            rules=json.loads(annotated.rules_json),
            waivers=json.loads(annotated.waivers_json),
        )

    return deliver(compiled, output_dir, writer)


__all__ = [
    "load_design",
    "compile_design",
    "check_design",
    "export_design",
    "CompiledDesign",
    "ElectricalError",
]
