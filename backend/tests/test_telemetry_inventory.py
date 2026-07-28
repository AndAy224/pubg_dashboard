"""The inventory state machine's ten rules.

Each rule exists because the obvious implementation is wrong in a way that
still renders. The corpus measurements quoted in the module docstring of
`telemetry/inventory.py` are what justify them; these tests pin the behaviour.
"""

from __future__ import annotations

import pathlib

import pytest

from pubg_dashboard.telemetry import events as E
from pubg_dashboard.telemetry import reader
from pubg_dashboard.telemetry.inventory import (
    OP_ADD_LOOSE,
    OP_ARMOR_DESTROY,
    OP_ARMOR_HIT,
    OP_CLEAR,
    OP_PROVENANCE,
    OP_SET_LOOSE,
    OP_UNEQUIP,
    SLOT_BACKPACK,
    SLOT_HELMET,
    SLOT_PRIMARY1,
    SLOT_PRIMARY2,
    SLOT_VEST,
    InventoryTracker,
    PlayerInventory,
)

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
T0 = reader.ts_ms("2026-07-22T00:00:00.000Z")


def _item(item_id: str, *, qty: int = 1, sub: str = "None", cat: str = "Use",
          attached: list[str] | None = None) -> dict:
    return {
        "itemId": item_id,
        "stackCount": qty,
        "category": cat,
        "subCategory": sub,
        "attachedItems": attached or [],
    }


def _ev(kind: str, t: str, account: str = "a", **kw: object) -> dict:
    return {"_T": kind, "_D": t, "character": {"accountId": account}, **kw}


def _run(events: list[dict]) -> tuple[InventoryTracker, dict[str, PlayerInventory]]:
    inv = InventoryTracker(T0)
    for e in events:
        inv.prescan(e)
    state: dict[str, PlayerInventory] = {}
    for e in events:
        inv.feed(e, state)
    return inv, state


# ---------------------------------------------------------------------------
# rule 1 / 2 — duplicate pickups
# ---------------------------------------------------------------------------


def test_lootbox_pickup_is_provenance_only() -> None:
    """Every crate pickup is *also* a plain LogItemPickup — 7,219/7,219 paired.

    Counting both doubles the quantity. Only 82% share the exact `_D`, so
    de-duplicating on timestamp equality still double-counts the other 18%.
    """
    inv, state = _run(
        [
            _ev("LogItemPickup", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Ammo_762mm_C", qty=30)),
            # 30 ms later, not the same instant — the case exact matching misses.
            _ev("LogItemPickupFromLootBox", "2026-07-22T00:01:00.030Z",
                item=_item("Item_Ammo_762mm_C", qty=30)),
        ]
    )
    assert state["a"].loose[("Item_Ammo_762mm_C", ())] == 30
    assert [d.op for d in inv.deltas] == [OP_ADD_LOOSE, OP_PROVENANCE]


def test_unpaired_trunk_pickup_is_applied() -> None:
    """~7.8% of trunk pickups have no plain pair and would otherwise be lost."""
    _, state = _run(
        [
            _ev("LogItemPickupFromVehicleTrunk", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Heal_FirstAid_C", qty=2)),
        ]
    )
    assert state["a"].loose[("Item_Heal_FirstAid_C", ())] == 2


def test_paired_trunk_pickup_is_not_double_counted() -> None:
    _, state = _run(
        [
            _ev("LogItemPickup", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Heal_FirstAid_C", qty=2)),
            _ev("LogItemPickupFromVehicleTrunk", "2026-07-22T00:01:00.020Z",
                item=_item("Item_Heal_FirstAid_C", qty=2)),
        ]
    )
    assert state["a"].loose[("Item_Heal_FirstAid_C", ())] == 2


# ---------------------------------------------------------------------------
# rule 3 — equip before pickup
# ---------------------------------------------------------------------------


def test_equip_creates_an_item_never_seen_picked_up() -> None:
    """LogItemEquip usually *precedes* LogItemPickup."""
    _, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon")),
        ]
    )
    assert state["a"].slots[SLOT_PRIMARY1] == ("Item_Weapon_AK47_C", ())


def test_second_primary_goes_to_the_other_slot() -> None:
    """The event carries no slot index, and there are two primary slots."""
    _, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon")),
            _ev("LogItemEquip", "2026-07-22T00:01:05.000Z",
                item=_item("Item_Weapon_M24_C", sub="Main", cat="Weapon")),
        ]
    )
    assert state["a"].slots[SLOT_PRIMARY1][0] == "Item_Weapon_AK47_C"
    assert state["a"].slots[SLOT_PRIMARY2][0] == "Item_Weapon_M24_C"


# ---------------------------------------------------------------------------
# rule 4 — the death bursts
# ---------------------------------------------------------------------------


def _kill(victim: str, t: str) -> dict:
    return {
        "_T": "LogPlayerKillV2",
        "_D": t,
        "victim": {"accountId": victim, "teamId": 1, "location": {"x": 0, "y": 0, "z": 0}},
        "killer": None,
        "killerDamageInfo": {},
    }


def test_item_events_after_the_final_death_are_suppressed() -> None:
    """The victim emits a LogItemUnequip burst at *exactly* +60 s.

    Measured: 7,409 such events across 15 matches. Applied, every dead
    player's kit evaporates one minute after they die.
    """
    inv, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Head_F_01_Lv2_C", sub="Headgear", cat="Equipment")),
            _kill("a", "2026-07-22T00:02:00.000Z"),
            # the +60 s engine burst
            _ev("LogItemUnequip", "2026-07-22T00:03:00.000Z",
                item=_item("Item_Head_F_01_Lv2_C", sub="Headgear", cat="Equipment")),
        ]
    )
    assert inv.suppressed_after_death == 1
    assert state["a"].frozen
    assert OP_CLEAR in [d.op for d in inv.deltas]


def test_freezing_on_the_first_death_would_lose_the_second_life() -> None:
    """A player can die twice; 211 accounts in the corpus do, 7 die three times.

    Measured on a real double-death match: freezing on the first death yields
    308 deltas for those accounts, freezing on the last yields 532 — a 42%
    loss of their inventory activity.
    """
    events = [
        _kill("a", "2026-07-22T00:05:00.000Z"),
        # second life
        _ev("LogItemPickup", "2026-07-22T00:10:00.000Z",
            item=_item("Item_Ammo_556mm_C", qty=60)),
        _kill("a", "2026-07-22T00:20:00.000Z"),
    ]
    inv, state = _run(events)
    # The mid-life pickup must survive: the freeze happens at the *last* death.
    assert any(d.op == OP_ADD_LOOSE for d in inv.deltas)
    assert state["a"].frozen


# ---------------------------------------------------------------------------
# rule 5 — attach/detach are authoritative pre-state
# ---------------------------------------------------------------------------


def test_attach_rebuilds_identity_from_the_payload() -> None:
    """Recomputing from `parentItem.attachedItems` self-heals earlier drift."""
    _, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon")),
            _ev(
                "LogItemAttach",
                "2026-07-22T00:01:10.000Z",
                parentItem=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon", attached=[]),
                childItem=_item("Item_Attach_Weapon_Upper_Holosight_C", cat="Attachment"),
            ),
        ]
    )
    assert state["a"].slots[SLOT_PRIMARY1] == (
        "Item_Weapon_AK47_C",
        ("Item_Attach_Weapon_Upper_Holosight_C",),
    )


def test_detach_removes_only_the_named_child() -> None:
    _, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon",
                           attached=["Item_Attach_Weapon_Upper_Holosight_C",
                                     "Item_Attach_Weapon_Lower_Foregrip_C"])),
            _ev(
                "LogItemDetach",
                "2026-07-22T00:01:10.000Z",
                parentItem=_item("Item_Weapon_AK47_C", sub="Main", cat="Weapon",
                                 attached=["Item_Attach_Weapon_Upper_Holosight_C",
                                           "Item_Attach_Weapon_Lower_Foregrip_C"]),
                childItem=_item("Item_Attach_Weapon_Lower_Foregrip_C", cat="Attachment"),
            ),
        ]
    )
    assert state["a"].slots[SLOT_PRIMARY1] == (
        "Item_Weapon_AK47_C",
        ("Item_Attach_Weapon_Upper_Holosight_C",),
    )


# ---------------------------------------------------------------------------
# rule 6 / 9 — LogItemUse sets, never decrements
# ---------------------------------------------------------------------------


def test_use_sets_the_stack_rather_than_decrementing() -> None:
    """`stackCount` is the count *before* the use.

    A cancelled use re-emits the event without consuming anything, so
    decrementing would drain a stack that never changed.
    """
    inv, state = _run(
        [
            _ev("LogItemPickup", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Heal_Bandage_C", qty=5)),
            _ev("LogItemUse", "2026-07-22T00:01:10.000Z",
                item=_item("Item_Heal_Bandage_C", qty=4)),
            # re-emitted (cancelled use): still 4, not 3
            _ev("LogItemUse", "2026-07-22T00:01:11.000Z", item=_item("Item_Heal_Bandage_C", qty=4)),
        ]
    )
    assert state["a"].loose[("Item_Heal_Bandage_C", ())] == 4
    assert [d.op for d in inv.deltas].count(OP_SET_LOOSE) == 2


def test_stack_count_zero_is_a_real_value() -> None:
    """`0` must set the count, not be read as "missing" and dropped."""
    _, state = _run(
        [
            _ev("LogItemPickup", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Ammo_556mm_C", qty=1)),
            _ev("LogItemUse", "2026-07-22T00:01:10.000Z",
                item=_item("Item_Ammo_556mm_C", qty=0)),
        ]
    )
    assert state["a"].loose[("Item_Ammo_556mm_C", ())] == 0


# ---------------------------------------------------------------------------
# rule 10 — casing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["backpack", "BackPack", "Backpack"])
def test_all_three_backpack_spellings_map_to_one_slot(spelling: str) -> None:
    """Three spellings exist across patches.

    `'backpack'` (lowercase) is what the current corpus emits, `'BackPack'` is
    what BUILD-SPEC recorded, and `'Backpack'` is what PUBG's own enum file
    says. Comparing case-sensitively silently drops the backpack.
    """
    _, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z",
                item=_item("Item_Back_C_01_Lv3_C", sub=spelling, cat="Equipment")),
        ]
    )
    assert state["a"].slots[SLOT_BACKPACK][0] == "Item_Back_C_01_Lv3_C"


# ---------------------------------------------------------------------------
# armour — rules 11 and 12
# ---------------------------------------------------------------------------


def _destroy(t: str, item: dict, victim: str = "a") -> dict:
    """A destroy carries `victim`, never `character` — the wire shape that the
    old handler misread (73 events, 0 deltas on a real match)."""
    return {
        "_T": "LogArmorDestroy",
        "_D": t,
        "attacker": {"accountId": "attacker"},
        "victim": {"accountId": victim},
        "item": item,
        "damageReason": "TorsoShot",
        "damageTypeCategory": "Damage_Gun",
    }


def _hit(t: str, *, victim: str = "a", damage: float, reason: str = "TorsoShot",
         category: str = "Damage_Gun") -> dict:
    return {
        "_T": "LogPlayerTakeDamage",
        "_D": t,
        "attacker": {"accountId": "attacker"},
        "victim": {"accountId": victim, "health": 100},
        "damage": damage,
        "damageReason": reason,
        "damageTypeCategory": category,
    }


def test_armor_destroy_is_victim_keyed_and_empties_the_slot() -> None:
    helmet = _item("Item_Head_F_01_Lv2_C", sub="Headgear", cat="Equipment")
    inv, state = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z", item=helmet),
            _destroy("2026-07-22T00:01:30.000Z", helmet),
        ]
    )
    assert state["a"].slots[SLOT_HELMET] is None
    assert OP_ARMOR_DESTROY in [d.op for d in inv.deltas]


def test_destroy_adjacent_engine_unequip_is_suppressed() -> None:
    """The engine unequips the destroyed piece 0-1 ms around the destroy.

    Applied, the destroyed helmet leaks into `loose` as a phantom item — or,
    when the same-millisecond order flips, wipes the slot the destroy op is
    about to report on.
    """
    helmet = _item("Item_Head_F_01_Lv2_C", sub="Headgear", cat="Equipment")
    for unequip_first in (True, False):
        pair = [
            _ev("LogItemUnequip", "2026-07-22T00:01:29.999Z", item=helmet),
            _destroy("2026-07-22T00:01:30.000Z", helmet),
        ]
        inv, state = _run(
            [_ev("LogItemEquip", "2026-07-22T00:01:00.000Z", item=helmet)]
            + (pair if unequip_first else pair[::-1])
        )
        ops = [d.op for d in inv.deltas]
        assert OP_UNEQUIP not in ops
        assert OP_ARMOR_DESTROY in ops
        assert inv.suppressed_destroy_unequips == 1
        assert not state["a"].loose, "destroyed armor leaked into loose"


def test_protected_hits_decrement_the_durability_estimate() -> None:
    """Loss is raw damage — reported health damage un-mitigated — against the
    corpus-fitted max. A Lv2 vest (max 235, mitigation 40%) hit for 60 health
    loses 100 raw: 57% remains."""
    vest = _item("Item_Armor_D_01_Lv2_C", sub="Vest", cat="Equipment")
    inv, _ = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z", item=vest),
            _hit("2026-07-22T00:01:10.000Z", damage=60.0),
        ]
    )
    hits = [d for d in inv.deltas if d.op == OP_ARMOR_HIT]
    assert len(hits) == 1
    assert hits[0].slot == SLOT_VEST
    assert hits[0].quantity == 57


def test_zero_damage_hit_on_a_knocked_victim_is_imputed() -> None:
    """Hits on a DBNO victim report `damage: 0` (285 of 288 zero-damage
    protected gun hits in one match) but still wear the armor down."""
    vest = _item("Item_Armor_D_01_Lv2_C", sub="Vest", cat="Equipment")
    inv, _ = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z", item=vest),
            _hit("2026-07-22T00:01:10.000Z", damage=0.0),
        ]
    )
    hits = [d for d in inv.deltas if d.op == OP_ARMOR_HIT]
    assert len(hits) == 1
    assert hits[0].quantity == 83  # (235 - 40) / 235


def test_unprotected_damage_does_not_touch_armor() -> None:
    """Arm shots bypass armor, and the blue zone destroys no vests."""
    vest = _item("Item_Armor_D_01_Lv2_C", sub="Vest", cat="Equipment")
    inv, _ = _run(
        [
            _ev("LogItemEquip", "2026-07-22T00:01:00.000Z", item=vest),
            _hit("2026-07-22T00:01:10.000Z", damage=30.0, reason="ArmShot"),
            _hit("2026-07-22T00:01:11.000Z", damage=30.0, category="Damage_BlueZone",
                 reason="NonSpecific"),
            _hit("2026-07-22T00:01:12.000Z", damage=30.0, reason="HeadShot"),  # no helmet
        ]
    )
    assert not [d for d in inv.deltas if d.op == OP_ARMOR_HIT]


# ---------------------------------------------------------------------------
# corpus
# ---------------------------------------------------------------------------


def test_corpus_survivors_hold_a_coherent_loadout() -> None:
    """End-state sanity: whoever is left alive should be carrying real gear.

    A state machine that drifts produces empty slots or nonsense keys, and
    neither raises.
    """
    root = DATA / "telemetry"
    files = sorted(root.glob("*.json.gz")) if root.is_dir() else []
    if not files:
        pytest.skip("no archived telemetry")
    biggest = max(files, key=lambda p: p.stat().st_size)
    evs = reader.load(biggest.read_bytes())
    t0 = next(
        (reader.ts_ms(e.get("_D")) for e in evs
         if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)), 0
    )
    inv = InventoryTracker(t0)
    for e in evs:
        inv.prescan(e)
    state: dict[str, PlayerInventory] = {}
    for e in evs:
        inv.feed(e, state)

    survivors = [s for s in state.values() if not s.frozen]
    assert survivors, "expected at least one player alive at the end"
    assert inv.suppressed_after_death > 0, "expected post-death bursts to be suppressed"

    armed = [s for s in survivors if any(v for v in s.slots.values())]
    assert armed, "every survivor ended with empty slots — the machine drifted"
    for s in armed:
        for key in s.slots.values():
            if key is not None:
                assert key[0].startswith("Item_"), f"nonsense item id: {key[0]}"


def test_corpus_armor_destroys_produce_deltas() -> None:
    """Rule 11 against the wire: every match has ~50 LogArmorDestroy events,
    and before the victim-keyed fix exactly zero of them produced a delta —
    a fixture-invented unit test hid that for the feature's whole life."""
    root = DATA / "telemetry"
    files = sorted(root.glob("*.json.gz")) if root.is_dir() else []
    if not files:
        pytest.skip("no archived telemetry")
    biggest = max(files, key=lambda p: p.stat().st_size)
    evs = reader.load(biggest.read_bytes())
    t0 = next(
        (reader.ts_ms(e.get("_D")) for e in evs
         if reader.norm(e.get("_T", "")) == reader.norm(E.MATCH_START)), 0
    )
    inv = InventoryTracker(t0)
    for e in evs:
        inv.prescan(e)
    state: dict[str, PlayerInventory] = {}
    for e in evs:
        inv.feed(e, state)

    wire_destroys = sum(1 for e in evs if reader.norm(e.get("_T", "")) == "logarmordestroy")
    destroy_deltas = [d for d in inv.deltas if d.op == OP_ARMOR_DESTROY]
    assert wire_destroys > 0
    # Destroys of a piece we never saw equipped (pre-equip drift) may drop,
    # but the bulk must survive; zero was the bug.
    assert len(destroy_deltas) >= wire_destroys * 0.8
    assert inv.suppressed_destroy_unequips > 0

    hit_deltas = [d for d in inv.deltas if d.op == OP_ARMOR_HIT]
    assert hit_deltas, "no protected hits in a whole match is implausible"
    assert all(0 <= d.quantity <= 100 for d in hit_deltas)
    assert all(d.slot in (SLOT_HELMET, SLOT_VEST) for d in hit_deltas)
