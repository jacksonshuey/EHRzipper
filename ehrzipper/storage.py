"""
Storage Protocol — re-exported from zipper.

EHRzipper uses zipper's engine, which defines the persistence contract. The
SQLite and Snowflake implementations in this package satisfy that same Protocol,
so there is no separate EHRzipper contract to maintain. Importing from here
(``from ehrzipper.storage import Storage``) keeps existing call sites stable.
"""

from __future__ import annotations

from zipper import Storage

__all__ = ["Storage"]
