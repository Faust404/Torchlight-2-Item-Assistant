"""How a pile of fish becomes the stacks the game will take.

The game holds five fish in a slot and no more, and the tool holds a pile: a
3-stack and a 1-stack of the same fish are one card reading ``×4``, and a
20-fish stack the player hoovered up from a modded game is twenty fish however
it was written.  Putting fish back means *dividing* that pile into shares the
game will draw -- and the one rule that keeps it honest is that a share may
re-count a stack **down, never up**: the tool gives away fish it holds, and a
"stack of five" is a slot of fish taken out of the pile.  Nothing here ever
conjures a fish.

That rule is why this is arithmetic rather than bookkeeping.  A share is a
size, where it came from, and whether the source's bytes can go back exactly as
they are; what happens to the registry because of it -- a re-count is inside
the item's fingerprint, so a split stack is a new row -- is
:mod:`tl2stash.service`'s end of the job.

Three asks, one per button on a pile's card:

``take=None``
    **Transfer all.**  Every held stack, whole where it fits in a slot and cut
    into ``limit``-sized shares where it does not: 20 becomes 5, 5, 5, 5 and 12
    becomes 5, 5, 2.
``one_stack=True``
    **Transfer a Stack.**  Exactly one game slot's worth -- the largest single
    stack the tool holds, whole if it fits and one ``limit``-sized share split
    off it if it does not.  A pile of ``{3, 1}`` gives 3, not 4: one press,
    one slot.
``take=n``
    **Transfer 1**, and only that from the window; ``n`` is general because the
    arithmetic does not care.  A whole ``n``-stack if one is held, and
    otherwise ``n`` fish split off the smallest stack that can spare them --
    1 out of ``{5}`` leaves 4, and 1 out of ``{5, 1}`` takes the 1-stack whole
    and leaves the 5 alone.

What the caller gets back is the whole plan, in the order it should be written:
whole shares first, largest first, because a stack that exactly fills a slot is
a slot freed rather than a slot shrunk; then the splits, smallest stack first,
because that is the stack whose count it costs least to change.  The remainder
a split leaves behind is not a field on anything here: it is what the source
still holds once its shares are subtracted, and :mod:`tl2stash.service` works
it out that way.

Pure, like everything beside it that is not the window: no registry, no Qt, and
no bytes -- the sizes are decided here and the patching is
:meth:`tl2stash.item.Item.requantified`'s.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Share", "shares"]


@dataclass(frozen=True)
class Share:
    """One stack's worth of a pile, and where in the pile it comes from.

    ``source`` is the fingerprint of the held stack rather than the stack
    itself: this module is arithmetic, and the caller is the one holding the
    bytes.  ``whole`` says the stack goes back exactly as it is held -- no
    re-count, and so no new identity -- which is what makes an untouched stack
    the cheap case rather than a special one.
    """

    source: str
    size: int
    whole: bool


def shares(
    held: list[tuple[str, int]],
    *,
    take: int | None = None,
    one_stack: bool = False,
    limit: int,
) -> list[Share]:
    """Divide ``held`` into the game's stacks, for one of the three asks.

    ``held`` is ``(fingerprint, quantity)`` per stack the tool holds, and
    ``limit`` is the game's own cap -- :func:`tl2stash.taxonomy.stack_limit_for`,
    passed in rather than looked up so this stays a function of its arguments.

    A stack of no fish is not a stack and is ignored.  Asking for both
    ``take`` and ``one_stack``, for a ``take`` below one, or for a ``limit``
    that fits nothing is a caller's mistake rather than a player's, and raises:
    a plan that quietly gave away nothing would look exactly like a write that
    failed.
    """
    if limit < 1:
        raise ValueError(f"a stack limit of {limit} fits nothing")
    if one_stack and take is not None:
        raise ValueError("ask for one stack or a count, never both")
    if take is not None and take < 1:
        raise ValueError(f"taking {take} fish is not an ask")

    held = [(source, quantity) for source, quantity in held if quantity > 0]
    if not held:
        return []

    if one_stack:
        source, quantity = max(held, key=lambda stack: stack[1])
        size = min(limit, quantity)
        return [Share(source, size, whole=size == quantity)]

    if take is None:
        out: list[Share] = []
        for source, quantity in held:
            out.extend(_wholly(source, quantity, limit))
        return out

    return _counted(held, min(take, sum(quantity for _, quantity in held)), limit)


def _wholly(source: str, quantity: int, limit: int) -> list[Share]:
    """One held stack, everything of it, in slot-sized shares."""
    if quantity <= limit:
        return [Share(source, quantity, whole=True)]
    out = [Share(source, limit, whole=False)] * (quantity // limit)
    rest = quantity % limit
    if rest:
        out.append(Share(source, rest, whole=False))
    return out


def _counted(
    held: list[tuple[str, int]], wanted: int, limit: int
) -> list[Share]:
    """Exactly ``wanted`` fish out of the pile, in slot-sized shares.

    Whole stacks first, largest first: a stack that fits in one slot and fits
    inside what is being asked for goes back untouched, which is both the least
    work and the only share that leaves the stack's identity alone.  Then what
    is left of the ask comes off the smallest stack with fish in it, so a split
    shrinks the stack whose count costs least to change and the pile's big
    stacks stay whole.
    """
    out: list[Share] = []
    remaining = wanted
    pool = list(held)

    for index, (source, quantity) in sorted(
        enumerate(pool), key=lambda pair: pair[1][1], reverse=True
    ):
        if remaining <= 0:
            break
        if quantity <= min(remaining, limit):
            out.append(Share(source, quantity, whole=True))
            remaining -= quantity
            pool[index] = (source, 0)

    while remaining > 0:
        live = [(index, stack) for index, stack in enumerate(pool) if stack[1] > 0]
        if not live:
            # Only reachable if ``wanted`` exceeded the pile, which ``shares``
            # has already capped it against.
            break
        index, (source, quantity) = min(live, key=lambda pair: pair[1][1])
        chunk = min(remaining, limit, quantity)
        out.append(Share(source, chunk, whole=False))
        remaining -= chunk
        pool[index] = (source, quantity - chunk)

    return out
