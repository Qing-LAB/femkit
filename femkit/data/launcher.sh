#!/bin/bash
# femkit: the command ~/.local/bin/femkit links, which activating the control environment puts on
# PATH too (docs/contracts/envs.md § 7). scripts/install-env.sh writes it here each time it runs,
# naming the checkout it ran from: femkit runs from that checkout, in the folder you are in, on this
# environment's own Python, isolated (-I): never that folder on its import path, none of your
# Python settings, no user site-packages. It keeps your shell otherwise — `PATH`, loaded modules,
# the scheduler's commands — so femkit sees the machine it probes as you do, and sheds only what
# femkit/data/process.toml's `femkit_sheds` names; every process femkit starts for an
# environment begins clean (envs.md §§ 4.4, 7).
checkout={checkout}
if [ ! -f "$checkout/femkit/__main__.py" ]; then
    echo "[femkit] refused: the femkit checkout $checkout is gone; from its new place, run: bash scripts/install-env.sh bootstrap" >&2
    exit 2
fi
{start}
exec {python} -I "$checkout/femkit/__main__.py" "$@"
