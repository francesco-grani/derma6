"""Shared stage-event callback type (Requirement 7).

Extracted into its own module for the same reason `domain_search.py` was
extracted in product-source-agent: `product_source_discovery.py`,
`relevance_filter.py`, and `product_finder.py` all need to accept an
`on_stage` callback parameter, and `product_finder.py` already imports from
both of the other two — defining the type in either of them would work for
one import direction but not the other, and defining it in `product_finder.py`
would force a circular import back into it. A separate module with no
dependency on any of the three callers avoids that entirely, the same
resolution `domain_search.py`'s docstring already documents for an identical
shape of problem.
"""

from typing import Callable

# (stage_id, human_readable_message) -> None. Deliberately a plain
# synchronous callable, not a coroutine: every call site that invokes it
# (discovery, per-domain queries running concurrently under asyncio.gather,
# relevance filtering, enrichment) does so as one cheap, non-blocking
# statement — see product_finder.py's QueuedStageEmitter for why this must
# stay synchronous (asyncio.Queue.put_nowait, not put) for concurrency
# (Req 7.4, Non-Functional Consideration 2) to be preserved.
StageEmitter = Callable[[str, str], None]
