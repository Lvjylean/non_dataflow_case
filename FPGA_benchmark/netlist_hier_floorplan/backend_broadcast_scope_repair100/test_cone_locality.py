"""Structural safety and bounded planning tests for SLR round-trip cones."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("cone_locality", ROOT / "code/regional/cone_locality.py")
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


def cell(ref, slr="SLR1", inputs=None, editable=True, config=None):
    return dict(ref=ref, slr=slr, x=3, y=5 if slr == "SLR1" else 2,
                config=config if config is not None else {"INIT": "2'h2"},
                inputs={} if inputs is None else inputs, editable=editable)


def nets_for(cells):
    nets = {}
    for name, obj in cells.items():
        for pin, source in obj["inputs"].items():
            nets.setdefault(source, []).append(name + "/" + pin)
    return nets


class ConeLocality(unittest.TestCase):
    def simple(self):
        return dict(src=cell("FDRE"), a=cell("LUT1", "SLR0", {"I0": "src/Q"}),
                    b=cell("LUT1", "SLR0", {"I0": "a/O"}),
                    local=cell("LUT1", inputs={"I0": "b/O"}),
                    end=cell("URAM288", inputs={"BWE_A[7]": "local/O"}))

    def candidate(self, cells, root="b/O", **kwargs):
        found = planner.discover(cells, nets_for(cells), **kwargs)
        return next(c for c in found["candidates"] if c["root"] == root)

    def test_low_fanout_roundtrip_discovery(self):
        cells = self.simple()
        result = planner.discover(cells, nets_for(cells))
        self.assertEqual(len(result["candidates"]), 1)
        c = result["candidates"][0]
        self.assertEqual(c["clone_cells"], ["a", "b"])
        self.assertEqual(c["target_sinks"], ["local/I0"])
        self.assertEqual(c["source_slrs"], ["SLR1"])
        self.assertEqual(c["endpoint_slrs"], ["SLR1"])

    def test_plan_preserves_original_and_exact_connections(self):
        cells = self.simple()
        before = deepcopy(cells)
        nets = nets_for(cells)
        plan = planner.plan_candidate(cells, nets, self.candidate(cells))
        self.assertEqual(cells, before)
        self.assertEqual(set(plan["clones"]), {"a", "b"})
        a, b = plan["clones"]["a"], plan["clones"]["b"]
        self.assertEqual(a["inputs"], {"I0": "src/Q"})
        self.assertEqual(b["inputs"], {"I0": a["name"] + "/O"})
        self.assertEqual(plan["rewires"], {"local/I0": b["name"] + "/O"})
        self.assertEqual(plan["metadata"]["clone_boundaries"], ["src/Q"])
        self.assertEqual(plan, planner.plan_candidate(cells, nets, self.candidate(cells)))

    def test_all_data_and_selection_inputs_retained(self):
        cells = self.simple()
        cells["select"] = cell("FDRE", "SLR0")
        cells["b"] = cell("LUT3", "SLR0", {"I0": "a/O", "I1": "select/Q", "I2": "ONE"},
                          config={"INIT": "8'hAC"})
        plan = planner.plan_candidate(cells, nets_for(cells), self.candidate(cells))
        self.assertEqual(plan["clones"]["b"]["inputs"]["I1"], "select/Q")
        self.assertEqual(plan["clones"]["b"]["inputs"]["I2"], "ONE")
        self.assertEqual(plan["clones"]["b"]["config"], {"INIT": "8'hAC"})
        self.assertEqual(plan["metadata"]["source_slrs"], ["SLR0", "SLR1"])
        self.assertIn("select", plan["owners"])

    def test_native_constant_keys_preserved(self):
        cells = self.simple()
        cells["b"] = cell("LUT3", "SLR0", {"I0": "a/O", "I1": "constant POWER", "I2": "constant GROUND"})
        c = self.candidate(cells)
        p = planner.plan_candidate(cells, nets_for(cells), c)
        self.assertEqual(p["clones"]["b"]["inputs"]["I1"], "constant POWER")
        self.assertEqual(p["clones"]["b"]["inputs"]["I2"], "constant GROUND")
        self.assertEqual(c["boundaries"]["constant POWER"]["kind"], "constant")

    def test_shared_remote_sink_keeps_original_output(self):
        cells = self.simple()
        cells["other"] = cell("FDRE", "SLR0", {"D": "b/O"})
        nets = nets_for(cells)
        plan = planner.plan_candidate(cells, nets, self.candidate(cells))
        self.assertNotIn("other/D", plan["rewires"])
        self.assertIn("other/D", nets["b/O"])

    def test_stops_cloning_at_local_combinational_boundary(self):
        cells = self.simple()
        cells["a"]["slr"] = "SLR1"
        c = self.candidate(cells)
        self.assertEqual(c["cone"], ["a", "b"])
        self.assertEqual(c["clone_cells"], ["b"])
        plan = planner.plan_candidate(cells, nets_for(cells), c)
        self.assertEqual(plan["clones"]["b"]["inputs"], {"I0": "a/O"})

    def test_no_roundtrip_is_not_candidate(self):
        cells = self.simple()
        cells["src"]["slr"] = "SLR0"
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertEqual(result["rejected"][0]["status"], "no_same_slr_source")

    def test_endpoint_must_be_reachable_in_target_slr(self):
        cells = self.simple()
        cells["end"]["slr"] = "SLR2"
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertTrue(any(r["status"] == "no_local_sequential_endpoint" for r in result["rejected"]))

    def test_complete_mux_macro_copied_atomically(self):
        cells = self.simple()
        cells["data1"] = cell("LUT1", "SLR1", {"I0": "src/Q"})
        cells["b"] = cell("MUXF7", "SLR0", {"I0": "a/O", "I1": "data1/O", "S": "src/Q"})
        c = self.candidate(cells)
        self.assertEqual(c["clone_cells"], ["a", "b", "data1"])
        plan = planner.plan_candidate(cells, nets_for(cells), c)
        self.assertEqual(plan["clones"]["b"]["inputs"]["S"], "src/Q")
        self.assertEqual(plan["clones"]["b"]["inputs"]["I1"], plan["clones"]["data1"]["name"] + "/O")

    def test_incomplete_mux_macro_rejected(self):
        cells = self.simple()
        cells["b"] = cell("MUXF7", "SLR0", {"I0": "a/O", "I1": "src/Q", "S": "src/Q"})
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("incomplete_mux_macro:b", [r["status"] for r in result["rejected"]])

    def test_mux_sink_partial_macro_rejected(self):
        cells = self.simple()
        cells["local"] = cell("MUXF7", inputs={"I0": "b/O", "I1": "src/Q", "S": "src/Q"})
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertTrue(any("target_mux_data_requires_macro_expansion" in r["status"] for r in result["rejected"]))

    def test_protected_clone_cell_rejected(self):
        cells = self.simple()
        cells["a"]["editable"] = False
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("protected_clone_cell:a", [r["status"] for r in result["rejected"]])

    def test_protected_target_sink_never_rewired(self):
        cells = self.simple()
        cells["local"]["editable"] = False
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("protected_target_sink:local/I0", [r["status"] for r in result["rejected"]])

    def test_protected_local_boundary_allowed(self):
        cells = self.simple()
        cells["a"].update(slr="SLR1", editable=False)
        self.assertEqual(self.candidate(cells)["clone_cells"], ["b"])

    def test_missing_pin_rejected(self):
        cells = self.simple()
        cells["b"]["ref"] = "LUT2"
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("incomplete_inputs:b", [r["status"] for r in result["rejected"]])

    def test_unknown_boundary_rejected_with_evidence(self):
        cells = self.simple()
        cells["src"]["ref"] = "DSP48E2"
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("unsupported_boundary:src:DSP48E2", [r["status"] for r in result["rejected"]])

    def test_cycle_rejected(self):
        cells = self.simple()
        cells["a"]["inputs"]["I0"] = "b/O"
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertTrue(any(r["status"].startswith("combinational_cycle:") for r in result["rejected"]))

    def test_bounded_inventory(self):
        cells = self.simple()
        result = planner.discover(cells, nets_for(cells), max_cells=1)
        self.assertFalse(result["candidates"])
        self.assertIn("cone_cell_budget", [r["status"] for r in result["rejected"]])

    def test_stale_candidate_and_changed_sink_rejected(self):
        cells = self.simple()
        c = self.candidate(cells)
        changed = deepcopy(c)
        changed["clone_cells"] = ["b"]
        with self.assertRaisesRegex(planner.LocalityError, "stale_candidate:clone_cells"):
            planner.plan_candidate(cells, nets_for(cells), changed)
        cells["local"]["inputs"]["I0"] = "src/Q"
        with self.assertRaisesRegex(planner.LocalityError, "sink_connectivity_mismatch"):
            planner.plan_candidate(cells, nets_for(cells), c)

    def test_stale_function_and_shared_load_change_rejected(self):
        cells = self.simple()
        c = self.candidate(cells)
        cells["a"]["config"]["INIT"] = "2'h1"
        with self.assertRaisesRegex(planner.LocalityError, "stale_candidate:inventory_signature"):
            planner.plan_candidate(cells, nets_for(cells), c)

    def test_clock_is_not_a_data_endpoint(self):
        cells = self.simple()
        cells["end"] = cell("FDRE", inputs={"C": "local/O"})
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])

    def test_missing_geometry_rejected(self):
        cells = self.simple()
        cells["a"]["x"] = float("nan")
        result = planner.discover(cells, nets_for(cells))
        self.assertFalse(result["candidates"])
        self.assertIn("missing_position", [r["status"] for r in result["rejected"]])

    def test_incomplete_net_inventory_rejected(self):
        cells = self.simple()
        nets = nets_for(cells)
        nets["a/O"] = []
        result = planner.discover(cells, nets)
        self.assertFalse(result["candidates"])
        self.assertIn("input_connectivity_mismatch:b/I0", [r["status"] for r in result["rejected"]])

    def test_memoized_dag_reconvergence(self):
        cells = self.simple()
        for i in range(12):
            cells[f"s{i}"] = cell("LUT2", "SLR0", {"I0": "src/Q" if i == 0 else f"s{i-1}/O",
                                                      "I1": "src/Q" if i == 0 else f"s{i-1}/O"})
            cells[f"z{i}"] = cell("FDRE", inputs={"D": f"s{i}/O"})
        result = planner.discover(cells, nets_for(cells))
        self.assertEqual(len(result["candidates"]), 13)
        self.assertLessEqual(result["stats"]["origin_nodes"], 14)

    def test_planner_requires_global_budget_and_sta(self):
        cells = self.simple()
        plan = planner.plan_candidate(cells, nets_for(cells), self.candidate(cells))
        self.assertTrue(plan["metadata"]["requires_shared_fanout_and_full_sta"])
        self.assertTrue(plan["metadata"]["original_cells_preserved"])


if __name__ == "__main__":
    unittest.main()
