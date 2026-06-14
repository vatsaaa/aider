"""Environment configuration helpers.

This module loads environment variables from a `.env` file using
`python-dotenv` and exposes a typed `Env` helper for retrieving values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Env:
    """Helper for accessing environment variables.

    Use `Env.load()` early in process startup to read `.env` into the
    environment. Certificates and secrets must never be hard-coded.
    """

    @staticmethod
    def load(dotenv_path: Optional[str] = None) -> None:
        """Load environment variables from `dotenv_path` into `os.environ`.

        Args:
            dotenv_path: Optional path to a dotenv file. If None, default
                lookup rules from `python-dotenv` are used.
        """

        load_dotenv(dotenv_path)

    @staticmethod
    def get(key: str, default: Optional[str] = None) -> Optional[str]:
        """Return the value of environment variable `key` or `default`.

        Args:
            key: Environment variable name.
            default: Value to return if `key` is not present.
        """

        return os.getenv(key, default)
