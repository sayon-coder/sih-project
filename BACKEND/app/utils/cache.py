"""
In-process TTL cache for IP-SAKTI Sahayak.

Why in-process and not Redis: the project runs on free-tier hosting
(Supabase free + a single small VM). There is no budget for a managed
Redis, and a second stateful service would add an ops burden the team did
not ask for. This module gives the 80% win - repeated reads served
without touching Supabase - with zero new dependencies and zero new
infrastructure.

Design
------
* Thread-safe (uvicorn threads share the process).
* Per-entry TTL + LRU eviction bounded by ``max_entries``.
* Key namespaces (``"overview:"``, ``"dashboard:"``, ...) so one writer
  can invalidate a whole family with ``invalidate_prefix``.
* Hit/miss/eviction counters per namespace for ``GET /api/admin/cache/stats``.
* Multi-worker note: each uvicorn worker keeps its own copy. Keys carry a
  data revision (content hash / max row id) wherever correctness matters,
  so a stale worker copy can only be old by TTL seconds, never wrong by
  content. TTLs are short on purpose.

What is cached and what is NOT
------------------------------
Cached: overview aggregates (composite key incl. content hash + max run
ids), dashboard roll-ups (per user, 60 s), corpus status (30 s),
official-sources registry (filter tuple, 300 s - static data), graph node
lists (filter tuple, 60 s), query embeddings (normalised text, 600 s),
completed analyses by (version, content hash, type) - reuse, not TTL.

Never cached: auth, mutations, per-user private query paths (chat with
attachments/product context/private docs), paid/permission-gated payloads.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Dict, Optional


@dataclass
class _Entry:
    value: Any
    expires_at: float
    # Last-access tick for LRU ordering (maintained by the OrderedDict;
    # the field exists so tests can introspect without touching internals).


@dataclass
class NamespaceStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    invalidations: int = 0

    def as_dict(self) -> Dict[str, int]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "invalidations": self.invalidations,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


class TTLCache:
    """Bounded, thread-safe, per-entry-TTL LRU cache."""

    def __init__(self, max_entries: int = 2048, default_ttl: float = 60.0) -> None:
        self.max_entries = max_entries
        self.default_ttl = default_ttl
        self._store: "OrderedDict[str, _Entry]" = OrderedDict()
        self._lock = threading.RLock()
        self._stats: Dict[str, NamespaceStats] = {}

    # -- internals ----------------------------------------------------

    @staticmethod
    def _namespace(key: str) -> str:
        return key.split(":", 1)[0] if ":" in key else "default"

    def _stat(self, key: str) -> NamespaceStats:
        ns = self._namespace(key)
        stat = self._stats.get(ns)
        if stat is None:
            stat = self._stats[ns] = NamespaceStats()
        return stat

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, e in self._store.items() if e.expires_at <= now]
        for k in expired:
            del self._store[k]

    # -- public API ---------------------------------------------------

    def get(self, key: str) -> Any:
        """Return the value or None on miss/expiry (None values are never stored)."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._stat(key).misses += 1
                return None
            if entry.expires_at <= time.monotonic():
                del self._store[key]
                self._stat(key).misses += 1
                return None
            self._store.move_to_end(key)
            self._stat(key).hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store a value. None values and non-positive TTLs are ignored."""
        if value is None:
            return
        ttl = self.default_ttl if ttl is None else ttl
        if ttl <= 0:
            return
        with self._lock:
            if key in self._store:
                del self._store[key]
            self._store[key] = _Entry(
                value=value, expires_at=time.monotonic() + ttl
            )
            while len(self._store) > self.max_entries:
                old_key, _ = self._store.popitem(last=False)
                self._stat(old_key).evictions += 1

    def invalidate_prefix(self, prefix: str) -> int:
        """Delete every key starting with ``prefix``. Returns the count removed."""
        with self._lock:
            doomed = [k for k in self._store if k.startswith(prefix)]
            for k in doomed:
                del self._store[k]
            if doomed:
                self._stat(doomed[0]).invalidations += len(doomed)
            return len(doomed)

    def clear(self) -> int:
        """Delete everything. Returns the count removed."""
        with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def stats(self) -> Dict[str, Any]:
        """Snapshot of per-namespace counters plus process-wide size."""
        with self._lock:
            self._purge_expired()
            return {
                "namespaces": {
                    ns: s.as_dict() for ns, s in sorted(self._stats.items())
                },
                "entries": len(self._store),
                "max_entries": self.max_entries,
                "default_ttl_seconds": self.default_ttl,
            }


# Process-wide singleton. Workers each get their own (see module docstring).
cache = TTLCache()


def configure(max_entries: int, default_ttl: float) -> None:
    """Apply settings at startup (tests may also call this)."""
    cache.max_entries = max_entries
    cache.default_ttl = default_ttl


def cache_get(key: str) -> Any:
    return cache.get(key)


def cache_set(key: str, value: Any, ttl: Optional[float] = None) -> None:
    cache.set(key, value, ttl=ttl)


def cache_invalidate_prefix(prefix: str) -> int:
    return cache.invalidate_prefix(prefix)


def cached(
    key_fn: Callable[..., str],
    ttl: Optional[float] = None,
    *,
    enabled_fn: Optional[Callable[[], bool]] = None,
):
    """Decorator for pure, sync, idempotent functions.

    ``key_fn`` receives the same args and must return the cache key.
    The wrapped function gains a ``cache_key`` attribute builder and a
    ``bust(*args)`` helper that invalidates the exact key.
    """

    def deco(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if enabled_fn is not None and not enabled_fn():
                return fn(*args, **kwargs)
            try:
                key = key_fn(*args, **kwargs)
            except Exception:
                return fn(*args, **kwargs)
            hit = cache.get(key)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            cache.set(key, value, ttl=ttl)
            return value

        def bust(*args, **kwargs) -> None:
            try:
                cache.invalidate_prefix(key_fn(*args, **kwargs))
            except Exception:
                pass

        wrapper.bust = bust  # type: ignore[attr-defined]
        wrapper.cache_key = key_fn  # type: ignore[attr-defined]
        return wrapper

    return deco


#: Marker mixed into cached API payloads so the UI can show
#: "served from cache" honestly instead of implying a fresh compute.
CACHED_MARKER = "served_from_cache"
