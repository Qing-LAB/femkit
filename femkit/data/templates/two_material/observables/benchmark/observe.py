# The functions that compute the benchmark's observables (manual: 3 · Write each part). Each takes
# one argument, `case` — the folder of the case's finished solve run, `case.run`; the definitions
# its `takes` names, `case.defs.<name>`, in SI units; the groups it names, `case.groups.<name>`,
# each with its regions in the case's mesh; the study and the engine whose solve it reads,
# `case.study` and `case.engine` — and returns a number of its type, in SI units. This file holds
# functions alone. femkit runs it after each case's solve, in its postprocess environment, as a
# stage of its own. The solve is not built yet, and what it writes in its run is not settled, so
# each function says what it would read and computes nothing.


def potential_low(case):
    """The potential halfway through the first layer, halfway up."""
    x, y = case.defs.interface / 2, case.defs.height / 2          # in metres
    raise NotImplementedError(f"the potential at ({x} m, {y} m) is read from the solve's output, which femkit does not make yet")


def potential_middle(case):
    """The potential on the interface, halfway up."""
    x, y = case.defs.interface, case.defs.height / 2              # in metres
    raise NotImplementedError(f"the potential at ({x} m, {y} m) is read from the solve's output, which femkit does not make yet")


def potential_high(case):
    """The potential halfway through the second layer, halfway up."""
    x, y = (case.defs.interface + case.defs.length) / 2, case.defs.height / 2   # in metres
    raise NotImplementedError(f"the potential at ({x} m, {y} m) is read from the solve's output, which femkit does not make yet")


def energy_low(case):
    """The field's energy in the first layer, per metre of depth."""
    regions = case.groups.low.regions                             # the engine's own IDs of `low` in the case's mesh
    raise NotImplementedError(f"the energy in the regions {regions} is read from the solve's output, which femkit does not make yet")


def energy_high(case):
    """The field's energy in the second layer, per metre of depth."""
    regions = case.groups.high.regions                            # the engine's own IDs of `high` in the case's mesh
    raise NotImplementedError(f"the energy in the regions {regions} is read from the solve's output, which femkit does not make yet")
