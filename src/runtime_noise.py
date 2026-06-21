"""Runtime initialization for known third-party startup noise."""

import logging
import os
import warnings


def configure_runtime_noise_filters() -> None:
    """Suppress known third-party advisory noise without hiding real errors."""
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "true")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    logging.getLogger("transformers").setLevel(logging.ERROR)
    try:
        from langchain_core._api.deprecation import (  # pylint: disable=import-outside-toplevel
            LangChainPendingDeprecationWarning,
        )
    except ImportError:
        pending_warning = Warning
    else:
        pending_warning = LangChainPendingDeprecationWarning

    warnings.filterwarnings(
        "ignore",
        message=r"The default value of `allowed_objects` will change.*",
        category=pending_warning,
    )
