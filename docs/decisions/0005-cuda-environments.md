# ADR 0005: CUDA builds are separate environments, installed on request

**Role:** ADR

**Status:** accepted (2026-11-21)

**Authority:** the reasons and the evidence only;
[`definitions.md`](../contracts/definitions.md) § 4.5 owns the rule

## Decision

An engine definition with a `[cuda]` part is **two environments**, made by
the catalogue from the one file:

- `<name>` (`ngsolve`, `elmer`): CPU solvers, MPI and threads. The default:
  `bootstrap` and `env install --all` install it on any machine, and it needs no
  CUDA setting.
- `<name>-cuda` (`ngsolve-cuda`, `elmer-cuda`): the same plus the CUDA part.
  It is installed only on request, needs `build.cuda_architectures`, and is
  where the GPU checks run. A job that asks for GPUs runs in it.

## Technical background

### What each engine puts on a GPU

**NGSolve.** Its GPU module converts an assembled operator into a device
counterpart: "A sparse matrix becomes a DeviceSparseMatrix, a Jacobi smoother
a DeviceDiagonalMatrix, a block smoother a DeviceBlockJacobi, a sparse
Cholesky factorization a DeviceSparseCholesky." The conjugate-gradient
iteration "runs on the host, but all operations involving big data are
performed on the accelerator", and "the block inverses and the Cholesky
factorization are computed on the host, the device applies them". Assembly
stays on the host. With no GPU backend in the build, the module falls back to a
host reference device. [1, 2, 3]

The tutorial's own timings (on its single consumer NVIDIA GPU) for CG solves of a Poisson
problem [2]:

| preconditioner | unknowns | host | device |
|---|---|---|---|
| Jacobi (2000 iterations) | 460 033 | 4.22 s | 0.31 s |
| block-Jacobi with a low-order solve | 2 870 401 | 3.87 s | 1.01 s |
| BDDC | 718 401 | 2.15 s | 0.58 s |

**Elmer.** Release 26.1 added an interface to NVIDIA's AmgX, chosen per solver
with `Linear System Solver = amgx` and compiled with the flag `WITH_AMGX`. The
release notes name no other GPU path [4]. AmgX is a GPU library of
algebraic-multigrid and Krylov solvers for NVIDIA GPUs, distributed over MPI
[5].

**Direct solvers.** MUMPS, the direct solver both engine builds use, "has no
GPU support" (Ghysels and Synk, 2022) [6]; no source found since says
otherwise. GPU direct solvers do exist:
- NVIDIA cuDSS;
- STRUMPACK, whose exact GPU factorization is on average 1.9 times faster than
  cuDSS on a SuiteSparse collection [7];
- SuperLU_DIST, which moves the Schur-complement update to GPUs while the
  panel factorization stays on the CPU [8].

Neither engine's build uses them.

### When a GPU pays, in the literature

- **High-order matrix-free operators suit GPUs; sparse matrices do not.**
  MFEM's developers (2024): applying high-order operators in partially assembled
  form "is very well-suited for GPU acceleration; the arithmetic intensity of
  the algorithm increases with increasing polynomial degree", while "sparse
  matrix computations have low arithmetic intensity and are memory bandwidth
  bound; these operations often do not fully utilize the computational
  resources afforded by GPUs". Matrix-based algebraic multigrid "cannot be
  directly used" with matrix-free operators, so MFEM uses p-multigrid and
  low-order-refined preconditioners. [9]
- **A GPU needs a lot of work at once.** The PETSc developers (2021): GPUs
  "deliver much higher memory bandwidth and throughput, while the CPUs offer
  much lower latency". In a multigrid V-cycle, "although level 5 is 237 times
  larger than level 1, the time spent on the two levels is nearly identical".
  Their GPU Krylov phases "scale well only up to 6 MPI processes (1 GPU each),
  and then computing times tend to increase with GPU oversubscription and
  smaller problem sizes". [10]
- **Algebraic multigrid on GPUs is recent work.** hypre's BoomerAMG was
  redesigned to run well on GPUs. Its developers expect the Maxwell solver AMS,
  built on it, to benefit, which is an expectation, not a measurement. [11]

### What that means for femkit's work

GPU acceleration pays in a narrow class of problems:
- large problems, hundreds of thousands to millions of unknowns per GPU (the
  sizes in NGSolve's own examples), solved iteratively with a preconditioner
  that runs on the device;
- matrix-free high-order operators.

It does not pay for:
- moderate meshes;
- solves that rely on MUMPS;
- indefinite or H(curl) systems that a direct solver handles today.

That is most everyday finite-element work. So femkit supports GPU builds, and
never as the default.

### The machines

The machines femkit runs on differ. A workstation may have no NVIDIA GPU at
all, and a shared cluster has GPU nodes beside CPU nodes. GPU work belongs on
those GPU nodes, alongside CPU work on the same cluster.

### How others package a CPU and a GPU build

- **Spack** gives a package a `cuda` variant, off by default, and a
  `cuda_arch` variant [12].
- **conda-forge** builds CPU and CUDA variants of one package, and the solver
  chooses between them through a variant or mutex package [13].

Both keep one recipe and build it twice.

## Alternatives

1. **One environment per engine, always with CUDA.**
   Rejected:
   - nothing installs on a machine without CUDA architectures to name;
   - every CPU job carries the CUDA toolkit, AmgX and the architecture pins;
   - hours of CUDA compile happen where no GPU exists.
2. **One environment, with CUDA switched on or off per machine.** Rejected:
   - a machine gets one build, but a cluster runs CPU jobs and GPU jobs;
   - a job could not choose between them;
   - a CPU-only node may have no NVIDIA driver. The CUDA runtime is in the
     prefix, but the driver library comes from the system. Whether a CUDA
     build starts without it is not yet measured.
3. **Separate definition files for the CPU and the CUDA build.** Rejected: two
   copies of every pin and option, which drift apart.
4. **One definition file, two environments.** Chosen. It is the
   one-recipe-two-builds practice above, and keeps both builds on one source of
   pins.

## Consequences

- **Bootstrap:** it installs the CPU environments on any machine, with no CUDA
  decision to make.
- **The CUDA environments:** a person installs one deliberately
  (`env install ngsolve-cuda`), with `build.cuda_architectures` set. The GPU
  qualification and `validate --gpu` belong to it, and `validate --gpu` on the
  CPU environment names it instead.
- **Cost:** on a cluster that wants both, both are built: twice the build time
  and disk, paid only where GPU work is wanted.
- **Jobs:** a GPU job runs in the engine's CUDA environment.
- **Still to measure, with the first CUDA build on the cluster** (plan § 4, M1):
  - whether a CUDA build starts on a node without the NVIDIA driver;
  - whether nvcc's host compiler and CMake's CUDA toolkit are found inside the
    prefix.

## Sources

1. NGSolve, "Common GPU interface" tutorial — https://docu.ngsolve.org/latest/i-tutorials/unit-5.6-gpu/commonGPU.html
2. NGSolve, "Poisson on the GPU" tutorial — https://docu.ngsolve.org/latest/i-tutorials/unit-5.6-gpu/poisson_gpu.html
3. NGSolve, "Poisson with CUDA" tutorial — https://docu.ngsolve.org/latest/i-tutorials/unit-5.5-cuda/poisson_cuda.html
4. Elmer release notes 26.1 — https://github.com/ElmerCSC/elmerfem/blob/devel/ReleaseNotes/release_26.1.md
5. NVIDIA AmgX — https://github.com/NVIDIA/AMGX
6. P. Ghysels, R. Synk, high-performance sparse multifrontal solver on modern GPUs (2022) — https://escholarship.org/uc/item/7tn9n67r
7. GPU-accelerated sparse direct solver and preconditioner with block low-rank compression (STRUMPACK) — https://www.osti.gov/biblio/2499469
8. Newly released capabilities in the distributed-memory SuperLU sparse direct solver — https://www.ornl.gov/publication/newly-released-capabilities-distributed-memory-superlu-sparse-direct-solver
9. J. Andrej et al., "High-performance finite elements with MFEM" (2024) — https://arxiv.org/abs/2402.15940
10. R. T. Mills et al., "Toward performance-portable PETSc for GPU-based exascale systems", Parallel Computing (2021) — https://arxiv.org/abs/2011.00715
11. Exascale Computing Project, GPU-based algebraic multigrid in hypre — https://www.exascaleproject.org/highlight/a-new-approach-in-the-hypre-library-brings-performant-gpu-based-algebraic-multigrid-to-exascale-supercomputers-and-the-general-hpc-community/
12. Spack, CudaPackage — https://spack.readthedocs.io/en/latest/build_systems/cudapackage.html
13. prefix.dev, mutex packages in the conda ecosystem — https://prefix.dev/blog/what-are-mutex-packages-in-the-conda-ecosystem
