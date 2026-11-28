# ADR 0021: definitions — constants and computed values, each a typed number with its unit

**Role:** ADR

**Status:** accepted (2026-11-25); built; decisions
5–6 amended by [ADR 0022](0022-one-prep-step.md) — the values kept per
study by prep, the expansion now prep's. It amends
[ADR 0016](0016-every-step-runs-from-a-run-folder.md) decision 1 for one
thing: a project's definitions are computed by its functions during a check
and an expansion, outside a job — beside the geometry script, the second
exception of `models.md` § 8.4. Decision 2's observable's point, and its
"only a definition carries `type`", amended by
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 5): an
observable is a typed value, as a definition is, computed by the person's
function; none has a point. Decisions 1's types and 6's file amended by ADR
0025 (decision 6): a typed value may also be an array with named dimensions
and coordinates, and the kept values are written through xarray, their
metadata by the CF conventions, and the time leaves the file — the run's
records hold it, so the same values are the same bytes, and the file's
provenance names the study it is kept for and `definitions.py`'s SHA-256
once, as the script that computed it. Decision 7's list of what `definitions.py`
may import amended by ADR 0025 (decision 5): the modules `model_prep`'s
definition declares it provides, beside `project.definitions`, `math` and
`cmath`

**Authority:** the reasons and the alternatives only;
[`models.md`](../contracts/models.md) § 3 owns the definitions,
[`projects.md`](../contracts/projects.md) § 2 the file `definitions.py`,
[`core.md`](../contracts/core.md) § 11 the units

## Context

A project's shared values were its parameters, in `project.toml`: each a text,
a quantity with its unit (`"10 nm"`) or an arithmetic expression of other
parameters (`"gap / 2"`), read by femkit's one quantity grammar; every other
part wrote its quantities as text the same way (`size = "1 nm"`). Asked
whether parameter expressions should gain mathematical functions and physical
constants, the person, 2026-11-25, set the design instead, over several
messages:

- "just two kinds (1) constant with units, (2) a constant name with a python
  script that calculate what it is, and the python script should only assume
  numpy and scipy installed (or some defined package that we provide), and
  return a number and a unit";
- "it should not be presented as a string, no? it should be "name", "value",
  "type", "unit"";
- "due to python potential issues with default integer treatment etc, better
  specify number type as int or float/double/complex";
- one designated file for every computed definition, whose function femkit
  calls, femkit controlling what can be imported;
- "anything that is just an expression would be evaluated by python? or we
  should insist explicit script function?" — explicit functions;
- "our code guarantee a project.definitions namespace/module which will take
  care of all constants defined, and the program always just import
  project.definitions as def, and the citation of constants is always
  explicitly def.xxx";
- that femkit, not the person's code, converts units, and asked how
  dimensionless values and a permittivity written in different units are
  handled.

Measured that day with femkit's own units module: one permittivity written
`8.854187817e-12 F/m`, `C^2/(N m^2)`, `C/(V m)`, `A^2 s^4/(kg m^3)` and
`8.854187817e-3 pF/mm` reads as the same exact value, of one dimension.

## Decision

1. **Definitions replace parameters.** `project.toml`'s `[definitions]` holds
   each shared value, by its name, as a table: `type` — `int`, `float` (a
   64-bit double) or `complex`; `unit`, any unit of femkit's table or a
   product of them, `"1"` for a dimensionless value, never left out — an
   `int` takes `"1"` alone, a count; and exactly one of `value` — a number of
   its type, a complex as `[real, imaginary]` — or `function`, the name of a
   function in the project's `definitions.py`. Its address is
   `project:definitions.<name>`. A written value is read exactly; a computed
   one is recorded as its function returned it.
2. **No physical quantity is written as text** in the person's files — the
   parts and the materials: a recipe's size, a condition's value, an
   observable's point is `{value, unit}`, its number's type the field's own,
   or the name of a definition. Only a definition carries `type`. A job's
   resources keep the scheduler's own spellings (`wall = "02:00:00"`).
3. **Computed definitions are Python functions in one file**,
   `definitions.py`, which the person owns: femkit's template writes its header
   once — `import numpy as np`, `from scipy import constants`, `import
   project.definitions as defs` — and never edits it. The file holds imports
   and functions only. A definition's function takes no arguments, reads every
   other definition as `defs.<name>`, and returns a plain number of the
   definition's type, in SI units of its declared unit. No string is ever
   evaluated as Python: anything computed is a function.
4. **femkit provides `project.definitions`**, in memory, at each call — never
   a file in the project: every definition as a plain number, of its declared
   type, converted by femkit from its declared unit into SI — an angle in
   degrees, femkit's one convention for angles ([`design.md`](../design.md)) —
   computed ones in the order their reads of `defs.<name>` give,
   which femkit reads from the file without running it. femkit converts each
   function's result from SI into its declared unit. The person's code never
   converts a unit; a unit outside femkit's table is a finding.
5. **femkit runs the functions in an environment of its own**, holding numpy
   and scipy, once per distinct set of values: when an axis sweeps a constant,
   every function that reads it is computed again for each case, and each case
   records the value it got. They run during `project check` and `study
   expand` (the person, 2026-11-25: "during check and expand") — the second
   named exception to "code a person supplies is never run by a check"
   ([`models.md`](../contracts/models.md) § 8.4), beside the geometry script:
   in their own process, in that environment, never inside femkit, with a time
   limit; a save's impact in the page does not run them before the save, and
   says which computed values are computed again.
6. **The computed values are kept** by `study expand` — `project check`
   computes them and writes nothing — so every reader uses the same numbers
   (the person: "the middle result is saved … something that can be directly
   used everywhere in the project. time stamp/sha256 can be used to make sure
   the results are sync"): one entry per distinct set of constants, each
   holding the constants it was computed from, every computed value, when, and
   the SHA-256 of `definitions.py`, of the `[definitions]` table and the
   running environment's fingerprint, which every reader compares before using
   it — a mismatch is stale and computed again, never used silently; the time
   is shown, never trusted. The file is netCDF (the person, 2026-11-26: JSON
   declares no number's type and holds no complex number or array),
   `computed/definitions.nc`: one variable per computed definition, of its
   declared type — a complex one by netCDF4-python's complex convention
   (`auto_complex`, version 1.7 and later) — along one dimension, `point`, an
   entry per distinct set of constants; each variable's values in SI, its
   `units` the SI unit and `declared_unit` the one its definition states; the
   SHA-256s, the fingerprint and the time as the file's own attributes.
7. **What is checked before anything runs**: a `defs.<name>` naming no
   definition, a circle of definitions, a function named in `project.toml`
   that the file lacks, an import of anything but `project.definitions`,
   numpy, scipy, `math` and `cmath`, anything at the file's top level but imports and functions. **What
   is checked when it runs**: each result is a finite number of its declared
   type; an exception, a NaN, an infinity or a call past the time limit is a
   finding at the file and the line. Its dimension is the person's promise,
   written as its declared unit.

## Alternatives not chosen

- **Arithmetic expressions as text** (`"gap / 2"`), femkit's own grammar
  growing mathematical functions and physical constants: a second language
  beside Python, for what one function says.
- **A script file per computed definition**, reading its inputs from a JSON
  file: a file and a convention for each value; one file of functions reads
  as one place.
- **Importing each constant by name** (`from project import gap`), or all at
  once (`import *`): the first cannot be kept in step as definitions are
  added; the second hides which name is a definition. `defs.<name>` is
  explicit and needs no upkeep.
- **Each definition an object with `.value` and `.unit`**: every function
  would convert units and return a unit, where an nm read as m goes unseen.
- **Running the functions in femkit's own environment**: the person's code
  would share femkit's packages and their versions.

## Consequences

- Every part's schema, the materials' values, the templates, the manual and
  every axis address change with the definitions: `models.md` §§ 3, 5.1,
  `geometry.md` § 6 (a recipe's `"gap / 4"`), `materials.md` §§ 3, 7 (a
  value written `"4"`, an importer's `"0.0684043 um"`), `core.md` §§ 2, 11 (the
  quantity kinds that read expressions), and
  [ADR 0019](0019-section-order-block-states-axes-together.md) decision 3,
  whose formula of a parameter becomes a function in `definitions.py`.
- A study's axis writes its values as plain numbers and its `unit` once (the
  person, 2026-11-26, asked how a sweep is written): `values = [0.1, 0.05,
  0.025]`, `unit = "m"`.
- A dimensionless unit, `1`, is read by the units grammar as a plain number
  already; the table gains no row.
- A material's property stays in its material, with its source and its
  sign convention ([`materials.md`](../contracts/materials.md) § 3); a complex
  definition is for a value no material holds — a source's amplitude.
- The environment that runs `definitions.py` is `model_prep` (the person,
  2026-11-25), declared and installed by femkit like the engines', holding
  numpy and scipy.
- A geometry script keeps working in its component's frame unit (the person,
  2026-11-25): femkit hands it the definitions it declares — computed ones
  included, taken from the case, which records each value it got —
  converted into that unit, as today,
  since Gmsh's and OpenCASCADE's tolerances are lengths in the drawing's own
  unit; `definitions.py` works in SI. The person converts neither way.
- femkit's control environment, which reads the kept values, and
  `model_prep`, whose program writes them, gain the netCDF4 library, version
  1.7.1 or later (the person's approval, 2026-11-26).
