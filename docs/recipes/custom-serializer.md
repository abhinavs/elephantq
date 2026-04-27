# Recipe: Custom Serializer

Soniq encodes job arguments and return values through a `Serializer` that defaults to JSON. Most users never need to think about it. Two cases where centralizing encode/decode pays off:

- Stamping a schema version on every payload so old workers can refuse incompatible jobs.
- Redacting sensitive fields (PII, tokens) before they hit the database.

## Protocol

```python
# soniq/utils/serialization.py
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Serializer(Protocol):
    def dumps(self, value: Any) -> str: ...
    def loads(self, raw: Any) -> Any: ...
```

`dumps` returns the string the backend stores. `loads` accepts whichever shape the backend hands back: an already-decoded dict (Postgres JSONB codec), a JSON string (SQLite `TEXT`), or `None`. Implementations should be idempotent on dicts.

## Example: schema-versioned payloads

```python
import json

from soniq import Soniq
from soniq.utils.serialization import Serializer


class VersionedJSONSerializer:
    """Wrap every payload as `{"v": SCHEMA_VERSION, "data": <original>}`.

    Workers that load a payload with an unrecognized `v` raise so the job
    dead-letters with a clear error rather than silently calling a handler
    against incompatible data.
    """

    SCHEMA_VERSION = 2
    SUPPORTED = {1, 2}

    def dumps(self, value):
        return json.dumps(
            {"v": self.SCHEMA_VERSION, "data": value},
            default=str,
        )

    def loads(self, raw):
        decoded = raw if isinstance(raw, dict) else json.loads(raw)
        if not isinstance(decoded, dict) or "v" not in decoded:
            raise ValueError(
                f"Payload missing schema version: {decoded!r}"
            )
        version = decoded["v"]
        if version not in self.SUPPORTED:
            raise ValueError(
                f"Unsupported payload version {version}; "
                f"supported versions: {sorted(self.SUPPORTED)}"
            )
        return decoded["data"]


app = Soniq(
    database_url="postgresql://localhost/myapp",
    serializer=VersionedJSONSerializer(),
)
```

## Caveat: backends are JSON-shaped

The bundled backends (Postgres JSONB, SQLite `TEXT`, Memory dict) all expect JSON-compatible payloads. A custom `Serializer` that emits, say, msgpack bytes would break the storage layer. If you need a non-JSON wire format, you also need a custom `StorageBackend` that stores `bytea` instead of `JSONB`.

For most use cases - validation, redaction, schema versioning - a JSON-shaped serializer like the example above is enough.

## Combining with `args_model`

`@app.job(args_model=MyPydanticModel)` runs *after* the serializer's `loads`. A `Serializer` that strips a wrapper key before returning to the registry plays cleanly with Pydantic validation.
