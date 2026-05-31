"""
Guest parser – maps GuestCollector raw output into the normalized assessment schema.

Raw shape (from collector/guests.py):
{
  "guests": [ <normalized guest dict>, ... ],
  "inventory_path": "/path/to/inventory"
}

The guests list is already normalized by guest_inventory.normalize_guest().
This parser adds the state_sources.configured metadata and merges the guest
list into the top-level assessment.
"""

from __future__ import annotations

from engine.parser import register_parser


@register_parser("guests")
def parse_guests(raw: dict) -> dict:
    if "error" in raw:
        return {}

    guests = raw.get("guests") or []
    inventory_path = raw.get("inventory_path")

    fragment: dict = {}

    if guests:
        fragment["guests"] = guests

    # Record configured-state metadata (path only, never credentials)
    fragment["state_sources"] = {
        "configured": {
            "tool": "ansible",
            "inventory_path": inventory_path,
            "collected": bool(guests),
        },
        "observed": {
            "tool": "broodforge",
            "collected": True,
        },
        "declared": {
            "tool": None,
            "state_path": None,
            "collected": False,
        },
    }

    return fragment
