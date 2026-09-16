import json
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
                "category": "testpoint",
                "prefix": "U",
                "pins": {str(n): {"type": kind} for n, kind in functions.items()},
                "packages": {
                    "test": {
                        "allegro": "PKG_" + ref,
                        "pads": {str(n): str(n) for n in functions},
                    }
                },
            }
        module = {
            "parts": {
                ref: {"id": ref, "device": ref, "package": "test", "assembly": "fitted"}
                for ref in parts
            },
            "nets": {
                name: {
                    "endpoints": [{"part": ref, "pin": str(pin)} for ref, pin in ends]
                }
                for name, ends in nets.items()
            },
            "nc": [{"part": ref, "pin": str(pin)} for ref, pin in nc],
        }
        doc = {
            "version": 2,
            "id": "test-board",
            "name": "test_board",
            "library": {"name": "test", "version": "1"},
            "top": "board",
            "modules": {"board": module},
        }
        if rules is not None:
            doc["rules"] = rules
        library_root = tmp_path / "catalogs"
        (library_root / "test").mkdir(parents=True, exist_ok=True)
        (library_root / "test/1.json").write_text(
            json.dumps(
                {"version": 2, "name": "test", "revision": "1", "devices": components}
            )
        )
        write_yaml(tmp_path / "board.yaml", doc)
        return compile_design(
            load_design(tmp_path / "board.yaml", library_root=library_root)
        )

    return make
