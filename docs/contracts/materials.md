# Materials contract — the property list, the material format, libraries and importers

**Role:** contract
**Status:** current, approved by the person
([ADR 0014](../decisions/0014-materials.md)). Built in `femkit/materials/`:
the property list and its equivalent forms (§ 1), the variables and dispersion
models (§ 2), materials with their values, tables and models and their checks
(§ 3), the global library (§ 4), the assignment and its check (§ 5), a case's
data under a step that supplies no variable, and the conversions of § 6 as
functions, and the first importer (§ 7). Not built: a case taking a dataset at
a variable's value (§ 6; plan § 4, M9); translation (§ 8; plan § 4, M6)
**Authority:** the property list and its names in each engine and source;
the variables a dataset may vary with; dispersion models; the material format;
the global library and a project's own, and how a material is found; the
material assignment of a component; working out a property's data for a case;
importers; how a translator names a property. Where a material folder sits in
a project is [`projects.md`](projects.md) § 2; the physics a property enters
is the formulation's ([`models.md`](models.md) § 4); what the data means — the
conventions, the conversions, each model's formula — is
[`../science/material-data.md`](../science/material-data.md). The reasons are
[ADR 0014](../decisions/0014-materials.md).

## The short version

| rule | § |
|---|---|
| One **property list** names every property once, with its unit, its form, and its name in each engine and each source | 1 |
| The **variables** a dataset may vary with, and the **dispersion models**, are closed lists, declared as data | 2 |
| A **material** is a folder: `material.toml` and its tables; each property holds datasets, each named by its source: a value, a table or a model | 3 |
| A material is found in the **project first, then the global library**; `GLOBAL/` names the global one explicitly; where each came from is shown | 4 |
| A component **assigns** a material, and a dataset per property, to each body group its contract promises | 5 |
| A case holds the **data it used**, never where it was found; a changed material makes new cases, and the old ones keep their runs | 6 |
| **Importers**, one per source, declared as data, each writing a **new** material; a value without a source is refused | 7 |
| A translator writes a property under **the list's name for its engine** | 8 |

## 1. The property list — `femkit/data/properties.toml`

Every material property femkit knows, named once:

```toml
[relative_permittivity]
description = "the material's relative permittivity"
unit = "1"
values = "complex"                 # real | complex
shape = "scalar"                   # scalar | tensor (3 x 3, in the component's frame)
depends_on = ["wavelength", "frequency", "photon_energy", "temperature"]   # the variables (§ 2) a dataset may vary with
equivalents = ["refractive_index"] # forms convertible to it, by material-data.md § 3
names = { elmer = "Relative Permittivity" }  # its name in each engine and source that has one

[refractive_index]
description = "the complex refractive index"
unit = "1"
values = "complex"
shape = "scalar"
depends_on = ["wavelength", "frequency", "photon_energy", "temperature"]
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
- **An equivalent form** is a property a formulation never reads but a source
  gives: `refractive_index`, listed under `relative_permittivity`'s
  `equivalents`. A material may hold a dataset under either; a formulation
  reading `relative_permittivity` takes a dataset held under an equivalent, and
  femkit converts it when a case is expanded (§ 6) by
  [`material-data.md`](../science/material-data.md) § 3 — never a translator.
  An assignment names the dataset by the property the formulation reads
  (§ 5); one name held under both the property and an equivalent is a finding
  on the material, naming both.
- Every key of the list is in
  [`../reference/definitions.md`](../reference/definitions.md).
- **The entries**: `relative_permittivity`, the one property `electrostatics`
  reads, and `refractive_index`, its equivalent, which the first importer
  writes (§ 7); the others join with the formulations that read them. A
  formulation names the properties it reads from the list — never their unit
  or description — and one naming a property the list lacks is refused when
  it loads.

## 2. Variables and dispersion models — `femkit/data/dispersion.toml`

**The variables** a dataset may vary with, each named once with its dimension:
`wavelength` (the vacuum wavelength, a length), `frequency` (1/time) and
`photon_energy` (an energy) — one spectral position stated three ways,
converted exactly among each other by
[`material-data.md`](../science/material-data.md) § 4 — and `temperature`.
The conditions a dataset states (`temperature`) are declared once, beside the
conventions, and each must be a variable of the list: one that is not is
refused when the list loads. A
property's `depends_on` names the variables its datasets may vary with; a step
kind names the variable it supplies ([`models.md`](models.md) § 4.2).

**The dispersion models**, a closed list: each model's name, its sentence, the
property it gives, the variable its formula is written in, its parameters
with their dimensions and their signs — a list of terms where the model sums
them — the convention its formula is written in, and the section of
[`material-data.md`](../science/material-data.md) that states it; the list is
the data file, its keys on [`../reference/definitions.md`](../reference/definitions.md).
It holds `sellmeier` and `drude_lorentz`. A model not on the list is refused,
naming the list. A model joins the list with its formula's code, its science
section and its checks there, and a test holds the list and the code to each
other: a model declared without a formula, or a formula of no declared model,
fails it.

## 3. A material — `<name>/material.toml` and its tables

```toml
schema = 1
display = "Gold"
formula = "Au"
aliases = ["Au"]                                   # other names it goes by, for a person

[properties.refractive_index.johnson]
table = "johnson.csv"                              # beside this file
sha256 = "…"
interpolation = "linear"
convention = "exp(-iwt)"
source = "P. B. Johnson and R. W. Christy. Optical constants of the noble metals. Phys. Rev. B 6, 4370-4379 (1972), doi:10.1103/PhysRevB.6.4370"
range = ["0.1879 um", "1.9370 um"]

[properties.refractive_index.johnson.variable]
name = "wavelength"
unit = "um"

[notes]                                            # anything the person keeps beside it; read by no step
johnson = "Room temperature"
```

- **The file states its shape**, `schema = 1`, as every part's file does
  ([`models.md`](models.md) § 2).
- **`display`, `formula` and `aliases` are for a person**, each optional but
  `display`: nothing refers to a material by them, since its name is its
  folder's path.
- **The material's name is its folder's path in its library** — `gold`,
  `silicon_dioxide`, or grouped, `metals/gold` — under the one name rule of
  [`projects.md`](projects.md) § 3.
- **A property holds one or more datasets**, each named by its source
  (`johnson`, `olmon_2012`). A dataset is exactly one of:
  - **`value`**: a real constant, with its unit where it has one (a complex
    constant is not built: plan § 4, M9);
  - **`table`**: a file beside `material.toml`, with its `sha256`, its
    `variable` — a name from the variables list and the unit its column is
    written in, of that variable's dimension — and its `interpolation`,
    `linear` ([`material-data.md`](../science/material-data.md) § 5). The file
    is comma-separated text: a first row naming its columns — a first row of
    numbers is a finding, since its point would be lost — then one row per
    point, the variable increasing strictly, blank lines at its end ignored;
    each row the variable, then the value — or, for data that is not `real`,
    its real and imaginary parts in the dataset's convention (for
    `refractive_index` under `exp(-iwt)`, $n$ and $\kappa$) — each a decimal
    number, read exactly, in the property's unit;
  - **`model`**: a dispersion model's name from the list (§ 2), and its
    `parameters`, each a quantity in its declared dimension and of its
    declared sign.
- **Passive data**: complex data whose loss has the sign a passive material
  cannot have under its convention
  ([`material-data.md`](../science/material-data.md) § 2) — a table's row, a
  model's negative damping — is a finding, naming the row or the parameter.
- **A table's digest is required**: a table without `sha256`, or whose file's
  SHA-256 differs, is a finding of `project check` at `sha256`, its right
  value the file's digest — so the person who writes a table by hand pastes
  it, and a table changed under its material is seen. A table whose file is
  missing, unreadable, or not of the shape above is a finding at `table`,
  naming its line.
- **Every dataset states** its `source` — a citation a reader can check, with
  its DOI where there is one — its `convention` for complex data (`real`,
  `exp(-iwt)`, `exp(+iwt)`), its `range` (`all`, or `[from, to]` in any of its
  variable's forms), and its conditions where they matter — `temperature`,
  for one; `uncertainty` where the source gives one. These are `stated` fields
  ([`core.md`](core.md) § 2): a dataset being written may lack them, a finding
  of `project check`; `study expand` refuses a case resting on one that does.
  A model's dataset states the convention its model is written in, and
  another is a finding naming the model's. A table's range is `[from, to]`,
  from below to, within its first and last rows — `all`, or a range beyond
  them, is a finding at `range` naming the rows' extent.
- **Findings come in the order a person fixes them**: a table's shape before
  its digest, so the digest offered is that of a table that reads.
- A material file starts from one in femkit's project templates or in the
  library ([`projects.md`](projects.md) § 7), or is written by an importer
  (§ 7) — a fixed value as the two-material template's `dielectric_2`:

  ```toml
  schema = 1
  display = "Dielectric 2"

  [properties.relative_permittivity.benchmark]
  value = "4"
  convention = "real"
  source = "the two-material benchmark's choice (docs/science/electrostatics.md § 9.1)"
  range = "all"
  ```

## 4. Where materials live, and how one is found

- **The global library**: `<projects root>/materials/`, the person's, shared by
  their projects — the folder of the one part kind the layout declares with a
  library ([`projects.md`](projects.md) § 4).
- **femkit's shipped materials** are `femkit/data/materials/`, starting with
  `vacuum`, each written as a template is, the comment above each key its
  help ([`projects.md`](projects.md) § 7). When `project new` finds the root
  without `materials/`, it makes it and copies the shipped materials into it,
  and records, in the library's own side file `materials/.femkit/shipped.json`,
  each copied material's name and the digest of femkit's files it was copied
  from. They are the person's from then on.
- **A changed shipped material is offered, never applied.** When femkit's
  shipped material no longer has the digest its copy recorded, and the
  person's copy differs from femkit's file as it is now, `project check` says
  so for each library material the project uses, as an `info` finding
  `shipped-changed` on that material: the keys at which the person's copy and
  femkit's file differ — some may be the person's own edits — and where
  femkit's file is. Once the copy matches femkit's file, nothing is said. femkit
  never overwrites the person's copy; they copy what they want.
- **A project's own**: `<project>/materials/`.
- **Finding a material by name**:
  - `GLOBAL/metals/gold` names the global library's, explicitly — the prefix is
    capitals, and a name never is ([`projects.md`](projects.md) § 3);
  - any other name, `metals/gold`, is the project's own first, then the global
    library's: a project's material takes priority, as the person's
    customization;
  - a name in neither is a finding of `project check` on the assignment's
    `material` key, `no-such-material`, naming the name and both places it
    looked in — "did you mean" the closest, by its whole name or its last
    step, in either place, written as the choice would be, as its right
    value; with none close, the materials each holds as its choices
    ([`core.md`](core.md) § 10); where the root has no library yet, the
    finding says so, and that the next `project new` makes it. A name the
    name rule refuses — `Global/gold` — is `bad-name` at the same key,
    saying what in it breaks the rule, its right value the name it most
    likely meant.
- **Every load is checked**: each value's type, sign and range rules; every
  value's unit, read by the one unit grammar ([`core.md`](core.md) § 11), so it
  converts to what each engine reads (§ 8); a dataset's missing source,
  convention or range, as § 3 says. A library material is loaded and checked
  when a project names it; its findings name its file by its full path, since
  it lies outside the project. A shipped material is checked by the basic
  tests as well.
- **Where each material came from is always shown**: `case list` shows, for
  each case's assignment, the material's name, where that name finds it now
  — the project, the library, or nowhere — the dataset and its source:
  `gold_left ← gold (GLOBAL/metals/gold), dataset johnson — P. B. Johnson and R. W. Christy, …`;
  the page beside each assignment (plan § 4, G), and every run's log and
  every result, the same (plan § 4, M6).
- **A moved project** — zipped and unpacked under another root — finds its
  `GLOBAL/` materials in that root's library; one missing there is a finding
  naming it.
- **Writes** go through the door ([`projects.md`](projects.md) § 6). A write to
  the global library — the seeding above, an import (§ 7) — holds the
  library's lock and is shown as its plan before it is applied; this is the
  rule's one home.

## 5. The assignment — a component's `[assign]`

```toml
[assign.gold_left]                                 # a body group the component's contract promises (geometry.md § 3)
material = "GLOBAL/metals/gold"
datasets = { relative_permittivity = "johnson" }
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
- **A property with several datasets names one**, by the property the
  formulation reads, among the datasets held under it and its equivalents
  (§ 1); there is no default dataset.
- A study may vary a dataset as an axis — a physical sweep across sources
  ([`models.md`](models.md) § 5).

## 6. A property's data for a case

When a study is expanded ([`models.md`](models.md) § 5.3), for every property
the physics reads, in every assigned body:

- the dataset is read and checked against its SHA-256;
- a dataset that varies with a variable the step does not supply is refused —
  a table or a model for a `stationary` step, which supplies none
  ([`models.md`](models.md) § 4.2): `project check` gives it as an error at
  the assignment's `datasets.<property>`, `dataset-varies`, naming the
  variable and the step, and saying what would be right — a dataset that
  holds there: for a static step, a `value` of the property at zero
  frequency, its range `all` — and that no step femkit has yet supplies a
  wavelength (plan § 4, M9); `study expand` refuses a case resting on it. A
  `value` whose range is not `all` holds only where its range says, never at
  zero frequency, and is refused under a static step the same way
  ([`material-data.md`](../science/material-data.md) § 7);
- otherwise it is taken at the value the step's kind supplies — the vacuum
  wavelength or the frequency, for a `frequency` step — converted exactly to
  the dataset's variable; a case whose value lies outside the dataset's range
  is refused;
- an equivalent form is converted to the property the formulation reads (§ 1);
- complex data is converted from its source's convention to the physics'
  convention, and the conversion recorded; a passive material whose converted
  loss has the wrong sign is refused, naming the material and its source
  convention ([`material-data.md`](../science/material-data.md) § 2);
- every quantity is read by the one unit grammar ([`core.md`](core.md) § 11).

Each of these is built as a function of a dataset and the variable's value,
exact, with the checks of [`material-data.md`](../science/material-data.md)
§ 8; a case uses them with the first step that supplies a variable, the
`frequency` kind (plan § 4, M9). Until then a case takes a `value` held under
the property the formulation reads; one held under an equivalent form is a
finding of `project check` at the assignment's `datasets.<property>`,
`form-unconverted`, saying what would be right — a dataset of the property
the formulation reads — and `study expand` refuses a case resting on it.

The case holds the data it used — each material by its name in its library,
never `GLOBAL/`, so one material written either way is one case, and each
dataset's name and its content, its source, convention and range among it —
and never where the material was found or what else its file holds: copying a
library material into the project, or editing its `[notes]`, changes no
case. Where each material was found, and its file's hash,
are recorded in each preparation's manifest ([`models.md`](models.md) § 9.4).
A dataset edited after the case was written is new content: expanding the
study again makes new cases, and the old ones become `orphaned` and keep their
runs ([`models.md`](models.md) § 9.5); until then `case list` flags each case
whose data differs from what its materials now hold, naming the body, the
material and dataset, and what differs — shown, never applied silently — and
each step of the plan of `study expand` that writes a case because its
materials' data changed names the case it renews.

## 7. Importers — `femkit/data/importers/<source>.toml`

`material import SOURCE FILE --as NAME --into library|project [--project P]`
reads one source's file and writes a **new** material, `NAME`'s folder — its
`material.toml` and its table — in the global library or the project's
`materials/`; never over one there, and never into one: femkit changes no
file the person wrote ([`projects.md`](projects.md) § 7). To add a source to
a material they have, the person copies the dataset's lines and its table
from the imported folder into theirs, and `project check` checks them. The
written file is one the person reads and edits as their own: each key under
its help, as a template's — a model's parameters under the help the
dispersion list gives them, its terms each a table of their own, and a key it
cannot fill, such as a range, a temperature or an uncertainty the source does
not state, shown commented out under its help. A condition the declaration
maps must be a field a dataset states; one that is not is refused when the
declaration loads. Every refusal
says what to do instead: over a material there, to import it under another
name and copy its lines; a file whose name gives no dataset's name, to
rename the file; an unknown source, the sources there are. An import whose
name a library material also has says, in its plan, as a warning
`found-first`, that the project's will be found first.

Each source is declared as data: its file format, how its records map onto
the dataset forms of § 3, the units its data is in, and its names in the
property list's `names`, and every key a file may hold. The dataset is named
by the file's name, by the name rule (`Johnson.yml`, `johnson`). A key the
declaration does not map, at the file's top or in a record, is refused,
naming it, `unmapped-key`: nothing a file says is dropped; the declaration
lists the keys it knows of but does not map, each with what it can state, so
the refusal says it. A record that maps onto no form —
a formula the dispersion list lacks — is refused, naming it; a record without
a source is refused. A file holding several records is refused, naming them:
one import is one dataset — a refractive index whose $n$ and $\kappa$ come as
two tables on their own wavelengths is not imported, since joining them would
resample the source's data. femkit never fetches a file itself: the person
supplies it.

The first importer is for refractiveindex.info's files — one YAML file per
material and source, its data in the public domain (CC0) — read with PyYAML's
`BaseLoader`, so every number stays text and is read exactly. Its declaration,
`femkit/data/importers/refractiveindex_info.toml`, maps `tabulated nk` and
`tabulated n` to `refractive_index` tables and `formula 1` and `formula 2` to
the `sellmeier` model, as [`material-data.md`](../science/material-data.md)
§§ 3 and 6.1 say; any other record is refused, naming it. Its `SPECS` block,
which can state that a file's wavelengths are in air or its index relative to
air, is not mapped, so a file holding one is refused, naming it
([`material-data.md`](../science/material-data.md) § 4).

`REFERENCES` becomes the dataset's `source`, its links reduced to their text
and their DOIs kept; `CONDITIONS`' `temperature` its `temperature`, in K, and
any other condition is refused, naming it, never dropped; `wavelength_range`,
or a table's first and last rows, its `range`, each number as the source wrote
it — a formula without its range is written without one, which `project
check` then asks for; `NOTES`, or `COMMENTS` as older files call it, the
material's `[notes]`, under the dataset's name. An import into the library of
a root that has none is refused, saying that the next `project new` makes it
(§ 4).

## 8. Translation

A translator ([`models.md`](models.md) § 9.1) writes each property of a case
under the property list's name for its engine, which reaches it with the
environment's bindings — the documents that cross into the environment carry
the names for that engine — never from a material file or a library. An engine
with no name of its own for a property — NGSolve, whose script femkit writes —
uses femkit's name.
