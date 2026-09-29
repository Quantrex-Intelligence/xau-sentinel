"""Process-independent RNG seeds for mock data (VAL-027).

Python's built-in hash() of a str (or a tuple containing one) is salted per
process unless PYTHONHASHSEED is pinned, so a seed built from it changes on
every restart. The mock generators' docstrings promise output that's
deterministic per timeframe/day; a SHA-256 digest of the same parts keeps
that promise across restarts, machines and Python versions.
"""
import hashlib


def stable_seed(*parts) -> int:
    """A 32-bit seed that depends only on `parts` (each rendered with
    str()), suitable for numpy.random.default_rng()."""
    payload = "\x1f".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:4], "big")
