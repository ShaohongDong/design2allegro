"""Handwritten language fixtures, independent of the normalized-document writer."""

import json
import re

import pytest

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.formatting import dumps
from design2allegro.syntax import parse
from design2allegro.verify import verify_package

SOURCE = """circuit 1;
// Deliberately declare the template after its instances.
board example { id = "syntax-board"; library = "standard@1"; top = board; }
module board {
    part pullup using resistor {
        id = "stable-r"; identity_namespace = "";
        properties { resistance = 10 kohm; }
    }
    part series using resistor {
        id = "stable-s"; identity_namespace = "";
        properties { resistance = 22 kohm; }
    }
    net SIGNAL = pullup.A, series.A { electrical { role = signal; } };
    nc pullup.B, series.B;
}
template resistor {
    device = "generic.resistor"; package = "resistor_0603"; assembly = fitted;
    properties { resistance = 1 kohm; tolerance = 1 %; power_rating = 0.1 W; }
}
rules {
    rule LINK connected [pin(pullup.A)] { targets = [pin(series.A)]; }
    rule SPARES no_connect [pin(pullup.B), pin(series.B)];
    rule SELECT required { selector { entity = pins; pattern = "*.A"; } }
    rule LITERAL attribute [part(pullup)] { name = role; equals = resistor; }
}
"""


def load(tmp_path, source=SOURCE):
    path = tmp_path / "board.circuit"
    path.write_text(source)
    return compile_design(load_design(path))


def test_templates_refs_selectors_and_delivery(tmp_path):
    c = load(tmp_path)
    assert c.check().ok
    assert c.data["parts"]["stable-r"]["properties"]["resistance"] == "10 kohm"
    assert c.data["parts"]["stable-s"]["properties"]["resistance"] == "22 kohm"
    assert len(c.data["parts"]["stable-r"]["source"]) == 2
    rules = json.loads(c.rules_json)["rules"]
    assert rules[0]["params"]["targets"] == ["stable-s.A"]
    assert rules[2]["scope"] == ["stable-r.A", "stable-s.A"]
    assert rules[3]["params"]["equals"] == "resistor"
    export_design(c, tmp_path / "out")
    assert verify_package(tmp_path / "out") == {"parts": 2, "pins": 4, "nets": 1}


def test_model_keys_net_alias_and_waiver(tmp_path):
    text = (
        SOURCE.replace(
            "rules {",
            """rules {
        models {
            parts { part(pullup) { bank = B0; } }
            pins { pin(pullup.A) { capability = clock; } }
            nets { net(SIGNAL) { domain = LOGIC; } }
        }
        rule RESERVED required [pin(pullup.B)];
        rule BANK attribute [part(pullup)] { name = bank; equals = B0; }
    """,
        )
        + """
    waiver { rule = RESERVED; object = pin(pullup.B); reason = "reserved"; owner = "team"; }
    """
    )
    c = load(tmp_path, text)
    assert c.check().ok
    models = json.loads(c.rules_json)["models"]
    assert models["parts"] == {"stable-r": {"bank": "B0"}}
    assert models["nets"]["SIGNAL"]["domain"] == "LOGIC"
    assert json.loads(c.waivers_json)[0]["object"] == "stable-r.B"


def test_rule_source_parameter_is_distinct_from_origin(tmp_path):
    text = SOURCE.replace("rule LINK connected", "rule LINK voltage").replace(
        "targets = [pin(series.A)];",
        'source = pin(series.A); origin = "datasheet section 4";',
    )
    rule = json.loads(load(tmp_path, text).rules_json)["rules"][0]
    assert rule["params"]["source"] == "stable-s.A"
    assert rule["source"] == "datasheet section 4"


@pytest.mark.parametrize(
    "before,after,match",
    [
        ("part pullup using resistor", "part pullup using missing", "unknown template"),
        (
            "tolerance = 1 %;",
            "tolerance = 1 %; tolerance = 5 %;",
            "duplicate declaration",
        ),
        ("power_rating = 0.1 W;", "power_rating = 0.1 V;", "template at"),
        (
            "template resistor {",
            "template resistor { id = bad;",
            "template only permits",
        ),
        ("pin(series.A)", "pin(missing.A)", "unknown pin reference"),
        ("[pin(pullup.A)]", '["pullup.A"]', "requires pin"),
        (
            "targets = [pin(series.A)];",
            "targtes = [pin(series.A)];",
            "unknown parameter",
        ),
        ("rule LINK connected", "rule LINK nonexistent", "unknown rule kind"),
        ('id = "stable-s"', 'id = "stable-r"', "duplicate stable identity"),
        ("net SIGNAL =", "nc pullup.A; net SIGNAL =", "NC conflicts"),
        ("nc pullup.B, series.B;", "nc pullup.B;", "unconnected endpoint"),
        ("pin(series.A)", "part(series.A)", "unknown part reference"),
        ('library = "standard@1"', 'library = "standard"', "library must"),
    ],
)
def test_located_failures(tmp_path, before, after, match):
    with pytest.raises(ElectricalError, match=match) as exc:
        load(tmp_path, SOURCE.replace(before, after))
    assert re.search(r"board\.circuit:\d+:\d+", str(exc.value))


def test_template_inheritance_does_not_supply_identity(tmp_path):
    with pytest.raises(ElectricalError, match="'id' is a required property"):
        load(tmp_path, SOURCE.replace('id = "stable-r";', ""))


def test_empty_selector_blocks_export(tmp_path):
    c = load(tmp_path, SOURCE.replace('pattern = "*.A"', 'pattern = "absent.*"'))
    assert not c.check().ok
    with pytest.raises(ElectricalError, match="blocked"):
        export_design(c, tmp_path / "out")
    assert not (tmp_path / "design.lock.json").exists()


def test_plain_strings_are_not_resolved(tmp_path):
    c = load(tmp_path, SOURCE.replace("equals = resistor", 'equals = "pullup"'))
    assert json.loads(c.rules_json)["rules"][-1]["params"]["equals"] == "pullup"
    assert not c.check().ok


def test_rename_keeps_annotation_and_stale_rule_fails(tmp_path):
    c = load(tmp_path)
    out = tmp_path / "out"
    export_design(c, out)
    before = (out / "references.json").read_bytes()
    renamed = SOURCE.replace("pullup", "renamed")
    export_design(load(tmp_path, renamed), out)
    assert (out / "references.json").read_bytes() == before
    with pytest.raises(ElectricalError, match="unknown pin reference"):
        load(tmp_path, renamed.replace("pin(renamed.A)", "pin(pullup.A)"))
    assert (out / "references.json").read_bytes() == before


def test_circuit_writer_preserves_typed_nested_models(tmp_path):
    text = SOURCE.replace(
        "rules {", "rules { models { parts { part(pullup) { role = resistor; } } }"
    )
    before = load(tmp_path, text)
    after = load(tmp_path, dumps(parse(text)))
    assert before.digest == after.digest
    assert before.rules_json == after.rules_json


def test_retired_yaml_and_non_utf8(tmp_path):
    p = tmp_path / "board.yaml"
    p.write_text("version: 2")
    with pytest.raises(ElectricalError, match="YAML input retired"):
        load_design(p)
    p = p.with_suffix(".circuit")
    p.write_bytes(b"\xff")
    with pytest.raises(ElectricalError, match="invalid UTF-8"):
        load_design(p)


def test_nesting_limit(tmp_path):
    text = SOURCE.replace(
        "resistance = 10 kohm", "resistance = " + "[" * 65 + "1" + "]" * 65
    )
    with pytest.raises(ElectricalError, match="nesting limit"):
        load(tmp_path, text)


@pytest.mark.parametrize("literal", ["1e999", "9" * 5000])
def test_nonfinite_and_excessive_numbers_are_located(tmp_path, literal):
    with pytest.raises(
        ElectricalError, match="board.circuit:[0-9]+:[0-9]+: numeric literal"
    ):
        load(tmp_path, SOURCE.replace("10 kohm", literal))


def test_fixed_library_specs_cannot_be_overridden_by_template(tmp_path):
    text = SOURCE.replace("generic.resistor", "RC0603FR-071KL.f4611e61").replace(
        'package = "resistor_0603"', 'package = "0603R"'
    )
    with pytest.raises(ElectricalError, match="template at"):
        load(tmp_path, text)


def test_dotted_logical_pin_reference():
    from design2allegro.syntax import Reference, resolve_references

    data = {
        "hierarchy": {"child/r": "fixed-id"},
        "parts": {"fixed-id": {}},
        "pins": {"fixed-id.A.B": {}},
        "nets": {},
        "net_aliases": {},
    }
    assert (
        resolve_references(
            Reference("child.r.A.B", "pin", ("board.circuit", 1, 1)), data
        )
        == "fixed-id.A.B"
    )


def test_local_port_namespace_is_reserved(tmp_path):
    with pytest.raises(ElectricalError, match="port is reserved"):
        load(tmp_path, SOURCE.replace("pullup", "port"))


def test_bus_net_reference_resolves_alias(tmp_path):
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "fixtures/fpga_soc/board.circuit"
    source = path.read_text().replace(
        "rules {",
        """rules {
        models { nets { net(fpga.endpoint.data[0]) { domain = DATA; } } }
        rule ALIAS attribute [net(fpga.endpoint.data[0])] { name = domain; equals = DATA; }
    """,
    )
    compiled = load(tmp_path, source)
    rule = next(
        r for r in json.loads(compiled.rules_json)["rules"] if r["id"] == "ALIAS"
    )
    assert rule["scope"] == ["DATA[0]"]
    assert compiled.check().ok
