"""
Serializer Protocol and the JSON default.

The `Serializer` Protocol formalizes how Soniq turns Python values into
something the backend stores, and back. The shipped default is
`JSONSerializer`, which uses `json.dumps(..., default=str)` on encode and
`json.loads` on decode - matching the JSONB codec registered on the
asyncpg pool, the SQLite TEXT-as-JSON column, and the in-memory dict
backend.

Custom serializers are advisory at present: backends are JSON-shaped, and
something like a pickle or msgpack codec would need a backend that stores
bytes (a separate body column) rather than JSONB. We ship the Protocol so
applications can centralize encode/decode logic (e.g., to stamp a schema
version on every payload, or to redact sensitive fields), but if you
swap to a non-JSON wire format you also need to write a serializer-aware
backend.
"""

import json
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Serializer(Protocol):
    """Encode/decode job arguments and results."""

    def dumps(self, value: Any) -> str:
        """Serialize a Python value to a string the backend can store."""
        ...

    def loads(self, raw: Any) -> Any:
        """Deserialize a stored value back to Python.

        Backends pass either the raw stored object (e.g. a dict that the
        Postgres JSONB codec already decoded) or a string. Implementations
        should accept both forms idempotently.
        """
        ...


class JSONSerializer:
    """The default. Idempotent on dicts; tolerant of `default=str`-eligible
    values like `datetime`, `UUID`, `Decimal`."""

    def dumps(self, value: Any) -> str:
        return json.dumps(value, default=str)

    def loads(self, raw: Any) -> Any:
        if isinstance(raw, (dict, list)) or raw is None:
            return raw
        return json.loads(raw)


DEFAULT_SERIALIZER: Serializer = JSONSerializer()
