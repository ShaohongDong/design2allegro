from pathlib import Path

import pytest
import yaml

from design2allegro import compile_design, load_design


class Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def write_yaml(path, data):
    path.write_text(yaml.dump(data, Dumper=Dumper, sort_keys=False))


@pytest.fixture
def make_board(tmp_path):
    def make(parts, nets, nc=(), rules=None):
        components = {}
        for ref, functions in parts.items():
            components[ref] = {
                "package": "PKG_" + ref,
                "pins": {
                    str(n): {"name": str(n), "type": kind}
                    for n, kind in functions.items()
                },
            }
        module = {
            "parts": {ref: {"component": ref} for ref in parts},
            "nets": {
                name: {
                    "endpoints": [{"part": ref, "pin": str(pin)} for ref, pin in ends]
                }
                for name, ends in nets.items()
            },
            "nc": [{"part": ref, "pin": str(pin)} for ref, pin in nc],
        }
        doc = {
            "version": 1,
            "libraries": ["parts.yaml"],
            "top": "board",
            "references": {ref: ref for ref in parts},
            "modules": {"board": module},
        }
        if rules is not None:
            doc["rules"] = rules
        write_yaml(tmp_path / "parts.yaml", {"version": 1, "components": components})
        write_yaml(tmp_path / "board.yaml", doc)
        return compile_design(load_design(tmp_path / "board.yaml"))

    return make
