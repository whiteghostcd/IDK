"""Core dice and combat resolution functions for v0.1.

These implementations follow the design notes in base_rules.md and focus on
reproducible, inspectable outputs with detailed breakdowns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class DieSpec:
    sides: int
    count: int


@dataclass
class DieRoll:
    sides: int
    value: int
    tags: List[str] = field(default_factory=list)


@dataclass
class RerollRule:
    times: int
    strategy: str
    indexes: Optional[List[int]] = None


@dataclass
class DiceRules:
    mode: str
    top_n: Optional[int] = None
    threshold: Optional[int] = None
    reroll: Optional[RerollRule] = None


@dataclass
class DiceResult:
    rolls: List[DieRoll]
    final: int
    meta: Dict[str, Any]
    breakdown: List[Dict[str, Any]]


@dataclass
class ActorStats:
    accuracy: int
    evade: int
    block: int
    hp: int


@dataclass
class CombatContext:
    enemy_count: int
    difficulty_mod: int = 0
    tags: List[str] = field(default_factory=list)


@dataclass
class WeaponSpec:
    name: str
    hit_tn_base: int
    hit_dice: List[DieSpec]
    weakpoint_threshold: int
    weakpoint_scale: int
    weakpoint_cap: Optional[int] = None
    damage_base: Optional[int] = None
    damage_scale: Optional[float] = None


@dataclass
class TargetSpec:
    evasion_mod: int
    tags: List[str] = field(default_factory=list)


@dataclass
class AttackResult:
    hit: bool
    TN: int
    roll: DiceResult
    score: int
    margin: int
    weakpoint_bonus: int
    breakdown: Dict[str, Any]


@dataclass
class DefenseProfile:
    type: str
    stat_key: str
    tn_base: int
    success_reward: Dict[str, Any]
    fail_model: Dict[str, Any]


@dataclass
class AttackSpec:
    name: str
    pattern: str
    tn_base: int
    dice: List[DieSpec]
    N: Optional[int] = None
    M: Optional[int] = None
    V: Optional[int] = None
    min_damage: Optional[int] = None
    max_damage: Optional[int] = None


@dataclass
class DefenseResult:
    pattern: str
    profile_type: str
    TN_breakdown: List[Dict[str, Any]]
    rolls: List[DiceResult]
    successes: int
    failures: int
    damageTaken: int
    extraActions: int
    breakdown: List[Dict[str, Any]]


def _expand_pool(pool: Iterable[Dict[str, int]]) -> List[DieSpec]:
    return [DieSpec(sides=item["sides"], count=item["count"]) for item in pool]


def _roll_die(sides: int, rng: Any) -> int:
    return rng.randint(1, sides)


def _apply_reroll(
    rolls: List[DieRoll],
    reroll_rule: RerollRule,
    rng: Any,
    breakdown: List[Dict[str, Any]],
) -> None:
    for _ in range(reroll_rule.times):
        if not rolls:
            return
        if reroll_rule.strategy == "lowest":
            target_index = min(range(len(rolls)), key=lambda idx: rolls[idx].value)
        elif reroll_rule.strategy == "specific_indexes":
            if not reroll_rule.indexes:
                return
            target_index = reroll_rule.indexes[0]
            reroll_rule.indexes = reroll_rule.indexes[1:]
            if target_index >= len(rolls):
                return
        else:
            return

        before = rolls[target_index].value
        after = _roll_die(rolls[target_index].sides, rng)
        rolls[target_index].value = after
        rolls[target_index].tags.append("rerolled")
        breakdown.append(
            {
                "step": "reroll",
                "target_index": target_index,
                "before": before,
                "after": after,
            }
        )


def _reduce_rolls(rolls: List[DieRoll], rules: DiceRules, breakdown: List[Dict[str, Any]]) -> int:
    values = [roll.value for roll in rolls]
    if rules.mode == "sum":
        final = sum(values)
    elif rules.mode == "max":
        final = max(values) if values else 0
    elif rules.mode == "top_n_sum":
        top_n = rules.top_n or 0
        final = sum(sorted(values, reverse=True)[:top_n])
    elif rules.mode == "success_count":
        threshold = rules.threshold or 0
        final = sum(1 for value in values if value >= threshold)
    else:
        final = sum(values)

    breakdown.append({"step": "reduce", "mode": rules.mode, "final": final})
    return final


def resolveDice(pool: Iterable[Dict[str, int]], rules: Dict[str, Any], rng: Any) -> DiceResult:
    specs = _expand_pool(pool)
    die_rules = DiceRules(
        mode=rules.get("mode", "sum"),
        top_n=rules.get("top_n"),
        threshold=rules.get("threshold"),
        reroll=RerollRule(**rules["reroll"]) if rules.get("reroll") else None,
    )

    rolls: List[DieRoll] = []
    breakdown: List[Dict[str, Any]] = []

    for spec in specs:
        for _ in range(spec.count):
            rolls.append(DieRoll(sides=spec.sides, value=_roll_die(spec.sides, rng)))

    breakdown.append({"step": "initial_roll", "rolls": [{"sides": r.sides, "value": r.value} for r in rolls]})

    if die_rules.reroll:
        _apply_reroll(rolls, die_rules.reroll, rng, breakdown)

    final = _reduce_rolls(rolls, die_rules, breakdown)

    meta = {
        "mode": die_rules.mode,
        "top_n": die_rules.top_n,
        "threshold": die_rules.threshold,
    }

    return DiceResult(rolls=rolls, final=final, meta=meta, breakdown=breakdown)


def resolveAttack(
    attacker: Dict[str, Any],
    weapon: Dict[str, Any],
    target: Dict[str, Any],
    context: Dict[str, Any],
    rng: Any,
) -> AttackResult:
    enemy_count = context.get("enemy_count", 1)
    difficulty_mod = context.get("difficulty_mod", 0)
    tn_parts = {
        "base": weapon["hit_tn_base"],
        "target_mod": target.get("evasion_mod", 0),
        "enemy_count_mod": max(0, enemy_count - 1),
        "difficulty_mod": difficulty_mod,
    }
    tn = sum(tn_parts.values())

    hit_dice = weapon.get("hit_dice", [{"sides": 6, "count": 1}])
    roll = resolveDice(hit_dice, {"mode": "sum"}, rng)
    score = roll.final + attacker.get("accuracy", 0)
    margin = score - tn
    hit = score >= tn

    weakpoint_threshold = weapon.get("weakpoint_threshold", 0)
    weakpoint_scale = weapon.get("weakpoint_scale", 1)
    weakpoint_margin = max(0, margin - weakpoint_threshold)
    weakpoint_bonus = weakpoint_margin // weakpoint_scale if hit else 0

    weakpoint_cap = weapon.get("weakpoint_cap")
    if weakpoint_cap is not None:
        weakpoint_bonus = min(weakpoint_bonus, weakpoint_cap)

    breakdown = {
        "tn_parts": tn_parts,
        "weakpoint": {
            "threshold": weakpoint_threshold,
            "scale": weakpoint_scale,
            "raw_margin": margin,
            "effective_margin": weakpoint_margin,
        },
    }

    return AttackResult(
        hit=hit,
        TN=tn,
        roll=roll,
        score=score,
        margin=margin,
        weakpoint_bonus=weakpoint_bonus,
        breakdown=breakdown,
    )


def _apply_fail_model(delta: int, base_damage: int, fail_model: Dict[str, Any]) -> int:
    if fail_model.get("mode") != "graded":
        return base_damage

    rules = fail_model.get("graded_rules", {})
    minor_delta = rules.get("minor_fail_max_delta")
    if minor_delta is not None and delta <= minor_delta:
        multiplier = rules.get("minor_damage_multiplier")
        if multiplier is not None:
            return int(round(base_damage * multiplier))
        return base_damage

    extra_damage = rules.get("major_extra_damage")
    if extra_damage is not None:
        return base_damage + extra_damage

    return base_damage


def resolveDefense(
    defender: Dict[str, Any],
    profile: Dict[str, Any],
    attackSpec: Dict[str, Any],
    context: Dict[str, Any],
    rng: Any,
) -> DefenseResult:
    enemy_count = context.get("enemy_count", 1)
    difficulty_mod = context.get("difficulty_mod", 0)
    g_enemy_mod = max(0, enemy_count - 1)

    profile_stat = defender.get(profile.get("stat_key", "evade"), 0)
    profile_tn_base = profile.get("tn_base", 0)
    fail_model = profile.get("fail_model", {"mode": "all_or_nothing"})

    pattern = attackSpec.get("pattern", "heavy_hit")
    dice_pool = attackSpec.get("dice", [{"sides": 6, "count": 1}])
    rolls: List[DiceResult] = []
    breakdown: List[Dict[str, Any]] = []
    tn_breakdown: List[Dict[str, Any]] = []

    successes = 0
    failures = 0
    damage_taken = 0
    extra_actions = int(profile.get("success_reward", {}).get("extra_actions", 0))

    if pattern == "multi_hit":
        N = attackSpec.get("N", 0)
        M = attackSpec.get("M", 0)
        V = attackSpec.get("V", 0)
        for i in range(N):
            tn = attackSpec.get("tn_base", 0) + M + profile_tn_base + g_enemy_mod + difficulty_mod
            roll = resolveDice(dice_pool, {"mode": "sum"}, rng)
            score = roll.final + profile_stat
            success = score >= tn
            if success:
                successes += 1
            else:
                failures += 1
                base_damage = V
                damage = _apply_fail_model(tn - score, base_damage, fail_model)
                damage_taken += damage
            rolls.append(roll)
            tn_breakdown.append({"i": i, "TN": tn})
            breakdown.append(
                {
                    "i": i,
                    "TN": tn,
                    "roll": roll.final,
                    "score": score,
                    "success": success,
                    "damage_if_fail": V,
                }
            )
    else:
        M = attackSpec.get("M", 0)
        V = attackSpec.get("V", 0)
        tn = attackSpec.get("tn_base", 0) + M + profile_tn_base + g_enemy_mod + difficulty_mod
        roll = resolveDice(dice_pool, {"mode": "sum"}, rng)
        score = roll.final + profile_stat
        success = score >= tn
        if success:
            successes = 1
        else:
            failures = 1
            delta = tn - score
            base_damage = delta * V
            damage = _apply_fail_model(delta, base_damage, fail_model)
            min_damage = attackSpec.get("min_damage")
            max_damage = attackSpec.get("max_damage")
            if min_damage is not None:
                damage = max(min_damage, damage)
            if max_damage is not None:
                damage = min(max_damage, damage)
            damage_taken = damage
        rolls.append(roll)
        tn_breakdown.append({"TN": tn})
        breakdown.append(
            {
                "TN": tn,
                "roll": roll.final,
                "score": score,
                "delta": tn - score,
                "damage": damage_taken,
            }
        )

    return DefenseResult(
        pattern=pattern,
        profile_type=profile.get("type", "evade"),
        TN_breakdown=tn_breakdown,
        rolls=rolls,
        successes=successes,
        failures=failures,
        damageTaken=damage_taken,
        extraActions=extra_actions if successes else 0,
        breakdown=breakdown,
    )
