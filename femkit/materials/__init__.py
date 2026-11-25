"""The `materials` domain (materials.md): a project's own materials and the assignment of a material
to each body group of a component.

Its modules, each the one home of what it names:

- `material` — a material's file, `materials/<name>/material.toml`, and its check: each property by
               its name in the property list, holding its datasets; in step D each dataset a fixed
               value (§ 3)
- `assign`   — a component's `[assign]` table and its check: a material, and a dataset per
               property, for each body group (§§ 4, 5)

The property list's model is `femkit/definitions/properties.py`, since the catalogue that loads it
sits below this package (framework.md § 1). The global library, tables, dispersion models and
importers are step E's (plan § 4, E).
"""
