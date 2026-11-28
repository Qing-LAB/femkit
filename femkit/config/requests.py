"""The config domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT, spelling
from femkit.config import settings
from femkit.core.schema import Model
from typing import Literal

from pydantic import Field, create_model, model_validator


class PathRequest(Model):
    """No inputs."""


class ShowRequest(Model):
    """No inputs."""


class SetRequest(Model):
    """One key and its new value."""

    key: Literal[tuple(k.dotted for k in settings.keys())] = Field(  # the keys config.toml has, and no other
        description="a dotted key, e.g. build.jobs", json_schema_extra=ARGUMENT)
    value: str = Field(description='a TOML value, as the file writes it: 8, "text", ["80", "90"], []',
                       json_schema_extra={**ARGUMENT, "toml": "whole"})


#: Each key by its name, the field `config init` takes it by — its option spelled as the key's
#: `cli` annotation says, where it says one (`--activation`).
OPTION_KEYS = {k.name: k for k in settings.keys()}
if len(OPTION_KEYS) != len(settings.keys()):  # a defect of femkit's own: two keys would be one `config init` option
    raise TypeError("config key names must be unique across sections: each is one `config init` option")

#: Each key a flag of `config init`'s states empty, by that flag's field, as the key's field declares
#: it (`empty`, config.md § 3.2).
EMPTIES = {k.empty[0]: k for k in settings.keys() if k.empty is not None}


def _one_form(req):
    """A key's values and the flag stating it empty — `--preamble` and `--no-preamble` — contradict
    each other: a request naming both is refused by its schema, never one of them dropped
    (config.md § 3.2)."""
    fields = type(req).model_fields
    both = [(k.name, flag) for flag, k in EMPTIES.items() if getattr(req, flag) and getattr(req, k.name) is not None]
    if both:
        typed = [spelling(name, fields[name]).flag for name in both[0]]
        raise ValueError(f"{typed[0]} and {typed[1]} contradict each other: give one")
    return req


InitRequest = create_model(
    "InitRequest",
    __base__=Model,
    __validators__={"_one_form": model_validator(mode="after")(_one_form)},
    __doc__="Values for keys the file lacks; a key not given is proposed where something measured suggests a value.",
    **{name: (k.annotation, Field(default=None, description=f"{k.dotted}: {k.description}",
                                  json_schema_extra={"cli": k.extras["cli"]} if "cli" in k.extras else None))
       for name, k in OPTION_KEYS.items()},
    **{flag: (bool, Field(default=False, description=settings.empty_said(k))) for flag, k in EMPTIES.items()},
)


# ------------------------------------------------------------------ the operations these requests are for

CONFIG_INIT = Verb("config.init", InitRequest, on_machine=True, effect="changes")
CONFIG_PATH = Verb("config.path", PathRequest, on_machine=True, effect="reads")
CONFIG_SET = Verb("config.set", SetRequest, on_machine=True, effect="changes")
CONFIG_SHOW = Verb("config.show", ShowRequest, on_machine=True, effect="reads")
