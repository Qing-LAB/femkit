"""The one door to a project (projects.md § 6): only this package forms a path in a project,
opens a project's file or writes one; every other package asks it.

Its modules, each the one home of what it names:

- `project`      — a project: its root, its name, its folder, its lock subject, the project file
                   that makes a folder one (`PROJECT_FILE`), and the one place a path inside it is
                   formed (`Project.path`)
- `names`        — the name rule: a part's name is its path inside its kind's folder (§ 3)
- `addresses`    — `<kind>:<name>[:<dotted path>]`, the one grammar naming a part and a value (§ 5)
- `layout`       — the layout as data: each part kind's folder, shape, schema, rank, writer, and
                   each folder that holds no part (§ 4)
- `schemas`      — the part schemas, registered by the registry at start, never imported (§ 6)
- `location`     — the projects root, the projects under it, a project named by its path or by
                   the folder a command runs in (§ 1)
- `door`         — listing and opening a project, each part on its own; a part's text; the
                   references between parts (§§ 2, 3, 5, 6)

The framework names no part kind: every kind is the layout's (`femkit/data/project/layout.toml`).
"""
