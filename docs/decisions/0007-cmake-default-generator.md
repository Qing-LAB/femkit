# ADR 0007: each project builds with CMake's own default generator

**Role:** ADR

**Status:** accepted (2026-11-22)

**Authority:** the reasons and the evidence only;
[`definitions.md`](../contracts/definitions.md) § 4.2 owns the rule

## Decision

femkit names no CMake generator. Each build is configured as its project
configures itself, so CMake's default applies — Unix Makefiles on Linux — and
the environment's `make` runs it (`cmake --build --parallel`). The generator
stays framework-owned: a definition cannot set it. Commands inside a prefix are
confined ([`envs.md`](../contracts/envs.md) § 4.4), so a `CMAKE_GENERATOR` in
the person's shell cannot change it.

## Evidence

How each pinned project builds itself on Linux, at the commit femkit pins:

| project | its own Linux CI | its documented build |
|---|---|---|
| Elmer | `cmake … ..`, no `-G` (`.github/workflows/build.yaml`) | `cmake ..`, `make` |
| Netgen | `cmake …` then `make -j12` (`tests/build_mpi.sh`, `tests/build_debug.sh`); Ninja only in its Windows job | — |
| NGSolve | `cmake -G "Unix Makefiles"` then `make` (`tests/gitlab-ci/conda/*/build.sh`) | — |
| Mmg | `cmake -S… -B…`, no `-G` (`.github/workflows/main-job.yml`) | `cmake ..`, `make`, `make install` |
| ParMmg | `cmake -S… -B…`, no `-G` (`.github/workflows/main-job.yml`) | `cmake ..`, `make`, `make install` |
| AmgX | no CI | `cmake ../`, `make -j16 all` |

## Alternative not chosen: one generator for every build

Forcing Ninja on every build holds for Elmer and NGSolve, and fails for
ParMmg 1.5.0: a rule there writes a header without declaring it as its product,
which make tolerates and Ninja refuses — the generator ParMmg's authors never
build with.

## Consequences

- Neither toolchain carries Ninja; make, proven by the toolchain step, is the
  build tool of both.
- A project that supports only Ninja would bring its own evidence, and a build
  could then declare its generator; none does today.
