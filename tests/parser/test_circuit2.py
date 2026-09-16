"""Circuit 2 dependencies, lexical reuse and dimensional parameters."""

import json
from pathlib import Path

import pytest

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.syntax import Parser
from design2allegro.verify import verify_package

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/parameterized"
COMMON = (FIXTURE / "common.circuit").read_text()
BOARD = (FIXTURE / "board.circuit").read_text()


@pytest.fixture
def project(tmp_path):
    (tmp_path / "common.circuit").write_text(COMMON)
    p = tmp_path / "board.circuit"
    p.write_text(BOARD)
    return p


def compile_file(p):
    return compile_design(load_design(p))


def test_parameter_defaults_units_lexical_scope_and_local_rules(project):
    c = compile_file(project)
    assert c.check().ok
    assert (
        c.data["parts"]["sense-stable/upper"]["normalized_properties"]["resistance"][
            "value"
        ]
        == "20000"
    )
    assert (
        c.data["parts"]["sense-stable/lower"]["normalized_properties"]["resistance"][
            "value"
        ]
        == "10000"
    )
    assert (
        c.data["parts"]["other-stable/upper"]["normalized_properties"]["resistance"][
            "value"
        ]
        == "10000"
    )
    assert (
        c.data["parts"]["other-stable/lower"]["normalized_properties"]["resistance"][
            "value"
        ]
        == "5000"
    )
    rules = {r["id"]: r for r in json.loads(c.rules_json)["rules"]}
    assert rules["sense-stable/SELECT"]["scope"] == [
        "sense-stable/upper.A",
        "sense-stable/upper.B",
    ]
    assert rules["other-stable/MIDPOINT"]["params"]["targets"] == [
        "other-stable/lower.A"
    ]
    assert len(c.data["inputs"]) == 3


def test_include_hash_rename_and_parameter_changes_preserve_refs(project, tmp_path):
    out = tmp_path / "out"
    c = compile_file(project)
    export_design(c, out)
    refs = (out / "references.json").read_bytes()
    common = project.parent / "common.circuit"
    common.write_text(COMMON + "\n// provenance change\n")
    changed = compile_file(project)
    assert changed.data["inputs"] != c.data["inputs"] and changed.digest == c.digest
    project.write_text(
        BOARD.replace("as analog", "as renamed")
        .replace("analog.", "renamed.")
        .replace("*2", "*3")
    )
    export_design(compile_file(project), out)
    assert (out / "references.json").read_bytes() == refs
    assert verify_package(out) == {"parts": 4, "pins": 8, "nets": 6}
    lock = (project.parent / "design.lock.json").read_bytes()
    project.write_text(project.read_text().replace("*3", "/0"))
    with pytest.raises(ElectricalError, match="division by zero"):
        export_design(compile_file(project), out)
    assert (project.parent / "design.lock.json").read_bytes() == lock
    assert (out / "references.json").read_bytes() == refs


def test_shared_and_diamond_includes(project):
    common = project.parent / "common.circuit"
    for name in ("left", "right"):
        (project.parent / (name + ".circuit")).write_text(
            'circuit 2; include "common.circuit";'
        )
    project.write_text(
        BOARD.replace(
            'include "common.circuit" as analog;',
            'include "left.circuit"; include "right.circuit";',
        )
        .replace("const R: resistance = 99 kohm;", "")
        .replace("analog.", "")
    )
    assert compile_file(project).check().ok
    assert len(load_design(project).inputs) == 5
    common.write_text(COMMON.replace("circuit 2;", "circuit 1;"))
    with pytest.raises(ElectricalError):
        load_design(project)


@pytest.mark.parametrize(
    "old,new,match",
    [
        ("$analog.R*2", "$analog.R/0", "division by zero"),
        ("$analog.R*2", "$analog.R + 1 V", "matching dimensions"),
        ("$analog.R*2", "2 V", "wrong dimension"),
        ("$analog.R*2", "true", "expected numeric"),
        ("upper = $analog.R*2", "absent = 1", "unknown module arguments"),
        ("group ROOTS = [", "group ROOTS = [part(sense.hi), ", "one kind"),
        ("pin(sense.hi.A),", "pin(sense.hi.A), pin(sense.hi.A),", "unique references"),
        ("as analog;", 'as analog; include "absent.circuit";', "included from"),
        ('"common.circuit"', '"/tmp/absolute.circuit"', "relative file"),
        (
            "const R: resistance = 99 kohm;",
            "const R: resistance = $S; const S: resistance = $R;",
            "dependency cycle",
        ),
        ('id = "sense-stable"', "id = $R", "identity cannot"),
        ("analog.divider(upper = $analog.R*2)", "missing()", "unknown module"),
    ],
)
def test_invalid_designs(project, old, new, match):
    project.write_text(BOARD.replace(old, new))
    with pytest.raises(ElectricalError, match=match):
        compile_file(project)


def test_cycle_and_include_chain(project):
    common = project.parent / "common.circuit"
    common.write_text('circuit 2; include "board.circuit";')
    with pytest.raises(ElectricalError, match="include cycle") as exc:
        load_design(project)
    assert "common.circuit" in str(exc.value) and "included from" in str(exc.value)


def test_duplicate_exports_and_board_in_fragment(project):
    other = project.parent / "other.circuit"
    other.write_text("circuit 2; const R: resistance = 1 kohm;")
    project.write_text(
        BOARD.replace("as analog;", 'as analog; include "other.circuit";')
    )
    with pytest.raises(ElectricalError, match="duplicate declaration"):
        load_design(project)
    other.write_text('circuit 2; board bad { id="bad"; library="standard@1"; top=x; }')
    with pytest.raises(ElectricalError, match="cannot declare a board"):
        load_design(project)


def test_isolated_all_detects_short_and_nc(project):
    project.write_text(
        BOARD.replace("pin(sense.hi.B)", "pin(sense.lo.A)").replace(
            "pin(sense.hi.A)", "pin(sense.hi.B)"
        )
    )
    c = compile_file(project)
    d = next(d for d in c.check().data["diagnostics"] if d["rule"] == "SEP")
    assert d["status"] == "FAIL"
    assert d["evidence"]["conflicts"]["OUT"] == [
        "sense-stable/upper.B",
        "sense-stable/lower.A",
    ]


def test_missing_argument_and_constant_default_cycle(project):
    p = project.parent / "common.circuit"
    p.write_text(COMMON.replace("upper: resistance = $R", "upper: resistance"))
    with pytest.raises(ElectricalError, match="missing required"):
        compile_file(project)
    p.write_text(
        COMMON.replace("lower: resistance = $upper/2", "lower: resistance = $lower")
    )
    with pytest.raises(ElectricalError, match="dependency cycle"):
        compile_file(project)


def test_pure_parse_does_not_read_includes():
    doc = Parser(BOARD, "/not/a/real/path").parse()
    assert doc.includes == [("common.circuit", "analog", ("/not/a/real/path", 2, 1))]


def test_dimensions_precedence_and_bus_parameters(project):
    source = BOARD.replace(
        "const R: resistance = 99 kohm;",
        """
        const A: resistance = 10 V / 2 mA;
        const B: power = 2 V * 10 mA;
        const C: number = 10 kohm / 5 kohm;
        const D: resistance = -(1 kohm - 3 kohm)*2;
    """,
    ).replace("$analog.R*2", "$A + $D")
    project.write_text(source)
    c = compile_file(project)
    assert (
        c.data["parts"]["sense-stable/upper"]["normalized_properties"]["resistance"][
            "value"
        ]
        == "9000"
    )
    fixture = Path(__file__).resolve().parents[1] / "fixtures/fpga_soc/board.circuit"
    text = (
        fixture.read_text()
        .replace("circuit 1;", "circuit 2;")
        .replace("module endpoint {", "module endpoint(width: integer = 2*2) {")
        .replace("data[4]", "data[$width]", 1)
    )
    project.write_text(text)
    assert compile_file(project).check().ok
    project.write_text(text.replace("2*2", "3/2"))
    with pytest.raises(ElectricalError, match="integer"):
        compile_file(project)


def test_comments_in_version_header(project):
    project.write_text(
        BOARD.replace("circuit 2;", "// header\ncircuit // version\n2 // end\n;")
    )
    assert compile_file(project).check().ok


def test_bounds_and_read_only_check(project):
    assert compile_file(project).check().ok
    assert not (project.parent / "design.lock.json").exists()
    project.write_text(BOARD.replace("$analog.R*2", "+".join(["1 kohm"] * 1000)))
    with pytest.raises(ElectricalError, match="evaluation depth limit"):
        load_design(project)
    project.write_text(BOARD.replace('"common.circuit"', '"level0.circuit"'))
    for i in range(65):
        (project.parent / f"level{i}.circuit").write_text(
            f'circuit 2; include "level{i+1}.circuit";'
        )
    with pytest.raises(ElectricalError, match="include depth limit"):
        load_design(project)


@pytest.mark.parametrize("refs", ["pin(sense.hi.A)", "part(sense.hi), part(sense.lo)"])
def test_isolated_all_rejects_wrong_scope(project, refs):
    source = BOARD.replace("pin(sense.hi.A), pin(sense.hi.B), pin(sense.lo.B)", refs)
    project.write_text(source)
    report = compile_file(project).check()
    assert not report.ok
    assert any(d["rule"] == "CONFIG.INVALID" for d in report.data["diagnostics"])


def test_isolated_all_rejects_nc(project):
    common = project.parent / "common.circuit"
    # Keep the external IN port valid while isolating the selected physical pad.
    common.write_text(
        COMMON.replace("hi.A,port.IN", "spare.A,port.IN").replace(
            "group MID =",
            'part spare using resistor { id = "spare"; properties { resistance = 10 kohm; } } nc hi.A, spare.B; group MID =',
        )
    )
    report = compile_file(project).check()
    assert not report.ok
    assert any(
        d["rule"] == "CONFIG.INVALID" and "NC" in d["message"]
        for d in report.data["diagnostics"]
    )


def test_module_local_models_and_binding_conflicts(project):
    common = project.parent / "common.circuit"
    common.write_text(
        COMMON.replace(
            "rules {",
            """rules {
        models { pins { pin(hi.A) { domain = ANALOG; } } }
        rule DOMAIN attribute [pin(hi.A)] { name = domain; equals = ANALOG; }
    """,
        )
    )
    board = compile_file(project)
    assert board.check().ok
    rules = json.loads(board.rules_json)
    assert set(rules["models"]["pins"]) == {
        "sense-stable/upper.A",
        "other-stable/upper.A",
    }
    project.write_text(
        BOARD.replace(
            "rules { rule SEP",
            """rules {
        models { pins { pin(sense.hi.A) { domain = DIGITAL; } } }
        rule SEP""",
        )
    )
    with pytest.raises(ElectricalError, match="conflict"):
        compile_file(project)


def test_aliases_mount_global_rules_once_and_keep_lexical_constants(project):
    common = project.parent / "common.circuit"
    common.write_text(
        COMMON
        + "\ngroup GLOBAL = [pin(sense.hi.A)];\nrules { rule PRESENT required $GLOBAL; }\n"
    )
    project.write_text(
        BOARD.replace(
            "as analog;",
            'as analog; include "common.circuit" as analog; include "common.circuit" as second;',
        )
    )
    rules = json.loads(compile_file(project).rules_json)["rules"]
    ids = [r["id"] for r in rules]
    assert ids.count("analog/PRESENT") == 1 and ids.count("second/PRESENT") == 1
    assert compile_file(project).check().ok


def test_string_boolean_parameters_and_local_rule_identity(project):
    common = project.parent / "common.circuit"
    common.write_text(
        COMMON.replace(
            "upper: resistance = $R,",
            'package: string = "resistor_0603", fitted: string = fitted, enabled: boolean = true, upper: resistance = $R,',
        )
        .replace(
            'id = "upper";', 'id = "upper"; package = $package; assembly = $fitted;'
        )
        .replace(
            "targets = [pin(lo.A)];", "targets = [pin(lo.A)]; applicable = $enabled;"
        )
    )
    before = compile_file(project)
    project.write_text(
        BOARD.replace("sense:", "renamed:").replace("sense.", "renamed.")
    )
    after = compile_file(project)
    assert {r["id"] for r in json.loads(before.rules_json)["rules"]} == {
        r["id"] for r in json.loads(after.rules_json)["rules"]
    }
    assert after.check().ok
    project.write_text(
        project.read_text().replace(
            "upper = $analog.R*2", "enabled = false, upper = $analog.R*2"
        )
    )
    report = compile_file(project).check()
    assert report.ok
    assert any(
        d["rule"] == "sense-stable/MIDPOINT" and d["status"] == "NOT_APPLICABLE"
        for d in report.data["diagnostics"]
    )


def test_isolated_all_requires_explicit_representatives(project):
    project.write_text(
        BOARD.replace(
            "rule SEP isolated_all $ROOTS;",
            'rule SEP isolated_all { selector { entity = pins; pattern = "sense/*.*"; } }',
        )
    )
    with pytest.raises(ElectricalError, match="explicit scope"):
        compile_file(project)
