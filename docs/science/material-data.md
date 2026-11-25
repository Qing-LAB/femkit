# Material data

**Role:** scientific background

**Status:** current

**Authority:** what a material's data means: the phasor conventions and the
passive sign, the equivalent forms and their conversion, the spectral variables
and their exact relations, a table's interpolation, and each dispersion model's
formula; how a material states them is
[`../contracts/materials.md`](../contracts/materials.md)

## Contents

1. Terms and symbols
2. Phasor conventions and passivity
3. Equivalent forms — `refractive_index` to `relative_permittivity`
4. Spectral variables — wavelength, frequency, photon energy
5. Tables — linear interpolation
6. Dispersion models — `sellmeier`, `drude_lorentz`
7. Validity
8. Checks

## 1. Terms and symbols

| term or symbol | meaning | unit |
|---|---|---|
| $\epsilon_r$ | relative permittivity, complex in general: $\epsilon_r=\epsilon'+i\epsilon''$ | 1 |
| $\tilde n$ | complex refractive index | 1 |
| $n$ | refractive index, the real part of $\tilde n$ | 1 |
| $\kappa$ | extinction coefficient, the magnitude of the imaginary part of $\tilde n$, $\kappa\ge0$ for a passive material | 1 |
| $\lambda$ | vacuum wavelength | m |
| $\nu$ | frequency | Hz |
| $\omega=2\pi\nu$ | angular frequency | rad/s |
| $\mathcal{E}=h\nu$ | photon energy | J, or eV |
| $c_0$ | speed of light in vacuum, $299\,792\,458$ exactly (SI 2019) | m/s |
| $h$ | Planck constant, $6.626\,070\,15\times10^{-34}$ exactly (SI 2019) | J s |
| $e$ | elementary charge, $1.602\,176\,634\times10^{-19}$ exactly (SI 2019); 1 eV $=e\cdot$1 V | C |

## 2. Phasor conventions and passivity

A field oscillating at one frequency is the real part of a phasor,
$\mathbf{E}_{\mathrm{physical}}(t)=\operatorname{Re}[\mathbf{E}\,e^{s i\omega t}]$,
with $s=-1$, written `exp(-iwt)`, or $s=+1$, written `exp(+iwt)`
([`electromagnetics.md`](electromagnetics.md)). Data with no imaginary part
is written `real`, and needs no convention.

- **Between the two conventions, a complex material quantity is conjugated.**
  Since $\operatorname{Re}z=\operatorname{Re}\bar z$, the same physical field
  and response written with $e^{+i\omega t}$ have the conjugate phasors, so
  $\epsilon_r^{(+)}=\overline{\epsilon_r^{(-)}}$ and
  $\tilde n^{(+)}=\overline{\tilde n^{(-)}}$.
- **The passive sign.** Under `exp(-iwt)` the polarization current is
  $\mathbf{J}=-i\omega\epsilon_0(\epsilon_r-1)\mathbf{E}$, and the power a
  material absorbs per unit volume, averaged over a period, is
  $\tfrac12\operatorname{Re}(\mathbf{J}\cdot\bar{\mathbf{E}})
  =\tfrac12\,\omega\epsilon_0\,\epsilon''\,|\mathbf{E}|^2$.
  A passive material absorbs, so $\epsilon''\ge0$ under `exp(-iwt)`, and
  $\epsilon''\le0$ under `exp(+iwt)`. This is the one statement of the sign;
  a material whose converted $\epsilon''$ has the other sign is refused
  ([`../contracts/materials.md`](../contracts/materials.md) § 6).

## 3. Equivalent forms

A source may give the complex refractive index instead of the permittivity.
Under `exp(-iwt)`, $\tilde n=n+i\kappa$, so a plane wave
$e^{i(\tilde n\omega x/c_0-\omega t)}$ decays as $e^{-\kappa\omega x/c_0}$ for
$\kappa>0$; under `exp(+iwt)`, $\tilde n=n-i\kappa$. For a non-magnetic
material, $\mu_r=1$, so that $\tilde n^2=\epsilon_r\mu_r=\epsilon_r$ — the
only materials femkit's property list describes today — in either,

$$
\epsilon_r=\tilde n^2,\qquad \epsilon'=n^2-\kappa^2,\qquad
\epsilon''=\pm2n\kappa,
$$

with $+$ under `exp(-iwt)` and $-$ under `exp(+iwt)`. The conversion is
exact: it squares the source's numbers. For $n>0$, the passive sign of § 2
holds exactly when $\kappa\ge0$. femkit converts only this way, from
`refractive_index` to `relative_permittivity`; the reverse needs a square
root and is never done. A relative permeability joining the property list
makes this conversion need it: $\epsilon_r=\tilde n^2/\mu_r$.

A source's extinction coefficient $\kappa$ is a magnitude, so data giving $n$
and $\kappa$ are written as $\tilde n=n+i\kappa$ under `exp(-iwt)`.

## 4. Spectral variables

A dataset may vary with the vacuum wavelength $\lambda$, the frequency $\nu$
or the photon energy $\mathcal{E}$, one spectral position stated three ways:

$$
\lambda=\frac{c_0}{\nu},\qquad \mathcal{E}=h\nu=\frac{h c_0}{\lambda},\qquad
\mathcal{E}/\mathrm{eV}=\frac{h c_0}{e\,\lambda\cdot1\,\mathrm{V}}.
$$

$c_0$, $h$ and $e$ are exact, so a rational $\lambda$ gives a rational
$\nu$ and $\mathcal{E}$: femkit converts between the three exactly. The
angular frequency $\omega=2\pi\nu$ is never formed, since $\pi$ is not
rational. A model written in a frequency-like variable is stated in photon
energies (§ 6.2), never in $\omega$.

A wavelength in a material's data is the vacuum wavelength, and a refractive
index is the absolute one, relative to vacuum. A source giving the wavelength
in air, or the index relative to air, must be converted before its data is
used: in air the wavelength is shorter by the air's index, about 3 parts in
$10^4$, and an index relative to air is smaller than the absolute one by the
same factor — an index of 1.45846 relative to air is 1.45886 absolute.
refractiveindex.info's files can say which they hold in a `SPECS` block;
femkit's importer refuses a file holding one rather than drop what it says.
Its documentation (read 2026-11-25) does not state what a file without one
holds; that is not measured.

## 5. Tables

A table gives a property at points $x_1<x_2<\dots<x_N$ of its variable. At
$x_i\le x\le x_{i+1}$, each column — the real value, or the real and
imaginary parts, or $n$ and $\kappa$ — is interpolated linearly in the
table's own variable, as the source tabulated it:

$$
y(x)=y_i+(y_{i+1}-y_i)\,\frac{x-x_i}{x_{i+1}-x_i},
$$

and then converted (§§ 2–3). In exact arithmetic this is exact. A table is
never extrapolated: $x<x_1$ or $x>x_N$ lies outside its range.

## 6. Dispersion models

Each model is stated once, with its parameters, their dimensions, and the
convention its formula is written in. The list is closed and declared in
`femkit/data/dispersion.toml`; a model not on it is refused.

### 6.1 `sellmeier`

$$
\epsilon_r(\lambda)=n^2=1+A+\sum_{i}\frac{B_i\,\lambda^2}{\lambda^2-C_i},
$$

with $A$ and each $B_i$ dimensionless, and each $C_i$ a length squared. A
term may state its pole as a resonance wavelength $\lambda_i$ instead, a
length, and then $C_i=\lambda_i^2$; the dimension of what the term states
tells which, so the conversion is exact. The model is real and lossless, so
its data is `real`. refractiveindex.info's formula 1 is
$n^2-1=C_1+\sum_i C_{2i}\lambda^2/(\lambda^2-C_{2i+1}^2)$ and its formula 2
is $n^2-1=C_1+\sum_i C_{2i}\lambda^2/(\lambda^2-C_{2i+1})$, both with
$\lambda$ in µm (its "Dispersion formulas", 2014): $A=C_1$, $B_i=C_{2i}$, and
$C_{2i+1}$ a resonance wavelength in µm (formula 1) or its square in µm²
(formula 2).

### 6.2 `drude_lorentz`

Written under `exp(-iwt)`, with $\epsilon_\infty$, $\mathcal{E}_p$ and each
$\mathcal{E}_j$ positive, and each strength $f$ and damping $\Gamma$ not
negative:

$$
\epsilon_r(\mathcal{E})=\epsilon_\infty
-\frac{f_0\,\mathcal{E}_p^2}{\mathcal{E}^2+i\Gamma_0\mathcal{E}}
+\sum_{j=1}^{k}\frac{f_j\,\mathcal{E}_p^2}{\mathcal{E}_j^2-\mathcal{E}^2-i\Gamma_j\mathcal{E}},
$$

| symbol | meaning | unit |
|---|---|---|
| $\epsilon_\infty$ | the permittivity the oscillators leave at high energy | 1 |
| $\mathcal{E}_p$ | the plasma energy, $\hbar\omega_p$ | eV |
| $f_0$, $\Gamma_0$ | the free electrons' strength and damping | 1, eV |
| $f_j$, $\mathcal{E}_j$, $\Gamma_j$ | oscillator $j$'s strength, resonance and damping | 1, eV, eV |

Each term absorbs: the free term's imaginary part is
$f_0\mathcal{E}_p^2\Gamma_0\mathcal{E}/(\mathcal{E}^4+\Gamma_0^2\mathcal{E}^2)\ge0$,
and oscillator $j$'s is
$f_j\mathcal{E}_p^2\Gamma_j\mathcal{E}/((\mathcal{E}_j^2-\mathcal{E}^2)^2+\Gamma_j^2\mathcal{E}^2)\ge0$,
the passive sign of § 2. A negative damping or strength would make a term
give energy rather than absorb it, and another term can hide it in the sum:
each parameter's sign is checked on its own. A source that writes the model under `exp(+iwt)`
gives the same positive parameters, since the convention changes only the
sign of $i$; this statement fixes it. Rakić et al. tabulate the parameters
for eleven metals with $\epsilon_\infty=1$ (A. D. Rakić, A. B. Djurišić,
J. M. Elazar and M. L. Majewski, Appl. Opt. 37, 5271 (1998),
doi:10.1364/AO.37.005271).

Every rational $\mathcal{E}$ gives a rational complex $\epsilon_r$: the model
is evaluated exactly.

## 7. Validity

- A dataset holds within its stated range, and never outside it: a table is
  not extrapolated (§ 5), and a model's range is its source's.
- `sellmeier` holds for a transparent material, away from its poles; its
  range lies between them.
- `drude_lorentz` is a fit: its range is the range its source fitted.
- A static field reads a material's response at zero frequency. A dataset
  that varies with a spectral variable says nothing there, nor does a
  constant whose range is a spectral interval, and a static step refuses
  both ([`../contracts/materials.md`](../contracts/materials.md) § 6). An
  optical index squared is not the static permittivity — water's is about
  1.77 against about 80.

## 8. Checks

The values a model's or a conversion's code must give exactly:

- fused silica by Malitson's Sellmeier coefficients — $B_i$ = 0.6961663,
  0.4079426, 0.8974794 and $\lambda_i$ = 0.0684043, 0.1162414, 9.896161 µm —
  gives $n=1.4585$ at $\lambda=0.5876$ µm, to four decimals (I. H. Malitson,
  J. Opt. Soc. Am. 55, 1205 (1965), doi:10.1364/JOSA.55.001205); the same
  coefficients stated as squares give the same value exactly;
- `sellmeier` with $A=1$ and no term is $2$ at every wavelength;
- `drude_lorentz` with no oscillator and $\Gamma_0=0$ is
  $\epsilon_\infty-f_0\mathcal{E}_p^2/\mathcal{E}^2$, zero at
  $\mathcal{E}=\mathcal{E}_p\sqrt{f_0/\epsilon_\infty}$ — with
  $\epsilon_\infty=4$, $\mathcal{E}_p=9$ eV and $f_0=1/4$, at 2.25 eV; with
  positive parameters its $\epsilon''$ is positive at every energy;
- one oscillator alone — $\epsilon_\infty=2$, $\mathcal{E}_p=3$ eV, $f_0=0$,
  $f=1/2$, $\mathcal{E}_j=2$ eV, $\Gamma=1/4$ eV — gives $2+9i$ at 2 eV and
  $506/145+18/145\,i$ at 1 eV;
- $(n,\kappa)=(0.29, 2.863)$ — Johnson and Christy's gold at 0.5821 µm —
  gives $\epsilon_r=-8.112669+1.66054\,i$ under `exp(-iwt)` exactly, and its
  conjugate under `exp(+iwt)`;
- a table interpolated at one of its points gives that point's row, and
  halfway between two, their mean; an $(n,\kappa)$ table with rows
  $(1\ \mu\text{m}: 1, 0)$ and $(3\ \mu\text{m}: 3, 2)$ gives $3+4i$ at
  2 µm — $n$ and $\kappa$ interpolated, then squared — not the $3+6i$ of
  squaring first.
