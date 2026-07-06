#!/usr/bin/env python3
"""Core logic for bigram cross-entropy scoring against a language model.

Shared by the `entropy` custom search command and the model-upload
REST handler. No Splunk imports here, so it stays unit-testable
outside of Splunk.
"""

import csv
import io
import math
import os
import re

DEFAULT_FLOOR = 1e-7

# Characters stripped before scoring: spaces, dots, commas, hyphens, underscores.
# Dots/hyphens make the command usable on domain names (C2 / DGA hunting)
# without punctuation bigrams polluting the score.
_STRIP_RE = re.compile(r"[ _.,\-]")

# Lookup names must be plain basenames - no path traversal.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def app_lookups_dir():
    """Absolute path to this app's lookups directory."""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "lookups")
    )


def list_lookup_files():
    """All CSV files in the app's lookups directory (safe names only)."""
    directory = app_lookups_dir()
    if not os.path.isdir(directory):
        return []
    return sorted(
        name for name in os.listdir(directory)
        if name.lower().endswith(".csv")
        and _SAFE_NAME_RE.match(name)
        and os.path.isfile(os.path.join(directory, name))
    )


def resolve_lookup_path(lookup_name):
    """Resolve a lookup file name inside the app's lookups dir, safely.

    Raises ValueError on anything that is not a plain file name.
    """
    if not _SAFE_NAME_RE.match(lookup_name or ""):
        raise ValueError(
            "Invalid lookup name %r (letters, digits, '_', '-', '.' only)"
            % lookup_name
        )
    path = os.path.join(app_lookups_dir(), lookup_name)
    if not os.path.isfile(path):
        raise FileNotFoundError("Lookup file not found: %s" % path)
    return path


def normalize(text):
    """Lowercase and strip separator characters ( .,-)."""
    return _STRIP_RE.sub("", (text or "").lower())


def load_bigram_probs(path):
    """Load a CSV of `bigram,probability` into a dict.

    Skips the header row and any malformed/empty rows. Keys are
    lowercased so lookups stay consistent with normalize().
    """
    probs = {}
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) < 2:
                continue
            bigram = row[0].strip().lower()
            if len(bigram) != 2:
                continue
            try:
                p = float(row[1])
            except ValueError:
                continue
            if p > 0.0:
                probs[bigram] = p
    return probs


def cross_entropy(text, probs, floor=DEFAULT_FLOOR):
    """Bigram cross-entropy of `text` in bits per bigram.

    Returns None when the normalized text is shorter than 2 chars
    (no bigrams to score).
    """
    text = normalize(text)
    n = len(text)
    if n < 2:
        return None
    log_sum = 0.0
    for i in range(1, n):
        prob = probs.get(text[i - 1] + text[i], floor)
        log_sum += math.log2(prob)
    return -log_sum / (n - 1)


def frequencies_to_probabilities(csv_text):
    """Convert `bigram,count` CSV text to conditional probabilities.

    q(c2 | c1) = count(c1 c2) / sum over x of count(c1 x)

    Returns (output_csv_text, stats_dict). Raises ValueError on
    unusable input.
    """
    reader = csv.reader(io.StringIO(csv_text))
    header = next(reader, None)
    if header is None:
        raise ValueError("Empty CSV file")

    counts = {}
    skipped = 0
    for row in reader:
        if len(row) < 2:
            skipped += 1
            continue
        bigram = row[0].strip().lower()
        if len(bigram) != 2:
            skipped += 1
            continue
        try:
            count = int(row[1].strip())
        except ValueError:
            skipped += 1
            continue
        if count <= 0:
            skipped += 1
            continue
        counts[bigram] = counts.get(bigram, 0) + count

    if not counts:
        raise ValueError(
            "No valid rows found. Expected CSV with a header and rows "
            "of the form: bigram,count (e.g. 'ie,1962799')"
        )

    first_char_sums = {}
    for bigram, count in counts.items():
        first = bigram[0]
        first_char_sums[first] = first_char_sums.get(first, 0) + count

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["bigram", "probability"])
    min_prob = 1.0
    for bigram in sorted(counts):
        prob = counts[bigram] / first_char_sums[bigram[0]]
        min_prob = min(min_prob, prob)
        # Full float precision - rounding to a fixed number of decimals
        # can flatten rare bigrams to 0, which breaks log2().
        writer.writerow([bigram, repr(prob)])

    stats = {
        "bigrams": len(counts),
        "contexts": len(first_char_sums),
        "skipped_rows": skipped,
        "min_probability": min_prob,
    }
    return out.getvalue(), stats
