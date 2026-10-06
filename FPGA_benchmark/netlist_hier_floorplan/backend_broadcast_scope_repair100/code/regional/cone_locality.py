"""Bounded, structural SLR round-trip discovery and combinational cloning.

No timing or fanout admission is performed here.  The caller must budget every
new input load, protect all affected setup/hold endpoints, legalize placement,
and verify physical SLRs before routing.  Original cells are never moved/deleted.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
import re


COMB = re.compile(r"^(LUT[1-6]|MUXF[789])$")
BOUNDARY = re.compile(r"^(FDRE|FDSE|RAMB(?:18|36)E[12]|URAM288(?:_BASE)?)$")
SLR = re.compile(r"^SLR[0-9]+$")
CONSTANT_KEYS = frozenset({"ZERO", "ONE", "GND", "VCC", "0", "1", "<const0>", "<const1>",
                          "constant POWER", "constant GROUND"})
CLOCK_PINS = frozenset({"C", "CLK", "CLKA", "CLKB", "CLK_A", "CLK_B"})


class LocalityError(ValueError):
    pass


def _cell(pin):
    return pin.rsplit("/", 1)[0] if "/" in pin else ""


def _pin(pin):
    return pin.rsplit("/", 1)[-1]


def _comb(cell):
    return bool(COMB.fullmatch(cell.get("ref", "")))


def _position(cell):
    slr = cell.get("slr", "")
    try:
        x, y = float(cell["x"]), float(cell["y"])
    except (KeyError, TypeError, ValueError):
        raise LocalityError("missing_position") from None
    if not SLR.fullmatch(slr) or not math.isfinite(x) or not math.isfinite(y):
        raise LocalityError("missing_position")
    return slr, x, y


class Graph:
    """Memoized DAG summaries; traversal never enumerates individual paths."""

    def __init__(self, cells, nets):
        self.cells = cells
        self.nets = {key: tuple(sinks) for key, sinks in nets.items()}
        self.net_sets = {}
        self.origins = {}
        self.local_endpoints = {}
        self.origin_nodes = 0
        self.endpoint_nodes = 0

    def source(self, key):
        if key in CONSTANT_KEYS:
            return None, "constant"
        name = _cell(key)
        obj = self.cells.get(name)
        if obj is None:
            raise LocalityError("unknown_boundary:" + key)
        if obj.get("ref") in {"VCC", "GND"}:
            return name, "constant"
        if _comb(obj):
            if _pin(key) != "O":
                raise LocalityError("unsupported_combinational_output:" + key)
            return name, "comb"
        if not BOUNDARY.fullmatch(obj.get("ref", "")):
            raise LocalityError("unsupported_boundary:" + name + ":" + obj.get("ref", ""))
        _position(obj)
        return name, "sequential"

    def inputs(self, name):
        obj = self.cells[name]
        result = obj.get("inputs")
        if not isinstance(result, dict):
            raise LocalityError("missing_inputs:" + name)
        ref = obj.get("ref", "")
        if ref.startswith("LUT"):
            required = {"I" + str(i) for i in range(int(ref[3:]))}
        elif ref.startswith("MUXF"):
            required = {"I0", "I1", "S"}
        else:
            raise LocalityError("unsupported_combination:" + name)
        if set(result) != required or any(not isinstance(k, str) or not k for k in result.values()):
            raise LocalityError("incomplete_inputs:" + name)
        if "config" not in obj:
            raise LocalityError("missing_configuration:" + name)
        for pin, key in result.items():
            if key in CONSTANT_KEYS or self.cells.get(_cell(key), {}).get("ref") in {"VCC", "GND"}:
                continue
            if key not in self.net_sets:
                self.net_sets[key] = frozenset(self.nets.get(key, ()))
            if name + "/" + pin not in self.net_sets[key]:
                raise LocalityError("input_connectivity_mismatch:" + name + "/" + pin)
        return result

    def source_slrs(self, name):
        if name in self.origins:
            return self.origins[name]
        active = set()
        stack = [(name, False)]
        while stack:
            node, finish = stack.pop()
            if node in self.origins:
                continue
            if finish:
                result = set()
                for key in self.inputs(node).values():
                    src, kind = self.source(key)
                    if kind == "comb":
                        result.update(self.origins[src])
                    elif kind == "sequential":
                        result.add(self.cells[src]["slr"])
                self.origins[node] = frozenset(result)
                active.remove(node)
                self.origin_nodes += 1
                continue
            if node in active:
                raise LocalityError("combinational_cycle:" + node)
            active.add(node)
            stack.append((node, True))
            children = []
            for key in self.inputs(node).values():
                src, kind = self.source(key)
                if kind == "comb":
                    children.append(src)
            stack.extend((child, False) for child in reversed(sorted(set(children))))
        return self.origins[name]

    def endpoint_summary(self, start, target):
        """Reach a sequential endpoint without leaving target again.

        Only an SLR set is cached, avoiding large per-node endpoint sets.  All
        downstream STA endpoint enumeration remains a caller responsibility.
        """
        key = (start, target)
        if key in self.local_endpoints:
            return self.local_endpoints[key]
        active = set()
        stack = [(start, False)]
        while stack:
            node, finish = stack.pop()
            memo_key = (node, target)
            if memo_key in self.local_endpoints:
                continue
            obj = self.cells.get(node)
            if obj is None or obj.get("slr") != target:
                self.local_endpoints[memo_key] = False
                continue
            if not _comb(obj):
                self.local_endpoints[memo_key] = bool(BOUNDARY.fullmatch(obj.get("ref", "")))
                continue
            if finish:
                answer = any(self.local_endpoints.get((_cell(p), target), False)
                             for p in self.nets.get(node + "/O", ()) if _pin(p) not in CLOCK_PINS)
                self.local_endpoints[memo_key] = answer
                active.remove(node)
                self.endpoint_nodes += 1
                continue
            if node in active:
                raise LocalityError("combinational_cycle:" + node)
            active.add(node)
            stack.append((node, True))
            children = sorted({_cell(p) for p in self.nets.get(node + "/O", ()) if _pin(p) not in CLOCK_PINS})
            stack.extend((child, False) for child in reversed(children))
        return self.local_endpoints[key]

    def cone(self, root, max_cells):
        seen = set()
        boundaries = {}
        stack = [root]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            if len(seen) > max_cells:
                raise LocalityError("cone_cell_budget")
            _position(self.cells[node])
            for pin, key in self.inputs(node).items():
                src, kind = self.source(key)
                if kind == "comb":
                    stack.append(src)
                else:
                    record = boundaries.setdefault(key, dict(key=key, cell=src or "", kind=kind,
                        ref=self.cells[src]["ref"] if src else "CONSTANT",
                        slr=self.cells[src].get("slr", "") if src else "", pins=[]))
                    record["pins"].append(node + "/" + pin)
        for record in boundaries.values():
            record["pins"].sort()
        return seen, boundaries

    def clone_set(self, root, target, cone):
        parents = {name: name for name in cone}

        def representative(name):
            while parents[name] != name:
                parents[name] = parents[parents[name]]
                name = parents[name]
            return name

        for name in sorted(cone):
            if self.cells[name]["ref"].startswith("MUXF"):
                for pin in ("I0", "I1"):
                    src, kind = self.source(self.inputs(name)[pin])
                    if kind != "comb" or src not in cone:
                        raise LocalityError("incomplete_mux_macro:" + name)
                    parents[representative(src)] = representative(name)
        groups = defaultdict(set)
        for name in cone:
            groups[representative(name)].add(name)
        selected = set()
        pending = [root]
        while pending:
            name = pending.pop()
            if name in selected:
                continue
            members = groups[representative(name)]
            for member in members - selected:
                if not self.cells[member].get("editable", False):
                    raise LocalityError("protected_clone_cell:" + member)
                for key in self.inputs(member).values():
                    src, kind = self.source(key)
                    if kind == "comb" and self.cells[src].get("slr") != target:
                        pending.append(src)
            selected.update(members)
        return selected

    def candidate(self, root_key, target, sinks, max_cells):
        root = _cell(root_key)
        if root_key != root + "/O" or root not in self.cells or not _comb(self.cells[root]):
            raise LocalityError("unsupported_root")
        if not SLR.fullmatch(target) or self.cells[root].get("slr") == target:
            raise LocalityError("not_cross_slr_root")
        cone, boundaries = self.cone(root, max_cells)
        origins = self.source_slrs(root)
        if target not in origins:
            raise LocalityError("no_same_slr_source")
        targets = []
        for pin in sorted(set(sinks)):
            cell = _cell(pin)
            obj = self.cells.get(cell, {})
            if pin not in self.nets.get(root_key, ()) or obj.get("inputs", {}).get(_pin(pin)) != root_key:
                raise LocalityError("sink_connectivity_mismatch:" + pin)
            if obj.get("slr") != target:
                raise LocalityError("sink_slr_mismatch:" + pin)
            if not obj.get("editable", False):
                raise LocalityError("protected_target_sink:" + pin)
            _position(obj)
            if _pin(pin) in CLOCK_PINS:
                raise LocalityError("clock_sink:" + pin)
            if obj.get("ref", "").startswith("MUXF") and _pin(pin) in {"I0", "I1"}:
                raise LocalityError("target_mux_data_requires_macro_expansion:" + pin)
            if self.endpoint_summary(cell, target):
                targets.append(pin)
        if not targets:
            raise LocalityError("no_local_sequential_endpoint")
        selected = self.clone_set(root, target, cone)
        owners = sorted(cone | {_cell(p) for p in targets} |
                        {item["cell"] for item in boundaries.values() if item["cell"]})
        signature = hashlib.sha256(json.dumps(
            dict(cells={name: self.cells[name] for name in owners},
                 nets={key: sorted(self.nets.get(key, ())) for key in
                       sorted({name + "/O" for name in cone} | set(boundaries))}),
            sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        return dict(id="cone:" + root_key + "@" + target, root=root_key, target_slr=target,
                    target_sinks=targets, cone=sorted(cone), clone_cells=sorted(selected),
                    boundaries=boundaries, source_slrs=sorted(origins), endpoint_slrs=[target],
                    owners=owners, inventory_signature=signature)


def discover(cells, nets, max_cells=128):
    """Return candidates/rejections, including low-fanout SLR round trips."""
    if max_cells <= 0:
        raise ValueError("max_cells must be positive")
    graph = Graph(cells, nets)
    candidates, rejected = [], []
    for root_key in sorted(nets):
        root = _cell(root_key)
        obj = cells.get(root, {})
        if not _comb(obj):
            continue
        groups = defaultdict(list)
        for pin in nets[root_key]:
            target = cells.get(_cell(pin), {}).get("slr", "")
            if SLR.fullmatch(target) and target != obj.get("slr"):
                groups[target].append(pin)
        for target, sinks in sorted(groups.items()):
            try:
                candidates.append(graph.candidate(root_key, target, sinks, max_cells))
            except LocalityError as error:
                rejected.append(dict(root=root_key, target_slr=target, status=str(error)))
    return dict(schema="cone-locality-v1", candidates=candidates, rejected=rejected,
                stats=dict(candidates=len(candidates), rejected=len(rejected),
                           origin_nodes=graph.origin_nodes, endpoint_nodes=graph.endpoint_nodes))


def plan_candidate(cells, nets, candidate, *, prefix="sbeco_locality", max_cells=128):
    """Return deterministic clone and exact terminal rewiring proposals.

    This intentionally revalidates a discovered candidate against the supplied
    inventory.  It does not claim feasibility until caller fanout/STA gates pass.
    """
    graph = Graph(cells, nets)
    current = graph.candidate(candidate["root"], candidate["target_slr"], candidate["target_sinks"], max_cells)
    for key in ("id", "cone", "clone_cells", "boundaries", "source_slrs", "endpoint_slrs", "owners", "inventory_signature"):
        if candidate.get(key) != current[key]:
            raise LocalityError("stale_candidate:" + key)
    target = current["target_slr"]
    selected = set(current["clone_cells"])
    names = {name: prefix + "_" + hashlib.sha256((current["id"] + "\0" + name).encode()).hexdigest()[:20]
             for name in sorted(selected)}
    if any(name in cells for name in names.values()):
        raise LocalityError("clone_name_collision")
    anchors = {_cell(p) for p in current["target_sinks"]}
    boundary_keys = set()
    for name in selected:
        for key in graph.inputs(name).values():
            src, kind = graph.source(key)
            if src not in selected:
                boundary_keys.add(key)
                if kind != "constant" and cells[src].get("slr") == target:
                    anchors.add(src)
    positions = [_position(cells[name]) for name in sorted(anchors)]
    x = sum(p[1] for p in positions) / len(positions)
    y = sum(p[2] for p in positions) / len(positions)
    clones = {}
    for original, name in names.items():
        inputs = {pin: names[_cell(key)] + "/O" if _cell(key) in names else key
                  for pin, key in graph.inputs(original).items()}
        clones[original] = dict(name=name, key=original + "/O", ref=cells[original]["ref"],
            config=deepcopy(cells[original]["config"]), slr=target, x=x, y=y, inputs=inputs)
    output = names[_cell(current["root"])] + "/O"
    return dict(clones=clones, rewires={pin: output for pin in current["target_sinks"]},
                owners=current["owners"], metadata=dict(current, mode="clone_only",
                    clone_boundaries=sorted(boundary_keys), original_cells_preserved=True,
                    requires_shared_fanout_and_full_sta=True))
