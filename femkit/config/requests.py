"""The config domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.config import settings
from femkit.core.schema import Model
from typing import Literal

from pydantic import Field, create_model


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


def option_name(k: settings.Key) -> str:
    return "activation" if k.dotted == settings.COMMAND else k.name


OPTION_KEYS = {option_name(k): k for k in settings.keys()}
if len(OPTION_KEYS) != len(settings.keys()):  # a defect of femkit's own: two keys would be one `config init` option
    raise TypeError("config key names must be unique across sections: each is one `config init` option")

InitRequest = create_model(
    "InitRequest",
    __base__=Model,
    __doc__="Values for keys the file lacks; a key not given is proposed where something measured suggests a value.",
    **{name: (k.annotation, Field(default=None, description=f"{k.dotted}: {k.description}"))
       for name, k in OPTION_KEYS.items()},
    no_preamble=(bool, Field(default=False, description="activation.preamble = []: this machine needs none")),
)


# ------------------------------------------------------------------ the operations these requests are for

CONFIG_INIT = Verb("config.init", InitRequest)
CONFIG_PATH = Verb("config.path", PathRequest)
CONFIG_SET = Verb("config.set", SetRequest)
CONFIG_SHOW = Verb("config.show", ShowRequest)
