"""The `workflow` domain (workflow.md): a case's stages, declared as data, between the project and
its jobs (framework.md § 1).

Its modules, each the one home of what it names:

- `graph`      — a study's workflow graph for one machine's record, from the cases the study makes
                 now: each case's geometry and mesh, the study's own, holding nothing of an engine
                 and shared by identity within it, their typed ports and wires, each case a box;
                 the mesher its recipe states; the finding at the study's `mesh` where a mesh has
                 no input, at each case's geometry order, and why an engine chosen takes it not
                 (§§ 2.2, 2.3, 3, 7)
- `identity`   — what a stage is made from — `stage.json`, its model, written and read there
                 alone — and its ID (§ 4)
- `folder_writing` — a stage to a calculation folder's request and files, which `study prep`
                 writes through the jobs domain's one writer; a study's stages to its meshing job's
                 batches and sequence, each launch folder named by the study (§§ 5, 7)
- `state`      — a stage's own states, and past them its folder's, by the rules
                 `femkit/data/states/stage.toml` declares; what `study prep` does in each, the
                 table's own tasks (§ 6)
- `impact`     — a change's impact: one file's new text against the project as it is, by the
                 table of comparisons, each its owner's — the file, the findings, a built
                 geometry's promise, each study's cases and workflow, the jobs going (§ 10)
- `operations` — `case list` with each case's stages, `study flow` with each
                 stage's outputs and the lines that open them, `study prep`, its five steps one
                 table, which conducts folder writing, and `project save`, of the page alone, its
                 plan the change's impact (§§ 7, 8, 10)
- `requests`   — the requests of its operations and their verbs

The stage kinds, artifacts, meshers and hand-overs it reads are the shipped definitions
(`femkit/definitions/stages.py`, `meshers.py`); the programs a stage runs, `femkit/engines/stages/`.
`project check` reads no stage: the models domain declares it (models.md § 11.1). Not built yet:
the solve stage (plan § 4, M6).
"""
