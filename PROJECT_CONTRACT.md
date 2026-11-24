# femkit root contract

**Role:** root contract
**Status:** current
**Authority:** which document wins, the organizing rule, and the repository's
top-level zones

This file says which document governs what and where each top-level entry
belongs. It restates no rule another document owns; it names that document.

If two documents disagree:

1. this file wins for the organizing rule and the zones;
   [`docs/README.md`](docs/README.md) for what a document may contain and how
   it is written; [`docs/process/conventions.md`](docs/process/conventions.md)
   for the order of work and the rules for code;
2. [`docs/contracts/framework.md`](docs/contracts/framework.md) wins for the
   package layout and layers, and its § 2 names the contract that governs each
   concern of the code; that contract wins for its own objects;
3. code and tests are evidence of the current implementation, never permission
   to contradict a contract;
4. the plan, [`docs/plans/plan.md`](docs/plans/plan.md), holds unfinished work
   and never overrides a contract.

The person's requirements and safety constraints stand above every document.

## 1. The organizing rule

Every durable fact has:

1. **one name** — no aliases with subtly different meanings;
2. **one authority** — the document, schema or module that defines it;
3. **one writer** — the person, a probe, the installer, the preparer, the run
   script, a solver;
4. **one scope** — repository, machine, environment, calculation, run;
5. **one reader** — consumers call the owning API instead of reparsing it.

Other documents and modules link to the authority. They may summarize it in one
sentence; they never carry a second field list, state table, formula, default
or validation rule that could drift.

When no authority fits, add it first — in the owning contract, and in
`framework.md` § 2 when it is a new concern — rather than solving the case at
hand with a private helper, a second file shape or an unwritten convention.

## 2. Repository zones

These are the permitted top-level entries. Adding one changes this table in the
same change.

| path | owns | never owns |
|---|---|---|
| `README.md` | what femkit is and the first commands, verified | design rules or a second plan |
| `PROJECT_CONTRACT.md` | this file's authority | domain rules |
| `CONTRIBUTING.md` | where a contributor starts, pointing to the rules | a second set of rules |
| `SECURITY.md` | the trust boundary and how to report a problem | scientific validation |
| `LICENSE` | the terms femkit is distributed under | anything else |
| `pyproject.toml` | developer-tool configuration (pytest) | package metadata for installing femkit |
| `scripts/` | the install script ([`envs.md`](docs/contracts/envs.md) § 7) | version or package knowledge kept outside `femkit/data/` |
| `femkit/` | product code and shipped definitions, run from the checkout | user projects, generated cases or results |
| `frontend/` | the web page's source, built into `femkit/web/static/` ([`web.md`](docs/contracts/web.md) § 3) | the built bundle, or `node_modules/` |
| `tests/` | executable evidence of the contracts ([`testing.md`](docs/contracts/testing.md)) | data copied from `projects/` or `work/` |
| `tools/` | developer tools that import nothing from `femkit` | product code |
| `docs/` | the documents [`docs/README.md`](docs/README.md) lists | generated dumps other than `docs/reference/`, copied upstream manuals, or history |
| `examples/` | small reviewed inputs that show a public contract | research results or machine settings |

`projects/` and `work/` are the person's research data: ignored by git, never
read as evidence or test input. The repository holds no user, machine or
environment data ([`config.md`](docs/contracts/config.md) § 1).
