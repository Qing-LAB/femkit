"""The config domain's request models: every input its operations take, apart from the code
that runs them, so a next step can name one without importing that code (web.md § 7.2)."""

from __future__ import annotations

from femkit.core.view import Verb

from femkit.core.commandline import ARGUMENT
from femkit.config import settings
from femkit.core.schema import Model
from pydantic import Field, create_model


class PathRequest(Model):
    """No inputs."""


class ShowRequest(Model):
    """No inputs."""


class SetRequest(Model):
    """One key and its new value."""

    key: str = Field(description="a dotted key, e.g. build.jobs", json_schema_extra=ARGUMENT)
    value: str = Field(description='a TOML value, as the file writes it: 8, "text", ["80", "90"], []',
                       json_schema_extra={**ARGUMENT, "toml": "whole"})


def option_name(k: settings.Key) -> str:
    return "activation" if k.dotted == settings.COMMAND else k.name


OPTION_KEYS = {option_name(k): k for k in settings.keys()}
assert len(OPTION_KEYS) == len(settings.keys()), "config key names must be unique across sections"

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
