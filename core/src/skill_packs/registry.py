"""Discover and list available skill packs."""

from __future__ import annotations

from skill_packs.base import SkillPack


def discover_skills() -> dict[str, SkillPack]:
    """Scan for available skill packs and return them by name.

    Each skill pack is a subpackage of skill_packs/ with a skill.py module
    that exports a SkillPack subclass.
    """
    available: dict[str, SkillPack] = {}

    # Import known skill packs
    # Add new skill packs here as they are created
    try:
        from skill_packs.stock_strategy.skill import StockStrategySkill
        skill = StockStrategySkill()
        available[skill.name] = skill
    except ImportError:
        pass

    try:
        from skill_packs.wealth_guide.skill import WealthGuideSkill
        skill = WealthGuideSkill()
        available[skill.name] = skill
    except ImportError:
        pass

    try:
        from skill_packs.coding.skill import CodingSkill
        skill = CodingSkill()
        available[skill.name] = skill
    except ImportError:
        pass

    return available
