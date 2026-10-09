#!/usr/bin/env python3
"""Check native cleanup equivalence or a full-run affected-net manifest."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def rows(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        require(reader.fieldnames is not None and key in reader.fieldnames, f"Missing {key} header: {path}")
        result = {}
        for row in reader:
            require(None not in row and all(value is not None for value in row.values()), f"Malformed row: {path}")
            name = row[key]
            require(bool(name) and name not in result, f"Empty/duplicate {key} {name}: {path}")
            result[name] = row
        return result


def actions(path: Path) -> dict[str, str]:
    result = {name: row["action"] for name, row in rows(path, "net").items()}
    require(set(result.values()) <= {"ordinary_incident_net", "clock_preserved", "physical_constant_cleanup"}, "Unknown cleanup action")
    return result


def action_summary(reference: Path, fast: Path) -> dict[str, int]:
    old, new = actions(reference), actions(fast)
    missing = sorted(set(old) - set(new))
    extra = sorted(set(new) - set(old))
    changed = sorted(name for name in old.keys() & new.keys() if old[name] != new[name])
    require(old == new, f"Affected union differs: missing={missing[:8]}, extra={extra[:8]}, changed_actions={changed[:8]}")
    return {action: sum(value == action for value in old.values()) for action in sorted(set(old.values()))}


def material_route(row: dict[str, str]) -> bool:
    # Native Vivado serializes an empty ROUTE as "{}", which is truthy in Python.
    return bool(row["route"].strip(" \t\r\n{}"))


def compare_native(root: Path) -> dict[str, object]:
    require(all((root / mode / "NATIVE_COMPLETE").is_file() for mode in ("build", "legacy", "fast")), "Incomplete native probe")
    summary = action_summary(root / "legacy/cleanup/unroute.tsv", root / "fast/cleanup/unroute.tsv")
    before = {mode: rows(root / mode / "before.tsv", "net") for mode in ("legacy", "fast")}
    after = {mode: rows(root / mode / "after.tsv", "net") for mode in ("legacy", "fast")}
    require(before["legacy"] == before["fast"], "Fresh checkpoint initial route state differs")
    require(after["legacy"] == after["fast"], "Ordinary/clock/supply or unaffected route state differs")
    require(before["fast"].keys() == after["fast"].keys(), "Live route-state inventory changed")
    scope = actions(root / "fast/cleanup/unroute.tsv")
    ordinary = {name for name, action in scope.items() if action == "ordinary_incident_net"}
    clocks = {name for name, action in scope.items() if action == "clock_preserved"}
    supplies = {name for name, row in before["fast"].items() if row["type"] in {"POWER", "GROUND"}}
    require(len(ordinary) > 512 and bool(clocks) and bool(supplies), "Fixture lacks multi-batch ordinary/clock/supply coverage")
    require(scope.get("VCC_GND_PHYSICAL_NETS") == "physical_constant_cleanup", "Missing device-wide constant cleanup")
    require(ordinary | clocks <= before["fast"].keys(), "Incomplete route-state inventory")
    require(all(before["fast"][name] == after["fast"][name] for name in clocks), "Clock route was changed")
    routed_clocks = {name for name in clocks if before["fast"][name]["route_status"] == "ROUTED" and material_route(before["fast"][name])}
    require(bool(routed_clocks), "No material routed clock was checked")
    routed_ordinary = {name for name in ordinary if before["fast"][name]["route_status"] == "ROUTED"}
    require(all(material_route(before["fast"][name]) for name in routed_ordinary), "Routed ordinary net has no material route")
    witnesses = rows(root / "build/ordinary_witnesses.tsv", "net")
    require(len(witnesses) == 64 and witnesses.keys() <= ordinary, "Fixture lacks 64 affected registered-data witnesses")
    require(all(row["source_slr"] == "SLR0" and row["sink_slr"] == "SLR1" for row in witnesses.values()), "Fixture witness placement regions differ")
    require(witnesses.keys() <= routed_ordinary, "Registered ordinary witness has no complete fabric route")
    require(all(after["fast"][name]["route_status"] == "UNROUTED" and not material_route(after["fast"][name]) for name in routed_ordinary), "Routed ordinary net was not completely unrouted")
    routed_supplies = {name for name in supplies if before["fast"][name]["route_status"] == "ROUTED" and material_route(before["fast"][name])}
    require(bool(routed_supplies), "No material routed supply was checked")
    require(all(after["fast"][name]["route_status"] == "UNROUTED" and not material_route(after["fast"][name]) for name in routed_supplies), "Routed supply was not completely unrouted")
    unaffected = before["fast"].keys() - ordinary - supplies
    require(all(before["fast"][name] == after["fast"][name] for name in unaffected), "Outside ordinary cleanup changed")
    contexts = {mode: {name: row["value"] for name, row in rows(root / mode / "native_context.tsv", "key").items()} for mode in ("legacy", "fast")}
    for key in ("version", "part", "checkpoint", "ordinary_nets", "clock_aliases", "physical_constant_completed_calls"):
        require(contexts["legacy"][key] == contexts["fast"][key], f"Native context differs: {key}")
    require(all(context["completed"] == "1" and context["physical_constant_completed_calls"] == "1" for context in contexts.values()), "Native cleanup incomplete")
    require(int(contexts["fast"]["ordinary_nets"]) == len(ordinary), "Ordinary count differs from manifest")
    require(int(contexts["fast"]["clock_aliases"]) == len(clocks), "Clock count differs from manifest")
    expected_old = (len(ordinary) + 511) // 512
    batch_size = int(contexts["fast"]["batch_size"])
    require(1 <= batch_size <= 1048576, "Invalid native batch size")
    expected_new = (len(ordinary) + batch_size - 1) // batch_size
    require(int(contexts["legacy"]["ordinary_completed_calls"]) == expected_old, "Legacy native call count differs")
    require(int(contexts["fast"]["ordinary_completed_calls"]) == expected_new, "Fast native call count differs")
    require(int(contexts["fast"]["ordinary_started_calls"]) == expected_new, "Fast started/completed native calls differ")
    require(int(contexts["fast"]["exact_native_queries"]) == expected_new, "Fast native collection resolved repeatedly")
    require(0 < int(contexts["fast"]["max_native_collection_size"]) <= batch_size, "Fast native collection exceeds bound")
    require(expected_new < expected_old, "Probe did not reduce native calls")
    checkpoint = root / "baseline_edited.dcp"
    digest = hashlib.sha256()
    with checkpoint.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"status": "PASS", "actions": summary, "route_state_nets": len(before["fast"]), "supply_aliases": len(supplies),
            "routed_ordinary_checked": len(routed_ordinary), "registered_ordinary_witnesses": len(witnesses),
            "routed_clocks_preserved": len(routed_clocks), "routed_supplies_unrouted": len(routed_supplies),
            "legacy_ordinary_calls": expected_old, "fast_ordinary_calls": expected_new, "batch_size": batch_size,
            "legacy_cleanup_ms": int(contexts["legacy"]["cleanup_elapsed_ms"]),
            "fast_cleanup_ms": int(contexts["fast"]["cleanup_elapsed_ms"]), "checkpoint_sha256": digest.hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    native = commands.add_parser("native")
    native.add_argument("root", type=Path)
    manifest = commands.add_parser("manifest")
    manifest.add_argument("reference", type=Path)
    manifest.add_argument("fast", type=Path)
    manifest.add_argument("--ordinary-count", type=int)
    manifest.add_argument("--clock-count", type=int)
    args = parser.parse_args()
    if args.command == "native":
        result = compare_native(args.root)
        (args.root / "comparison.json").write_text(json.dumps(result, indent=2) + "\n")
    else:
        counts = action_summary(args.reference, args.fast)
        for field, count in (("ordinary_incident_net", args.ordinary_count), ("clock_preserved", args.clock_count)):
            if count is not None:
                require(counts.get(field, 0) == count, f"Expected {count} {field}, got {counts.get(field, 0)}")
        result = {"status": "PASS", "actions": counts}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
