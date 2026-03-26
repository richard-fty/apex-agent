"""Discover and list available skill packs."""

from __future__ import annotations

from skills.base import SkillPack


def discover_skills() -> dict[str, SkillPack]:
    """Scan for available skill packs and return them by name.

    Each skill pack is a subpackage of skills/ with a skill.py module
    that exports a SkillPack subclass.
    """
    available: dict[str, SkillPack] = {}

    # Import known skill packs
    # Add new skill packs here as they are created
    try:
        from skills.stock_strategy.skill import StockStrategySkill
        skill = StockStrategySkill()
        available[skill.name] = skill
    except ImportError:
        pass

    return available
