# Frequency-domain electromagnetics

**Role:** scientific background

**Status:** current; no rung of the validation ladder has been run yet
([`../plans/plan.md`](../plans/plan.md) § 3, M9)

**Authority:** electromagnetic equations, assumptions, and validation ladder

The initial problem is the complex frequency-domain Maxwell curl-curl equation
for electric field **E**:

$$
\nabla \times \mu_r^{-1}\nabla \times \mathbf{E}
- k_0^2\epsilon_r(\omega)\mathbf{E}=0.
$$

Here $\mathbf{E}$ is the complex electric-field amplitude in V/m,
$\nabla\times$ is the spatial curl with coordinates in metres,
$\mu_r$ is dimensionless relative permeability and $\epsilon_r(\omega)$
is dimensionless complex relative permittivity. The angular frequency $\omega$
has units rad/s, and $k_0=\omega/c_0=2\pi/\lambda_0$ is the free-space
wavenumber in m$^{-1}$, with vacuum light speed $c_0$ in m/s and vacuum
wavelength $\lambda_0$ in metres. This is the source-free equation; excitation,
boundary conditions and any impressed source require their own explicit model.

A phasor convention also needs an explicit choice:
$\mathbf{E}_{\mathrm{physical}}(\mathbf{x},t)=
\operatorname{Re}[\mathbf{E}(\mathbf{x})e^{s i\omega t}]$, with $s=+1$ or
$s=-1$ and time $t$ in seconds. The homogeneous equation above does not select
that sign. Selection and loss-sign conversion for material and excitation data are the
model's: it states the phasor sign and the amplitude convention, and each
material's source convention is converted to it with a passivity check
([`../contracts/models.md`](../contracts/models.md) § 3); each engine's
matching translation is proven by the formulation's benchmarks
([`../contracts/models.md`](../contracts/models.md) § 6.3). Installation smoke
calculations do not establish that portable scientific translation.

Metal permittivity is complex and wavelength-dependent. A material record must
therefore identify the source data, interpolation rule, unit convention, and
wavelength range; a bare constant called “gold” is not acceptable.

The bowtie validation ladder will separate:

1. analytic field and boundary-condition benchmarks;
2. domain/PML convergence — PML stays off until its formulation and a
   reflection benchmark are documented and tested;
3. gap-mesh and polynomial-order convergence;
4. geometry-length convergence and mode-pattern stability;
5. physical studies of water and effective tunneling conductivity.

### Adaptive meshes: what a converged result requires

Rung 3 may refine the gap mesh adaptively — by NGSolve's own refinement for the
frequency-domain problem, or by Elmer with Mmg (serial) and ParMmg (parallel)
for solvers that estimate their own error: electrostatics, steady currents,
heat, elasticity, flow, not Elmer's `VectorHelmholtz`. Either way:

- **The error limit controls the mesh, not the result.** An adaptive loop stops
  when its largest element error *estimate* falls below the limit (Elmer's
  `Adaptive Error Limit`); the reported quantity is accurate only to about that
  level. In Elmer's adaptive electrostatics case with a limit of 1e-2, four
  loops in one run ended at field norms 3 % apart. The limit is chosen from the
  accuracy the study needs.
- **Convergence is judged on the reported quantity.** An integrated quantity
  — capacitance, field energy, enhancement integrated over the gap — converges
  far more steadily than a field norm: in the same case, serial and parallel
  re-meshes agreed on the capacitance to 1.6e-4 and differed on the field norm
  by 7e-3.
- **One adaptive run is not evidence.** The limit is tightened in steps
  (halved, then halved again), and the reported quantity's change must shrink
  with each; the sequence is reported, not the last value alone.
- **A loop must end by meeting its limit.** Elmer ends a loop either way —
  `Mesh convergence limit reached` when the limit is met, `Max adaptive depth
  reached` when it runs out of refinement levels — and prints `Adaptive Meshing
  Finished` for both; a result whose loop hit its depth limit is not converged.
  Those lines appear at `Max Output Level` 6 or above.
- **Element sizes are bounded.** Near a sharp metal corner the field is
  singular and the error estimate does not fall with refinement there; a minimum
  element size (Elmer's `Adaptive Min H`, Mmg's `hmin`) keeps the loop from
  chasing it, and the size is reported with the result.
- **The re-mesher is part of the result.** Another Mmg version, other Mmg
  settings (`hmin`, `hmax`, `hausd`, `hgrad`, angle detection) or parallel
  instead of serial re-meshing lands on another mesh, so a result reproduces
  to the level its error limit allows, not to the last digit; the re-mesher, its
  version and its settings are recorded with every adaptive result.

The tunneling layer is an effective classical model, not a first-principles
quantum calculation. Its geometry, constitutive law, calibration range, and
limits must be reported with every study.

