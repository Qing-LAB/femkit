# ADR 0003: NGSolve stability-first source baseline

**Role:** ADR

**Status:** accepted

**Authority:** the reasons only; the pins, options and checks live in
[`femkit/data/environments/ngsolve.toml`](../../femkit/data/environments/ngsolve.toml),
the install and validation rules in
[`definitions.md`](../contracts/definitions.md) § 4 and
[`envs.md`](../contracts/envs.md) § 4–5

## Decision

femkit builds the regular NGSolve **6.2.2606** release, with the exact Netgen
commit that release records as its submodule. An established, deployed release
is preferred over a feature-new one. Upstream sources are not patched, MPI,
MUMPS and Hypre are not silently disabled, and release numbering is not taken
as production readiness: the definition says `maturity = "candidate"`. Python
is 3.12, the minor every environment shares (`control.txt`,
[`definitions.md`](../contracts/definitions.md) § 3).

The commits, archive digests and release names live in `ngsolve.toml` only;
the install's `fetch` step verifies each archive's SHA-256
([`envs.md`](../contracts/envs.md) § 4.1).

## Evidence and limits

- The [official PyPI release](https://pypi.org/project/ngsolve/6.2.2606/) was
  published June 29, 2026, supports Python >=3.10 and includes Python 3.12
  Linux wheels. Wheels show the release is available, not that our source
  build works.
- [FEM-on-Colab's release build](https://github.com/fem-on-colab/fem-on-colab/blob/main/ngsolve/build.sh)
  selected 6.2.2606 when this release was chosen, and enables MPI in the
  matching Netgen: a concrete downstream deployment choice. It applies
  downstream patches and disables the built-in MUMPS, so it is **not** evidence
  for our unpatched MPI/MUMPS/Hypre combination. No version-level usage ranking
  was found, so this decision does not call the release the most-used version.
- The pinned source contains the upstream February 2025 MUMPS constructor fix
  and the June 2026 timer fix. It predates
  [the September header-removal change](https://github.com/NGSolve/ngsolve/commit/f3d2ec0bfc7eab7653b55f5b5d97d8e6d406b144)
  that explains the reported 6.2.2608 `ngcomp`/`ParallelVVector` compilation
  errors.
- [Upstream issue 92](https://github.com/NGSolve/ngsolve/issues/92) reports a
  6.2.2606 1D mesh-save crash on Windows/Python 3.13. That is not a case femkit
  runs, but it rules out any claim that the release is free of defects.

## Build configuration

The build keeps MPI, TaskManager threads, LAPACK, UMFPACK, MUMPS and Hypre.
Options the pinned source does not have — `NG_FP_CONTRACT`, `USE_METAL`,
`USE_ACCELERATE_SPARSE` — are not declared as invented disable switches: a
declared option the project never reads fails its `configure` step
([`definitions.md`](../contracts/definitions.md) § 4.2). Metal is not a
compiled interface of this release; ROCm, Metal and AmgX packages are forbidden
in the lock (`forbid`).

Netgen is configured with `BUILD_FOR_CONDA = false` and
`BUILD_STUB_FILES = false`:

- **`BUILD_FOR_CONDA`.** Netgen and NGSolve each set their own install RPATH,
  `$ORIGIN`-based, as a normal CMake variable over the cache entry femkit
  passes, so an installed library carries the project's RPATH, not femkit's.
  With `BUILD_FOR_CONDA` on, Netgen's CMake appends a bare `../lib` (the
  relative path from `/bin` to `/lib`), which the loader resolves against the
  working directory, not against the library. With it off, Netgen links the
  prefix's Python library and keeps only the `$ORIGIN`-based entries. NGSolve's
  own `BUILD_FOR_CONDA` is a different switch and stays on.
- **`BUILD_STUB_FILES`.** Both projects' stub generation needs
  `pybind11-stubgen`, which the environment does not declare; with the option
  on, upstream may warn and leave the stubs out while the cache still says on.
  Both builds turn it off rather than add a package nothing else needs.

## Checks

The checks solve one small complex H(curl) problem serially, with two threads
and on two ranks, and require the three to agree; MUMPS and Hypre each solve on
two ranks; three of NGSolve's own pytest tests run against the installed build.
The H(curl) check program uses NGSolve's supported `SetNumThreads` and
`TaskManager` APIs; its `threads` quantity is the configured setting, not a
measured worker count. Acceptance is real residuals, the single-rank field
exported to VTK and read back, and agreement; no log text is judged.

### Check tolerances

Every relative residual femkit's check programs compute is bounded by 1e-9, and
the H(curl) field L2 norms of the serial, threaded and two-rank solves must
agree within 1e-9. Measured with 6.2.2606 on a workstation, the residuals ran
from 3e-16 (MUMPS) to 6e-12 (two-rank H(curl)) — serial and threaded 1.7e-15,
Hypre 9.7e-13 — so the bound leaves more than two orders of magnitude of
margin. The CUDA check bounds the CPU/GPU solution difference and both
residuals by 1e-9; measured: difference 6.5e-16, both residuals 4.6e-13.
NGSolve's own pytest tests keep their own tolerances.

## CUDA: the `ngsolve-cuda` environment

The CUDA build is a separate environment, `ngsolve-cuda`, installed only on
request ([ADR 0005](0005-cuda-environments.md);
[`definitions.md`](../contracts/definitions.md) § 4.5). This release's CUDA
implementation is compiled ahead of time with NVCC and exposes the older
`ngsolve.ngscuda` API; the newer NVRTC-based interface is a different one, and
checks written for it do not apply. `ngsolve-cuda` builds NGSolve with
`USE_CUDA` and the prefix's own NVCC, for the architectures
`build.cuda_architectures` names ([`config.md`](../contracts/config.md) § 3.1).

Its device check solves with the release's device sparse matrix, vector and CG
solver APIs, requires the device vectors to live in CUDA memory, and compares
the result with the same solve on the CPU. GPU qualification is separate from
the CPU checks: a missing GPU or a failed device check is never reported as a
GPU solve ([`envs.md`](../contracts/envs.md) § 5). Supporting this interface
is not a reason to move to a newer source release.

## Toolchain selection

- The pinned commit's [Linux wheel-build configuration](https://github.com/NGSolve/ngsolve/blob/b42211d28ab7a030e4e669ddfc204152aa5674a0/tests/gitlab-ci/pip.yml)
  names `cerbsim/manylinux_2_28_x86_64_cuda_12.9`. This is upstream evidence
  for CUDA 12.9, not proof that our MPI/MUMPS/Hypre build or a GPU calculation
  works. It states no exact GCC version.
- The pinned commit's [Linux installation instructions](https://github.com/NGSolve/ngsolve/blob/b42211d28ab7a030e4e669ddfc204152aa5674a0/docs/install/installlinux.rst)
  ask for a recent compiler, not an exact GCC. The container's name alone does
  not imply an exact compiler version.
- [NVIDIA's CUDA 12.9 host-compiler policy](https://docs.nvidia.com/cuda/archive/12.9.1/cuda-installation-guide-linux/index.html#host-compiler-support-policy)
  supports GCC major versions 6 through 14 on x86_64, including newer minor
  versions within those majors. GCC 15 is outside that range.

So `[cuda]` installs CUDA 12.9 Update 1 as the `cuda-toolkit` metapackage
composes it, less `cuda-tools`, whose profilers cannot share the toolchain's
CMake ([ADR 0004](0004-elmer-stability-first-baseline.md) has the measurement
and the reason for a whole toolkit rather than the libraries the pinned
[`ngscuda` build](https://github.com/NGSolve/ngsolve/blob/b42211d28ab7a030e4e669ddfc204152aa5674a0/ngscuda/CMakeLists.txt)
names), plus the CUDA Python bindings — and `[toolchain]` pins the C, C++ and Fortran compilers to
gcc 14 — each environment declares and proves its own
([ADR 0006](0006-toolchain-first.md)). gcc 14 is our compatible choice, not a
compiler NGSolve mandates; NVIDIA's NVCC policy covers the host C++ compiler
and does not itself qualify Fortran or the engine's numerics. Exact package
builds are in the saved lock ([`envs.md`](../contracts/envs.md) § 4.1).

## Dependency tree and version-selection map

This map shows relationships; it is not a second package list or a resolver.
`ngsolve.toml` holds the direct constraints and source identities; the saved
lock holds the full resolved and transitive package graph. A name repeated
below is one dependency inside the prefix, not a second installation.

```text
ngsolve: the selected NGSolve release
├── Matching Netgen source from that release's recorded submodule
│   ├── ngcore / pyngcore and Netgen Python/native interfaces
│   ├── Python + pybind11 development support
│   ├── zlib development headers and linker library
│   └── The same prefix-owned MPI and C++ toolchain used by NGSolve
├── CPU numerical capabilities
│   ├── LAPACK / BLAS → OpenBLAS package variants
│   ├── UMFPACK → SuiteSparse package
│   ├── MUMPS MPI → compatible MPI, Fortran and numerical dependencies
│   │   └── ScaLAPACK/BLAS dependencies supplied by the solved package graph
│   ├── Hypre → compatible MPI/numerical package variants
│   ├── METIS / ParMETIS → ordering and partitioning support
│   └── TaskManager → NGSolve/Netgen's shared-memory execution support
├── CUDA, in ngsolve-cuda only: this release's ngsolve.ngscuda interface
│   ├── Prefix-owned NVCC + compatible host C++ compiler
│   ├── CUDA runtime (cudart), cuBLAS and cuSPARSE
│   ├── Matching toolkit development headers / CCCL
│   ├── cuda-bindings → femkit's device check helpers
│   └── Architectures from build.cuda_architectures, never a device query
├── Python scientific/validation support
│   ├── numpy / scipy
│   ├── mpi4py → the same MPI implementation
│   ├── meshio → reading the exported field
│   └── pytest → the selected upstream NGSolve tests
└── Toolchain ([toolchain], proven before any source is fetched)
    ├── gcc 14 C/C++/Fortran compilers and runtimes; sysroot 2.28
    ├── CMake 4.5 + make
    └── pkg-config, git, bash and the shell utilities
```

ScaLAPACK is not requested directly; the MUMPS package's solution supplies what
it needs. The Python validation packages serve femkit's checks; upstream
NGSolve does not need meshio or CUDA Python bindings to solve.
GUI/OpenCASCADE, MKL/Pardiso, Metal, ROCm and AmgX are not selected
capabilities; none is added because another engine uses it.

| Selection edge | Requirement or compatibility question | Current selection and upgrade consequence |
|---|---|---|
| NGSolve → Netgen | Match the source, API and compiled-interface partner the target release records, not merely two similar version labels | The exact pair is in `ngsolve.toml`. Change both together; Netgen builds first (`after`). |
| Native/Python interfaces → Python/pybind11 | Compatible Python development ABI and binding API | Python 3.12 is the minor every environment shares (`control.txt`); pybind11 comes from the environment's own packages (`PREFER_SYSTEM_PYBIND11`), never an upstream bundled copy or the host. A Python-minor change rebuilds every environment, not NGSolve alone. |
| NGSolve → C++ compiler | The pinned source uses C++20; MPI/native interfaces and package runtimes must be compatible | gcc 14 is our compatibility choice, not an upstream pin. A new compiler must satisfy NGSolve, Netgen, CUDA and the numerical dependencies together. |
| Netgen → zlib | Meshing needs development headers and a linkable library, not just a runtime package | `zlib` is requested explicitly: without it Netgen's configure fails on the missing header and library. Keep the development support when packaging changes. |
| MPI consumers → MPI | Netgen, NGSolve, mpi4py, MUMPS, Hypre and ParMETIS must use mutually compatible provider and build variants | The provider is the prefix's OpenMPI. A provider or package-build change reviews the whole MPI-linked group and reruns the two-rank checks. |
| CPU solvers → numerical libraries | Scalar types, integer interfaces, Fortran runtime and BLAS/MPI variants must work with the engine's callers | SuiteSparse, MUMPS and Hypre stay enabled. Exact versions and builds come from the lock; a solver upgrade is no permission to disable a failing capability. |
| NGSolve CUDA interface → toolkit | This release uses ahead-of-time NVCC and `ngsolve.ngscuda`; later GPU APIs are different interfaces | CUDA 12.9 follows the pinned release's build evidence. A source upgrade reviews its actual GPU API and the device check program, never reusing the old one blindly. |
| CUDA → host compiler/architectures | NVIDIA's toolkit/compiler policy and the release's supported device targets must overlap | Keep the prefix's compiler and explicit architectures. A toolkit change may require reviewing the architectures; never bypass NVCC's checks, and never `native` or `all` (§ Changing a pin). |
| Device validation → cuda-bindings | femkit's device helpers must work with the toolkit's bindings API | The bindings are in the 12.9 family and locked exactly. Their version need not equal NVCC's, cuBLAS's or the toolkit metapackage's. |
| Upstream numerical validation → pytest | The release's own Python tests must run with their engine | The NGSolve environment declares its own pytest. A source-release change reviews the selected test IDs and their assertions. |

The [pinned main CMake input](https://github.com/NGSolve/ngsolve/blob/b42211d28ab7a030e4e669ddfc204152aa5674a0/CMakeLists.txt)
and [pinned CUDA component](https://github.com/NGSolve/ngsolve/blob/b42211d28ab7a030e4e669ddfc204152aa5674a0/ngscuda/CMakeLists.txt)
are the primary interface and build references for this selection. Reading
them during an upgrade is dependency research, not a post-install source-text
test.

## Changing a pin

A change starts from the target NGSolve release and follows the map outward:
its enabled interfaces, their dependencies and their toolchain requirements,
as a whole. Upstream requirements, our candidate choices and what has actually
passed are recorded apart, in this ADR. A changed definition changes the
install fingerprint, so the environment is rebuilt and its lock solved again
([`envs.md`](../contracts/envs.md) § 2). Two rules hold on every change:

- **Review the whole changed package set in the new lock**, not only the
  package you moved: a request for one change can move several packages, and a
  dry solve shows only that the packages exist and fit the constraints.
- **Never `all` or `native` as CUDA architectures**: their meaning is decided
  at build time, by the toolkit and the build host's GPU, not by the GPUs the
  environment is for. `build.cuda_architectures` names them explicitly, never
  from a device query ([`definitions.md`](../contracts/definitions.md) § 4.2).

## Acceptance still open

What this environment still has to show is in [the plan](../plans/plan.md)
§ 3, M1.
