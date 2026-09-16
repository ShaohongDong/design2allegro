"""Render normalized design documents as Circuit 1 source.

Used by generated regression designs and the benchmark. Human-authored templates
and comments are intentionally not reconstructed from a normalized document.
"""

import json
import re

from .syntax import Reference


def key_text(value):
    if isinstance(value, Reference):
        return scalar(value)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(value)):
        return str(value)
    return scalar(value)


def packed(items, indent):
    lines, current = [], " " * indent
    for item in items:
        if current.strip() and len(current) + len(item) + 2 > 100:
            lines.append(current + ",")
            current = " " * indent
        if current.strip():
            current += ", "
        current += item
    if current.strip():
        lines.append(current)
    return "\n".join(lines)


def scalar(value, indent=0):
    if isinstance(value, Reference):
        path = str(value)
        safe = (
            path
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_./-]*(?:\[\d+\])?", path)
            else json.dumps(path)
        )
        return f"{value.kind}({safe})"
    if isinstance(value, (dict, list)):
        if isinstance(value, dict):
            items = [f"{key_text(k)} = {scalar(v)};" for k, v in value.items()]
            opening, closing, separator = "{ ", " }", " "
        else:
            items = [scalar(v) for v in value]
            opening, closing, separator = "[", "]", ", "
        inline = opening + separator.join(items) + closing
        if "\n" not in inline and len(inline) + indent <= 100:
            return inline
        if isinstance(value, dict):
            items = [
                f"{key_text(k)} = {scalar(v, indent + 4)};" for k, v in value.items()
            ]
            separator = "\n"
        else:
            items = [scalar(v, indent + 4) for v in value]
            return "[\n" + packed(items, indent + 4) + "\n" + " " * indent + "]"
        return (
            opening.strip()
            + "\n"
            + separator.join(" " * (indent + 4) + v for v in items)
            + "\n"
            + " " * indent
            + closing.strip()
        )
    if isinstance(value, str) and re.fullmatch(
        r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)? [A-Za-zµΩ%][A-Za-z0-9µΩ%/]*",
        value,
    ):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def identity_paths(document):
    result = {}

    def walk(module_name, path, namespace, stack):
        if module_name in stack or module_name not in document["modules"]:
            return
        module = document["modules"][module_name]
        for local, part in module.get("parts", {}).items():
            identity = "/".join(
                filter(None, [part.get("identity_namespace", namespace), part["id"]])
            )
            result.setdefault(identity, ".".join(filter(None, [path, local])))
        for local, instance in module.get("instances", {}).items():
            walk(
                instance["module"],
                ".".join(filter(None, [path, local])),
                "/".join(filter(None, [namespace, instance["id"]])),
                stack + [module_name],
            )

    walk(document["top"], "", "", [])
    return result


def dumps(document, *, templates=None):
    paths = identity_paths(document)

    def ref(value, kind=None):
        if isinstance(value, Reference):
            return value
        if not isinstance(value, str):
            return value
        if value in paths:
            return Reference(paths[value], kind or "part", ("<generated>", 0, 0))
        owner, sep, pin = value.rpartition(".")
        if sep and owner in paths:
            return Reference(
                paths[owner] + "." + pin, kind or "pin", ("<generated>", 0, 0)
            )
        return Reference(value, kind or "net", ("<generated>", 0, 0))

    def rule_values(value, key=""):
        if isinstance(value, dict):
            return {k: rule_values(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rule_values(v, key) for v in value]
        if isinstance(value, str) and key not in (
            "equals",
            "allowed",
            "description",
            "reason",
            "owner",
            "id",
            "kind",
            "pattern",
        ):
            owner = value.rpartition(".")[0]
            if value in paths or owner in paths:
                return ref(value)
        return value

    def fields(body, indent):
        return [
            " " * indent + f"{key} = {scalar(value, indent)};"
            for key, value in body.items()
        ]

    def endpoint(ep):
        if "group" in ep:
            return f'{ep["part"]}.group({scalar(ep["group"])})'
        if "part" in ep:
            return (
                ep["part"] + "." + ep["pin"]
                if re.fullmatch(r"[A-Za-z0-9_]+", ep["pin"])
                else scalar(ep["part"] + "." + ep["pin"])
            )
        return ep.get("instance", "port") + "." + ep["port"]

    board = {
        k: v
        for k, v in document.items()
        if k not in ("version", "name", "modules", "rules", "waivers", "accessories")
    }
    lib = board["library"]
    board["library"] = lib["name"] + "@" + lib["version"]
    language = (
        2
        if any(
            r["kind"] == "isolated_all"
            for r in document.get("rules", {}).get("rules", [])
        )
        else 1
    )
    lines = [
        f"circuit {language};",
        "",
        "board " + scalar(document["name"]) + " {",
        *fields(board, 4),
        "}",
    ]
    for name, template in (templates or {}).items():
        lines += ["", f"template {name} {{", *fields(template, 4), "}"]
    for name, module in document["modules"].items():
        lines += ["", f"module {name} {{"]
        if module.get("ports"):
            ports = [
                p + (f'[{scalar(v["width"])}]' if v["width"] != 1 else "")
                for p, v in module["ports"].items()
            ]
            lines.append(
                "    ports "
                + (
                    ", ".join(ports)
                    if len(", ".join(ports)) < 88
                    else "\n" + packed(ports, 8)
                )
                + ";"
            )
        for name, part in module.get("parts", {}).items():
            selected = None
            for template_name, template in (templates or {}).items():
                if all(
                    (
                        all(part.get(k, {}).get(a) == b for a, b in v.items())
                        if isinstance(v, dict)
                        else part.get(k) == v
                    )
                    for k, v in template.items()
                ):
                    selected = template_name
                    part = {
                        k: (
                            {a: b for a, b in v.items() if a not in template.get(k, {})}
                            if isinstance(v, dict)
                            else v
                        )
                        for k, v in part.items()
                        if isinstance(v, dict) or k not in template
                    }
                    part = {k: v for k, v in part.items() if v != {}}
                    break
            using = f" using {selected}" if selected else ""
            lines += [f"    part {name}{using} {{", *fields(part, 8), "    }"]
        for name, instance in module.get("instances", {}).items():
            lines += [
                f'    instance {name}: {instance["module"]} {{ '
                + " ".join(
                    f"{k} = {scalar(v)};" for k, v in instance.items() if k != "module"
                )
                + " }"
            ]
        for name, net in module.get("nets", {}).items():
            attrs = {k: v for k, v in net.items() if k != "endpoints"}
            ends = [endpoint(ep) for ep in net["endpoints"]]
            content = ", ".join(ends)
            if len(content) + len(name) > 88:
                content = "\n" + packed(ends, 8)
            lines.append(
                f"    net {name} = "
                + content
                + (" " + scalar(attrs, 4) if attrs else "")
                + ";"
            )
        if module.get("nc"):
            lines.append(
                "    nc\n" + packed([endpoint(ep) for ep in module["nc"]], 8) + ";"
            )
        lines.append("}")
    for accessory in document.get("accessories", []):
        lines += [
            "",
            "accessory " + scalar(accessory["id"]) + " {",
            *fields({k: v for k, v in accessory.items() if k != "id"}, 4),
            "}",
        ]
    if "rules" in document:
        rules = document["rules"]
        if not isinstance(rules, dict):
            raise ValueError("Circuit source requires inline rules")
        lines += ["", "rules {"]
        for key, value in rules.items():
            if key in ("version", "rules"):
                continue
            if key == "models":
                value = {
                    kind: {
                        ref(k, kind[:-1]): rule_values(v) for k, v in objects.items()
                    }
                    for kind, objects in value.items()
                }
            lines += fields({key: value}, 4)
        for rule in rules.get("rules", []):
            header = f'    rule {scalar(rule["id"])} {rule["kind"]}'
            if "scope" in rule:
                header += " " + scalar([ref(v) for v in rule["scope"]], 4)
            body = rule_values(rule.get("params", {}))
            body.update(
                {
                    ("origin" if k == "source" else k): v
                    for k, v in rule.items()
                    if k not in ("id", "kind", "scope", "params")
                }
            )
            if body:
                content = " ".join(f"{k} = {scalar(v, 8)};" for k, v in body.items())
                if "\n" not in header + content and len(header + content) < 100:
                    lines += [header + " { " + content + " }"]
                else:
                    lines += [header + " {", *fields(body, 8), "    }"]
            else:
                lines += [header + ";"]
        lines.append("}")
    for waiver in document.get("waivers", []):
        value = dict(waiver, object=ref(waiver["object"]))
        lines += ["", "waiver " + scalar(value)]
    return "\n".join(line.rstrip() for line in "\n".join(lines).splitlines()) + "\n"
