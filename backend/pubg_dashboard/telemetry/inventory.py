"""Per-player inventory state machine.

Ten rules, every one of them measured against the archived corpus rather than
taken from documentation, and every one of them a class of silent corruption
if omitted. The measurements quoted below are from 15 matches of the current
65-match archive.

1.  **Quantity comes only from `LogItemPickup`.** Every
    `LogItemPickupFromLootBox` / `...FromCarepackage` event is *also* emitted
    as a plain `LogItemPickup` — 7,219 of 7,219 had a pair, 0 unpaired. But
    only **82.0% share the exact `_D`**; the other **18.0% land within 50 ms**.
    De-duplicating on timestamp equality therefore double-counts 18% of
    crate loot. The specialised events are used for **provenance only**.

2.  Exception: `LogItemPickupFromVehicleTrunk` is applied only when no plain
    pickup for the same `(account, itemId)` falls within 50 ms — measured
    **7.8%** of trunk pickups have no pair and would otherwise be lost.

3.  **`LogItemEquip` usually precedes `LogItemPickup`,** so equipping must be
    able to create an item nobody has seen picked up. Same for `LogItemAttach`
    on an attachment not yet in the inventory.

4.  **`LogItemDrop` never fires on death.** Instead the victim emits a
    `LogItemDetach` burst at +0 s (measured: 5,161 events) and a
    `LogItemUnequip` burst at **exactly +60 s** (measured: 7,409 events, with
    66 more at +61 s). Both are engine bookkeeping. Applied naively, every dead
    player's weapons lose their attachments immediately and their whole kit
    evaporates one minute later. **All item events are suppressed after an
    account's final death** — final, because a player can die twice.

5.  **Attach/detach payloads are authoritative pre-state.** The new attachment
    list is `parentItem.attachedItems` ± `childItem.itemId`, not a mutation of
    our own accumulator. Recomputing from the payload self-heals drift.

6.  **`LogItemUse.stackCount` is the pre-deduction count**, so a use is
    `set(item, stackCount)`, never `-= 1`. A cancelled use re-emits the event
    without consuming anything.

7.  **Ammunition:** `LogItemUse` with `category == 'Ammunition'` is the
    *reload*, and its `stackCount` is the exact reserve at that instant. There
    is no per-shot consumption event, so magazine contents are not derivable.

8.  **`LogHeal.item` is uninitialised memory** — measured **90.0%** garbage
    (blank `itemId`, or `stackCount` in the hundreds of millions). Never read
    it; correlate with the preceding `LogItemUse` instead.

9.  **Items have no instance id.** The inventory is a multiset keyed on
    `(itemId, sorted(attachedItems))` — two identical AKs are distinguishable
    only by their attachments.

10. **Casing is not stable across patches.** Backpacks are `'backpack'`
    (all lowercase) on the current patch, `'BackPack'` on the patch BUILD-SPEC
    was written against, and `'Backpack'` in PUBG's own enum file. Three
    spellings, so every comparison here normalises.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry.reader import norm, ts_ms

__all__ = ["SLOT_NAMES", "InventoryDelta", "InventoryTracker"]

# --- slots -----------------------------------------------------------------
SLOT_PRIMARY1: Final = 0
SLOT_PRIMARY2: Final = 1
SLOT_SIDEARM: Final = 2
SLOT_MELEE: Final = 3
SLOT_THROWABLE: Final = 4
SLOT_HELMET: Final = 5
SLOT_VEST: Final = 6
SLOT_BACKPACK: Final = 7
SLOT_LOOSE: Final = 0xFF

SLOT_NAMES: Final[tuple[str, ...]] = (
    "primary1", "primary2", "sidearm", "melee",
    "throwable", "helmet", "vest", "backpack",
)

# --- ops (BUILD-SPEC 4.5) --------------------------------------------------
OP_ADD_LOOSE: Final = 0
OP_REMOVE_LOOSE: Final = 1
OP_SET_LOOSE: Final = 2
OP_EQUIP: Final = 3
OP_UNEQUIP: Final = 4
OP_ATTACH: Final = 5
OP_DETACH: Final = 6
OP_CLEAR: Final = 7
OP_ARMOR_DESTROY: Final = 8
OP_PROVENANCE: Final = 9

#: Window for pairing a specialised pickup with its plain `LogItemPickup`.
#: Exact `_D` equality misses 18% of pairs.
PAIR_WINDOW_MS: Final = 50

#: Normalised `subCategory` -> slot. Backpack appears here once because every
#: lookup lowercases; the three historical spellings collapse to one key.
_SUBCATEGORY_SLOT: Final[dict[str, int]] = {
    "handgun": SLOT_SIDEARM,
    "melee": SLOT_MELEE,
    "throwable": SLOT_THROWABLE,
    "headgear": SLOT_HELMET,
    "vest": SLOT_VEST,
    "backpack": SLOT_BACKPACK,
}

#: `(itemId, sorted attachments)` — the only workable identity for an item.
ItemKey = tuple[str, tuple[str, ...]]


@dataclass(slots=True)
class InventoryDelta:
    t_ms: int
    account_id: str
    op: int
    item: str = ""
    other: str = ""
    quantity: int = 0
    slot: int = SLOT_LOOSE


@dataclass(slots=True)
class PlayerInventory:
    slots: dict[int, ItemKey | None] = field(default_factory=dict)
    loose: Counter[ItemKey] = field(default_factory=Counter)
    frozen: bool = False


def _key(item: Mapping[str, Any] | None) -> ItemKey:
    item = item or {}
    attachments = tuple(sorted(str(a) for a in (item.get("attachedItems") or [])))
    return (str(item.get("itemId") or ""), attachments)


def _slot_for(item: Mapping[str, Any] | None) -> int | None:
    """Which slot an equip targets. `None` means "not a slotted item"."""
    item = item or {}
    sub = norm(str(item.get("subCategory") or ""))
    if sub in _SUBCATEGORY_SLOT:
        return _SUBCATEGORY_SLOT[sub]
    # `Main` is a primary weapon and there are two primary slots; the event
    # carries no slot index, so the first free one wins.
    if sub == "main":
        return SLOT_PRIMARY1
    return None


class InventoryTracker:
    """Builds the delta track and keyframes for one match.

    Two passes, because two of the rules need lookahead:
    `prescan()` indexes plain pickups and final deaths, `feed()` runs the
    state machine.
    """

    __slots__ = (
        "_deaths",
        "_keyframe_ms",
        "_next_keyframe",
        "_pickups",
        "_t0_ms",
        "deltas",
        "keyframes",
        "suppressed_after_death",
    )

    def __init__(self, t0_ms: int, keyframe_ms: int = 60_000) -> None:
        self._t0_ms = t0_ms
        self._keyframe_ms = keyframe_ms
        self._pickups: dict[tuple[str, str], list[int]] = {}
        self._deaths: dict[str, int] = {}
        self.deltas: list[InventoryDelta] = []
        self.keyframes: list[tuple[int, dict[str, PlayerInventory]]] = []
        self._next_keyframe = 0
        #: Events dropped by rule 4. Counted so the death-burst suppression is
        #: measurable rather than invisible.
        self.suppressed_after_death = 0

    # -- pass 0 -------------------------------------------------------------
    def prescan(self, event: Mapping[str, Any]) -> None:
        kind = norm(event.get("_T", ""))
        if kind == norm(E.ITEM_PICKUP):
            account = str((event.get("character") or {}).get("accountId") or "")
            item_id = str((event.get("item") or {}).get("itemId") or "")
            if account and item_id:
                self._pickups.setdefault((account, item_id), []).append(ts_ms(event.get("_D")))
        elif kind == norm(E.PLAYER_KILL_V2) or kind == norm(E.PLAYER_KILL_V1):
            account = str((event.get("victim") or {}).get("accountId") or "")
            if account:
                # max(), not setdefault: the *final* death is what freezes the
                # inventory. A player can die twice, and 7 in the corpus died
                # three times.
                t = ts_ms(event.get("_D"))
                self._deaths[account] = max(self._deaths.get(account, 0), t)

    def _has_plain_pickup(self, account: str, item_id: str, t_ms: int) -> bool:
        return any(
            abs(t - t_ms) <= PAIR_WINDOW_MS
            for t in self._pickups.get((account, item_id), ())
        )

    # -- pass 1 -------------------------------------------------------------
    def feed(self, event: Mapping[str, Any], state: dict[str, PlayerInventory]) -> None:
        kind = norm(event.get("_T", ""))
        account = str((event.get("character") or {}).get("accountId") or "")
        t_ms = ts_ms(event.get("_D"))

        self._maybe_keyframe(t_ms, state)

        if kind == norm(E.PLAYER_KILL_V2) or kind == norm(E.PLAYER_KILL_V1):
            victim = str((event.get("victim") or {}).get("accountId") or "")
            if victim and t_ms >= self._deaths.get(victim, 0):
                self._clear(victim, t_ms, state)
            return

        if not account:
            return

        # Rule 4: everything after the final death is engine bookkeeping.
        if t_ms > self._deaths.get(account, 1 << 62):
            if kind in _ITEM_EVENT_KINDS:
                self.suppressed_after_death += 1
            return

        inv = state.setdefault(account, PlayerInventory())
        if inv.frozen:
            return
        item = event.get("item") or {}

        if kind == norm(E.ITEM_PICKUP):
            self._add_loose(account, t_ms, item, inv)

        elif kind in (
            norm(E.ITEM_PICKUP_FROM_LOOTBOX),
            norm(E.ITEM_PICKUP_FROM_CAREPACKAGE),
        ):
            # Rule 1: provenance only. The quantity already arrived (or is
            # about to) as a plain LogItemPickup.
            owner = event.get("ownerCharacter") or event.get("owner") or {}
            self.deltas.append(
                InventoryDelta(
                    t_ms=t_ms,
                    account_id=account,
                    op=OP_PROVENANCE,
                    item=str(item.get("itemId") or ""),
                    other=str(owner.get("accountId") or ""),
                )
            )

        elif kind == norm(E.ITEM_PICKUP_FROM_VEHICLE_TRUNK):
            # Rule 2: only the ~7.8% with no plain pickup within 50 ms.
            if not self._has_plain_pickup(account, str(item.get("itemId") or ""), t_ms):
                self._add_loose(account, t_ms, item, inv)

        elif kind == norm(E.ITEM_DROP):
            self._remove_loose(account, t_ms, item, inv)

        elif kind == norm(E.ITEM_EQUIP):
            self._equip(account, t_ms, item, inv)

        elif kind == norm(E.ITEM_UNEQUIP):
            self._unequip(account, t_ms, item, inv)

        elif kind == norm(E.ITEM_ATTACH):
            self._reattach(account, t_ms, event, inv, attach=True)

        elif kind == norm(E.ITEM_DETACH):
            self._reattach(account, t_ms, event, inv, attach=False)

        elif kind == norm(E.ITEM_USE):
            self._use(account, t_ms, item, inv)

        elif kind == norm(E.ARMOR_DESTROY):
            self._armor_destroy(account, t_ms, event.get("item") or {}, inv)

    # -- operations ---------------------------------------------------------
    def _add_loose(
        self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory
    ) -> None:
        key = _key(item)
        if not key[0]:
            return
        qty = int(item.get("stackCount") or 1)
        inv.loose[key] += qty
        self.deltas.append(
            InventoryDelta(account_id=account, t_ms=t_ms, op=OP_ADD_LOOSE,
                           item=key[0], quantity=qty)
        )

    def _remove_loose(
        self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory
    ) -> None:
        key = _key(item)
        if not key[0]:
            return
        qty = int(item.get("stackCount") or 1)
        inv.loose[key] -= qty
        if inv.loose[key] <= 0:
            del inv.loose[key]
        self.deltas.append(
            InventoryDelta(account_id=account, t_ms=t_ms, op=OP_REMOVE_LOOSE,
                           item=key[0], quantity=qty)
        )

    def _use(self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory) -> None:
        """Rule 6: `stackCount` is the count *before* this use is applied.

        `set`, never decrement — a cancelled use re-emits the event without
        consuming anything, and decrementing would drain the stack to nothing.
        """
        key = _key(item)
        if not key[0]:
            return
        # `stackCount: 0` is a real value on genuine items, so it must set the
        # count rather than be treated as "missing" and deleted.
        count = item.get("stackCount")
        qty = 0 if count is None else int(count)
        inv.loose[key] = qty
        self.deltas.append(
            InventoryDelta(account_id=account, t_ms=t_ms, op=OP_SET_LOOSE,
                           item=key[0], quantity=qty)
        )

    def _equip(
        self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory
    ) -> None:
        key = _key(item)
        if not key[0]:
            return
        slot = _slot_for(item)
        if slot is None:
            return
        # Two primary slots, and the event does not say which.
        if slot == SLOT_PRIMARY1 and inv.slots.get(SLOT_PRIMARY1) is not None:
            slot = SLOT_PRIMARY2
        # Rule 3: equip routinely precedes pickup, so the item may be unknown.
        # Consume from loose if we have it, otherwise create it implicitly.
        if inv.loose.get(key):
            inv.loose[key] -= 1
            if inv.loose[key] <= 0:
                del inv.loose[key]
        inv.slots[slot] = key
        self.deltas.append(
            InventoryDelta(account_id=account, t_ms=t_ms, op=OP_EQUIP, item=key[0], slot=slot)
        )

    def _unequip(
        self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory
    ) -> None:
        key = _key(item)
        if not key[0]:
            return
        slot = next((s for s, held in inv.slots.items() if held == key), _slot_for(item))
        if slot is None:
            return
        inv.slots[slot] = None
        inv.loose[key] += 1
        self.deltas.append(
            InventoryDelta(account_id=account, t_ms=t_ms, op=OP_UNEQUIP, item=key[0], slot=slot)
        )

    def _reattach(
        self,
        account: str,
        t_ms: int,
        event: Mapping[str, Any],
        inv: PlayerInventory,
        *,
        attach: bool,
    ) -> None:
        """Rule 5: rebuild the parent's attachment list from the payload.

        `parentItem.attachedItems` is the state *before* this event, so the new
        identity is that list plus (or minus) the child. Recomputing rather
        than mutating means a missed earlier event self-heals here.
        """
        parent = event.get("parentItem") or {}
        child = event.get("childItem") or {}
        parent_id = str(parent.get("itemId") or "")
        child_id = str(child.get("itemId") or "")
        if not parent_id or not child_id:
            return

        before = tuple(sorted(str(a) for a in (parent.get("attachedItems") or [])))
        if attach:
            after = tuple(sorted([*before, child_id]))
        else:
            remaining = list(before)
            if child_id in remaining:
                remaining.remove(child_id)
            after = tuple(sorted(remaining))

        old_key, new_key = (parent_id, before), (parent_id, after)
        for slot, held in inv.slots.items():
            if held == old_key:
                inv.slots[slot] = new_key
                break
        else:
            if inv.loose.get(old_key):
                inv.loose[old_key] -= 1
                if inv.loose[old_key] <= 0:
                    del inv.loose[old_key]
            inv.loose[new_key] += 1

        self.deltas.append(
            InventoryDelta(
                account_id=account,
                t_ms=t_ms,
                op=OP_ATTACH if attach else OP_DETACH,
                item=parent_id,
                other=child_id,
            )
        )

    def _armor_destroy(
        self, account: str, t_ms: int, item: Mapping[str, Any], inv: PlayerInventory
    ) -> None:
        key = _key(item)
        slot = _slot_for(item)
        if slot is None:
            return
        inv.slots[slot] = None
        self.deltas.append(
            InventoryDelta(
                account_id=account, t_ms=t_ms, op=OP_ARMOR_DESTROY, item=key[0], slot=slot
            )
        )

    def _clear(self, account: str, t_ms: int, state: dict[str, PlayerInventory]) -> None:
        inv = state.setdefault(account, PlayerInventory())
        # A keyframe at the moment of death, so "what were they holding when
        # they died" and the death-crate view are exact rather than rebuilt.
        self.keyframes.append((t_ms, _snapshot(state)))
        inv.slots.clear()
        inv.loose.clear()
        inv.frozen = True
        self.deltas.append(InventoryDelta(account_id=account, t_ms=t_ms, op=OP_CLEAR))

    # -- keyframes ----------------------------------------------------------
    def _maybe_keyframe(self, t_ms: int, state: dict[str, PlayerInventory]) -> None:
        """Bound the cost of a backwards seek.

        Rewind to the nearest keyframe <= t and apply forward deltas: worst
        case a few hundred records. Rebuilding from t=0 is ~9k records and
        visibly janky when scrubbing.
        """
        rel = t_ms - self._t0_ms
        if rel < self._next_keyframe:
            return
        while self._next_keyframe <= rel:
            self._next_keyframe += self._keyframe_ms
        self.keyframes.append((t_ms, _snapshot(state)))


_ITEM_EVENT_KINDS: Final[frozenset[str]] = frozenset(
    norm(n)
    for n in (
        E.ITEM_PICKUP, E.ITEM_PICKUP_FROM_LOOTBOX, E.ITEM_PICKUP_FROM_CAREPACKAGE,
        E.ITEM_PICKUP_FROM_VEHICLE_TRUNK, E.ITEM_PUT_TO_VEHICLE_TRUNK, E.ITEM_DROP,
        E.ITEM_EQUIP, E.ITEM_UNEQUIP, E.ITEM_ATTACH, E.ITEM_DETACH, E.ITEM_USE,
        E.ARMOR_DESTROY,
    )
)


def _snapshot(state: Mapping[str, PlayerInventory]) -> dict[str, PlayerInventory]:
    return {
        account: PlayerInventory(
            slots=dict(inv.slots), loose=Counter(inv.loose), frozen=inv.frozen
        )
        for account, inv in state.items()
    }
