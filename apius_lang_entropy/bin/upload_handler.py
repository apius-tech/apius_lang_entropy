#!/usr/bin/env python3
"""Persistent REST handler: accepts a `bigram,count` CSV, converts it to
conditional probabilities and writes `<name>_probabilities.csv` into
this app's lookups directory.

Endpoint (via splunkweb proxy):
    POST /splunkd/__raw/services/entropy_upload?name=<model_name>
    body: raw CSV text (bigram,count with a header row)
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(__file__))

from splunk.persistconn.application import PersistentServerConnectionApplication

import entropy_lib

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
MAX_BODY_BYTES = 5 * 1024 * 1024  # 5 MB is plenty for any bigram table


def _response(status, body):
    return {
        "payload": json.dumps(body),
        "status": status,
        "headers": {"Content-Type": "application/json"},
    }


class UploadHandler(PersistentServerConnectionApplication):
    def __init__(self, command_line, command_arg):
        super().__init__()

    def handle(self, in_string):
        try:
            request = json.loads(in_string)
        except ValueError:
            return _response(400, {"error": "Malformed request"})

        if request.get("method", "").upper() != "POST":
            return _response(405, {"error": "Use POST"})

        query = dict(request.get("query") or [])
        name = query.get("name", "")
        if not _NAME_RE.match(name):
            return _response(
                400,
                {
                    "error": "Invalid model name. Use 1-64 characters: "
                    "letters, digits, '_' or '-'."
                },
            )

        payload = request.get("payload") or ""
        if not payload.strip():
            return _response(400, {"error": "Empty CSV body"})
        if len(payload.encode("utf-8", "ignore")) > MAX_BODY_BYTES:
            return _response(413, {"error": "CSV larger than 5 MB"})

        try:
            out_csv, stats = entropy_lib.frequencies_to_probabilities(payload)
        except ValueError as exc:
            return _response(400, {"error": str(exc)})

        filename = f"{name}_probabilities.csv"
        out_path = os.path.join(entropy_lib.app_lookups_dir(), filename)
        try:
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                f.write(out_csv)
        except OSError as exc:
            return _response(500, {"error": f"Could not write lookup: {exc}"})

        floor_hint = None
        if stats["min_probability"] <= entropy_lib.DEFAULT_FLOOR:
            floor_hint = (
                "Smallest probability in this model ({:.2e}) is not above the "
                "default floor ({:.0e}). Pass a smaller floor= to the entropy "
                "command, e.g. floor={:.0e}".format(
                    stats["min_probability"],
                    entropy_lib.DEFAULT_FLOOR,
                    stats["min_probability"] / 10,
                )
            )

        return _response(
            200,
            {
                "lookup": filename,
                "bigrams": stats["bigrams"],
                "contexts": stats["contexts"],
                "skipped_rows": stats["skipped_rows"],
                "min_probability": stats["min_probability"],
                "floor_hint": floor_hint,
                "example_spl": f"| entropy field=your_field lookup={filename}",
            },
        )
