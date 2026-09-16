"""File dependencies, lexical symbols and deterministic module elaboration."""

import copy
import hashlib
from dataclasses import dataclass
from pathlib import Path

from .expressions import Expr, error, evaluate, materialize, typed
from .syntax import MarkedDict, Parser, Reference


class BoundReference(Reference):
    pass


@dataclass
class Symbol:
    kind: str
    value: object
    env: object
    source: tuple


class Environment:
    def __init__(self, parent=None, path=""):
        self.parent, self.path = parent, path
        self.symbols, self.cache, self.active = {}, {}, []

    def add(self, name, symbol):
        if name in self.symbols and self.symbols[name] is not symbol:
            error(
                f"duplicate declaration {name!r}; first at {self.symbols[name].source}",
                symbol.source,
            )
        self.symbols[name] = symbol

    def find(self, name, source):
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.find(name, source)
        error(f"unknown symbol {name!r}", source)

    def required(self, name, kind, source):
        try:
            symbol = self.find(name, source)
        except ValueError:
            error(f"unknown {kind} {name!r}", source)
        return symbol

    def lookup(self, name, source):
        symbol = self.find(name, source)
        if symbol.kind != "value":
            error(f"{name!r} is not a constant, parameter or group", source)
        env = symbol.env
        key = id(symbol)
        if len(env.active) >= 64:
            error("constant/parameter dependency depth limit exceeded", source)
        if key in env.active:
            error(f"constant/parameter dependency cycle at {name}", source)
        if key not in env.cache:
            env.active.append(key)
            try:
                kind, value, location = symbol.value
                env.cache[key] = typed(tree(value, env, numeric=True), kind, location)
            finally:
                env.active.pop()
        return env.cache[key]


def tree(value, env, *, numeric=False):
    if isinstance(value, Expr):
        if value.op == "literal" and value.args[1] is not None and not numeric:
            evaluate(value, env.lookup)
            return value.args[0] + " " + value.args[1]
        result = evaluate(value, env.lookup)
        # Lookup groups are already bound in their definition environment.
        return result if numeric else finish(result, value.source)
    if isinstance(value, BoundReference):
        return value
    if isinstance(value, Reference):
        path = ".".join(filter(None, [env.path.replace("/", "."), str(value)]))
        return BoundReference(path, value.kind, value.source)
    if isinstance(value, dict):
        result = copy.copy(value)
        if isinstance(result, MarkedDict):
            result.locations = value.locations.copy()
        result.clear()
        for k, v in value.items():
            key = tree(k, env, numeric=numeric)
            if key in result:
                error(
                    "duplicate evaluated object key",
                    getattr(value, "source", ("<memory>", 0, 0)),
                )
            result[key] = tree(v, env, numeric=numeric)
        return result
    if isinstance(value, list):
        return [tree(v, env, numeric=numeric) for v in value]
    return value


def finish(value, source):
    if isinstance(value, list):
        return [finish(v, source) for v in value]
    return materialize(value, source)


def add_bindings(env, bindings):
    for name, definition in bindings.items():
        env.add(name, Symbol("value", definition, env, definition[2]))


def merge_rules(target, rules, env, prefix=""):
    from .rules import intersect

    evaluated = tree(rules, env)
    for rule in evaluated.get("rules", []):
        rule["id"] = "/".join(filter(None, [prefix, rule["id"]]))
        if any(r["id"] == rule["id"] for r in target["rules"]):
            error(
                "duplicate rule ID " + rule["id"], getattr(rule, "source", rules.source)
            )
        if "selector" in rule and env.path:
            rule["selector"]["pattern"] = env.path + "/" + rule["selector"]["pattern"]
        if "scope" in rule and (
            not isinstance(rule["scope"], list)
            or any(not isinstance(v, Reference) for v in rule["scope"])
        ):
            error("rule scope requires typed references or a group", rule.source)
        target["rules"].append(rule)
    if evaluated.get("models"):
        target["models"] = intersect(target.get("models", {}), evaluated["models"])
    if evaluated.get("description"):
        desc = evaluated["description"]
        target["description"] = (
            target["description"] + "\n" + desc if "description" in target else desc
        )


def load_source(path, inputs):
    cache, active, texts = {}, [], {}

    def read(file, fragment=False):
        file = file.resolve()
        if len(active) >= 64:
            error("include depth limit exceeded", (str(file), 1, 1))
        if file in active:
            error(
                "include cycle: " + " -> ".join(map(str, active + [file])),
                (str(file), 1, 1),
            )
        if file in cache:
            if fragment and "name" in cache[file][0]:
                error("included files cannot declare a board", (str(file), 1, 1))
            return cache[file]
        active.append(file)
        try:
            if file.suffix != ".circuit":
                error("include requires a .circuit file", (str(file), 1, 1))
            raw = file.read_bytes()
            texts[file] = raw.decode("utf-8")
            document = Parser(texts[file], str(file)).parse(raw=True, fragment=fragment)
            if fragment and document.language_version != 2:
                error("included fragments require circuit 2", (str(file), 1, 1))
            inputs[str(file)] = hashlib.sha256(raw).hexdigest()
            env = Environment()
            imports = []
            for spelling, alias, source in document.includes:
                include = Path(spelling)
                if include.is_absolute() or not spelling or "://" in spelling:
                    error("include requires an explicit relative file path", source)
                try:
                    child = read(file.parent / include, True)
                except (OSError, UnicodeError, ValueError) as exc:
                    error(
                        f"{exc}\nincluded from {file}:{source[1]}:{source[2]}", source
                    )
                imports.append((alias, child))
                for name, symbol in child[1].symbols.items():
                    env.add(".".join(filter(None, [alias, name])), symbol)
            add_bindings(env, document.bindings)
            for kind, declarations in [
                ("template", document.templates),
                ("module", document["modules"]),
            ]:
                for name, value in declarations.items():
                    env.add(name, Symbol(kind, value, env, value.source))
            result = (document, env, imports, file)
            cache[file] = result
            return result
        finally:
            active.pop()

    try:
        root = read(Path(path))
    except UnicodeError as exc:
        error(f"invalid UTF-8: {exc}", (str(path), 1, 1))
    if root[0].language_version == 1:
        return Parser(texts[Path(path).resolve()], str(Path(path).resolve())).parse()
    return elaborate(root)


def elaborate(root):
    doc, root_env, _, _ = root
    if isinstance(doc.get("id"), Expr):
        error("board identity cannot be parameterized", doc.source)
    result = tree(
        {
            k: v
            for k, v in doc.items()
            if k not in ("modules", "rules", "waivers", "accessories")
        },
        root_env,
    )
    result = MarkedDict(result, source=doc.source)
    result.locations = doc.locations.copy()
    modules = MarkedDict()
    result["modules"] = modules
    rules = MarkedDict(version=1, rules=[], source=doc.source)
    result["rules"] = rules
    mounted = set()

    def collect(unit, namespace=""):
        document, env, imports, file = unit
        key = (file, namespace)
        if key in mounted:
            return
        mounted.add(key)
        for alias, child in imports:
            collect(child, ".".join(filter(None, [namespace, alias])))
        for name in document.bindings:
            env.lookup(name, document.bindings[name][2])
        if "rules" in document:
            merge_rules(rules, document["rules"], env, namespace)
        for waiver in document.get("waivers", []):
            w = tree(waiver, env)
            if namespace:
                w["rule"] = namespace + "/" + w["rule"]
            result.setdefault("waivers", []).append(w)
        for accessory in document.get("accessories", []):
            a = tree(accessory, env)
            if namespace:
                a["id"] = namespace.replace(".", "-") + "-" + a["id"]
            result.setdefault("accessories", []).append(a)

    collect(root)
    seen = 0

    def expand(symbol, arguments, caller, path, identity, stack, call_source):
        nonlocal seen
        if symbol.kind != "module":
            error("expected module", call_source)
        if id(symbol) in stack or len(stack) >= 64:
            error("recursive module or module depth limit exceeded", call_source)
        seen += 1
        if seen > 100000:
            error("expanded instance limit exceeded", call_source)
        module = symbol.value
        env = Environment(symbol.env, path)
        parameters = module.parameters
        if set(arguments) - set(parameters):
            error(
                "unknown module arguments: "
                + str(sorted(set(arguments) - set(parameters))),
                call_source,
            )
        for name, (kind, default, source) in parameters.items():
            if name in arguments:
                value = tree(arguments[name], caller, numeric=True)
            elif default is not None:
                value = default
            else:
                error("missing required module argument " + name, call_source)
            env.add(name, Symbol("value", (kind, value, source), env, source))
        add_bindings(env, module.bindings)
        for name in env.symbols:
            env.lookup(name, env.symbols[name].source)
        out = tree(module, env)
        out["parts"] = MarkedDict(source=module.source)
        for name, part in module["parts"].items():
            for field in ("id", "identity_namespace"):
                if isinstance(part.get(field), Expr):
                    error("identity fields cannot be parameterized", part.source)
            config = tree(part, env)
            template = getattr(part, "template", None)
            if template is not None:
                definition = env.required(template, "template", part.source)
                if definition.kind != "template":
                    error("expected template", part.source)
                merged = tree(definition.value, definition.env)
                for key, value in config.items():
                    if (
                        key in ("properties", "electrical")
                        and isinstance(value, dict)
                        and isinstance(merged.get(key), dict)
                    ):
                        merged[key].update(value)
                    else:
                        merged[key] = value
                    merged.locations[key] = config.locations.get(key, part.source)
                merged.template_source = merged.source
                merged.source = part.source
                config = merged
            out["parts"][name] = config
        if hasattr(module, "local_rules"):
            merge_rules(rules, module.local_rules, env, identity)
        key = module.declaration_name
        if key in modules:
            key += "_" + str(seen)
        modules[key] = out
        for name, instance in module["instances"].items():
            if isinstance(instance.get("id"), Expr):
                error("instance identity cannot be parameterized", instance.source)
            target = env.required(instance["module"], "module", instance.source)
            childpath = "/".join(filter(None, [path, name]))
            childid = "/".join(filter(None, [identity, instance["id"]]))
            try:
                child = expand(
                    target,
                    instance.arguments,
                    env,
                    childpath,
                    childid,
                    stack + [id(symbol)],
                    instance.source,
                )
            except ValueError as exc:
                error(f"{exc}\ninstantiated at {call_source}", instance.source)
            out["instances"][name]["module"] = child
        return key

    result["top"] = expand(
        root_env.required(doc["top"], "top module", doc.source),
        {},
        root_env,
        "",
        "",
        [],
        doc.source,
    )
    return result
