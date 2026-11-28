# The functions that compute this project's computed definitions (manual: 3 · Write each part).
# A definition in project.toml names its function, `function = "<name>"`; the function takes no
# arguments, reads every other definition as `defs.<name>`, a plain number in SI units — an angle
# in degrees — and returns its own value the same way, a number of the definition's type. This
# file holds imports and functions alone; femkit runs it in its own environment, model_prep.

import numpy as np
from scipy import constants
import project.definitions as defs          # femkit's: every definition, constant or computed
