"""Compile YAML circuit designs to offline-verified Allegro Telesis packages."""

from .compiler import compile_design
from .loader import load_design
from .model import CompiledDesign, ElectricalError

__version__ = "1.0.0"


def check_design(compiled):
    return compiled.check()


def export_design(compiled, output_dir):
    import json

    from .telesis import export

    mapping = {
        "version": 1,
        "parts": {
            ref: {"package": part["footprint"]}
            for ref, part in compiled.data["parts"].items()
        },
    }
    return export(
        compiled,
        output_dir,
        mapping,
        rules=json.loads(compiled.rules_json),
        waivers=json.loads(compiled.waivers_json),
    )


__all__ = [
    "load_design",
    "compile_design",
    "check_design",
    "export_design",
    "CompiledDesign",
    "ElectricalError",
]
