# ADR 0006: each environment declares its toolchain, proven before its builds

**Role:** ADR

**Status:** accepted (2026-11-21)

**Authority:** the reasons and the measurements only;
[`definitions.md`](../contracts/definitions.md) § 4.6 and
[`envs.md`](../contracts/envs.md) § 4.1, § 4.4, § 4.5 own the rules

## Decision

- **Each environment declares its own toolchain.** Its `[toolchain]` holds the
  compilers (gcc 14 today), the sysroot, and every tool a build calls, solved
  with the engine's own packages. Environments may need different compilers,
  versions or patches, so none shares another's.
- **Proven first.** The install's `toolchain` step runs before any source is
  fetched. Inside the prefix, it compiles, links and runs a trivial program in
  each language the toolchain names (C, C++ and Fortran for both engines),
  builds and runs an MPI program on two ranks, and checks that every tool and
  compiler resolves inside the prefix.
- **Confined.** Every command femkit runs inside a prefix starts from a fixed
  allow-list of variables, and the manager's activation adds the prefix's own.
- **The sysroot is pinned at 2.28.**
- **CMake is pinned to the 4.5 series,** the one both environments were proven
  with.

## What an unproven toolchain does

Without a pinned sysroot, on a workstation whose processor supports x86-64-v2,
both CPU environments fail to build, each at a misleading place:
- **Elmer's configure** stopped with "GNU Fortran major version is too old,
  should be at least 7". Its version test program compiles and then cannot
  run: "CPU ISA level is lower than required".
- **NGSolve's netgen** compile failed on `operator '&&' has no right operand`.
  Its configure-time ABI test program dies the same way, and netgen puts
  that error text into `-D_GLIBCXX_USE_CXX11_ABI=…`.

The cause is one startup object. `gcc_impl_linux-64` 14 depends on
`sysroot_linux-64` with no version, so an unconstrained solve takes the newest,
2.39. Its `Scrt1.o` is marked
`x86 ISA needed: x86-64-baseline, x86-64-v2, x86-64-v3`, and every program
linked in the environment inherits that marking. A toolchain check that runs one
trivial program stops the install there, in seconds, with the real reason.

## Measurements behind the sysroot

- **Versions on conda-forge:** 2.12, 2.17, 2.28, 2.34 and 2.39.
- **Startup-object marking:**
  - 2.17 and 2.28: none (baseline x86-64);
  - 2.34: needs x86-64-v2;
  - 2.39: needs x86-64-v3.
- **The solved prebuilt packages** of both environments need at most
  `GLIBC_2.25` (`libfabric`); nearly everything stops at `GLIBC_2.17`.
- **Chosen: 2.28.** It is the newest sysroot that runs on any x86-64 processor.
  It raises the environments' glibc floor only from 2.25 to 2.28, which
  RHEL 8-class hosts meet, and its headers are richer than 2.17's.
- **The fallback is 2.17,** if a machine femkit builds on has a glibc older
  than 2.28 — its toolchain step would stop, saying so. It has the same
  processor reach and keeps the floor at 2.25.

## Why CMake is pinned

Unpinned, `cmake` is whatever release is newest on the day of a fresh solve.
Measured: such a solve took CMake 4.5.1, and both environments built with it
and passed every check.

CMake drops support for old projects on a schedule. 3.27 deprecated
compatibility with CMake versions before 3.5, and 4.0 removed it; 3.31
deprecated compatibility with versions before 3.10
([`cmake_minimum_required`, CMake 4.5](https://cmake.org/cmake/help/v4.5/command/cmake_minimum_required.html)).
The pinned Mmg 5.8.0 and ParMmg 1.5.0 declare 3.5
([Mmg](https://github.com/MmgTools/mmg/blob/4d8232c8aebfed877935d75d4d4a67e850962422/CMakeLists.txt),
[ParMmg](https://github.com/MmgTools/ParMmg/blob/cd8a6e340e466e857b0bb9952f115d8999337167/CMakeLists.txt)),
so the CMake release that removes what 3.31 deprecated stops their configure,
and with it every Elmer install. Elmer declares 3.10, Netgen 3.16 and NGSolve
3.18; their builds are pinned the same way, so that every fresh solve builds
with the CMake the checks passed under. Patch releases within 4.5 are taken; the
saved lock records the exact one.

## Why an allow-list

A deny-list has to know every variable a build reads, for these two builds:
- **Elmer's own CMake** reads about 45 `*_ROOT` and `*ROOT` package roots, and
  `MKLROOT`.
- **NGSolve's** reads `MKLROOT` and `NETGENDIR`.
- **CMake itself** reads `CC`, `CXX`, `FC`, the `*FLAGS` variables,
  `CMAKE_PREFIX_PATH` and `<Package>_ROOT`.
- **gcc** reads `CPATH` and `LIBRARY_PATH`.
- **The loader** reads `LD_LIBRARY_PATH`, which affects the test programs both
  builds run while configuring.

An allow-list is complete by construction. Measured: the manager runs a command
in a prefix from `HOME`, `USER`, `LANG` and `PATH=/usr/bin:/bin` alone. It
cannot run with an empty `PATH`, because its wrapper needs a shell, so the
system `PATH` stays, after the prefix's `bin`.

## Consequences

- **A broken toolchain fails fast:** a machine that cannot run what its
  toolchain builds stops the install at the `toolchain` step, with the reason.
- **Nothing more is recorded:** an environment is built on the machine that runs
  it, and a job is a script that machine's installed engine runs, so the proof
  on that machine is the whole guarantee.
- **On resume:** the check runs again on every resume, because an install may
  resume on another node.
- **A new CMake is a change of definition:** moving the pin changes each
  environment's install fingerprint, so each is rebuilt and proven again.
