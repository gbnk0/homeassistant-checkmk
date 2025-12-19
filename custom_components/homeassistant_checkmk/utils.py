"""Utility helpers for filtering and parsing."""
import fnmatch


def split_terms(raw):
    return [term for term in raw.replace(",", " ").split() if term]


def match_any(value, patterns):
    return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)
