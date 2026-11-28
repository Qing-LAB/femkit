# ADR 0014: materials in femkit's own format, named once and per engine

**Role:** ADR

**Status:** accepted (2026-11-23); its translators are what
[ADR 0025](0025-one-engine-per-study-observables-after.md) (decision 10)
names the engines' input writers

**Authority:** the reasons and the alternatives only;
[`materials.md`](../contracts/materials.md) owns the rules

## Context

Materials were tables inside `model.toml`, and each formulation declared the
properties it reads under its own names. Existing libraries differ (read on
2026-11-23): Elmer's own library holds 25 materials as bare numbers with no
unit, source or dependence stated; refractiveindex.info keeps one YAML file per
material and source, its data tabulated or as one of nine dispersion formulas,
with its range in micrometres; Tidy3D keeps several datasets per material, each
named by its source; NIST's MatML
separates a material, its property data and the metadata of where the data
came from.

## Decision

1. **One property list**, a data file: each property's common name, its
   dimension, real or complex, a number or direction-dependent, what it may
   depend on, its equivalent forms and how to convert between them, and its
   name in each engine and each source. Translators and importers read the same
   names, in opposite directions.
2. **femkit's own material format**: one material is a folder holding
   `material.toml` and its tables; each property holds one or more datasets,
   each named by its source, each a constant, a table or a dispersion model from
   a closed list declared as data, with its source, convention, range and
   conditions.
3. **A global library and a project's own**: `GLOBAL/metals/gold` names the
   global library's explicitly; any other name is looked up in the project's
   `materials/` first, then in the global library, a local material of the same
   name taking priority as the person's customization. Where each material came
   from — project or global, dataset, source — is shown in every log and
   result. femkit's shipped materials are copied into the global library when
   it is first made, validated, with their sources and explicit units; a later
   femkit offers updates and never overwrites them.
4. **Every case holds the material data it used**, never where it was found,
   so a later edit of a global material makes new cases and leaves the old ones
   with their runs, flagged by `case list` — never changed silently. A project
   moved to another root finds its `GLOBAL/` materials in that root's library.
5. **Importers**, one per source, declared as data, bring other libraries'
   data into a library, keeping the source; a value with no source is refused,
   so Elmer's library is not imported.

## Alternatives not chosen

- **Each formulation naming its own properties.** Two formulations would
  declare one property twice, and differ.
- **Copying every material into the project.** Safe, but loses the shared
  library the person wants; the case's record gives the same safety.
- **Adopting one existing format.** None carries every form femkit needs —
  tables, dispersion models, conventions, ranges, sources and engine names —
  and each importer keeps the others reachable.

## Consequences

- Formulations name properties from the list; each engine's translator writes
  a property under the list's name for that engine.
- The library's first entry is `vacuum`; others enter only with data from a
  source that can be checked.
