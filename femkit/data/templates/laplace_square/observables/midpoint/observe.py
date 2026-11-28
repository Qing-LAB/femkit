# The functions that compute this part's observables (manual: 3 · Write each part). Each takes one
# argument, `case` — the folder of the case's finished solve run, `case.run`; the definitions its
# `takes` names, `case.defs.<name>`, in SI units; the groups it names, `case.groups.<name>`; the
# study and the engine whose solve it reads, `case.study` and `case.engine` — and returns a number
# of its type, in SI units. This file holds functions alone. femkit runs it after each case's
# solve, in its postprocess environment, as a stage of its own. The solve is not built yet, and
# what it writes in its run is not settled, so a function says what it would read and computes
# nothing.


def potential_middle(case):
    """The potential at the square's centre: half the bias, exactly, at any mesh."""
    middle = case.defs.side / 2                                   # the centre's x and y, in metres
    raise NotImplementedError(f"the potential at ({middle} m, {middle} m) is read from the solve's output, which femkit does not make yet")
