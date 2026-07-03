#!/usr/bin/env python3
"""`entropy` - custom streaming search command.

Usage in SPL:

    ... | entropy field=domain
    ... | entropy field=query lookup=english_bigrams_probabilities.csv output=score
    ... | entropy field=domain floor=1e-7

Computes bigram cross-entropy (bits/bigram) of the given field's value
against a conditional-probability model stored as a CSV lookup in this
app's lookups/ directory. Low score = looks like the modeled language,
high score = random-looking (hashes, DGA domains, C2 noise).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))

from splunklib.searchcommands import (  # noqa: E402
    Configuration,
    Option,
    StreamingCommand,
    dispatch,
    validators,
)

import entropy_lib  # noqa: E402


@Configuration()
class EntropyCommand(StreamingCommand):
    """Score events with bigram cross-entropy against a language model."""

    field = Option(
        doc="Field containing the string to score (required).",
        require=True,
        validate=validators.Fieldname(),
    )
    lookup = Option(
        doc="CSV lookup with bigram probabilities, located in the app's "
            "lookups directory. Default: polish_bigrams_probabilities.csv",
        require=False,
        default="polish_bigrams_probabilities.csv",
    )
    output = Option(
        doc="Name of the output field. Default: entropy",
        require=False,
        default="entropy",
    )
    floor = Option(
        doc="Probability assigned to bigrams missing from the model. "
            "Default: 1e-7",
        require=False,
        default=entropy_lib.DEFAULT_FLOOR,
        validate=validators.Float(minimum=1e-30, maximum=1.0),
    )

    # Model cache shared across chunks: {abs_path: (mtime, probs_dict)}
    _models = {}

    def _get_model(self):
        path = entropy_lib.resolve_lookup_path(self.lookup)
        mtime = os.path.getmtime(path)
        cached = self._models.get(path)
        if cached is None or cached[0] != mtime:
            probs = entropy_lib.load_bigram_probs(path)
            if not probs:
                raise ValueError(
                    "Lookup %s contains no usable bigram rows" % self.lookup
                )
            self._models[path] = (mtime, probs)
        return self._models[path][1]

    def stream(self, records):
        try:
            probs = self._get_model()
        except (ValueError, FileNotFoundError) as exc:
            self.error_exit(exc, str(exc))
            return

        floor = float(self.floor)
        for record in records:
            value = record.get(self.field)
            if isinstance(value, list):  # multivalue field: score each
                record[self.output] = [
                    _fmt(entropy_lib.cross_entropy(v, probs, floor))
                    for v in value
                ]
            else:
                record[self.output] = _fmt(
                    entropy_lib.cross_entropy(value, probs, floor)
                )
            yield record


def _fmt(score):
    return "" if score is None else round(score, 4)


dispatch(EntropyCommand, sys.argv, sys.stdin, sys.stdout, __name__)
