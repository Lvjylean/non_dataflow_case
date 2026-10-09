"""Exercise fail-closed native comparison with compact serialized route states."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from verify_physical_cleanup_probe import action_summary, compare_native


class NativeCleanupComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.ordinary = [f"data_{i}" for i in range(514)]
        self.clocks = ["clock", "hier/clock_alias"]
        self.all_names = self.ordinary + self.clocks + ["VCC", "GND", "outside"]
        self.before = [{"net": name, "type": "POWER" if name == "VCC" else "GROUND" if name == "GND" else "SIGNAL",
                        "route_status": "ROUTED", "route": f"{{NODE_{name} PIP_{name}}}"} for name in self.all_names]
        self.after = [dict(row, route_status="UNROUTED", route="") if row["net"] in self.ordinary + ["VCC", "GND"] else dict(row) for row in self.before]
        self.actions = [{"net": name, "action": "ordinary_incident_net"} for name in self.ordinary]
        self.actions += [{"net": name, "action": "clock_preserved"} for name in self.clocks]
        self.actions += [{"net": "VCC_GND_PHYSICAL_NETS", "action": "physical_constant_cleanup"}]
        for mode in ("build", "legacy", "fast"):
            (self.root / mode).mkdir()
            (self.root / mode / "NATIVE_COMPLETE").write_text("completed 1\n")
        self.write_rows(self.root / "build/ordinary_witnesses.tsv", [
            {"net": name, "source_slr": "SLR0", "sink_slr": "SLR1"} for name in self.ordinary[:64]])
        for mode in ("legacy", "fast"):
            self.write_rows(self.root / mode / "before.tsv", self.before)
            self.write_rows(self.root / mode / "after.tsv", self.after)
            self.write_rows(self.root / mode / "cleanup/unroute.tsv", self.actions)
            values = {"completed": "1", "batch_size": "512" if mode == "legacy" else "32768", "ordinary_nets": "514",
                      "clock_aliases": "2", "ordinary_completed_calls": "2" if mode == "legacy" else "1",
                      "physical_constant_completed_calls": "1", "cleanup_elapsed_ms": "20", "version": "2023.2",
                      "part": "xcu250-figd2104-2L-e", "checkpoint": str(self.root / "baseline_edited.dcp")}
            if mode == "fast":
                values.update(ordinary_started_calls="1", exact_native_queries="1", max_native_collection_size="514")
            self.write_rows(self.root / mode / "native_context.tsv", [{"key": key, "value": value} for key, value in values.items()])
        (self.root / "baseline_edited.dcp").write_bytes(b"immutable test checkpoint")

    def tearDown(self) -> None:
        self.scratch.cleanup()

    @staticmethod
    def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)

    def test_complete_native_equivalence_and_call_count(self) -> None:
        result = compare_native(self.root)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["legacy_ordinary_calls"], 2)
        self.assertEqual(result["fast_ordinary_calls"], 1)
        self.assertEqual(result["supply_aliases"], 2)
        self.assertEqual(result["actions"]["ordinary_incident_net"], 514)
        self.assertEqual(result["registered_ordinary_witnesses"], 64)
        self.assertEqual(result["routed_ordinary_checked"], 514)
        self.assertEqual(result["routed_clocks_preserved"], 2)
        self.assertEqual(result["routed_supplies_unrouted"], 2)

    def replace_both(self, filename: str, values: list[dict[str, str]]) -> None:
        for mode in ("legacy", "fast"):
            self.write_rows(self.root / mode / filename, values)

    def test_native_empty_route_braces_are_accepted_after_unroute(self) -> None:
        values = [dict(row, route="{}") if row["route_status"] == "UNROUTED" else dict(row) for row in self.after]
        self.replace_both("after.tsv", values)
        self.assertEqual(compare_native(self.root)["status"], "PASS")

    def test_empty_clock_braces_are_not_routing_evidence(self) -> None:
        before = [dict(row, route="{}") if row["net"] in self.clocks else dict(row) for row in self.before]
        after = [dict(row, route="{}") if row["net"] in self.clocks else dict(row) for row in self.after]
        self.replace_both("before.tsv", before)
        self.replace_both("after.tsv", after)
        with self.assertRaisesRegex(ValueError, "No material routed clock"):
            compare_native(self.root)

    def test_implicit_and_intrasite_ordinary_fixture_is_rejected(self) -> None:
        values = [dict(row, route_status="HIERPORT" if i % 2 else "INTRASITE", route="{}")
                  if row["net"] in self.ordinary else dict(row) for i, row in enumerate(self.before)]
        self.replace_both("before.tsv", values)
        self.replace_both("after.tsv", [dict(row) if row["net"] in self.ordinary else dict(self.after[i]) for i, row in enumerate(values)])
        with self.assertRaisesRegex(ValueError, "no complete fabric route"):
            compare_native(self.root)

    def test_routed_status_with_empty_ordinary_route_is_rejected(self) -> None:
        values = [dict(row) for row in self.before]
        values[0]["route"] = "{}"
        self.replace_both("before.tsv", values)
        with self.assertRaisesRegex(ValueError, "no material route"):
            compare_native(self.root)

    def test_one_retained_ordinary_route_in_both_modes_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[0] = dict(self.before[0])
        self.replace_both("after.tsv", values)
        with self.assertRaisesRegex(ValueError, "ordinary net was not completely unrouted"):
            compare_native(self.root)

    def test_residual_ordinary_route_despite_unrouted_status_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[0]["route"] = "{residual ordinary PIP}"
        self.replace_both("after.tsv", values)
        with self.assertRaisesRegex(ValueError, "ordinary net was not completely unrouted"):
            compare_native(self.root)

    def test_routed_supply_retained_in_both_modes_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[-3] = dict(self.before[-3])
        self.replace_both("after.tsv", values)
        with self.assertRaisesRegex(ValueError, "supply was not completely unrouted"):
            compare_native(self.root)

    def test_empty_supply_braces_are_not_routing_evidence(self) -> None:
        values = [dict(row, route="{}") if row["type"] in {"POWER", "GROUND"} else dict(row) for row in self.before]
        self.replace_both("before.tsv", values)
        with self.assertRaisesRegex(ValueError, "No material routed supply"):
            compare_native(self.root)

    def test_missing_registered_witness_is_rejected(self) -> None:
        self.write_rows(self.root / "build/ordinary_witnesses.tsv", [
            {"net": name, "source_slr": "SLR0", "sink_slr": "SLR1"} for name in self.ordinary[:63]])
        with self.assertRaisesRegex(ValueError, "64 affected registered-data witnesses"):
            compare_native(self.root)

    def test_missing_ordinary_net_is_rejected(self) -> None:
        self.write_rows(self.root / "fast/cleanup/unroute.tsv", self.actions[1:])
        with self.assertRaisesRegex(ValueError, "Affected union differs"):
            compare_native(self.root)

    def test_same_names_with_changed_clock_action_are_rejected(self) -> None:
        values = [dict(row) for row in self.actions]
        values[-2]["action"] = "ordinary_incident_net"
        self.write_rows(self.root / "fast/cleanup/unroute.tsv", values)
        with self.assertRaisesRegex(ValueError, "changed_actions"):
            compare_native(self.root)

    def test_duplicate_action_is_rejected(self) -> None:
        self.write_rows(self.root / "fast/cleanup/unroute.tsv", self.actions + self.actions[:1])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            compare_native(self.root)

    def test_supply_state_difference_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[-3]["route"] = "residual supply route"
        self.write_rows(self.root / "fast/after.tsv", values)
        with self.assertRaisesRegex(ValueError, "route state differs"):
            compare_native(self.root)

    def test_clock_change_in_both_implementations_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[len(self.ordinary)]["route"] = "changed clock route"
        for mode in ("legacy", "fast"):
            self.write_rows(self.root / mode / "after.tsv", values)
        with self.assertRaisesRegex(ValueError, "Clock route was changed"):
            compare_native(self.root)

    def test_unaffected_route_change_is_rejected(self) -> None:
        values = [dict(row) for row in self.after]
        values[-1]["route"] = "changed outside route"
        for mode in ("legacy", "fast"):
            self.write_rows(self.root / mode / "after.tsv", values)
        with self.assertRaisesRegex(ValueError, "Outside ordinary cleanup changed"):
            compare_native(self.root)

    def test_nonidentical_reopened_baseline_is_rejected(self) -> None:
        values = [dict(row) for row in self.before]
        values[0]["route"] = "other checkpoint route"
        self.write_rows(self.root / "fast/before.tsv", values)
        with self.assertRaisesRegex(ValueError, "initial route state differs"):
            compare_native(self.root)

    def test_incomplete_native_evidence_is_rejected(self) -> None:
        (self.root / "fast/NATIVE_COMPLETE").unlink()
        with self.assertRaisesRegex(ValueError, "Incomplete native probe"):
            compare_native(self.root)

    def test_manifest_is_order_independent(self) -> None:
        self.write_rows(self.root / "fast/cleanup/unroute.tsv", list(reversed(self.actions)))
        result = action_summary(self.root / "legacy/cleanup/unroute.tsv", self.root / "fast/cleanup/unroute.tsv")
        self.assertEqual(result["clock_preserved"], 2)


if __name__ == "__main__":
    unittest.main()
