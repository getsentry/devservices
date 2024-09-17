from __future__ import annotations

import os
from configparser import ConfigParser
from configparser import NoOptionError
from configparser import NoSectionError

from devenv.constants import home
from devenv.lib.config import read_config


def get_coderoot() -> str:
    config_path = os.path.join(home, ".config", "sentry-devenv", "config.ini")
    try:
        devenv_config: ConfigParser = read_config(config_path)
        return devenv_config.get("devenv", "coderoot", fallback="")
    except (FileNotFoundError, NoSectionError, NoOptionError):
        # TODO: Handle the case where there is no config file or the coderoot is not set
        raise Exception("Failed to read code root from config")
    except Exception as e:
        raise Exception(f"Failed to read config: {e}")
