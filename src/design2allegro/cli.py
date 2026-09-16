"""Command line interface; 0 success, 2 invalid design, 1 execution failure."""

import argparse
import json
import sys

from . import __version__, check_design, compile_design, export_design, load_design
from .model import ElectricalError
from .verify import NetlistFormatError, verify_package


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ElectricalError(message)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    json_mode = "--json" in argv
    parser = Parser(prog="design2allegro")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    for command in ("check", "build", "verify"):
        item = sub.add_parser(command)
        item.add_argument("input")
        item.add_argument(
            "--json", action="store_true", help="machine-readable diagnostics"
        )
        if command == "build":
            item.add_argument("-o", "--output", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "verify":
            result = dict(ok=True, statistics=verify_package(args.input))
        else:
            compiled = compile_design(load_design(args.input))
            report = check_design(compiled)
            result = report.data
            if not report.ok:
                print(json.dumps(result) if json_mode else report.markdown())
                return 2
            if args.command == "build":
                result = dict(
                    ok=True,
                    output=args.output,
                    manifest=export_design(compiled, args.output),
                )
            elif not json_mode:
                print(report.markdown())
                return 0
        if json_mode:
            print(json.dumps(result, ensure_ascii=False))
        else:
            stats = result.get(
                "statistics", result.get("manifest", {}).get("statistics", {})
            )
            action = (
                f"Built {args.output}"
                if args.command == "build"
                else f"Verified {args.input}"
            )
            print(
                f"{action}: {stats['parts']} parts, {stats['pins']} pins, {stats['nets']} nets"
            )
            if args.command == "build":
                print("Check report: " + str(args.output) + "/drc.md")
            print("Offline verification only; actual Allegro import is unverified.")
        return 0
    except (
        ElectricalError,
        NetlistFormatError,
        UnicodeError,
        json.JSONDecodeError,
    ) as exc:
        code = 2
        message = str(exc)
    except Exception as exc:
        code = 1
        message = f"{type(exc).__name__}: {exc}"
    print(
        (
            json.dumps({"ok": False, "error": message, "exit_code": code})
            if json_mode
            else message
        ),
        file=sys.stderr,
    )
    return code
