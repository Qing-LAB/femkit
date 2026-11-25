"""The `materials` domain (materials.md): a project's own materials and the assignment of a material
to each body group of a component; a material's data for a case; and the importers, each writing a
new material from another source's file.

Its modules, each the one home of what it names:

- `material` — a material's file, `materials/<name>/material.toml`, and its check: each property by
               its name in the property list, holding its datasets, each a value, a table or a
               dispersion model; which dataset answers which property (§§ 1–3)
- `assign`   — a component's `[assign]` table and its check: a material, and a dataset per
               property, for each body group (§§ 4, 5)
- `library`  — the global library's offer: a library material the project uses whose femkit's
               shipped original changed since it was copied, said, never applied (§ 4)
- `data`     — a dataset taken at one value of its variable, exactly: the spectral conversions,
               a table's interpolation, the dispersion models, the equivalent form, the
               convention and the passive sign, the range (§ 6)
- `importer` — another source's file read by its importer's declaration, and the new material it
               becomes, written as a person's own file (§ 7)
- `requests`, `operations` — `material import`, writing that new material whole into the global
               library or a project, never over or into one (§ 7)

The property list's model is `femkit/definitions/properties.py`, since the catalogue that loads it
sits below this package (framework.md § 1). Where a material is found — the project's own first,
then the global library's — and the library's seeding by `project new` are the door's
(`femkit/projects/`), which forms every path and reads and writes every file (projects.md § 6);
femkit's shipped materials are `femkit/data/materials/`; the variables and dispersion models,
`femkit/data/dispersion.toml`, are `femkit/definitions/dispersion.py`'s; the importers' declarations,
`femkit/data/importers/<source>.toml`, are `femkit/definitions/importers.py`'s.
"""
