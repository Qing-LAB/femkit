# ADR 0001: use the name femkit

**Role:** ADR

**Status:** accepted

**Authority:** rationale for the project, package, command and directory name

## Decision

The project, its Python package, its command, its entry script, its environment
variables (`FEMKIT_*`), its user directories and its schema IDs
(`femkit/<kind>@<major>`) are all named `femkit`. The repository folder carries
the same name.

## Reason

The name is typed constantly — as the command, in paths, and in variable names.
`femkit` is six letters with no awkward key sequence, keeps the meaning of a
workbench (a kit of tools to build, run and check finite-element studies), and
pairs with the sibling project `molbuilder`. It was unused on PyPI and
conda-forge when chosen.

## Consequences

One name everywhere, with no aliases: the command, the package, the install
script, the environment variables, the user directories and the schema IDs. A
hosted service, if one is ever built, can take its own deployment name without
changing the package or its schemas.
