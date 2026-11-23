# Electrostatics

**Role:** scientific background

**Status:** current; the formulation is declared
(`femkit/data/formulations/electrostatics.toml`), and no benchmark has been
solved yet ([`../plans/plan.md`](../plans/plan.md) § 3, M5, M6)

**Authority:** the `electrostatics` formulation's equation, conditions,
dimensional meanings and derived quantities

## The equation

The unknown is the electric potential $\phi$, in volts, a function in
$H^1(\Omega)$ on the computed domain $\Omega$, with coordinates in metres. It
satisfies

$$
-\nabla\cdot\left(\epsilon_0\,\epsilon_r\,\nabla\phi\right)=\rho
\quad\text{in }\Omega,
$$

where $\epsilon_0 = 8.8541878188\times10^{-12}$ F/m is the vacuum
permittivity (CODATA 2022), $\epsilon_r$ is the dimensionless relative
permittivity of the material at each point, real and positive, and $\rho$ is
the free charge density in C/m³ (zero unless a source states it). The electric
field and the displacement are

$$
\mathbf{E}=-\nabla\phi \ \ (\mathrm{V/m}),\qquad
\mathbf{D}=\epsilon_0\,\epsilon_r\,\mathbf{E} \ \ (\mathrm{C/m^2}),
$$

and the energy density is $w=\tfrac12\,\mathbf{E}\cdot\mathbf{D}$ in J/m³.

## Conditions

On the boundary $\partial\Omega$, $\mathbf{n}$ is the unit normal pointing out
of $\Omega$. Every outer boundary carries exactly one condition, stated in the
model, never implied:

| kind | states | parameter |
|---|---|---|
| `potential` | $\phi=\phi_D$ — a Dirichlet condition | `value`: $\phi_D$, in V |
| `insulating` | $\mathbf{n}\cdot\mathbf{D}=0$ — the natural condition; no field line crosses the boundary | — |
| `surface_charge` | $\mathbf{n}\cdot\mathbf{D}=q$ — a Neumann condition, a given normal flux | `value`: $q$, in C/m² |

For a conductor lying outside $\Omega$, whose surface is part of
$\partial\Omega$, the free charge on that surface is $\sigma=-\mathbf{n}\cdot\mathbf{D}$,
since $\mathbf{n}$ points into the conductor: a conductor carrying surface
charge $\sigma$ is stated as `surface_charge` with `value` $=-\sigma$.

Between two domains the potential is continuous by the function space, and so
is the normal displacement where no free surface charge lies there: in the weak
form, $\mathbf{n}\cdot\mathbf{D}$ jumps by the surface charge on the face, and
by nothing where none is stated. A face between two domains is therefore
continuous without being named; named as an interface, it carries `interface`,
which states that continuity ([`../contracts/models.md`](../contracts/models.md)
§ 3).

A source `charge_density` states $\rho$ in a domain, in C/m³.

## What each dimension means

- **3-D** (`full`): the equation as written.
- **2-D, `per unit depth`**: nothing varies along $z$; the domain is a
  cross-section, and every extensive quantity is per metre of depth — a charge
  per unit length in C/m, an energy per unit length in J/m.
- **2-D, `axisymmetric`**: nothing varies with the angle about the $z$ axis;
  coordinates are $(r, z)$ with $r\ge0$, and the operator becomes
  $-\frac1r\partial_r\!\left(r\,\epsilon_0\epsilon_r\,\partial_r\phi\right)
  -\partial_z\!\left(\epsilon_0\epsilon_r\,\partial_z\phi\right)=\rho$. On
  the axis $r=0$, the regularity of $\phi$ is the natural condition; a
  boundary on the axis is stated `insulating`, which is that condition.

## Validity

The equation is static: no current flows and nothing changes in time. Materials
are linear, isotropic and non-dispersive — $\epsilon_r$ is one real number per
material. A conductor is not a domain: it is a boundary held at a potential, or
carrying a charge.

## Benchmarks

What proves an environment's translation is listed in the formulation and
explained here as each is added ([`../contracts/models.md`](../contracts/models.md)
§ 6.3): first a two-material case, where $\phi$ depends on $\epsilon_r$ and the
interface; manufactured solutions follow with the expression language
([`../plans/plan.md`](../plans/plan.md) § 3, M6).
