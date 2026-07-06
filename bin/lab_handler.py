#!/usr/bin/env python3
"""Persistent REST handler backing the "Entropy lab" view.

Endpoints (via splunkweb proxy, /splunkd/__raw/services/entropy_lab):

  GET  ?action=models
      -> {"models": ["polish_bigrams_probabilities.csv", ...]}

  GET  ?action=maxentropy&floor=1e-6
      -> {"floor": ..., "max_entropy_bits": ...}
      Maximum possible score for a given floor: a string of digits
      contains only bigrams absent from every model, so each bigram
      scores the floor probability and H = -log2(floor) regardless of
      length (>= 2) and regardless of the model.

  POST ?action=score   (JSON body)
      {"strings": [...], "lookups": [...optional, default: all...],
       "floor": optional}
      -> {"models": [...], "rows": [{"string": s, "scores": [..]}],
          "stats": {model: {count, scored, too_short, min, max, mean,
                            median, stdev, p95}}}
"""

import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(__file__))

try:
    from splunk.persistconn.application import (
        PersistentServerConnectionApplication,
    )
except ImportError:  # outside Splunk (unit tests)
    PersistentServerConnectionApplication = object

import entropy_lib

MAX_STRINGS = 10000
MAX_BODY_BYTES = 5 * 1024 * 1024


def _response(status, body):
    return {
        "payload": json.dumps(body),
        "status": status,
        "headers": {"Content-Type": "application/json"},
    }


def _parse_floor(raw, default=entropy_lib.DEFAULT_FLOOR):
    try:
        floor = float(raw)
    except (TypeError, ValueError):
        return default
    if not 1e-30 <= floor <= 1.0:
        return default
    return floor


def _max_entropy(n, floor):
    """Entropy of '1' * n - every bigram unknown, so every bigram
    scores the floor probability."""
    return entropy_lib.cross_entropy("1" * n, {}, floor)


def _stats(scores, too_short):
    """Summary statistics for a list of non-null entropy scores."""
    out = {
        "count": len(scores) + too_short,
        "scored": len(scores),
        "too_short": too_short,
        "min": None, "max": None, "mean": None,
        "median": None, "stdev": None, "p95": None,
    }
    if not scores:
        return out
    out["min"] = min(scores)
    out["max"] = max(scores)
    out["mean"] = statistics.fmean(scores)
    out["median"] = statistics.median(scores)
    if len(scores) >= 2:
        out["stdev"] = statistics.stdev(scores)
        out["p95"] = statistics.quantiles(scores, n=100, method="inclusive")[94]
    return out


class LabHandler(PersistentServerConnectionApplication):

    def __init__(self, command_line=None, command_arg=None):
        if PersistentServerConnectionApplication is not object:
            super().__init__()

    def handle(self, in_string):
        try:
            request = json.loads(in_string)
        except ValueError:
            return _response(400, {"error": "Malformed request"})

        method = request.get("method", "").upper()
        query = dict(request.get("query") or [])
        action = query.get("action", "")

        if action == "models" and method == "GET":
            return self._models()
        if action == "maxentropy" and method == "GET":
            return self._maxentropy(query)
        if action == "score" and method == "POST":
            return self._score(request)
        return _response(400, {
            "error": "Unknown action. Use GET action=models, "
                     "GET action=maxentropy or POST action=score."
        })

    @staticmethod
    def _models():
        return _response(200, {"models": entropy_lib.list_lookup_files()})

    @staticmethod
    def _maxentropy(query):
        floor = _parse_floor(query.get("floor"))
        return _response(200, {
            "floor": floor,
            "max_entropy_bits": _max_entropy(2, floor),
        })

    @staticmethod
    def _score(request):
        payload = request.get("payload") or ""
        if len(payload.encode("utf-8", "ignore")) > MAX_BODY_BYTES:
            return _response(413, {"error": "Request larger than 5 MB"})
        try:
            body = json.loads(payload)
        except ValueError:
            return _response(400, {"error": "Body must be JSON"})

        strings = body.get("strings")
        if not isinstance(strings, list) or not strings:
            return _response(400, {"error": "Provide a non-empty 'strings' list"})
        if len(strings) > MAX_STRINGS:
            return _response(400, {
                "error": "Too many strings (%d). Limit: %d"
                         % (len(strings), MAX_STRINGS)
            })
        strings = [str(s) for s in strings]

        lookups = body.get("lookups") or entropy_lib.list_lookup_files()
        if not lookups:
            return _response(400, {
                "error": "No probability lookups found. Upload a model "
                         "on the 'Upload bigram model' page first."
            })

        floor = _parse_floor(body.get("floor"))

        models = {}
        for name in lookups:
            try:
                path = entropy_lib.resolve_lookup_path(str(name))
            except (ValueError, FileNotFoundError) as exc:
                return _response(400, {"error": str(exc)})
            probs = entropy_lib.load_bigram_probs(path)
            if not probs:
                return _response(400, {
                    "error": "Lookup %s contains no usable rows" % name
                })
            models[str(name)] = probs

        model_names = list(models)
        rows = []
        per_model_scores = {name: [] for name in model_names}
        per_model_too_short = {name: 0 for name in model_names}

        for s in strings:
            scores = []
            for name in model_names:
                score = entropy_lib.cross_entropy(s, models[name], floor)
                if score is None:
                    per_model_too_short[name] += 1
                    scores.append(None)
                else:
                    score = round(score, 4)
                    per_model_scores[name].append(score)
                    scores.append(score)
            rows.append({"string": s, "scores": scores})

        stats = {
            name: _stats(per_model_scores[name], per_model_too_short[name])
            for name in model_names
        }
        return _response(200, {
            "models": model_names,
            "floor": floor,
            "rows": rows,
            "stats": stats,
        })
