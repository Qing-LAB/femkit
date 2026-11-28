# ADR 0026: environments under conda's management; every call starts clean

**Role:** ADR

**Status:** accepted (2026-11-27); it amends decision 5 of
[ADR 0016](0016-every-step-runs-from-a-run-folder.md): a run no longer keeps
the shell it is started in

**Authority:** the reasons and the alternatives only;
[`envs.md`](../contracts/envs.md) §§ 1, 3, 4.4, 7,
[`definitions.md`](../contracts/definitions.md) §§ 4.7, 6 and
[`jobs.md`](../contracts/jobs.md) § 4 own the rules

## Context

femkit made its environments at prefixes of its own, under its data folder,
and ran the manager in places of its own, so that no setting of the person's
could reach an environment. That took over what the package manager manages:
where an environment lies, its package cache, its list of environments, how a
shell enters one. A review of the environment framework on 2026-11-27 found,
besides, that not every process femkit started on an environment's Python came
through the one clean start — the web server's supervisor and child, the
`femkit` command itself — and that the person's conda settings could still
change what a create installed.

The person, that day:

1. "why can't we leave conda's management as is, and have our env fitting
   there? … as long as we strictly make sure all components are placed within
   its own env dir, whereever conda manages it … why would you take over what
   conda manages"
2. "make sure the call has good practice in how each run/script call is
   guarded within env and toolchain from outside does not leak into the work.
   and you better make sure not handcrafted all the code but rather have
   framework/api design to handle this … simple task"

and, deciding between the two ways that answered the first: **"Conda manages,
recipe decides."**

## Decision

1. **Named environments, under the manager's management.** Every environment
   is an ordinary named environment of the manager, `femkit` and
   `femkit-<name>` (`naming.toml`), made by `create -n` where the manager keeps
   environments; its package cache, its list of environments and its
   activation are the manager's, as the person set it up. femkit sets none of
   the manager's own variables.
2. **Its prefix is the one the manager names so.** femkit takes, of the
   prefixes the manager lists, the one it names by the environment's name —
   conda's own name for each, or a listed one in its `envs_dirs` — as the
   earlier tool does; never a prefix formed, never a listed path elsewhere
   whose last step only happens to be the name. The earlier tool's presence
   states come with it: a folder in the manager's way it does not list,
   `orphan`, which femkit never makes an environment over nor removes; a
   listing with no folder, `ghost`; a listed folder that is no environment,
   `broken`.
3. **The recipe decides what goes in.** Every command that solves or installs
   carries the manager's own flags that set aside each of the person's
   settings that would change what goes in — their channels, default
   packages, pinned packages — and names every channel by its full address,
   which no channel alias or custom channel re-routes; a forced platform and
   overridden virtual packages never pass the clean start. A setting nothing
   sets aside refuses an install before any create, naming it and its file;
   the manifest records which were found and set aside. A project's packages
   are only new ones: one naming a package the recipe declares or pins is
   never delivered, and its project file says so.
4. **One clean-start door for every call, run scripts included.** Every
   process femkit starts for an environment — a manager command, a command in
   an environment, femkit's own programs on an environment's Python, the web
   server's supervisor and child, and a run script — begins from the one
   start `process.toml` declares, read by one owner (`envs/start.py`) and, before
   Python exists, by the install script from the same data. This amends
   ADR 0016 decision 5, "the run keeps the shell it is started in". femkit's
   own process is the one that guards the rest, not work: it runs isolated
   (`-I`) and keeps the shell it is typed in but library injection
   (`femkit_sheds`), so it sees the machine it probes as the person does. What
   failed there was a run script that restarted itself with an empty
   environment, losing the `module` function a batch job inherits, so a
   site's preamble failed on every run. The run script now unsets the
   declared families of variables in its own shell instead, and stops
   exporting every shell function but those a scheduler kind declares — the
   function stays defined in the shell — so the preamble's `module` survives.
   Whether that holds on a cluster's batch job is the person's own HPC test:
   it is not measured.
5. **Entering by the manager's own way.** A run script that enters by the
   shell function evaluates the manager's own hook, as the manager its
   record names prints it (`conda shell.bash hook`), never a file guessed from
   where the manager lies; one that enters by `source activate` stops, saying
   why, where nothing put `activate` on `PATH` after the clean start.

## Departures from the earlier tool

- **A clean start where the earlier tool passes the shell through.** The
  earlier tool runs a step with the environment it was started in, stripping
  a few known leaks; femkit starts every call from a declared pass list, the
  person's second requirement: a leak femkit does not know of cannot pass a
  list that does not name it.
- **Channels overridden.** The earlier tool honours the person's channels and
  mirrors; femkit names its own on every create, delivery and removal, and
  sets the person's aside: the recipe decides what goes in.

## Alternatives not chosen

- **femkit's own prefixes and manager home** — what came before: it took over
  what conda manages, against the person's first requirement.
- **The person's settings honoured** — a site's channel mirror among them:
  the person decided that the recipe decides.
- **A deny-list of leaking variables** — every variable a build reads would
  have to be known ([ADR 0006](0006-toolchain-first.md)).

## Consequences

- `env list` and `doctor` find each environment by the manager's name for it,
  name an orphan folder with its remedy, and say what a project added that is
  to be delivered.
- What femkit's own control process finds on `PATH` — a scheduler's commands
  for the probe, the GPU query — and the loaded modules `config init` shows
  are read in the clean start the `femkit` command begins it from.
- A mamba install records none of the person's settings: where mamba says it
  read them is not measured, nor whether it honours default or pinned packages.
