# ADR 0004: Elmer released baseline and bundled solver configuration

**Role:** ADR

**Status:** accepted

**Authority:** the reasons only; the pins, options and checks live in
[`femkit/data/environments/elmer.toml`](../../femkit/data/environments/elmer.toml),
the install and validation rules in
[`definitions.md`](../contracts/definitions.md) § 4 and
[`envs.md`](../contracts/envs.md) § 4–5

## Decision

femkit builds the official Elmer **26.2.1** release. Its bundled UMFPACK is
enabled explicitly alongside MUMPS, rather than patching the upstream source or
switching to an older release to get past the observed preprocessing failure.
Bundled Zoltan is compiled with one C diagnostic demoted from an error to a
warning. The CUDA environment, `elmer-cuda`
([ADR 0005](0005-cuda-environments.md)), adds AmgX 2.5.0 on CUDA 12.8
Update 1. The source commits and archive digests live in `elmer.toml` only.

## Deployment evidence and limits

How others deploy Elmer, as read on 2026-10-12:

- [CSC's Elmer HPC guide](https://docs.csc.fi/apps/elmer/) lists 26.2.1 on
  Roihu-CPU and 9.0 on Puhti, Mahti and LUMI. It also states that its default
  modules are frequently updated. A module label is therefore a deployment
  reference, not proof of an exact unpatched source commit or of our GNU/MPI
  stack.
- [Spack's maintained recipe](https://github.com/spack/spack-packages/blob/develop/repos/spack_repo/builtin/packages/elmerfem/package.py)
  includes 26.2.1, defaults MPI and OpenMP on, and keeps upstream's default
  enabled UMFPACK. MUMPS and Hypre are selectable, not default-qualified paths.
  Its Hypre source adjustment also prevents claiming our unmodified Hypre
  combination works merely because Spack has a recipe.
- [MSYS2's recipe](https://github.com/msys2/MINGW-packages/blob/master/mingw-w64-elmerfem/PKGBUILD)
  builds 26.2.1 with external UMFPACK, MUMPS and OpenMP, including an MPI
  variant. Its METIS patch and permissive CTest failure handling make this
  build and deployment evidence, not a numerical pass for our Linux build.
- [FreeBSD's recipe](https://github.com/freebsd/freebsd-ports/blob/main/science/elmerfem/Makefile)
  also selects 26.2.1 and external UMFPACK. Its platform-specific changes and
  compiler choices are not copied into femkit.

These references justify a regular released baseline. They do not measure
which version is most used, prove CUDA compatibility or make the build
production-qualified; the definition says `maturity = "candidate"`.

## UMFPACK: the failure it avoids

Configured with `WITH_UMFPACK=OFF` and MUMPS on, the build stops in GNU
Fortran's preprocessor: it rejects four `#elseif` directives in
`VankaCreate.F90`. They are upstream defects in a conditional solver-selection
section, and the active configuration decides whether preprocessing reaches
them. Official 26.1 contains the same directives, so downgrading is no remedy.

Preprocessing the digest-verified 26.2.1 file with the environment's own GNU
Fortran and the build's generated `config.h` reproduces all four errors with
the failing configuration's definitions; adding `HAVE_UMFPACK` passes. That
establishes the cause and a configuration route past this error. The
[upstream September correction](https://github.com/ElmerCSC/elmerfem/commit/d6a78ebe7fc2a2d8404174c7e07952d78debf21e)
also changes omitted-solver handling; it is not adopted into this baseline.

So the Elmer build declares `WITH_UMFPACK = true` and
`EXTERNAL_UMFPACK = false`: the UMFPACK bundled with Elmer, with no external
UMFPACK package. These are typed CMake cache entries like any other option,
and each must be one the project reads
([`definitions.md`](../contracts/definitions.md) § 4.2).

## Zoltan: one C diagnostic demoted

Built with GCC 15.3, Zoltan's `fort/cwrap.c` fails to compile:
`Zoltan_Destroy` receives a volatile-qualified pointer-to-pointer where its
declaration requires an unqualified one. GCC 14 changed this C diagnostic from
a warning to an error by default
([GCC porting notes](https://gcc.gnu.org/gcc-14/porting_to.html#incompatible-pointer-types)),
so moving from GCC 15 to GCC 14 alone is no remedy.

- **Pin GCC 13** — not chosen. The release's Ubuntu 24.04 build workflow is a
  GCC 13-family compatibility reference, not an explicit upstream GCC 13
  requirement.
- **Patch the source** — not chosen: upstream sources are not patched.
- **Demote the one diagnostic** — chosen, as MSYS2's Elmer recipe already does,
  with a flag GCC supports.

Pinned Zoltan's CMake has no compiler-flag option of its own, so the Elmer
build declares a typed `CMAKE_C_FLAGS = "-Wno-error=incompatible-pointer-types"`.
It demotes only incompatible-pointer errors to visible warnings; it is not
`-w`, unrestricted `-fpermissive`, or a numerical acceptance waiver. It covers
Elmer's C compilation, bundled Zoltan included, not just one target. The AmgX,
Mmg and ParMmg builds, the NGSolve environment, and the C++ and Fortran flags
are untouched. The warnings stay visible in the compile step's log. The
demotion is still needed with gcc 14; the compiler choice below does not
replace it.

No source patch, no source-text check and no Elmer-specific install path: each
choice here is data in `elmer.toml`, and changing it changes the install
fingerprint ([`envs.md`](../contracts/envs.md) § 2).

## Toolchain selection

- The selected release's [Ubuntu compilation instructions](https://github.com/ElmerCSC/elmerfem/blob/a19504ac53ec222e3355e182b08f2ff280c2203a/compilation_instructions/Ubuntu.md)
  use distribution compiler packages, not an exact GCC or CUDA pin. Its
  [full GCC build workflow](https://github.com/ElmerCSC/elmerfem/blob/a19504ac53ec222e3355e182b08f2ff280c2203a/.github/workflows/ubuntu-gcc-full.yaml)
  uses `ubuntu-latest` and generic compiler packages. Neither establishes an
  exact compiler requirement or qualifies the CUDA/AmgX combination.
- The enabled GPU solver's [AmgX 2.5.0 release notes](https://github.com/NVIDIA/AMGX/releases/tag/v2.5.0)
  require CUDA 12.0 or newer and report testing through CUDA 13.0. They also
  describe using CUDA-bundled Thrust rather than the removed Thrust submodule.
  CUDA 12.8 fits this documented range; release notes do not prove our Elmer
  integration works. Older README defaults or AmgX 2.4 compiler results are
  not attributed to 2.5.0.
- [NVIDIA's CUDA 12.8 Update 1 host-compiler policy](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-installation-guide-linux/index.html#host-compiler-support-policy)
  permits GCC major versions 6 through 14 on x86_64, including newer minor
  versions within those majors. It does not permit GCC 15.

`[toolchain]` pins the C, C++ and Fortran compilers to gcc 14 — each
environment declares and proves its own ([ADR 0006](0006-toolchain-first.md)).
gcc 14 is a compatible choice, not an exact Elmer requirement, and the NVCC
policy does not itself qualify GNU Fortran or the complete Elmer/AmgX build.
NGSolve's toolkit (CUDA 12.9, [ADR 0003](0003-ngsolve-stability-first-baseline.md))
belongs to its own environment and constrains nothing here. Exact package
builds are in the saved lock ([`envs.md`](../contracts/envs.md) § 4.1); femkit
does not guess toolchain versions, scan upstream source text as an acceptance
test, or bypass NVCC's compatibility checks.

## CUDA 12.8 and NVTX: the `elmer-cuda` environment

The CUDA build is a separate environment, `elmer-cuda`, installed only on
request ([ADR 0005](0005-cuda-environments.md);
[`definitions.md`](../contracts/definitions.md) § 4.5). It adds the AmgX
source and build, compiled for the architectures `build.cuda_architectures`
names ([`config.md`](../contracts/config.md) § 3.1), and Elmer's `WITH_AMGX`.

With CUDA 12.9, AmgX builds and installs, but Elmer's CMake configure fails:
its link list names `CUDA_nvToolsExt_LIBRARY`, which is missing. This is a real
upstream configure failure, not a femkit refusal. The pinned
[Elmer FindAMGX integration](https://github.com/ElmerCSC/elmerfem/blob/a19504ac53ec222e3355e182b08f2ff280c2203a/cmake/Modules/FindAMGX.cmake)
unconditionally appends that legacy library, and names no exact AmgX release.
AmgX 2.5 removed old NVTX linking in favor of NVTX3, so AmgX building on its
own does not show Elmer's link list works.
[CUDA 12.9 release notes](https://docs.nvidia.com/cuda/archive/12.9.2/cuda-toolkit-release-notes/index.html)
confirm the removal of NVTX v2; more 12.9 development headers cannot restore
the removed binary interface.

[CUDA 12.8 Update 1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-toolkit-release-notes/index.html),
whose NVTX/runtime component version is 12.8.90, supplies both the legacy
`nvToolsExt` and the NVTX3 headers: it satisfies Elmer's requirement and stays
within AmgX's supported range. NVIDIA's official `nvidia-nvtx-cu12==12.8.90`
archive, checksum-verified and inspected, contains `libnvToolsExt.so.1` and the
NVTX3 headers — evidence of NVIDIA's packaging, not of our package solve or an
Elmer run. `[cuda]` requests the NVTX runtime and development packages
explicitly, with CCCL in the same 12.8 toolkit family. No Python CUDA bindings
are installed: Elmer's GPU check reads AmgX's own solver output, and no check
program calls the CUDA runtime from Python.
Toolkit release and component versions differ; not every CUDA library is
pinned to one number.

`[cuda]` lists the toolkit's parts the builds use — nvcc and the runtime;
cuBLAS, cuSPARSE and cuSOLVER, which the pinned
[AmgX build](https://github.com/NVIDIA/AMGX/blob/cc1cebdbb32b14d33762d4ddabcb2e23c1669f47/CMakeLists.txt)
links; CCCL; and NVTX — never the `cuda-toolkit` metapackage. Measured with
mamba 2.9.0 on 2026-11-22, on a cluster and on a workstation alike: the
metapackage brings `cuda-visual-tools`, whose `nsight-compute 2025.1.1.2` pins
`krb5 < 1.22`, while the toolchain's CMake 4.5
([ADR 0006](0006-toolchain-first.md)) needs `libcurl >= 8.23` and with it
`krb5 >= 1.22.2`, so the environment does not solve. A build never runs the
profiler GUI.

Not chosen:

- **CUDA 12.9, NGSolve's toolkit**: it lacks the legacy NVTX library Elmer's
  finder links.
- **An older AmgX**: not needed for this error. AmgX 2.4/CUDA 12.2 upstream
  test evidence is not an Elmer-mandated pin and does not qualify this
  combination.
- **A separate legacy pip package, a library alias, an empty link variable, a
  source patch or a weakened build check.**

## Dependency tree and version-selection map

This map starts from the selected Elmer release and its enabled interfaces. It
shows relationships; it is not a second package list or a resolver.
`elmer.toml` holds the direct source, package and build constraints; the saved
lock holds exact builds and the full transitive package graph. A name repeated
below is one dependency in this Elmer prefix. No branch is supplied by NGSolve,
the control environment or a site library installation.

```text
elmer: the selected Elmer release
├── CPU numerical capabilities
│   ├── MPI + OpenMP → prefix-owned provider/toolchain
│   ├── BLAS / LAPACK → OpenBLAS package variants
│   ├── ScaLAPACK + MUMPS MPI → compatible MPI/Fortran/numerical variants
│   ├── Hypre → compatible MPI/numerical package variants
│   ├── ParMETIS → parallel partitioning support
│   ├── UMFPACK → implementation bundled with the Elmer source
│   ├── ARPACK / PARPACK → implementations bundled with the Elmer source
│   └── Zoltan → exact nested source revision pinned in elmer.toml
├── Mesh adaptation → Mmg and ParMmg, built from pinned sources (§ Mesh adaptation)
├── GPU interface, in elmer-cuda only → AmgX 2.5.0
│   ├── CUDA toolkit: NVCC, runtime, cuBLAS, cuSPARSE, cuSOLVER and headers
│   ├── CCCL → toolkit-compatible C++/Thrust support
│   ├── NVTX3 headers → AmgX 2.5's profiling interface when enabled
│   ├── Compatible host C++ compiler
│   └── Same MPI provider + architectures from build.cuda_architectures
├── Elmer's GPU build integration, in elmer-cuda only → legacy nvToolsExt link requirement
│   └── NVTX runtime + development/link support from the CUDA 12.8 family
├── Geometry/mesh tools
│   ├── Gmsh → mesh generation
│   └── ElmerGrid → mesh conversion, built from Elmer source
├── Python scientific/validation support
│   ├── Python + numpy / meshio
│   └── mpi4py → same prefix MPI provider
└── Toolchain ([toolchain], proven before any source is fetched)
    ├── gcc 14 C/C++/Fortran compilers and runtimes; sysroot 2.28
    ├── CMake / CTest 4.5 + make
    └── pkg-config, git, bash and the shell utilities
```

The legacy NVTX branch belongs to Elmer's integration, even though AmgX 2.5
itself no longer links that library: checking only AmgX's CUDA support is not
enough. Bundled UMFPACK is not an external SuiteSparse request; NGSolve's
different UMFPACK packaging is irrelevant to Elmer. Python validation packages
serve femkit's checks, not native Elmer physics. ElmerGUI, Elmer/Ice,
rocALUTION, cuDSS, MKL and other solver stacks are not selected.

| Selection edge | Requirement or compatibility question | Current selection and upgrade consequence |
|---|---|---|
| Elmer → bundled/nested sources | Match the implementations supplied or referenced by the selected engine source | Keep the bundled UMFPACK/ARPACK/PARPACK choices and the exact Zoltan revision in `elmer.toml`. An Elmer upgrade reviews those choices and the submodule revision, never keeping an unrelated old tree. |
| Elmer → AmgX | The engine's C interface, matrix types and resource/solver calls must be supported by the selected dependency | AmgX 2.5 is the candidate; the pinned finder names no exact AmgX. A support range or a standalone AmgX build does not prove the Elmer interface. |
| Elmer finder → legacy NVTX | Its unpatched link list requires nvToolsExt | CUDA 12.8 Update 1 with NVTX runtime and development 12.8.90 meets the identified packaging requirement. A toolkit upgrade rechecks this edge before changing CUDA. |
| AmgX → CUDA/CCCL/NVTX | Its own compiler, math-library and profiling interfaces must work with the toolkit | AmgX 2.5 requires CUDA ≥12.0 and reports testing through 13.0; it uses NVTX3 and CUDA-bundled Thrust. Select the intersection with Elmer's requirements, not that range alone. |
| CUDA → GNU host compiler | NVCC's supported host compiler range must include the chosen C++ compiler | gcc 14 is the compatible family under the CUDA 12.8 policy, not an exact Elmer requirement. The C/C++/Fortran compilers are the environment's own; numerical and runtime compatibility are checked too. |
| Zoltan C source → compiler diagnostics | The pinned source has an older pointer interface rejected by newer GNU defaults | The Elmer-only C diagnostic demotion is configuration, not a source patch. Review whether it is still needed after a source or compiler change; never apply it to AmgX or another environment. |
| MPI consumers → MPI/numerical variants | Elmer, AmgX, MUMPS, ScaLAPACK, Hypre, ParMETIS and mpi4py must use compatible provider/build interfaces | The prefix's OpenMPI and OpenBLAS are the providers. A provider, Fortran or integer-interface change reviews the whole dependent group and reruns the MPI checks. |
| Mesh tools → engine inputs | Generated meshes must convert and solve in the installed Elmer | Gmsh serves the model-input pipeline; a mesh-tool version change verifies generation, ElmerGrid conversion and solving together. |
| Validation support → Python packages | femkit's field helpers must work with the selected package APIs | The Python minor is shared (`control.txt`); numpy and meshio are the environment's own. |

Primary references for these edges are the selected
[Elmer finder](https://github.com/ElmerCSC/elmerfem/blob/a19504ac53ec222e3355e182b08f2ff280c2203a/cmake/Modules/FindAMGX.cmake),
the [AmgX release notes](https://github.com/NVIDIA/AMGX/releases/tag/v2.5.0)
and the CUDA release and compiler references above. The
[MUMPS guide](https://mumps-solver.org/index.php?page=doc) describes its
MPI/numerical dependencies and binary-compatibility considerations; during an
upgrade, use the guide matching the proposed MUMPS version, not the newest
guide as an engine version pin.

## Changing a pin

A change starts from the target Elmer release, then checks its enabled
interfaces, their dependencies and their toolchain requirements as a whole.
Upstream requirements, our candidate choices and what has actually passed are
recorded apart, in this ADR. A changed definition changes the install
fingerprint, so the environment is rebuilt and its lock solved again
([`envs.md`](../contracts/envs.md) § 2). Two rules hold on every change:

- **Review the whole changed package set in the new lock**, not only the
  package you moved: a request for one change can move several packages, and a
  dry solve shows only that the packages exist and fit the constraints.
- **Never `all` or `native` as CUDA architectures**: their meaning is decided
  at build time, by the toolkit and the build host's GPU, not by the GPUs the
  environment is for. `build.cuda_architectures` names them explicitly, never
  from a device query ([`definitions.md`](../contracts/definitions.md) § 4.2).

## Check tolerances

The checks are Elmer's own CTest cases, judged from each solver's `Norm` and
stored `RefNorm`; the reference error is the largest relative difference
between the two ([`definitions.md`](../contracts/definitions.md) § 5).

- `VectorHelmholtzWaveguide` with one and with two threads: reference error at
  most 1e-3 each, and the two runs' norms agree within 1e-4.
- Hypre (`mgdyn_hypre_ams2_np2`) and MUMPS (`WinkelBmPoissonMumps_np2`), each
  on two ranks: reference error at most 1e-5.
- AmgX on the GPU (`WinkelBmPoissonAMGX`, `elmer-cuda` only): reference error
  at most 1e-5, at least one AmgX solve, and norms within 1e-4 of the MUMPS
  run's. Measured with AmgX 2.5.0 on CUDA 12.8 on a workstation GPU: AmgX's
  norm was 8.9e-7 from the MUMPS reference, inside both bounds.
- Adaptive re-meshing: § Mesh adaptation (agreement within 1e-3, measured
  1.6e-4).

## Mesh adaptation: Mmg and ParMmg, parallel by default

Elmer re-meshes adaptively through Mmg, and in parallel through ParMmg; both are
built, ParMmg enabled by default because femkit builds the parallel variant of a
capability unless a reason says otherwise.

- **Pins: the pair ParMmg's own build uses.** Mmg v5.8.0 (commit `4d8232c`) and
  ParMmg v1.5.0 (commit `cd8a6e3`); ParMmg 1.5.0's CMake fetches exactly Mmg
  v5.8.0 when left to itself.
- **Both built from source.** ParMmg is not on conda-forge. Mmg is (`mmgsuite`),
  but without the private headers ParMmg compiles against, so one source-built
  Mmg serves Elmer (`libmmg`, `mmg/libmmgf.h`) and ParMmg (`libmmg3d` and the
  private headers). Order: `mmg`, `parmmg`, `elmer`.
- **No fetch while configuring.** With tests on, as femkit always builds, Mmg
  downloads its test meshes and ParMmg clones its own; by default ParMmg also
  clones Mmg and downloads Metis. `ONLY_VERY_SHORT_TESTS`, `ONLY_LIBRARY_TESTS`,
  `DOWNLOAD_MMG = false` and `DOWNLOAD_METIS = false` turn all four off; Metis
  and Scotch come from the environment.
- **Options follow ParMmg's own Mmg build** where it matters: shared libraries,
  private headers installed, point tracking on, Elas off. VTK I/O is off: Elmer
  passes meshes through the library calls.
- **Checks.** Elmer's own `StatElecSolveMMG3D` (one rank) and
  `StatElecSolveParMMG3D_np3` (three ranks, so `MPI_TEST_MAXPROC` is 3), with
  their own verdict set aside. Each compares its field norm with a stored
  reference to 1e-4 (serial) or 1e-3 (parallel), but its adaptive loop stops at
  an element error of 1e-2: in one serial run the four adaptive cycles ended at
  field norms from 0.5654 to 0.5824, and Mmg 5.8.0 / ParMmg 1.5.0 end 1.9e-2 and
  5.8e-3 from the references, which were last set by hand in 2023 and are not
  exercised by Elmer's CI (no workflow builds Mmg). A reference that tight pins
  one Mmg version's mesh, not convergence; reported upstream as
  [ElmerCSC/elmerfem#994](https://github.com/ElmerCSC/elmerfem/issues/994), and
  once fixed there the tests' own verdict counts again. femkit judges instead that each
  library re-meshed — Mmg's `MODULE MMG3D` and ParMmg's
  `MODULE PARMMGLIB_DISTRIBUTED` banners — that every adaptive loop met its
  error limit (`Mesh convergence limit reached`) and none stopped at its
  maximum depth (`Max adaptive depth reached`), which Elmer also reports as
  finished, and that the capacitance-matrix norm agrees between the serial and
  parallel re-meshes within 1e-3 (measured 1.6e-4).
- **What it does not give.** Elmer adapts a mesh only in solvers that compute an
  error estimate — electrostatics, steady currents, heat, elasticity, flow;
  `VectorHelmholtz`, the frequency-domain solver, computes none. Adaptive
  frequency-domain electromagnetics comes from NGSolve's own refinement, or a
  femkit-driven re-mesh loop, not from this switch.

## Acceptance still open

The shipped checks run Elmer's own CTest cases from its build tree; none runs
the installed solver on a mesh femkit prepares, and CPU evidence does not
qualify `elmer-cuda`. What this environment still has to show is in
[the plan](../plans/plan.md) § 3, M1.
