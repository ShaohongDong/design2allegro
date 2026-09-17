"""Circuit lexer and source-located AST; file loading lives in elaboration."""

import copy
import json
import math
import re
from dataclasses import dataclass

from .model import ElectricalError


class MarkedDict(dict):
    def __init__(self, *args, source=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        self.locations = {}


class Reference(str):
    """A typed functional path; ordinary strings are never resolved."""

    def __new__(cls, value, kind, source):
        obj = super().__new__(cls, value)
        obj.kind, obj.source = kind, source
        return obj

    def __reduce__(self):
        return (Reference, (str(self), self.kind, self.source))


@dataclass(frozen=True)
class Token:
    text: str
    kind: str
    source: tuple


TOKEN = re.compile(
    r"(?P<space>\s+)|(?P<comment>//[^\n]*)|"
    r'(?P<string>"(?:[^"\\\n]|\\.)*")|'
    r"(?P<number>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<word>[A-Za-z_µΩ%][A-Za-z0-9_µΩ%./-]*)|"
    r"(?P<symbol>[{}\[\]();,:=])"
)


TOKEN2 = re.compile(
    r"(?P<space>\s+)|(?P<comment>//[^\n]*)|"
    r'(?P<string>"(?:[^"\\\n]|\\.)*")|'
    r"(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)|"
    r"(?P<word>[A-Za-z_µΩ%][A-Za-z0-9_µΩ%.]*)|"
    r"(?P<symbol>[{}\[\]();,:=$+*/-])"
)


def lex(text, filename):
    trivia = r"(?:\s|//[^\n]*(?:\n|$))*"
    pattern = (
        TOKEN2
        if re.match(trivia + r"circuit\b" + trivia + "2" + trivia + ";", text)
        else TOKEN
    )
    offset, line, column = 0, 1, 1
    while offset < len(text):
        match = pattern.match(text, offset)
        source = (str(filename), line, column)
        if not match:
            raise ElectricalError(
                f"{filename}:{line}:{column}: unexpected character {text[offset]!r}"
            )
        raw = match.group()
        if match.lastgroup not in ("space", "comment"):
            yield Token(raw, match.lastgroup, source)
        lines = raw.count("\n")
        column = len(raw.rsplit("\n", 1)[-1]) + 1 if lines else column + len(raw)
        line += lines
        offset = match.end()
    yield Token("<eof>", "eof", (str(filename), line, column))


class Parser:
    def __init__(self, text, filename):
        self.tokens = iter(lex(text, filename))
        self.token = next(self.tokens)
        self.depth = 0
        self.version = 1

    def error(self, message, source=None):
        raise ElectricalError(
            ":".join(map(str, source or self.token.source)) + ": " + message
        )

    def take(self):
        token = self.token
        if token.kind != "eof":
            self.token = next(self.tokens)
        return token

    def accept(self, text):
        if self.token.text == text:
            self.take()
            return True
        return False

    def expect(self, text):
        if not self.accept(text):
            self.error(f"expected {text!r}, found {self.token.text!r}")

    def name(self):
        if self.token.kind == "string":
            token = self.take()
            try:
                return json.loads(token.text)
            except ValueError as exc:
                self.error(str(exc), token.source)
        if self.token.kind not in ("word", "number"):
            self.error("expected name or quoted string")
        return self.take().text

    def put(self, mapping, key, value, source):
        if key in mapping:
            self.error(f"duplicate declaration {key!r}", source)
        mapping[key] = value
        mapping.locations[key] = source

    def reference(self, kind, source):
        self.expect("(")
        path = self.name()
        while self.version == 2 and self.accept("/"):
            path += "/" + self.name()
        if self.accept("["):
            path += "[" + self.name() + "]"
            self.expect("]")
        self.expect(")")
        return Reference(path, kind, source)

    def value(self):
        self.depth += 1
        if self.depth > 64:
            self.error("value nesting limit (64) exceeded")
        try:
            if self.token.text == "{":
                return self.block()
            if self.accept("["):
                values = []
                if not self.accept("]"):
                    while True:
                        values.append(self.value())
                        if self.accept("]"):
                            break
                        self.expect(",")
                return values
            if self.version == 2 and (
                self.token.kind == "number" or self.token.text in ("$", "(", "+", "-")
            ):
                return self.expression()
            token = self.take()
            if token.kind == "string":
                try:
                    return json.loads(token.text)
                except ValueError as exc:
                    self.error(str(exc), token.source)
            if token.kind == "number":
                if self.token.kind == "word":
                    # Units are a single explicit token (kohm, pF, %, ...).
                    return token.text + " " + self.take().text
                try:
                    number = (
                        float(token.text)
                        if any(c in token.text for c in ".eE")
                        else int(token.text)
                    )
                except ValueError:
                    self.error(
                        "numeric literal exceeds supported precision", token.source
                    )
                if isinstance(number, float) and not math.isfinite(number):
                    self.error("numeric literal must be finite", token.source)
                return number
            if token.kind == "word":
                if token.text in ("pin", "part", "net") and self.token.text == "(":
                    return self.reference(token.text, token.source)
                return {"true": True, "false": False, "null": None}.get(
                    token.text, token.text
                )
            self.error("expected value", token.source)
        finally:
            self.depth -= 1

    def expression(self, minimum=0):
        from .expressions import Expr

        self.depth += 1
        if self.depth > 64:
            self.error("expression nesting limit (64) exceeded")
        source = self.token.source
        if self.accept("$"):
            left = Expr("lookup", (self.name(),), source)
        elif self.token.text in ("+", "-"):
            op = self.take().text
            left = Expr(
                "positive" if op == "+" else "negative", (self.expression(3),), source
            )
        elif self.accept("("):
            left = self.expression()
            self.expect(")")
        elif self.token.kind == "number":
            number = self.take().text
            unit = self.take().text if self.token.kind == "word" else None
            left = Expr("literal", (number, unit), source)
        else:
            self.error("expected numeric expression or $name")
        precedence = {"+": 1, "-": 1, "*": 2, "/": 2}
        while self.token.text in precedence and precedence[self.token.text] >= minimum:
            token = self.take()
            right = self.expression(precedence[token.text] + 1)
            left = Expr(token.text, (left, right), token.source)
        self.depth -= 1
        return left

    def binding(self, bindings, keyword, source):
        if self.version != 2:
            self.error("this declaration requires circuit 2", source)
        name = self.name()
        kind = "group"
        if keyword == "const":
            self.expect(":")
            kind = self.name()
        self.expect("=")
        value = self.value()
        self.expect(";")
        self.put(bindings, name, (kind, value, source), source)

    def arguments(self, declarations=False):
        result = MarkedDict(source=self.token.source)
        if not self.accept("("):
            return result
        if self.version != 2:
            self.error("module parameters require circuit 2")
        if not self.accept(")"):
            while True:
                source = self.token.source
                name = self.name()
                if declarations:
                    self.expect(":")
                    kind = self.name()
                    default = self.value() if self.accept("=") else None
                    value = (kind, default, source)
                else:
                    self.expect("=")
                    value = self.value()
                self.put(result, name, value, source)
                if self.accept(")"):
                    break
                self.expect(",")
        return result

    def field(self, result):
        source = self.token.source
        key = self.name()
        if key in ("pin", "part", "net") and self.token.text == "(":
            key = self.reference(key, source)
        if self.token.text == "{":
            value = self.value()
            self.accept(";")
        else:
            self.expect("=")
            value = self.value()
            self.expect(";")
        self.put(result, key, value, source)

    def block(self):
        result = MarkedDict(source=self.token.source)
        self.expect("{")
        while not self.accept("}"):
            self.field(result)
        return result

    def endpoint(self):
        source = self.token.source
        name = self.name()
        if "." not in name:
            self.error("endpoint must be owner.pin or port.name", source)
        owner, member = name.split(".", 1)
        if member == "group" and self.accept("("):
            result = MarkedDict(part=owner, group=self.name(), source=source)
            self.expect(")")
        elif owner == "port":
            result = MarkedDict(port=member, source=source)
        else:
            # Classify after the entire module is parsed, allowing forward declarations.
            result = MarkedDict(owner=owner, member=member, source=source)
        return result

    def endpoints(self):
        result = [self.endpoint()]
        while self.accept(","):
            result.append(self.endpoint())
        return result

    def module(self):
        module = MarkedDict(source=self.token.source)
        for key in ("parts", "instances", "ports", "nets"):
            module[key] = MarkedDict(source=self.token.source)
        module["nc"] = []
        module.bindings = MarkedDict()
        self.expect("{")
        while not self.accept("}"):
            source = self.token.source
            keyword = self.name()
            if keyword == "ports":
                while True:
                    port = self.name()
                    width = 1
                    if self.accept("["):
                        width = self.value()
                        self.expect("]")
                    self.put(
                        module["ports"],
                        port,
                        MarkedDict(width=width, source=source),
                        source,
                    )
                    if not self.accept(","):
                        break
                self.expect(";")
            elif keyword == "part":
                name = self.name()
                if name == "port":
                    self.error("port is reserved for local ports", source)
                template = self.name() if self.accept("using") else None
                part = self.block()
                part.source = source
                if template is not None:
                    part.template = template
                self.put(module["parts"], name, part, source)
            elif keyword == "instance":
                name = self.name()
                if name == "port":
                    self.error("port is reserved for local ports", source)
                self.expect(":")
                target = self.name()
                arguments = self.arguments()
                instance = self.block()
                instance.arguments = arguments
                self.put(instance, "module", target, source)
                self.put(module["instances"], name, instance, source)
            elif keyword == "net":
                name = self.name()
                self.expect("=")
                endpoints = self.endpoints()
                config = (
                    self.block()
                    if self.token.text == "{"
                    else MarkedDict(source=source)
                )
                self.put(config, "endpoints", endpoints, source)
                self.expect(";")
                self.put(module["nets"], name, config, source)
            elif keyword in ("const", "group"):
                self.binding(module.bindings, keyword, source)
            elif keyword == "rules" and self.version == 2:
                if hasattr(module, "local_rules"):
                    self.error("duplicate module rules", source)
                module.local_rules = self.rules()
            elif keyword == "nc":
                module["nc"].extend(self.endpoints())
                self.expect(";")
            else:
                self.error(f"unknown module declaration {keyword!r}", source)
        for ep in [
            ep for n in module["nets"].values() for ep in n["endpoints"]
        ] + module["nc"]:
            if "owner" in ep:
                owner, member = ep.pop("owner"), ep.pop("member")
                if owner in module["instances"]:
                    ep.update(instance=owner, port=member)
                else:
                    ep.update(part=owner, pin=member)
        return module

    def rules(self):
        result = MarkedDict(version=1, rules=[], source=self.token.source)
        ids = set()
        self.expect("{")
        while not self.accept("}"):
            if self.token.text != "rule":
                self.field(result)
                continue
            source = self.take().source
            name, kind = self.name(), self.name()
            if name in ids:
                self.error(f"duplicate rule {name!r}", source)
            ids.add(name)
            rule = MarkedDict(id=name, kind=kind, source=source)
            if self.token.text in ("[", "$"):
                rule["scope"] = self.value()
                if isinstance(rule["scope"], list) and any(
                    not isinstance(x, Reference) for x in rule["scope"]
                ):
                    self.error(
                        "rule scope requires pin(), part() or net() references", source
                    )
            if self.accept(";"):
                body = MarkedDict(source=source)
            else:
                body = self.block()
            params = MarkedDict(source=body.source)
            for key, value in body.items():
                dest = (
                    rule
                    if key
                    in ("selector", "required", "severity", "applicable", "origin")
                    else params
                )
                self.put(
                    dest,
                    "source" if key == "origin" else key,
                    value,
                    body.locations[key],
                )
            from .rules import PARAMS

            if kind == "isolated_all" and self.version != 2:
                self.error("isolated_all requires circuit 2", source)
            if kind == "isolated_all" and "scope" not in rule:
                self.error("isolated_all requires an explicit scope or group", source)
            if kind not in PARAMS:
                self.error(f"unknown rule kind {kind!r}", source)
            for key in params:
                if key not in PARAMS[kind]:
                    self.error(
                        f"unknown parameter {key!r} for {kind}", params.locations[key]
                    )
            rule["params"] = params
            result["rules"].append(rule)
        return result

    def parse(self, *, raw=False, fragment=False):
        self.expect("circuit")
        version = self.take().text
        if version not in ("1", "2"):
            self.error("unsupported circuit language version; expected 1 or 2")
        self.version = int(version)
        self.expect(";")
        document = MarkedDict(version=2, modules=MarkedDict(), source=self.token.source)
        templates, board_seen = MarkedDict(), False
        document.templates = templates
        document.bindings = MarkedDict()
        document.includes = []
        document.language_version = self.version
        while self.token.kind != "eof":
            source = self.token.source
            keyword = self.name()
            if keyword == "board":
                if board_seen:
                    self.error("duplicate board declaration", source)
                board_seen = True
                name = self.name()
                body = self.block()
                if set(body) - {"id", "library", "top", "netlist_expectations"}:
                    self.error(
                        "Additional properties are not allowed in board: "
                        + str(
                            sorted(
                                set(body)
                                - {"id", "library", "top", "netlist_expectations"}
                            )
                        ),
                        source,
                    )
                self.put(body, "name", name, source)
                for key, value in body.items():
                    if key == "library" and isinstance(value, str):
                        lib, sep, version = value.rpartition("@")
                        if not sep or not lib or not version:
                            self.error(
                                'library must be "name@version"', body.locations[key]
                            )
                        value = MarkedDict(
                            name=lib, version=version, source=body.locations[key]
                        )
                    self.put(document, key, value, body.locations[key])
            elif keyword == "module":
                name = self.name()
                parameters = self.arguments(declarations=True)
                module = self.module()
                module.parameters = parameters
                module.declaration_name = name
                self.put(document["modules"], name, module, source)
            elif keyword == "include" and self.version == 2:
                if self.token.kind != "string":
                    self.error("include requires a quoted relative path")
                path = self.name()
                alias = self.name() if self.accept("as") else ""
                if alias and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias):
                    self.error("invalid include alias", source)
                self.expect(";")
                document.includes.append((path, alias, source))
            elif keyword in ("const", "group"):
                self.binding(document.bindings, keyword, source)
            elif keyword == "template":
                name = self.name()
                if name == "port":
                    self.error("port is reserved for local ports", source)
                template = self.block()
                allowed = {
                    "device",
                    "package",
                    "assembly",
                    "properties",
                    "electrical",
                    "description",
                }
                if set(template) - allowed:
                    self.error(
                        "template only permits device, package, assembly, properties, electrical, description",
                        source,
                    )
                self.put(templates, name, template, source)
            elif keyword == "rules":
                self.put(document, "rules", self.rules(), source)
            elif keyword == "waiver":
                document.setdefault("waivers", []).append(self.block())
            elif keyword == "accessory":
                name = self.name()
                accessory = self.block()
                self.put(accessory, "id", name, source)
                document.setdefault("accessories", []).append(accessory)
            else:
                self.error(f"unknown declaration {keyword!r}", source)
        if not board_seen and not fragment:
            self.error("missing board declaration")
        if fragment and board_seen:
            self.error("included files cannot declare a board", document.source)
        if raw or self.version == 2:
            return document
        for module in document["modules"].values():
            for name, part in module["parts"].items():
                template_name = getattr(part, "template", None)
                if template_name is None:
                    continue
                if template_name not in templates:
                    self.error(f"unknown template {template_name!r}", part.source)
                merged = copy.deepcopy(templates[template_name])
                for key, value in part.items():
                    if (
                        key in ("properties", "electrical")
                        and isinstance(value, dict)
                        and isinstance(merged.get(key), dict)
                    ):
                        merged[key].update(value)
                        merged[key].locations.update(value.locations)
                    else:
                        merged[key] = value
                    merged.locations[key] = part.locations[key]
                merged.template_source = merged.source
                merged.source = part.source
                module["parts"][name] = merged
        return document


def parse(text, filename="<memory>"):
    return Parser(text, filename).parse()


def resolve_references(value, data):
    """Resolve typed functional references after physical hierarchy expansion."""

    def resolve(ref):
        path = str(ref)
        if ref.kind == "net":
            key = path.replace(".", "/")
            target = data["net_aliases"].get(key, key)
            valid = target in data["nets"]
        else:
            if ref.kind == "part":
                target = data["hierarchy"].get(path.replace(".", "/"))
            else:
                target = None
                # Find the longest existing instance/part path; logical pin names
                # may themselves contain punctuation (including dots).
                for offset in reversed(
                    [i for i, char in enumerate(path) if char == "."]
                ):
                    owner, pin = path[:offset], path[offset + 1 :]
                    identity = data["hierarchy"].get(owner.replace(".", "/"))
                    if identity is not None and identity + "." + pin in data["pins"]:
                        target = identity + "." + pin
                        break
            valid = target in data["pins" if ref.kind == "pin" else "parts"]
        if not valid:
            raise ElectricalError(
                ":".join(map(str, ref.source))
                + f": unknown {ref.kind} reference {path!r}"
            )
        return target

    if isinstance(value, Reference):
        return resolve(value)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            resolved_key = resolve(key) if isinstance(key, Reference) else key
            if resolved_key in result:
                raise ElectricalError(
                    f"duplicate resolved model reference {resolved_key}"
                )
            result[resolved_key] = resolve_references(item, data)
        return result
    if isinstance(value, list):
        return [resolve_references(item, data) for item in value]
    return value


def resolve_rules(rules, data):
    """Selectors match functional slash paths, never generated references or IDs."""
    import fnmatch

    result = resolve_references(rules, data)
    parts = data["hierarchy"]
    candidates = {
        "parts": parts,
        "pins": {
            path + "." + data["pins"][pin]["name"]: pin
            for path, identity in parts.items()
            for pin in data["parts"][identity]["pins"]
        },
        "nets": {name: name for name in data["nets"]},
    }
    for rule in result.get("rules", []):
        selector = rule.pop("selector", None)
        if selector is not None:
            rule["scope"] = sorted(
                {
                    identity
                    for path, identity in candidates[selector["entity"]].items()
                    if fnmatch.fnmatchcase(path, selector["pattern"])
                }
            )
    return result
