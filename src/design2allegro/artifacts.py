"""Deterministic design-derived component, procurement and pin documentation."""

import csv
import io
from collections import defaultdict

from .model import canonical


def table(title, headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    return (
        "\n".join(
            [
                "# " + title,
                "",
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
            ]
            + ["| " + " | ".join(cell(v) for v in row) + " |" for row in rows]
        )
        + "\n"
    )


def generate(data):
    components = []
    pins = []
    footprints = []
    groups = defaultdict(list)
    for identity, part in sorted(
        data["parts"].items(), key=lambda item: item[1]["reference"]
    ):
        ref = part["reference"]
        row = {
            k: part[k]
            for k in (
                "id",
                "reference",
                "device",
                "category",
                "properties",
                "normalized_properties",
                "footprint",
                "package_id",
                "assembly",
                "description",
                "library_source",
            )
        }
        row["path"] = "/".join(part["hierarchy"])
        components.append(row)
        group = {
            k: row[k]
            for k in ("device", "normalized_properties", "footprint", "assembly")
        }
        groups[canonical(group)].append(row)
        mapping = []
        for key in part["pins"]:
            pin = data["pins"][key]
            pins.append(
                [
                    ref,
                    identity,
                    pin["name"],
                    pin["num"],
                    "NC" if pin["nc"] else pin["net"],
                ]
            )
            mapping.append(pin["name"] + " → " + pin["num"])
        footprints.append(
            [
                ref,
                identity,
                part["footprint"],
                ", ".join(mapping),
                canonical(part["library_source"]),
            ]
        )
    bom = []
    for group, rows in sorted(groups.items()):
        first = rows[0]
        bom.append(
            [
                first["device"],
                first["assembly"],
                len(rows),
                ", ".join(r["reference"] for r in rows),
                first["footprint"],
                canonical(first["normalized_properties"]),
            ]
        )
    for a in data.get("accessories", []):
        bom.append(
            [
                a["description"],
                a["assembly"],
                a["quantity"],
                "accessory:" + a["id"],
                "",
                "{}",
            ]
        )
    headers = [
        "Device",
        "Assembly",
        "Quantity",
        "References",
        "Footprint",
        "Specifications (SI)",
    ]
    csvfile = io.StringIO(newline="")
    writer = csv.writer(csvfile, lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(bom)
    return {
        "components.json": canonical(
            {
                "version": 2,
                "components": components,
                "accessories": data.get("accessories", []),
            }
        )
        + "\n",
        "references.json": canonical(data["references"]) + "\n",
        "BOM.csv": csvfile.getvalue(),
        "BOM.md": table("Bill of Materials", headers, bom),
        "PINOUT.md": table(
            "Pinout", ["Reference", "Identity", "Logical pin", "Pad", "Net"], pins
        ),
        "FOOTPRINTS.md": table(
            "Footprints",
            ["Reference", "Identity", "Allegro symbol", "Pin mapping", "Source"],
            footprints,
        ),
    }
