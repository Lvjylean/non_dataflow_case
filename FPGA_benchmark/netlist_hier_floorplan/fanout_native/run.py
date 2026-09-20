"""Prepare/run first-placement native fanout handling; never requires a seed DCP."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import time


DEFAULTS = dict(native_target=96, memory_target=96, native_mode="NONE",
                refinement_passes=1, native_min_target=8, memory_lut_budget=50000,
                post_place_lut_budget=4096, local_site_attempts=64, upstream_levels=1)
DEPENDENCIES = (
    "fanout_native/core.tcl", "fanout_native/memory.tcl",
    "fanout_native/scan.tcl", "fanout_native/eco.tcl",
    "fanout_native/implement.tcl", "fanout_native/reopen.tcl", "fanout_native/run.py",
    "fanout96/core.tcl", "fanout96/fast.tcl", "fanout96/quick.tcl",
    "balanced_implementation/adapter.tcl", "balanced_implementation/prepare.py",
    "connection_floorplan/audit.tcl",
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def settings(overrides):
    if set(overrides) - set(DEFAULTS):
        raise ValueError("Unknown fanout setting")
    cfg = dict(DEFAULTS, **overrides)
    for key in ("native_target", "memory_target", "native_min_target"):
        if type(cfg[key]) is not int or not 2 <= cfg[key] < 100:
            raise ValueError(f"{key} must be an integer in 2..99")
    if cfg["native_min_target"] > cfg["native_target"]:
        raise ValueError("Minimum target exceeds initial target")
    for key, low, high in (("refinement_passes", 0, 1), ("memory_lut_budget", 1, 1000000),
                           ("post_place_lut_budget", 0, 1000000), ("local_site_attempts", 1, 1024),
                           ("upstream_levels", 0, 1)):
        if type(cfg[key]) is not int or not low <= cfg[key] <= high:
            raise ValueError(f"Invalid {key}")
    if cfg["native_mode"] not in ("NONE", "SLR", "CLOCK_REGION", "MACRO"):
        raise ValueError("Invalid native mode")
    return cfg


def validate_input(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    for required in ("membership.tsv", "regions.tcl"):
        if required not in manifest["files"]:
            raise ValueError(f"Input manifest omits {required}")
    checkpoint = Path(manifest["input_dcp"])
    if not checkpoint.is_absolute() or digest(checkpoint) != manifest["input_sha256"]:
        raise ValueError("Post-opt checkpoint hash mismatch")
    for name, expected in manifest["files"].items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or digest(path) != expected:
            raise ValueError(f"Input artifact hash/path mismatch: {name}")
    return manifest


def preflight(code):
    for name in DEPENDENCIES:
        if not (code / name).is_file():
            raise FileNotFoundError(f"Missing execution/readback dependency: {name}")


def prepare(source, output, cfg, code=None):
    source, output = Path(source).resolve(), Path(output).resolve()
    code = Path(code or Path(__file__).resolve().parent.parent)
    cfg = settings(cfg)
    preflight(code)
    if output == source or source in output.parents:
        raise ValueError("Output must not be inside the immutable input")
    if (source / "manifest.json").is_file() and (source / "membership.tsv").is_file():
        validate_input(source)
        adapted = True
    else:
        # Accept the existing implementation_input export format as well.
        modules = json.loads((source / "modules.json").read_text())
        adapted = False
    output.mkdir(parents=True, exist_ok=False)
    if adapted:
        shutil.copytree(source, output / "input")
    else:
        spec = importlib.util.spec_from_file_location("hf2_prepare", code / "balanced_implementation/prepare.py")
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        adapter.prepare(source, output / "input", len(modules["modules"]))
    manifest = validate_input(output / "input")
    hashes = {}
    for name in DEPENDENCIES:
        dest = output / "code" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(code / name, dest)
        hashes[name] = digest(dest)
    (output / "code_manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    (output / "config.json").write_text(json.dumps(cfg, indent=2) + "\n")
    # Only validated integers/enums enter this generated Tcl configuration.
    text = "set hf2_config [dict create " + " ".join(f"{k} {v}" for k, v in cfg.items()) + "]\n"
    (output / "config.tcl").write_text(text)
    (output / "execution_manifest.json").write_text(json.dumps({
        name: digest(output / name) for name in ("config.json", "config.tcl", "input/manifest.json", "code_manifest.json")
    }, indent=2) + "\n")
    (output / "source.json").write_text(json.dumps(dict(path=str(source), adapted=adapted), indent=2) + "\n")
    return manifest


def validate_execution(output):
    for name, expected in json.loads((output / "execution_manifest.json").read_text()).items():
        if digest(output / name) != expected:
            raise ValueError(f"Frozen execution input changed: {name}")
    for name, expected in json.loads((output / "code_manifest.json").read_text()).items():
        if digest(output / "code" / name) != expected:
            raise ValueError(f"Frozen source changed: {name}")
    return validate_input(output / "input")


def run(source, output, cfg=None, vivado="vivado", prepare_only=False):
    output = Path(output).resolve()
    manifest = prepare(source, output, cfg or {})
    state = dict(status="PREPARED_NOT_RUN", stages={}, flow="native_first_placement_v3",
                 input_sha256=manifest["input_sha256"], logical_limit_exclusive=100)

    def save():
        (output / "status.json").write_text(json.dumps(state, indent=2) + "\n")

    save()
    if prepare_only:
        return state
    try:
        for stage, checkpoint in (("implementation", Path(manifest["input_dcp"])),
                                  ("reopened", output / "implementation/post_route.dcp")):
            validate_execution(output)
            script = "implement.tcl" if stage == "implementation" else "reopen.tcl"
            contract = output / "implementation/identity_manifest.tsv"
            if stage == "reopened" and digest(contract) != contract_sha:
                raise RuntimeError("Identity manifest changed before readback")
            command = [vivado, "-mode", "batch", "-log", str(output / f"{stage}.vivado.log"),
                       "-journal", str(output / f"{stage}.jou"), "-source",
                       str(output / "code/fanout_native" / script), "-tclargs",
                       str(output / "input"), str(checkpoint), str(output / stage), str(output / "config.tcl")]
            if stage == "reopened":
                command.append(str(contract))
            state["status"] = stage.upper(); started = time.time(); save()
            with (output / f"{stage}.log").open("x") as log:
                rc = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT).returncode
            state["stages"][stage] = dict(seconds=time.time()-started, return_code=rc); save()
            if rc or not (output / stage / "complete.txt").is_file():
                raise RuntimeError(f"{stage} failed; evidence retained")
            if stage == "implementation":
                routed_sha = digest(output / "implementation/post_route.dcp")
                contract_sha = digest(contract)
        validate_execution(output)
        if digest(output / "implementation/post_route.dcp") != routed_sha:
            raise RuntimeError("Readback changed routed checkpoint")
        if digest(contract) != contract_sha:
            raise RuntimeError("Readback changed identity manifest")
        with (output / "reopened/fanout/acceptance.tsv").open() as f:
            acceptance = {row["metric"]: row["value"] for row in csv.DictReader(f, delimiter="\t")}
        state.update(status="IMPLEMENTED_AND_REOPENED", dcp=str(output / "implementation/post_route.dcp"),
                     dcp_sha256=routed_sha, identity_manifest_sha256=contract_sha, fanout_acceptance=acceptance,
                     note="Timing and placement spill are independent report annotations.")
        (output / "result.json").write_text(json.dumps(state, indent=2) + "\n")
        save()
        return state
    except Exception as error:
        state.update(status="STOPPED_WITH_RETAINED_EVIDENCE", error=str(error)); save()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--vivado", default="vivado")
    for key, default in DEFAULTS.items():
        parser.add_argument("--" + key.replace("_", "-"), type=type(default), default=default)
    args = parser.parse_args()
    cfg = {key: getattr(args, key) for key in DEFAULTS}
    print(json.dumps(run(args.input, args.output, cfg, args.vivado, args.prepare_only), indent=2))
