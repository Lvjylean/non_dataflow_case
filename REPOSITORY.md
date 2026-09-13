# Case repository maintenance

This directory is an independent Git repository on eda070:
`/Projects/jinyang/workspace/non_dataflow_crossSLR/case`.

Keep source, configurations, launch/Tcl scripts, upstream input HDL, case metadata,
and compact reports. Generated HLS projects, FPGA benchmark runs, Vivado caches,
checkpoints, bitstreams, archives, and logs are excluded. Files remain on disk.
Source RTL is deliberately not excluded globally: CNNA uses upstream exported HDL.

`Vitis_Libraries` is an upstream submodule pinned by this repository's index.
Its existing checkout and history are preserved. Clone with:
`git clone --recurse-submodules https://github.com/Lvjylean/non_dataflow_case.git`.
Other imported source trees are ordinary files, with their licenses retained.

Gitignore cannot express a file-size predicate. Before adding new files, run:

```sh
python3 update_large_file_ignores.py
git status --short
git add .
git diff --cached --stat
```

The helper adds exact exclusions for newly discovered untracked files exceeding
50 MiB. Existing exclusions remain until manually reviewed. It does not remove
already tracked files, and future growth of tracked files needs separate review.
Files inside the submodule are maintained by that repository, not this helper.
Directories ignored as generated state can contain scripts; copy any unique,
reusable input scripts into a maintained source/configuration directory first.

The remote repository is https://github.com/Lvjylean/non_dataflow_case.git.
On 2026-09-13 the user explicitly authorized the initial commit and push,
overriding the parent AGENTS.md restriction for this operation only.
Subsequent automated commits and pushes still require authorization.
