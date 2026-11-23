# Electrostatics

**Role:** scientific background

**Status:** current; the formulation is declared
(`femkit/data/formulations/electrostatics.toml`), and no benchmark has been
solved yet ([`../plans/plan.md`](../plans/plan.md) § 3, M5, M6)

**Authority:** the `electrostatics` formulation's terms, equation, conditions,
dimensional meanings and derived quantities; how each is stated in a model is
[`../contracts/models.md`](../contracts/models.md) § 3–4

## Contents

1. [Terms and symbols](#1-terms-and-symbols)
2. [The equation](#2-the-equation)
3. [Conditions on an outer boundary](#3-conditions-on-an-outer-boundary) —
   `potential`, `insulating`, `surface_charge`, `normal_flux`, and the sign of
   the normal
4. [Between two domains](#4-between-two-domains) — `interface`
5. [Sources](#5-sources) — `charge_density`
6. [What each dimension means](#6-what-each-dimension-means)
7. [Derived quantities](#7-derived-quantities) — what an observable may name
8. [Validity](#8-validity)
9. [Benchmarks](#9-benchmarks)

## 1. Terms and symbols

Every symbol below is used with this meaning, and in these units, throughout.

| term or symbol | meaning | unit |
|---|---|---|
| domain, $\Omega$ | the part of space where the equation is solved: the union of the model's domain regions. A conductor is never part of it (§ 3) | — |
| outer boundary, $\partial\Omega$ | the surface (in 2-D, the curve) that encloses $\Omega$ | — |
| interface | a surface inside $\Omega$ shared by two domain regions | — |
| conductor | a body of metal outside $\Omega$, whose surface is part of $\partial\Omega$; the field inside it is zero | — |
| $\mathbf{n}$ | on $\partial\Omega$, the unit normal pointing **out of** $\Omega$ — on a conductor's surface, into the conductor | — |
| $\phi$ | the electric potential, the unknown, a function in $H^1(\Omega)$ | V |
| $\mathbf{E}=-\nabla\phi$ | the electric field | V/m |
| $\mathbf{D}=\epsilon_0\,\epsilon_r\,\mathbf{E}$ | the electric displacement | C/m² |
| $\epsilon_0$ | the vacuum permittivity, $8.8541878188\times10^{-12}$ (CODATA 2022) | F/m |
| $\epsilon_r$ | a material's relative permittivity: real, positive, one number per material | 1 |
| $\rho$ | the free charge density in $\Omega$, zero unless a source states it | C/m³ |
| $\sigma$ | the free charge per unit area on a conductor's surface | C/m² |
| $q$ | a prescribed normal flux, $\mathbf{n}\cdot\mathbf{D}$ | C/m² |
| $w=\tfrac12\,\mathbf{E}\cdot\mathbf{D}$ | the energy density | J/m³ |

Coordinates are in metres.

## 2. The equation

In $\Omega$, the potential satisfies Gauss's law for $\mathbf{D}$:

$$
-\nabla\cdot\left(\epsilon_0\,\epsilon_r\,\nabla\phi\right)=\rho .
$$

One condition on each part of $\partial\Omega$ (§ 3) makes the solution unique;
where only flux conditions are stated, at least one `potential` must be, or
$\phi$ is fixed only up to a constant.

## 3. Conditions on an outer boundary

Every outer boundary carries exactly one condition, stated in the model, never
implied:

| kind | what it states | its parameter |
|---|---|---|
| `potential` | $\phi=\phi_D$: the boundary is held at a potential (a Dirichlet condition) | `value`: $\phi_D$, in V |
| `insulating` | $\mathbf{n}\cdot\mathbf{D}=0$: no field line crosses the boundary (the natural condition) | — |
| `surface_charge` | $\mathbf{n}\cdot\mathbf{D}=-\sigma$: the boundary is the surface of a conductor carrying free charge $\sigma$ | `value`: $\sigma$, in C/m² |
| `normal_flux` | $\mathbf{n}\cdot\mathbf{D}=q$: a known flux crosses the boundary, which is no charged conductor — a cut through a larger problem, say (a Neumann condition) | `value`: $q$, in C/m² |

**The sign of `surface_charge`.** On a conductor's surface, $\mathbf{n}$ points
into the conductor (§ 1), and $\mathbf{D}=0$ inside it. Gauss's law over a thin
pill-box across the surface then gives $-\mathbf{n}\cdot\mathbf{D}=\sigma$.
So `surface_charge` takes the physical charge $\sigma$, and femkit writes
$\mathbf{n}\cdot\mathbf{D}=-\sigma$ to the solver.

For example, take a parallel-plate capacitor. $\Omega$ is the gap, and the left
plate carries $+\sigma$:
- the field leaves the positive plate, so in the gap $\mathbf{D}$ points to the
  right, $+x$;
- on the left plate's surface, $\mathbf{n}$ points into the plate, $-x$;
- so $\mathbf{n}\cdot\mathbf{D}=-\sigma$, as `surface_charge` with `value`
  $=+\sigma$ writes it.

Stated instead as `normal_flux`, the same plate would need `value` $=-\sigma$.
That is why the two are separate kinds: each takes the number a person has in
hand, and neither leaves a sign to remember.

## 4. Between two domains

The potential is continuous across an interface by the function space. The
normal displacement is continuous too where no free surface charge lies: in the
weak form, $\mathbf{n}\cdot\mathbf{D}$ jumps by the surface charge on the face,
and by nothing where none is stated. A face between two domains is therefore
continuous without being named. Named as an interface region, it carries
`interface`, which states that continuity
([`../contracts/models.md`](../contracts/models.md) § 3).

## 5. Sources

`charge_density`, in a domain region: $\rho$ there, its `value` in C/m³.

## 6. What each dimension means

- **3-D, `full`**: the equation as written.
- **2-D, `per unit depth`**: nothing varies along $z$. The domain is a
  cross-section, and every extensive quantity is per metre of depth: a charge
  per unit length in C/m, an energy per unit length in J/m.
- **2-D, `axisymmetric`**: nothing varies with the angle about the $z$ axis.
  Coordinates are $(r, z)$ with $r\ge0$, and the equation becomes
  $-\frac1r\partial_r\!\left(r\,\epsilon_0\epsilon_r\,\partial_r\phi\right)
  -\partial_z\!\left(\epsilon_0\epsilon_r\,\partial_z\phi\right)=\rho$. On
  the axis $r=0$, the regularity of $\phi$ is the natural condition, and a
  boundary on the axis is stated `insulating`, which is that condition.

## 7. Derived quantities

What an observable may name (models.md § 5), each in its unit:

| name | quantity | unit |
|---|---|---|
| `potential` | $\phi$ | V |
| `electric_field` | $\mathbf{E}$ | V/m |
| `displacement` | $\mathbf{D}$ | C/m² |
| `energy_density` | $w$ | J/m³ |

## 8. Validity

The equation is static: no current flows and nothing changes in time.
Materials are linear, isotropic and non-dispersive, so $\epsilon_r$ is one real
number per material. A conductor is not a domain: it is a boundary held at a
potential (`potential`) or carrying a charge (`surface_charge`).

## 9. Benchmarks

What proves an environment's translation is listed in the formulation and
explained here as each is added ([`../contracts/models.md`](../contracts/models.md)
§ 6.3). First comes a two-material case, where $\phi$ depends on $\epsilon_r$
and on the interface. Manufactured solutions follow with the expression
language ([`../plans/plan.md`](../plans/plan.md) § 3, M6).
