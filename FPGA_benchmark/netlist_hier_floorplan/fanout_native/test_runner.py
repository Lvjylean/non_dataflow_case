"""Runner tests use synthetic byte fixtures and never execute Vivado."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hf2_run", HERE / "run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        self.dcp = self.root / "synthetic.dcp"
        self.dcp.write_bytes(b"Synthetic test fixture, not a Vivado checkpoint")
        (self.source / "membership.tsv").write_text("cell\tmodule\tresource\tref\n")
        (self.source / "regions.tcl").write_text("set planned_regions {}\nset planned_bounds {}\n")
        self.manifest = dict(input_dcp=str(self.dcp), input_sha256=runner.digest(self.dcp),
                             files={p.name: runner.digest(p) for p in self.source.iterdir()})
        self.write_manifest()

    def write_manifest(self):
        (self.source / "manifest.json").write_text(json.dumps(self.manifest))

    def test_prepare_only_is_offline_and_complete(self):
        with patch.object(runner.subprocess, "run", side_effect=AssertionError("No EDA process allowed")):
            state = runner.run(self.source, self.root / "out", prepare_only=True)
        self.assertEqual(state["status"], "PREPARED_NOT_RUN")
        self.assertEqual(state["logical_limit_exclusive"], 100)
        runner.preflight(self.root / "out/code")
        self.assertFalse((self.root / "out/seed_01").exists())
        self.assertEqual(runner.validate_input(self.root / "out/input"), self.manifest)

    def test_new_dependency_closure_and_single_pass_defaults(self):
        output = self.root / "out"
        runner.prepare(self.source, output, {})
        cfg = json.loads((output / "config.json").read_text())
        self.assertEqual(cfg["refinement_passes"], 1)
        self.assertEqual(cfg["post_place_lut_budget"], 4096)
        for name in ("scan.tcl", "eco.tcl"):
            path = output / "code/fanout_native" / name
            self.assertTrue(path.is_file())
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                runner.preflight(output / "code")
            path.write_bytes((HERE / name).read_bytes())

    def test_readback_cannot_silently_change_identity_contract(self):
        output = self.root / "out"

        def simulated_vivado(command, **kwargs):
            args = command[command.index("-tclargs") + 1:]
            stage = Path(args[2]); stage.mkdir()
            (stage / "complete.txt").write_text("Mock")
            if stage.name == "implementation":
                (stage / "post_route.dcp").write_bytes(b"mock")
                (stage / "identity_manifest.tsv").write_text("cell\troot\tstage\n")
            else:
                Path(args[4]).write_text("changed")
            return SimpleNamespace(returncode=0)

        with patch.object(runner.subprocess, "run", side_effect=simulated_vivado):
            with self.assertRaisesRegex(RuntimeError, "Readback changed identity manifest"):
                runner.run(self.source, output)

    def test_missing_readback_dependency_fails_before_output(self):
        code = self.root / "missing_code"
        code.mkdir()
        with self.assertRaises(FileNotFoundError):
            runner.prepare(self.source, self.root / "out", {}, code)
        self.assertFalse((self.root / "out").exists())

    def test_input_hash_mismatch(self):
        self.dcp.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            runner.prepare(self.source, self.root / "out", {})
        self.assertFalse((self.root / "out").exists())

    def test_manifest_must_bind_required_files(self):
        del self.manifest["files"]["regions.tcl"]
        self.write_manifest()
        with self.assertRaises(ValueError):
            runner.validate_input(self.source)

    def test_no_path_escape_or_overwrite(self):
        self.manifest["files"]["../synthetic.dcp"] = runner.digest(self.dcp)
        self.write_manifest()
        with self.assertRaises(ValueError):
            runner.validate_input(self.source)
        self.manifest["files"].pop("../synthetic.dcp")
        self.write_manifest()
        with self.assertRaises(ValueError):
            runner.prepare(self.source, self.source / "out", {})
        output = self.root / "existing"
        output.mkdir()
        with self.assertRaises(FileExistsError):
            runner.prepare(self.source, output, {})

    def test_settings_enforce_strict_limit(self):
        for cfg in ({"native_target": 100}, {"memory_target": 100}, {"native_target": True},
                    {"native_mode": "SLR; exit"}, {"refinement_passes": 9}, {"refinement_passes": 2}, {"post_place_lut_budget": -1}, {"upstream_levels": 2}):
            with self.assertRaises(ValueError):
                runner.settings(cfg)
        self.assertEqual(runner.settings({"memory_target": 99})["memory_target"], 99)

    def test_frozen_configuration_and_code_are_checked(self):
        output = self.root / "out"
        runner.prepare(self.source, output, {})
        runner.validate_execution(output)
        path = output / "code/fanout_native/core.tcl"
        original = path.read_bytes()
        path.write_text("changed")
        with self.assertRaises(ValueError):
            runner.validate_execution(output)
        path.write_bytes(original)
        (output / "config.tcl").write_text("set hf2_config {}")
        with self.assertRaises(ValueError):
            runner.validate_execution(output)

    def test_runner_does_not_turn_fanout_annotation_into_failure(self):
        output = self.root / "out"
        calls = []

        def simulated_vivado(command, **kwargs):
            calls.append(command)
            args = command[command.index("-tclargs")+1:]
            stage = Path(args[2])
            stage.mkdir()
            (stage / "complete.txt").write_text("Mock completion")
            if stage.name == "implementation":
                (stage / "post_route.dcp").write_bytes(b"mock routed checkpoint")
                (stage / "identity_manifest.tsv").write_text("cell\troot\tstage\n")
            else:
                (stage / "fanout").mkdir()
                (stage / "fanout/acceptance.tsv").write_text("metric\tvalue\nstatus\tANNOTATED_UNMET\nordinary_ge100\t1\n")
            return SimpleNamespace(returncode=0)

        with patch.object(runner.subprocess, "run", side_effect=simulated_vivado):
            result = runner.run(self.source, output)
        self.assertEqual(len(calls), 2)  # One implementation process, one read-only reopen.
        self.assertEqual(result["status"], "IMPLEMENTED_AND_REOPENED")
        self.assertEqual(result["fanout_acceptance"]["status"], "ANNOTATED_UNMET")
        self.assertIn(str(self.dcp), calls[0])
        self.assertFalse(any("seed" in arg for call in calls for arg in call))

    def test_failed_implementation_never_starts_readback(self):
        output = self.root / "out"
        with patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as command:
            with self.assertRaises(RuntimeError):
                runner.run(self.source, output)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(json.loads((output / "status.json").read_text())["status"], "STOPPED_WITH_RETAINED_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
