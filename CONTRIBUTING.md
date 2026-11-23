# Contributing

**Role:** guide
**Status:** current
**Authority:** where a contributor starts; the rules are in the documents it
names

femkit is designed contract first: every change starts at the architecture and
the framework, settles its contract, and reaches the code last. Read, in this
order:

1. [`PROJECT_CONTRACT.md`](PROJECT_CONTRACT.md) — which document wins, and
   where each file belongs.
2. [`docs/process/conventions.md`](docs/process/conventions.md) — the order of
   work, design discipline, rules for code, and the checklist a change passes
   before it lands.
3. [`docs/README.md`](docs/README.md) — every document, and how documents are
   written.
4. [`docs/contracts/framework.md`](docs/contracts/framework.md) — the layers,
   and which contract governs the part you are changing.

## Working in the checkout

femkit runs from its checkout and is never installed.
`bash scripts/install-env.sh bootstrap` creates its control environment
([`envs.md`](docs/contracts/envs.md) § 7); the tests run from the repository
root inside that environment, through the runner:

```bash
python tools/testrun.py run basic
```

What earns a test, and how the runner reports, is
[`testing.md`](docs/contracts/testing.md).

## Reporting a problem

Open an issue with the command, its output, and the log it names. Report a
security problem privately, as [`SECURITY.md`](SECURITY.md) says.
