"""Runtime shim making `vinted-api-wrapper` tolerant of Vinted API schema drift.

The pinned wrapper (0.3.9 — the latest release on PyPI) declares its response
dataclasses with every field *required*: e.g. `Item.icon_badges: List[any]` in
`vinted/models/items.py` has no default. Vinted's live `/catalog/items` API has
since stopped returning some of those keys (observed in production logs:
`icon_badges`), so `dacite.from_dict` raises `MissingValueError` on every
*non-empty* search response. The wrapper swallows that exception and returns a
bare `{"error": ...}` dict instead of a `SearchResponse`; our caller then reads
`.items` off it — which resolves to the `dict.items` *method* — and blows up
with `'builtin_function_or_method' object is not subscriptable`. Net effect:
Vinted yields zero listings precisely whenever it actually has results (an empty
result set has no `Item`s to construct, so it parses fine — which is why only
some queries failed).

There is no fixed upstream release to bump to, so we relax the wrapper's
response dataclasses in place at import time: every field that lacks a default
gets a `None` default, so `dacite.from_dict` fills a missing key with `None`
instead of raising. Keys that *are* present are parsed exactly as before (dacite
does not type-check filled-in defaults, only values drawn from the payload). The
relaxation is applied to the whole search-response model graph, not just
`icon_badges`, so a future single-field drop degrades the same graceful way
rather than re-breaking here and needing another point patch.

Imported purely for its side effect by `backend/tools/product_finder.py`, before
any `Vinted().search()` call. `apply()` is idempotent.
"""

import dataclasses
import importlib
import logging

logger = logging.getLogger(__name__)

# Ordered base-first so a base class is relaxed (and thus carries `None`
# defaults) before any subclass that inherits its fields is re-processed.
_MODEL_MODULES = (
    "vinted.models.base",
    "vinted.models.money",
    "vinted.models.photos",
    "vinted.models.users",
    "vinted.models.items",
    "vinted.models.search",
)

_applied = False


def _relax_dataclass(cls: type) -> None:
    """Give every currently-required field on `cls` a `None` default, then
    regenerate its `__init__`. Because *all* fields end up with a default
    afterwards, dataclasses' "non-default argument follows default argument"
    ordering rule is never tripped."""
    if not dataclasses.is_dataclass(cls):
        return

    changed = False
    for field in dataclasses.fields(cls):
        if (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        ):
            # Setting a class-level attribute with the field's name is how you
            # declare a dataclass default; re-running @dataclass below picks it up.
            setattr(cls, field.name, None)
            changed = True

    if changed:
        dataclasses.dataclass(cls)  # regenerate __init__/fields with new defaults


def apply() -> None:
    """Relax every response dataclass in the wrapper's model modules. Idempotent:
    once all fields have defaults, subsequent calls find nothing to change."""
    global _applied
    if _applied:
        return

    for module_name in _MODEL_MODULES:
        module = importlib.import_module(module_name)
        for obj in vars(module).values():
            if isinstance(obj, type) and dataclasses.is_dataclass(obj):
                _relax_dataclass(obj)

    _applied = True
    logger.debug("Applied vinted-api-wrapper schema-drift relaxation shim")
