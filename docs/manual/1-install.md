# 1 · Install and set up

**Role:** manual
**Status:** current; what is not built yet is marked so
**Authority:** none of its own: it shows what femkit does, and the basic
tests run each example and hold it to what femkit prints

This chapter takes you from a fresh machine to a femkit that is ready for
your first project: the install, the commands you type every day, the one
setting you choose — where your projects live — and where femkit keeps its
own files.

```mermaid
flowchart LR
    G["git clone<br/>~/femkit"] --> B["bash scripts/install-env.sh bootstrap"]
    B --> C["control environment femkit<br/>(femkit's own Python)"]
    B --> E["conda environments<br/>femkit-elmer, femkit-ngsolve, femkit-gmsh,<br/>femkit-model_prep, femkit-postprocess"]
    B --> L["~/.local/bin/femkit:<br/>femkit in every shell with ~/.local/bin on its path"]
    B --> R["this machine's record"]
    B --> D["doctor: ready?"]
    D --> P["config set paths.projects<br/>your projects root"]
    P --> N["chapter 2:<br/>your first project"]
```

## What you need

Linux, Bash, `flock`, and the conda package manager (or mamba). On a
cluster, load the manager's module in your shell first, and do the install
inside an interactive allocation: a login node's limits stop large
compilations.

femkit runs from its own folder — the copy of its repository you clone,
called the **checkout** — and is never installed into Python. This manual
puts the checkout at `~/femkit`. The install writes a `femkit` command into
femkit's own environment, which runs femkit from that checkout in whatever
folder you are in, and puts a link to it at `~/.local/bin/femkit`. If you
move the checkout, run the install script again from its new place; until
then `femkit` says the checkout is gone.

## Install

One script builds everything femkit needs, each piece in its own
environment — a self-contained folder of programs and libraries that your
own Python and packages never see. Each is an ordinary conda environment,
which conda keeps where it keeps all of yours and lists in `conda env list`;
femkit names each `femkit-…`:

- the **control environment**, `femkit`, femkit's own Python, which runs
  every `femkit` command;
- one **engine environment** for each solver — femkit calls a solver an
  **engine** — `elmer` for Elmer and `ngsolve` for NGSolve (`femkit-elmer`
  and `femkit-ngsolve` to conda), each compiled
  from pinned sources and then proven: before any source is downloaded, its
  compilers must build and run a small program on your machine, and
  afterwards the solver must solve small problems with known answers to
  within their tolerances;
- the `gmsh` environment, where your geometry scripts run and femkit meshes
  them, proven the same way on a small geometry of known size;
- the `model_prep` environment, where the functions of your
  `definitions.py` run (chapter 3), and the `postprocess` environment, where
  your observables scripts run — numpy, scipy, matplotlib, netCDF4, xarray
  and meshio, and the packages your projects add (below);
- **this machine's record**: what femkit measured about the machine — its
  cores, memory, GPUs, and on a cluster its scheduler and queues.

```bash
git clone https://github.com/Qing-LAB/femkit.git ~/femkit
cd ~/femkit
bash scripts/install-env.sh bootstrap
```

`bootstrap` asks what nothing on the machine can tell it:

- the shell lines a job runs before it can use the package manager — on a
  cluster, typically a `module load` line; on a workstation, often none;
- how a shell enters an environment here: `source activate`,
  `conda activate` or `mamba activate`;
- your **projects root**: the one folder that holds all your projects and
  your material library (chapter 2).

Where the environments go is conda's to decide, as for every environment of
yours: they take several gigabytes, so on a cluster with a small home folder,
point conda at project storage in your own conda settings (`envs_dirs` and
`pkgs_dirs` in `~/.condarc`) before you install.

Conda manages the environments; femkit's recipe decides what goes into them.
Conda keeps them where it keeps yours, with its own package cache, its list
and its activation, all as you set conda up. What each holds is femkit's
list alone: your own channels, pinned packages and the packages conda adds
to every new environment of yours are set aside for femkit's, and femkit
names its channel by its full address, so no mirror or alias of yours sends
it elsewhere. A setting of yours that nothing can set aside stops the
install before anything is made, naming the setting and the file it is in —
conda's `override_channels_enabled: false`, for instance, which forbids
femkit to name its own channels:

```text
[femkit] refused: your setting override_channels_enabled, in /home/you/.condarc: conda then refuses --override-channels, by which femkit names the channels an environment is made from: remove it, or set it true
```

Each environment records which of your settings it set aside.

What it can find out on the machine it proposes instead of asking: the GPU
architectures your graphics driver reports, which the GPU builds are compiled
for, and how a program starts on several processors — each environment's own
`mpirun`, which femkit proposes on a workstation and on a cluster whose
scheduler it knows. Each proposal is a line of the plan, written only when you
agree to the plan.

It shows its plan — every step it will take, including an install it would
refuse and why — and asks before it starts. To answer everything on the
command line and be asked nothing, give `--yes` with the answers:

```bash
bash scripts/install-env.sh bootstrap --yes --no-preamble --activation 'conda activate' --projects ~/femkit-projects
```

On a cluster, `--preamble 'module load conda'` (once per line) takes the
place of `--no-preamble`. The activation must be one your package manager
has: `bootstrap` refuses `mamba activate` with conda before it starts, naming
the ones it has.

`bootstrap` ends with a report of each part and the lines that enter
femkit's control environment the way you enter any conda environment of yours.

Your conda environments now include femkit's:

```bash
conda env list
```

```text
# conda environments:
#
base                     /home/you/miniforge3
femkit                   /home/you/miniforge3/envs/femkit
femkit-elmer             /home/you/miniforge3/envs/femkit-elmer
femkit-gmsh              /home/you/miniforge3/envs/femkit-gmsh
femkit-model_prep        /home/you/miniforge3/envs/femkit-model_prep
femkit-ngsolve           /home/you/miniforge3/envs/femkit-ngsolve
femkit-postprocess       /home/you/miniforge3/envs/femkit-postprocess
```

## Every day

Open a shell and type `femkit …`: nothing needs activating first. The install
linked the command at `~/.local/bin/femkit`, a folder most shells put on
their path once it exists. Where this shell's path lacks it, `bootstrap` says
so and prints the one line to add to your `~/.bashrc`:

```text
[femkit] /home/you/.local/bin is not on this shell's PATH, so a new shell does not find femkit; add this line to your ~/.bashrc:
    export PATH=/home/you/.local/bin:"$PATH"
[femkit] or enter the control environment the way you enter any of conda's: conda activate femkit
```

femkit finds conda the way your shell does: where conda is set up in your
shell (`conda init`), or on a cluster once its module is loaded.

```bash
femkit doctor
```

`conda activate femkit` enters femkit's own environment as you enter any of
yours, and also puts `femkit` on your path.

`femkit …` works in any folder. A command that works on one
project takes the project you are in — your shell inside its folder — or
names it with `--project` from anywhere else:

```bash
cd ~/femkit-projects/square
femkit project check                     # the project this folder is in
femkit project check --project square    # the same, from any folder
```

## Is the machine ready? — `doctor`

```bash
femkit doctor
```

`doctor` reads, and changes nothing. It reports one line for each thing
femkit needs — the control environment, your settings file, this machine's
record, each engine environment — with its state and, for anything not
ready, the command that fixes it. It exits with 0 only when every line is
ready, so a script can ask it too.

## Help on every command

Every command and every command group answers `--help`:

```console
$ femkit --help
Usage: femkit [OPTIONS] COMMAND [ARGS]...

  femkit — a solver-neutral finite-element workbench.

Options:
  --help  Show this message and exit.

Commands:
  case      the cases a study's prep wrote, each with its study and point
  config    this machine's settings, femkit's own
  doctor    Whether this machine is ready: control environment, configuration,
            this machine's record, every engine environment.
  env       the engine environments: install, validate, list, clean, log
  job       this machine's record and the jobs femkit runs
  material  materials: make a new one from another source's file
  project   a project: start one from a template, check it, list them,...
  schema    femkit's own definitions and the reference pages written from...
  serve     the web page's server: start, stop, status
  study     a project's studies: list them, prep each for its jobs — its...
  web       the web page's bundle, built from its sources

  (manual: 1 · Install and set up)
```

```console
$ femkit project new --help
Usage: femkit project new [OPTIONS] NAME

  Make a new project under the projects root, a copy of one of femkit's
  templates or of one of your projects: every part, the files each fixes and
  declares, and your own folder — nothing femkit or a run wrote; the first
  makes the root. A root without its global material library gets one, holding
  a copy of femkit's shipped materials, yours from then on.

  Arguments:
    NAME  its name: its path from the projects root

Options:
  --from TEXT  what it copies: a template by its bare name, or one of your
               projects by its path from the projects root; the templates:
               `laplace_square`, `two_material`
  --json       print one JSON document on stdout
  --dry-run    print the plan; change nothing
  -y, --yes    consent in advance
  --help       Show this message and exit.

  (manual: 2 · Start a project)
```

A command's help says what it does, then its **arguments** — the words it
needs, written in capitals in its usage line, such as `NAME` — and its
**options**, the words that open with `--`. A **template** is a whole,
working project femkit ships, which you copy to start your own (chapter 2).
`stdout` is the screen, unless you send it elsewhere. The last line,
`(manual: 2 · Start a project)`, names the chapter of this manual that
explains the command; the comments in the files femkit starts you with end
the same way.

Every command that changes something shows its **plan** first — the
numbered steps it will take — and asks on your terminal whether to proceed
before it acts. Two options change that:

- `--dry-run` shows the plan and changes nothing;
- `--yes` agrees in advance, so the command runs without asking.

The examples in this manual use `--yes`, so you see the plan, each step as
it runs, and the outcome in one go. Every command also takes `--json`, which
prints one JSON document instead, for a script to read.

## Your settings — `config`

femkit keeps your choices for this machine in one file, `config.toml`; each
setting in it is a **key**. `config show` prints every key, its value, and
what it means while it is unset. On a machine with no settings yet:

```console
$ femkit config show
[config show] no config.toml: every key is unset
  key                       value  when unset
  paths.projects            unset  no project is listed, made or named; each says so, naming this key
  build.cuda_architectures  unset  installing an environment with a build compiled for CUDA is refused, naming this key
  build.jobs                unset  the CPUs this process may use (its CPU affinity: on a cluster, the allocation's share, never the whole login node)
  launch.mpi                unset  a multi-rank check or job, and installing an environment with MPI, are refused, naming this key
  activation.preamble       unset  `job probe --write` is refused, naming this key
  activation.command        unset  `job probe --write` is refused, naming this key
```

Every line femkit prints opens with the command in brackets, here
`[config show]`. `<data>` is femkit's data folder, `~/.local/share/femkit`
(below).

The one setting every project needs is `paths.projects`, your projects root.
`config set` writes one setting; its value is written the way the file holds
it, so a folder goes in double quotes, and the single quotes keep your shell
from removing them:

```console
$ femkit config set paths.projects '"~/femkit-projects"' --dry-run
[config set] plan: 1 step
  1. set paths.projects: unset -> ~/femkit-projects
$ femkit config set paths.projects '"~/femkit-projects"' --yes
[config set] plan: 1 step
  1. set paths.projects: unset -> ~/femkit-projects
[config set] 1 step; logs in ~/.local/state/femkit/operations/config/20261125T181904.913703Z
[1/1] set paths.projects: unset -> ~/femkit-projects
[config set] set paths.projects: unset -> ~/femkit-projects, in ~/.config/femkit/config.toml
```

With `--dry-run`, femkit prints the plan and stops. With `--yes`, it prints
the plan, then runs it: the line with `logs in` names the folder where it
keeps a log of what it did, then each step is counted as it runs — `[1/1]`,
the first of one — and the last line is the outcome. The folder need not
exist yet: your first project makes it (chapter 2).

A bare word is not a value, so femkit refuses it rather than guess what you
meant — here your shell has already turned `~` into your home folder. A
**refused** command changes nothing, and under `next -- instead:` femkit
prints what you could type instead, ready to copy:

```console
$ femkit config set paths.projects ~/femkit-projects --yes
[config set] refused: /home/you/femkit-projects is no value as config.toml writes one: a text is written in quotes
next -- instead:
    femkit config set paths.projects '"/home/you/femkit-projects"'
```

`config show` now reads the file:

```console
$ femkit config show
[config show] read ~/.config/femkit/config.toml
  key                       value              when unset
  paths.projects            ~/femkit-projects
  build.cuda_architectures  unset              installing an environment with a build compiled for CUDA is refused, naming this key
  build.jobs                unset              the CPUs this process may use (its CPU affinity: on a cluster, the allocation's share, never the whole login node)
  launch.mpi                unset              a multi-rank check or job, and installing an environment with MPI, are refused, naming this key
  activation.preamble       unset              `job probe --write` is refused, naming this key
  activation.command        unset              `job probe --write` is refused, naming this key
```

Two more `config` commands:

```bash
femkit config init    # write config.toml from its template, adding only the keys it lacks
femkit config path    # where femkit keeps its files on this machine, and what chose each place
```

`config init` is what `bootstrap` runs to write your settings, asking for
each one nothing on the machine reveals; it never replaces a value you set,
and `config set` changes one. Its options give the answers on the command
line instead — `--projects`, `--cuda-architectures`,
`--jobs`, `--mpi`, `--preamble`, `--no-preamble`, `--activation`, and the
same on `bootstrap`. Every key, with
its type, is listed in the [settings reference](../reference/config.md).

## Where femkit puts things

femkit writes only into its own folders, each under your home folder by
default, and into your projects root; its environments are conda's, kept
where conda keeps all of yours:

```text
~/.config/femkit/            your settings: config.toml, and machines/ with this machine's record
~/.local/share/femkit/       the exact package list of each environment, to rebuild it as it was
~/.cache/femkit/             downloads and build files: safe to empty at any time
~/.local/state/femkit/       the log of every command that changed something
~/.local/bin/femkit          the link that puts `femkit` on your path
~/femkit-projects/           your projects root: your projects and your material library
```

`femkit config path` prints the folders on your machine. Each can be moved
by a variable, for instance `FEMKIT_CONFIG_DIR`; where the environments go is
your conda settings' (`envs_dirs`).

## The environments — `env`

Each step of a calculation runs in an environment of its own: a project's
definitions in `model_prep`, a geometry in `gmsh`, a mesh in the environment
of the mesher its recipe names — Gmsh's in `gmsh` — the solve in the engine
you choose when you prep the study, `elmer` or `ngsolve` (chapter 5), and the
observables in `postprocess`.
`bootstrap` installs and checks the five default environments, `elmer`,
`ngsolve`, `gmsh`, `model_prep` and `postprocess`. These commands look after
them afterwards:

```bash
femkit env list                 # every environment, its name with conda, its state, and whether its GPU path is proven
femkit env install ngsolve      # install one; an interrupted install resumes where it stopped
femkit env install --all        # every default environment
femkit env validate ngsolve     # run its checks again: small problems with known answers
femkit env validate ngsolve --gpu   # the GPU checks, on a machine with a GPU
femkit env log ngsolve          # the last command run on it: each step, how it ended, its log
femkit env clean ngsolve        # remove it; install it again any time
femkit env bootstrap            # what the install script runs: set up this machine again
```

An environment is `ready` only when its checks pass on this machine. GPU
builds are separate environments, `ngsolve-cuda` and `elmer-cuda`
(`femkit-ngsolve-cuda` and `femkit-elmer-cuda` to conda), installed only when
you ask for them by name; so is `web`, which the web page needs (below). `env
install NAME --clean` rebuilds one from scratch.

femkit knows each environment by the name conda gives it, `femkit-…`, in the
folders where conda keeps environments. A folder of that name there which
conda does not list as an environment — left over from something else — is
in the way: `env list` says so, naming the folder, and femkit never makes an
environment over it nor removes it; remove it or move it aside yourself, and
install again.

Whatever femkit starts — femkit itself, from the `femkit` command; an
install's build, a check, your `definitions.py`, the web page's server, a
job — starts clean: it keeps your home, your locale and your conda settings,
and none of what your own shell has set for other work — another active
environment, your own Python's settings, compilers and library paths, shell
functions of your own — so nothing of your shell reaches femkit or a solver
but what the environment itself sets. Then conda enters the environment, by
its name, as it enters any of yours.

## This machine's record — `job`

```bash
femkit job machines           # every machine record, or one with where each fact came from
femkit job probe              # measure this machine and show the record; --write keeps it
```

`job probe --write` writes the record after `activation.preamble` and
`activation.command` are set. On a cluster, `--set` says where one of the
scheduler's commands is, when femkit cannot find it — your site's own submit
command, `--set scheduler.commands.submit=PATH`, is enough for femkit to know
the scheduler — and `--scheduler` names the scheduler when femkit still
cannot tell.

To prepare calculations on your workstation for a cluster, carry the
cluster's record over: on the cluster, `femkit job probe --write --name
cluster-a` writes it as `machines/cluster-a.toml` in femkit's settings
folder; copy that file into the same folder on your workstation, and
`femkit job machines` there lists it.

## Computed definitions — `model_prep`

A project that computes a value in Python (chapter 3, `definitions.py`)
needs femkit's `model_prep` environment — numpy, scipy, netCDF4 and xarray,
nothing built — which `bootstrap` installs with the others:

```bash
femkit env install model_prep
```

`project check` and `study prep` say so when a project needs it and it is
not there.

## Your observables scripts — `postprocess`

The scripts that compute your observables (chapter 3, `observe.py`) run in
femkit's `postprocess` environment — numpy, scipy, matplotlib, netCDF4,
xarray and meshio. A project whose scripts need more says so in its project
file, `[postprocess] packages` (chapter 3), so a copy of the project carries
it; each machine installs them:

```bash
femkit env install postprocess
```

installs femkit's set and every package any project under your projects root
names, in one solve. Adding a package to a project later leaves `postprocess`
as it is: `femkit env list` and `femkit doctor` say a package is to be
delivered, and the same `femkit env install postprocess` installs it into the
environment as it stands. A package femkit's own set already holds — numpy,
say — is never installed again, nor held to another version: `project check`
says so at its line of your project file.

## The web page — `serve`

femkit's web page runs its commands and shows each one's progress, and it
shows femkit's documents — this manual among them — with their tables and
diagrams drawn. It needs the `web` environment
(`femkit env install web`).

```bash
femkit serve start        # start the page's server in the background and print the address to open
femkit serve status       # every server you run here: is it up, and does it answer
femkit serve stop         # stop it
femkit serve restart      # start it afresh, keeping its address
femkit serve foreground   # run it in this terminal; Ctrl-C stops it
```

On a workstation the page listens on `127.0.0.1`, port 8000 (`--port` to
change). On a cluster's login node it listens on a socket only your account
can open (`--socket`; `--tcp` for a port instead), which you reach from your
own computer through `ssh -L`. The page shows your projects as cards; open
one to see it as a flowchart — a card for each file, its section told by the
card's colour, shape and icon (the legend button shows each), its state in its
badge, its findings counted; and a small card for each definition, with its
value — and Runs to see a study's geometries and meshes, each card tagged
with its case on the same line as its state, with Preview and Prep. The project
file itself is no card: the Parts tab beside the flowchart lists it, then every
part by section — your definitions and materials first — each with its state
or value and its findings; press one to find its card. Each card lists its
slots — `domain material → vacuum` among them — each with a dot a wire plugs
into, on the side facing the cards its wires come from, and a finding counted
on the slot it belongs to. A study's card names no engine — you choose the
engine when you prepare it; an observables part stands after the studies it
reads, a wire running from each study into its `studies` slot. The wires
are coloured by what they carry, and a dashed one waits for the built
geometry. Drag any card anywhere: where it stands is the page's alone, kept
while the page is open and never saved, and Reset layout puts every card
back. A card's copy button, or its menu, puts a copy of it elsewhere — the
same file, so selecting either lights both — and each wire runs to whichever
copy stands nearer; copies too live only in the page. Click a wire to light
it and its two cards and read what names what, and at which key — moving the
mouse over the canvas lights nothing; a card's chevron folds it to its title.
Settings, environments and
every other command are forms under Operations; light and dark are switched
from the top bar.

To change a file on the page, open its card: the page's text editor shows
the file, each finding at its line, a key's help when the mouse rests on it,
and the values a key allows as you type. Save first shows what the change
affects — the stages it would make anew — and writes the file only when you
agree. Your `definitions.py` cannot be saved from the page yet.

## Commands for changing femkit itself

Three commands are for someone who changes femkit's own files, not for using
it:

```bash
femkit schema check    # load every definition femkit ships, and report each problem
femkit schema docs     # write the reference pages from femkit's definitions again
femkit web build       # build the web page from its sources, with the web environment
```

## What is not built yet

Solving a calculation on a workstation or through a cluster's scheduler, and
reading the results, are not built yet ([plan](../plans/plan.md) § 4, M4,
M6). Today femkit installs and proves the solvers; starts and checks your
projects; and preps a study — its cases, and the jobs that make each case's
geometry and mesh: chapters 2 to 7.
