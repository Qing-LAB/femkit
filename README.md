<p align="center">
  <img src="docs/assets/femkit.svg" alt="femkit" width="128">
</p>

<h1 align="center">femkit</h1>

<p align="center"><b>Reproducible finite-element studies with Elmer and NGSolve, on a workstation or an HPC cluster.</b></p>

**Role:** repository entry point
**Status:** under construction — installing the solvers, and writing, checking
and expanding a project, are built; running jobs is not yet
([`docs/plans/plan.md`](docs/plans/plan.md))
**Authority:** orientation only; [`PROJECT_CONTRACT.md`](PROJECT_CONTRACT.md)
says which document governs what

## What femkit does

- **Builds each solver from pinned sources, in its own environment.** Elmer and
  Netgen/NGSolve each get a conda environment with their own compilers and
  build tools. Before any source is downloaded, femkit proves that toolchain on
  your machine: a trivial program in each language compiles, links and runs,
  and an MPI program runs on two ranks.
- **Proves an install with numbers.** An environment is `ready` only when its
  checks — bounded calculations with known answers — come out within their
  tolerances, on that machine.
- **Keeps CPU and GPU builds apart.** `ngsolve` and `elmer` are the defaults;
  `ngsolve-cuda` and `elmer-cuda` are built only when asked for.
- **Knows the machine it is on.** A probe records the workstation or cluster —
  scheduler, partitions, limits, GPUs — once, and jobs are prepared against that
  record.
- **Writes everything down.** The model, the generated solver input, the run
  and the parsed results are separate files; every operation shows its plan
  before it acts and keeps a log.

Its first scientific use is frequency-domain electromagnetics of nanogaps.

| | |
|---|---|
| **works today** | installing and proving the solvers (`env bootstrap`, `doctor`, `env …`, `job probe`); projects started from templates, written in your own editor and checked (`project new / list / check / graph`); studies expanded into cases (`study list / expand`, `case list`); materials as values, tables and dispersion formulas, your material library, and imports from refractiveindex.info (`material import`) |
| **not built yet** | running a case — its geometry, mesh and solve — on a workstation and through SLURM, and reading its results |

## Start here

The [user manual](docs/manual/README.md) takes you from installing femkit to
a checked project and its cases, every step an example of what you type and
what femkit prints. In short:

femkit runs from this checkout and is never installed. It needs Linux, Bash,
`flock` and conda (on a cluster, load the manager's module in the shell first).
One script creates femkit's own control environment and hands everything else
to femkit:

```bash
git clone https://github.com/Qing-LAB/femkit.git && cd femkit
bash scripts/install-env.sh bootstrap   # control environment, config, both engines, record, doctor
```

`bootstrap` asks the two things nothing on the machine reveals: the shell lines
a job runs before it enters an environment (`module load …` on a cluster), and
where environments go. It shows its plan, including any install it will refuse
and why, and asks to proceed. With `--yes` it asks nothing, so give those
answers on the line: `--preamble LINE` (once per line) or `--no-preamble`, and
`--environments PATH`. On a cluster, run it inside an interactive allocation:
a login node's limits kill large builds. It ends by printing the lines that
enter femkit day to day on that machine; after them, you type `femkit …` in any
folder.

Every command takes `--help`, and every command that changes something takes
`--dry-run`.

## Where to read next

- [`docs/manual/`](docs/manual/README.md) — the user manual: install, start a
  project, write and check it, studies and cases, materials.
- [`docs/design.md`](docs/design.md) — what femkit is for, and the values behind it.
- [`docs/contracts/`](docs/contracts/) — the design, one contract per package.
- [`docs/README.md`](docs/README.md) — every document, one line each.
- [`PROJECT_CONTRACT.md`](PROJECT_CONTRACT.md) — which document wins, and where
  each file belongs.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — where a contributor starts.

## License

BSD 3-Clause; see [`LICENSE`](LICENSE).
