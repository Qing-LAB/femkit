#!/bin/sh
# femkit: the command the activated control environment puts on PATH (docs/contracts/envs.md § 7).
# scripts/install-env.sh writes it here each time it runs, naming the checkout it ran from: femkit
# runs from that checkout, in the folder you are in, on this environment's own Python, with no
# Python path and no user site-packages of yours, and never that folder on its import path (-P).
checkout={checkout}
if [ ! -f "$checkout/femkit/__main__.py" ]; then
    echo "[femkit] refused: the femkit checkout $checkout is gone; from its new place, run: bash scripts/install-env.sh bootstrap" >&2
    exit 2
fi
export PYTHONPATH="$checkout" PYTHONNOUSERSITE=1
exec {python} -P -m femkit "$@"
