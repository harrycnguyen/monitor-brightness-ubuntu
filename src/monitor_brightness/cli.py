"""Command line interface: monitor-brightness list|get|set|up|down|doctor|gui."""

from __future__ import annotations

import argparse
import json
import sys

from . import doctor, manager
from .display import BrightnessError, Display, clamp_percent


def _targets(args: argparse.Namespace, found: manager.Discovery) -> list[Display]:
    if not found.displays:
        print("No controllable displays found.", file=sys.stderr)
        for note in found.notes:
            print(f"  note: {note}", file=sys.stderr)
        return []
    if not args.display:
        return found.displays
    picked = manager.select(found.displays, args.display)
    if not picked:
        print(f"No display matches {args.display!r}. Run `monitor-brightness list`.", file=sys.stderr)
    return picked


def _each(displays: list[Display], action) -> int:
    failed = 0
    for d in displays:
        try:
            action(d)
        except (BrightnessError, OSError) as e:
            failed += 1
            print(f"{d.name}: {e}", file=sys.stderr)
    return 1 if failed else 0


def cmd_list(args: argparse.Namespace) -> int:
    found = manager.discover()
    rows = []
    for i, d in enumerate(found.displays, 1):
        try:
            level: int | None = d.get_percent()
        except BrightnessError:
            level = None
        rows.append({"index": i, "id": d.id, "name": d.name, "kind": d.kind, "brightness": level})
    if args.json:
        print(json.dumps({"displays": rows, "notes": found.notes}, indent=2))
        return 0
    for r in rows:
        level = "?" if r["brightness"] is None else f"{r['brightness']}%"
        print(f"{r['index']}  {r['id']:<28} {level:>5}  {r['name']}")
    for note in found.notes:
        print(f"note: {note}", file=sys.stderr)
    return 0 if rows else 1


def cmd_get(args: argparse.Namespace) -> int:
    displays = _targets(args, manager.discover())
    return _each(displays, lambda d: print(f"{d.name}: {d.get_percent()}%")) if displays else 1


def cmd_set(args: argparse.Namespace) -> int:
    displays = _targets(args, manager.discover())
    value = clamp_percent(args.value)
    return _each(displays, lambda d: d.set_percent(value)) if displays else 1


def _step(sign: int):
    def run(args: argparse.Namespace) -> int:
        displays = _targets(args, manager.discover())

        def change(d: Display) -> None:
            d.set_percent(clamp_percent(d.get_percent() + sign * args.amount))

        return _each(displays, change) if displays else 1

    return run


def cmd_doctor(_: argparse.Namespace) -> int:
    problems = doctor.check()
    for p in problems:
        print(f"- {p}")
    if not problems:
        print("DDC/CI setup looks fine.")
    return 1 if problems else 0


def cmd_gui(args: argparse.Namespace) -> int:
    from . import gui

    return gui.run(background=args.background)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="monitor-brightness", description="Per-monitor brightness control.")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn, help: str, display: bool = True) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        if display:
            sp.add_argument("-d", "--display", help="display index, id or part of its name (default: all)")
        return sp

    sp = add("list", cmd_list, "list displays and their brightness", display=False)
    sp.add_argument("--json", action="store_true")
    add("get", cmd_get, "print brightness")
    sp = add("set", cmd_set, "set brightness to a percentage")
    sp.add_argument("value", type=float, help="0-100")
    for name, sign in (("up", 1), ("down", -1)):
        sp = add(name, _step(sign), f"{name} by N percent (default 10)")
        sp.add_argument("amount", nargs="?", type=int, default=10)
    add("doctor", cmd_doctor, "check DDC/CI setup", display=False)
    sp = add("gui", cmd_gui, "run the tray app and open its window", display=False)
    sp.add_argument("--background", action="store_true", help="start in the tray without opening the window")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
