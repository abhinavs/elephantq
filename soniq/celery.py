"""
Celery compatibility layer for Soniq.

This module exists to make migrating from Celery less painful. It is not
a feature -- it is a bridge. Importing ``Soniq`` from ``soniq.celery``
instead of ``soniq`` is the visible signal that a file is mid-migration.
When the migration is complete, switch the import back::

    # During migration
    from soniq.celery import Soniq

    @app.task()
    async def send_welcome(to: str): ...

    # After migration
    from soniq import Soniq

    @app.job()
    async def send_welcome(to: str): ...

What is aliased
---------------
- ``@app.task`` / ``@app.task(...)`` -- alias for ``@app.job`` / ``@app.job(...)``.

What is intentionally NOT aliased
---------------------------------
- ``.delay(...)`` and ``.apply_async(...)``: these methods would hide the
  ``await`` that Soniq's async-native enqueue requires. Replace those call
  sites with ``await app.enqueue(func, arg=arg)``. The friction is the
  point -- it surfaces exactly what changed.

See ``docs/migration/from-celery.md`` for the full mapping.
"""

from __future__ import annotations

from typing import Any

from .app import Soniq as _BaseSoniq

__all__ = ["Soniq"]


class Soniq(_BaseSoniq):
    """
    Soniq subclass that adds a Celery-flavoured ``@app.task`` decorator alias.

    Behaviour is identical to :class:`soniq.Soniq` in every other respect.
    The class is intentionally located in ``soniq.celery`` so the import
    line itself documents the migration state of any file that uses it.
    """

    def task(self, *args: Any, **kwargs: Any) -> Any:
        """
        Alias for :meth:`Soniq.job`. Exists to keep ``@celery.task`` style
        decorators working during a migration.

        Once the migration is done, switch ``@app.task`` to ``@app.job`` and
        change the import to ``from soniq import Soniq``.
        """
        return self.job(*args, **kwargs)
