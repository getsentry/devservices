from __future__ import annotations

import os
from configparser import ConfigParser
from configparser import NoOptionError
from configparser import NoSectionError

from devenv.constants import home
from devenv.lib.config import read_config

from devservices.exceptions import CoderootNotFoundError
from devservices.exceptions import ConfigError


def get_coderoot() -> str:
    config_path = os.path.join(home, ".config", "sentry-devenv", "config.ini")
    try:
        devenv_config: ConfigParser = read_config(config_path)
        return os.path.expanduser(devenv_config.get("devenv", "coderoot", fallback=""))
    except (FileNotFoundError, NoSectionError, NoOptionError) as e:
        # TODO: Handle the case where there is no config file or the coderoot is not set
        raise CoderootNotFoundError() from e
    except Exception as e:
        raise ConfigError(f"Failed to read config: {e}") from e
