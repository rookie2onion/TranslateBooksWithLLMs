"""Offline reconstruction of a cached MinerU online recognition result.

The cache is the authorized probe output: ``sample-info.json``, ``layout.json``,
one V2 content list and the local image assets. Reconstruction is entirely
offline: it never performs network I/O, never calls a translation LLM and never
mutates the cache.
"""

from .cache import CachedBlock, MineruCache, MineruCacheError, PageInfo, load_cache

__all__ = [
    "CachedBlock",
    "MineruCache",
    "MineruCacheError",
    "PageInfo",
    "load_cache",
]
