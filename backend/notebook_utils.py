"""
Notebook sanitization and parsing utilities.
Handles real-world notebooks from Google Colab, VS Code, Kaggle, and Jupyter
that may contain non-standard metadata or schema quirks (e.g. metadata in stream outputs).
"""

import json
from typing import Union
import nbformat
from nbformat.validator import normalize


def sanitize_and_parse_notebook(content: Union[str, bytes]) -> nbformat.NotebookNode:
    """
    Parses and sanitizes a Jupyter notebook.
    Cleans known schema discrepancies (such as Colab stream output metadata)
    and relaxes strict validation so valid notebooks convert cleanly.
    """
    if isinstance(content, bytes):
        content_str = content.decode("utf-8", errors="replace")
    else:
        content_str = content

    try:
        raw_json = json.loads(content_str)
    except Exception as exc:
        raise ValueError(f"File is not valid JSON: {exc}")

    if not isinstance(raw_json, dict) or "cells" not in raw_json:
        raise ValueError("JSON structure is missing required 'cells' list.")

    # Read notebook node
    try:
        nb = nbformat.reads(content_str, as_version=4)
    except Exception:
        nb = nbformat.from_dict(raw_json)
        if nb.get("nbformat", 4) < 4:
            nb = nbformat.v4.upgrade(nb)

    # Automatically normalize cell IDs and spec versioning
    try:
        _, nb = normalize(nb)
    except Exception:
        pass

    # Sanitize known non-standard schema variations from Colab, VSCode, Kaggle
    for cell in nb.get("cells", []):
        if not isinstance(cell, dict):
            continue

        # Cell metadata tags must be a list if present, not None
        meta = cell.get("metadata")
        if isinstance(meta, dict) and meta.get("tags") is None:
            meta.pop("tags", None)

        if cell.get("cell_type") == "code":
            for output in cell.get("outputs", []):
                if not isinstance(output, dict):
                    continue
                # In Jupyter v4 JSON schema, stream and error outputs do not allow 'metadata'
                # Google Colab often attaches {'metadata': {'tags': None}} on stream stdout/stderr
                if output.get("output_type") in ("stream", "error"):
                    output.pop("metadata", None)

    # Validate with relax_add_props=True
    try:
        nbformat.validate(nb, relax_add_props=True)
    except TypeError:
        try:
            nbformat.validate(nb)
        except Exception:
            # Non-critical schema quirks should not block conversion
            pass
    except Exception:
        # If schema validation still complains about non-standard keys,
        # do not crash because nbconvert can still convert it successfully
        pass

    return nb

