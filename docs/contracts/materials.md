# Materials contract — the property list, the material format, libraries and importers

**Role:** contract
**Status:** current, approved by the person
([ADR 0014](../decisions/0014-materials.md)). Built in `femkit/materials/`:
the property list's first entry (§ 1), a project's own
materials with fixed values and their check (§ 3), the assignment and its
check (§ 5), and a fixed value held exactly by a case (§ 6). Not built:
dispersion models (§ 2), tables and models as datasets (§ 3), the global
library (§ 4), the conversions and the checks of § 6 beyond a fixed value,
importers (§ 7) (plan § 4, E), and translation (§ 8; plan § 4, M6)
**Authority:** the property list and its names in each engine and source;
dispersion models; the material format; the global library and a project's
own, and how a material is found; the material assignment of a component;
working out a property's data for a case; importers; how a translator names a
property. Where a material folder sits in a project is
[`projects.md`](projects.md) § 2; the physics a property enters is the
formulation's ([`models.md`](models.md) § 4). The reasons are
[ADR 0014](../decisions/0014-materials.md).

## The short version

| rule | § |
|---|---|
| One **property list** names every property once, with its unit, its form, and its name in each engine and each source | 1 |
| **Dispersion models** are a closed list, declared as data | 2 |
| A **material** is a folder: `material.toml` and its tables; each property holds datasets, each named by its source | 3 |
| A material is found in the **project first, then the global library**; `GLOBAL/` names the global one explicitly; where each came from is shown in every log and result | 4 |
| A component **assigns** a material, and a dataset per property, to each body group its contract promises | 5 |
| A case holds the **data it used**, never where it was found; a changed material makes new cases, and the old ones keep their runs | 6 |
| **Importers**, one per source, declared as data; a value without a source is refused | 7 |
| A translator writes a property under **the list's name for its engine** | 8 |

## 1. The property list — `femkit/data/properties.toml`

Every material property femkit knows, named once:

```toml
[relative_permittivity]
description = "the material's relative permittivity"
unit = "1"
values = "complex"                 # real | complex
shape = "scalar"                   # scalar | tensor (3 x 3, in the component's frame)
depends_on = ["wavelength", "temperature"]   # what a dataset may vary with
equivalents = ["refractive_index"] # forms convertible to it; electromagnetics.md states each conversion and its sign
names = { elmer = "Relative Permittivity" }  # its name in each engine and source that has one

[refractive_index]
description = "the complex refractive index, n + ik under exp(-iwt)"
unit = "1"
values = "complex"
shape = "scalar"
depends_on = ["wavelength", "temperature"]
equivalents = ["relative_permittivity"]
names = { refractiveindex_info = "nk" }
```

- **A name** is the property's plain name with underscores; a symbol is never
  a name.
- **`names`** is read in both directions: an importer reads a source's name
  to find the property (§ 7), a translator writes the engine's name (§ 8). A
  new engine or source is a key here, not code. A name may be a table of
  keywords where an engine writes one value as several — a complex value's real
  and imaginary parts, a tensor's components; which engines do so is not
  measured yet.
- **A formulation** lists the property names it reads, and whether it needs
  them real or allows them complex ([`models.md`](models.md) § 4); it never
  defines a property of its own.
- **An equivalent form** is converted by femkit when a case is expanded (§ 6),
  by the conversion its science document states — never by a translator.
- Every key of the list is in
  [`../reference/definitions.md`](../reference/definitions.md) once built.
- **The first entry** is `relative_permittivity`, the one property
  `electrostatics` reads; `refractive_index` and the others join with the
  formulations that read them. Built, read by the check frame
  ([`models.md`](models.md) § 11.1); not built yet: a formulation naming its
  properties from the list (plan § 7).

## 2. Dispersion models — `femkit/data/dispersion.toml`

A dataset may give a property as a named model of how it varies with
wavelength or frequency, from a closed list declared as data: each model's
name, its parameters with their units, the property it gives, and the section
of the science document that states its formula and sign convention. The first
models are those the bowtie's materials need (plan § 8); a model not on the
list is refused, naming the list. Not built yet (plan § 4, E).

## 3. A material — `<name>/material.toml` and its tables

```toml
schema = 1
display = "Gold"
formula = "Au"
aliases = ["Au"]                                   # names a search of a library finds it by

[properties.relative_permittivity.johnson_christy_1972]
table = "johnson_christy_1972.csv"                 # beside this file: the variable, then the real and imaginary parts
sha256 = "…"
variable = { name = "wavelength", unit = "nm" }
interpolation = "linear"
convention = "exp(-iwt)"                           # the source data's
source = "P. B. Johnson and R. W. Christy, Phys. Rev. B 6, 4370 (1972)"
range = ["188 nm", "1937 nm"]

[notes]                                            # anything the person keeps beside it; read by no step
```

- **The file states its shape**, `schema = 1`, as every part's file does
  ([`models.md`](models.md) § 2).
- **`display`, `formula` and `aliases` are for a person and a search**, each
  optional but `display`: nothing refers to a material by them, since its name
  is its folder's path.
- **The material's name is its folder's path in its library** — `gold`,
  `silicon_dioxide`, or grouped, `metals/gold` — under the one name rule of
  [`projects.md`](projects.md) § 3.
- **A property holds one or more datasets**, each named by its source
  (`johnson_christy_1972`, `olmon_2012`). A dataset is one of: `value` (a
  constant with its unit), `table` (a file beside `material.toml`, with its
  SHA-256, `variable` and `interpolation`), or `model` (a dispersion model of
  § 2, with its parameters).
- **Every dataset states** its `source` — a citation a reader can check, with
  its DOI where there is one — its `convention` for complex data (`real`,
  `exp(-iwt)`, `exp(+iwt)`), its `range` (`all`, or `[from, to]` in its
  variable), and its conditions where they matter — `temperature`, for one;
  `uncertainty` where the source gives one. These are `stated` fields
  ([`core.md`](core.md) § 2): a dataset being written may lack them, a finding
  of `project check`; `study expand` refuses a case resting on one that does.
- A material file starts from one in femkit's project templates or in the
  library ([`projects.md`](projects.md) § 7) — a fixed value as the
  two-material template's `dielectric_2`:

  ```toml
  schema = 1
  display = "Dielectric 2"

  [properties.relative_permittivity.benchmark]
  value = "4"
  convention = "real"
  source = "the two-material benchmark's choice (docs/science/electrostatics.md § 9.1)"
  range = "all"
  ```

- **Until step E**, a project's own materials are read, each dataset a `value`,
  and a case holds that value as § 6 says, so the templates are checked and
  expanded before step E; `table` and `model`, the global library, importers
  and the conversions of § 6 are step E (plan § 4, E).

## 4. Where materials live, and how one is found

- **The global library**: `<projects root>/materials/`, the person's, shared by
  their projects — the folder of the one part kind the layout declares with a
  library ([`projects.md`](projects.md) § 4). When `project new` finds the
  root without it, it makes it and copies femkit's shipped materials
  (`femkit/data/materials/`, starting with `vacuum`) into it, each with its
  origin recorded; they are the person's from then on. A later femkit whose
  shipped material differs says an update is available and shows what
  changed; it never overwrites the person's copy. Not built yet (plan § 4,
  E): today `project new` makes the root alone, and nothing reads the
  library.
- **A project's own**: `<project>/materials/`.
- **Finding a material by name**:
  - `GLOBAL/metals/gold` names the global library's, explicitly — the prefix is
    capitals, and a name never is ([`projects.md`](projects.md) § 3);
  - any other name, `metals/gold`, is the project's own first, then the global
    library's: a project's material takes priority, as the person's
    customization;
  - a name in neither is a finding of `project check` on the assignment's
    `material` key, naming the name and both places it looked in, with the
    materials each holds as its choices ([`core.md`](core.md) § 10). Until the
    global library is read (plan § 4, E), a name the project lacks, and every
    `GLOBAL/` name, is not checked yet — its component is `unchecked`
    ([`projects.md`](projects.md) § 8), the note saying "the global material
    library is not read yet" — and `study expand` refuses a case resting on
    it; but a name the project lacks that is close to one it holds — a
    misspelling, most likely — is a warning there, `no-such-material`: "no
    material `vaccum` in this project; did you mean `vacuum`?", the project's
    materials its choices.
- **Every load is checked**: each value's type, sign and range rules; every
  value's unit, read by the one unit grammar ([`core.md`](core.md) § 11), so it
  converts to what each engine reads (§ 8); a dataset's missing source,
  convention or range, as § 3 says.
  A shipped material is checked by the basic tests as well.
- **Where each material came from is always shown**: the page shows it beside
  each assignment, and every run's log and every result state, for each
  assignment, the material's name, whether it was the project's or `GLOBAL`,
  the dataset and its source:
  `gold_left ← gold (GLOBAL/metals/gold), dataset johnson_christy_1972 — P. B. Johnson and R. W. Christy, Phys. Rev. B 6, 4370 (1972)`.
- **A moved project** — zipped and unpacked under another root — finds its
  `GLOBAL/` materials in that root's library; one missing there is a finding
  naming it.
- **Writes** go through the door ([`projects.md`](projects.md) § 6). A write to
  the global library holds the library's lock and asks for confirmation; this
  is the rule's one home.

## 5. The assignment — a component's `[assign]`

```toml
[assign.gold_left]                                 # a body group the component's contract promises (geometry.md § 3)
material = "GLOBAL/metals/gold"
datasets = { relative_permittivity = "johnson_christy_1972" }
```

- **The table and its check are this package's**: the check is declared
  beside the table for the component's schema key, as `PART_CHECKS =
  {"geometry.component": check}` in `femkit/materials/assign.py`, and
  registered at femkit's start after the component's own check
  ([`projects.md`](projects.md) § 6; [`api.md`](api.md) § 6); it reads the
  component's frame and groups through the layout's object types.
- **Each body gets exactly one material** through the groups assigned; two
  assignments reaching one body are refused, naming the body — the rule's one
  home ([`geometry.md`](geometry.md) § 7 checks it once the geometry exists).
- **A property with several datasets names one**; there is no default dataset.
- A study may vary a dataset as an axis — a physical sweep across sources
  ([`models.md`](models.md) § 5).

## 6. A property's data for a case

When a study is expanded ([`models.md`](models.md) § 5.3), for every property
the physics reads, in every assigned body:

- the dataset is read and checked against its SHA-256;
- an equivalent form is converted to the property the formulation reads (§ 1);
- complex data is converted from its source's convention to the physics'
  convention, and the conversion recorded; a passive material whose converted
  loss has the wrong sign is refused, naming the material and its source
  convention;
- a dataset that varies with a variable the step does not supply — an
  optical-frequency table for a static step — is refused; otherwise it is taken
  at the value the step's kind supplies — the vacuum wavelength or the
  frequency, for a `frequency` step ([`models.md`](models.md) § 4.2) — and a
  case whose value lies outside the dataset's range is refused;
- every quantity is read by the one unit grammar ([`core.md`](core.md) § 11).

The case holds the data it used — each dataset's name and its content — and
never where the material was found or what else its file holds: copying a
library material into the project, or editing its `[notes]`, changes no case.
Where each material was found, and its file's hash, are recorded in each
preparation's manifest ([`models.md`](models.md) § 9.4). A dataset edited after
the case was written is new content: expanding the study again makes new cases,
and the old ones become `orphaned` and keep their runs ([`models.md`](models.md)
§ 9.5); until then `case list` flags each case whose data differs from what its
materials now hold — shown, never applied silently.

## 7. Importers — `femkit/data/importers/<source>.toml`

`material import SOURCE FILE --into library|project [--as NAME]` reads one
source's file and writes a material, or a new dataset of an existing one,
keeping the source. Each source is declared as data: its file format, how its
records map onto the dataset forms of § 3, the units its data is in, and its
names in the property list's `names`. A record that maps onto no form — a
formula the dispersion list lacks — is refused, naming it; a record without a
source is refused. femkit never fetches a file itself: the person supplies it.

The first importer is for refractiveindex.info's files (one YAML file per
material and source; tabulated `n`, tabulated `nk`, or one of nine formulas;
its range in micrometres). Reading YAML needs a library the control environment
does not hold (measured); adding it is an environment change, the
person's decision. Not built yet (plan § 4, E).

## 8. Translation

A translator ([`models.md`](models.md) § 9.1) writes each property of a case
under the property list's name for its engine, which reaches it with the
environment's bindings — the documents that cross into the environment carry
the names for that engine — never from a material file or a library. An engine
with no name of its own for a property — NGSolve, whose script femkit writes —
uses femkit's name.
