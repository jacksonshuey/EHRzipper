"""Snowflake connection helper with key-pair auth and clock-skew tolerance.

Key-pair auth signs a short-lived (60s) JWT whose ``iat``/``exp`` come from the
*local* clock. If the local machine runs ahead of Snowflake's clock, the token
looks "issued in the future" and the server rejects it with
``JWT token is invalid``. We can't assume the right to change the host clock, so
instead we measure the offset against Snowflake's own HTTP ``Date`` header and
backdate the JWT issue time by patching the clock the key-pair auth module reads.

The patch is process-local and touches only the ``datetime`` name inside
``snowflake.connector.auth.keypair`` (the sole place the JWT timestamp is built).
"""

from __future__ import annotations

import datetime as _dt
import email.utils
import os
import ssl
from http.client import HTTPSConnection
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from snowflake.connector import SnowflakeConnection

# Only backdate if the measured skew exceeds this many seconds.
_SKEW_THRESHOLD_S = 5.0
# Extra margin subtracted on top of the measured skew.
_SKEW_BUFFER_S = 5.0


class _SkewedClock:
    """Stand-in for ``datetime`` exposing ``now()`` shifted into the past."""

    def __init__(self, delta_seconds: float) -> None:
        self._delta = _dt.timedelta(seconds=delta_seconds)

    def now(self, tz: _dt.tzinfo | None = None) -> _dt.datetime:
        return _dt.datetime.now(tz) - self._delta


def server_skew_seconds(host: str) -> float:
    """Return ``local_utc - server_utc`` in seconds (positive => local is ahead)."""
    conn = HTTPSConnection(host, 443, timeout=10, context=ssl.create_default_context())
    try:
        conn.request("HEAD", "/")
        resp = conn.getresponse()
        date_hdr = resp.getheader("Date")
    finally:
        conn.close()
    if not date_hdr:
        return 0.0
    server = email.utils.parsedate_to_datetime(date_hdr).astimezone(_dt.UTC)
    local = _dt.datetime.now(_dt.UTC)
    return (local - server).total_seconds()


def _patch_jwt_clock(backdate_seconds: float) -> None:
    from snowflake.connector.auth import keypair

    keypair.datetime = _SkewedClock(backdate_seconds)


def connect(**overrides: Any) -> SnowflakeConnection:
    """Open a Snowflake connection from environment variables.

    Honors (in priority order) key-pair auth via ``SNOWFLAKE_PRIVATE_KEY_FILE``,
    then password via ``SNOWFLAKE_PASSWORD``. Compensates for local clock skew
    before the key-pair JWT is generated. Extra kwargs override the defaults.
    """
    import snowflake.connector

    account = os.environ["SNOWFLAKE_ACCOUNT"]
    key_file = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")

    if key_file:
        skew = server_skew_seconds(f"{account}.snowflakecomputing.com")
        if skew > _SKEW_THRESHOLD_S:
            _patch_jwt_clock(skew + _SKEW_BUFFER_S)

    kwargs: dict[str, Any] = {
        "account": account,
        "user": os.environ["SNOWFLAKE_USER"],
        # ``?`` positional binds (per-connection, not a global mutation) so
        # INSERT...SELECT templates with PARSE_JSON(?) bind cleanly. Other code
        # paths (e.g. storage_snowflake's %(name)s) keep their own connections.
        "paramstyle": "qmark",
    }
    if key_file:
        kwargs["private_key_file"] = key_file
        key_pwd = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE_PWD")
        if key_pwd:
            kwargs["private_key_file_pwd"] = key_pwd
    else:
        kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]

    role = os.environ.get("SNOWFLAKE_ROLE")
    if role:
        kwargs["role"] = role
    warehouse = os.environ.get("SNOWFLAKE_WAREHOUSE")
    if warehouse:
        kwargs["warehouse"] = warehouse
    database = os.environ.get("SNOWFLAKE_DATABASE")
    if database:
        kwargs["database"] = database

    kwargs.update(overrides)
    return snowflake.connector.connect(**kwargs)
