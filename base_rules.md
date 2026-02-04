# Base Rules — Dice Resolution Engine

## Design Goals
- Dice-based resolution with visible risk
- Multi-enemy pressure scales difficulty
- Build modifies probability distribution, not flat stats

## Core Concepts
- Dice Pool (granular dice, not rng(min,max))
- Margin-based success
- Profiles (Evade / Block)
- Attack patterns (Multi-hit / Heavy-hit)

## Dice Resolution
- resolveDice(...)
- supported dice pools
- supported modes (sum / max / success_count)
- reroll rules

## Attack Resolution
- resolveAttack(...)
- Hit TN formula
- Margin → Weakpoint conversion

## Defense Resolution
- resolveDefense(...)
- Profiles
  - Evade
  - Block
- Attack patterns
  - Multi-hit
  - Heavy-hit

## Dice & Combat Resolution Engine — Requirements Spec (v0.1)

本文件定義三個核心函式的行為與輸入/輸出：resolveDice、resolveAttack、resolveDefense。
目標是先完成「可重現、可測試、可印出 log 的純邏輯原型」，不依賴資料庫、不依賴引擎、不依賴 UI。

### Global Principles

#### 所有隨機必須可重現

- 支援注入 seed 或注入 RNG instance。
- 同一 seed / 同一 RNG 狀態下，輸出必須可重現（方便白箱與平衡測試）。

#### 以「顆粒化骰子」為準

- 多骰不可用 rng(min,max) 替代。
- 必須逐顆擲骰並保留每顆結果，因為 proc/規則會對單顆結果動手腳（重擲、取高、忽略最低等）。

#### 必須回傳「可解釋」的結果

- 每個 resolver 都要回傳 breakdown（或等價資訊），讓 log 可以清楚知道為何成功/失敗、傷害怎麼算的。

#### 不做 UI、不做資料持久化

- 這些函式只負責「計算」與「回傳結果」。

### 1) resolveDice — Dice Pool / Rolling Resolver

#### Purpose

提供通用「骰池」擲骰能力，支援多顆不同面數、以及常用的組合規則（加總、取最高、取前 N、計算成功數、重擲等）。

#### Function Signature (suggested)

resolveDice(pool, rules, rng) -> DiceResult

#### Inputs

**A. pool（骰池定義）**

形式建議：

pool = [ { sides: 6, count: 2 }, { sides: 12, count: 1 } ]

展開後視為具名的「骰子列表」，每顆骰子都應可被單獨標記/操作（例如第 2 顆 d6 被重擲）。

**B. rules（擲骰規則）**

至少要支援以下基礎規則（可用 enum 或字串）：

- mode = "sum"
  - 回傳所有骰子加總
- mode = "max"
  - 回傳最高點數（常用於閃避/爆發）
- mode = "top_n_sum"（參數：n）
  - 取最高 N 顆加總
- mode = "success_count"（參數：threshold）
  - 每顆結果 >= threshold 計為 1 成功，回傳成功數

必須能掛載 proc 類行為（以 rules 的欄位表達）：

- reroll:
  - reroll = { times: k, strategy: "lowest" | "all_fail" | "specific_indexes" }
- upgrade_die:
  - 例如把一顆 d6 升成 d8（可用外部先改 pool，也可在 rules 支援）
- add_dice:
  - 例如 +1d6（同上）

v0.1 可先只做 reroll（最常用）+ 基本 mode，upgrade/add 可先透過呼叫端修改 pool 來達成。

**C. rng**

可為：

- random.Random(seed) 之類的 RNG instance
- 或提供 randint(a,b) 的介面

不允許在 resolver 內部偷偷 new RNG（除非呼叫端沒給且明確允許 fallback）。

#### Outputs — DiceResult

必須包含：

- rolls: 展開後每顆骰子的結果列表（含 sides 與結果值）
  - 例如 [ {sides:6, value:3}, {sides:6, value:5}, {sides:12, value:9} ]
- final: 最終輸出值（依 mode 而定：sum / max / success_count 等）
- meta:
  - mode, threshold（若有）, top_n（若有）
- breakdown: 文字或結構化步驟（建議結構化），至少要能看出：
  - 原始結果
  - 是否重擲、重擲了哪顆、重擲後結果
  - 如何得出 final

### 2) resolveAttack — Hit & Weakpoint Resolver

#### Purpose

依據「命中/索敵」與目標防禦狀態，判定是否命中；若命中，將「過量成功（margin）」按規則轉換為「弱點攻擊加成」。

#### Function Signature (suggested)

resolveAttack(attacker, weapon, target, context, rng) -> AttackResult

#### Inputs

**A. attacker（攻擊者面板）**

至少包含：

- accuracy（命中/索敵值，可為整數）
- 可選：weakpoint_bonus（若你想讓某些 proc/晶片影響弱點轉換）

**B. weapon（武器）**

至少包含：

- hit_tn_base：基礎命中門檻（越高越難打中）
- weakpoint_threshold：margin 超過此值後才開始產生弱點加成（避免只要命中就暴擊）
- weakpoint_scale：弱點轉換比例（例如每 2 點 margin 換 +1 等級）
- damage_base（v0.1 可先不算傷害，只回弱點倍率也行）

**C. target（目標）**

至少包含：

- evasion_mod：目標對命中門檻的修正（越高越難命中）

**D. context（戰鬥情境）**

- enemy_count（同時敵人數）
- 可選：difficulty_mod（高難度修正）

**E. rng / dice behavior**

- v0.1 建議命中擲骰使用：1d6（或由 weapon/系統指定）
- 之後可讓武器/晶片改變骰型（例如 2d6 取高、d8 等），但 v0.1 先用簡化版即可。

#### Core Logic (v0.1 baseline)

- 計算命中門檻（Hit TN）：
  - TN = weapon.hit_tn_base + target.evasion_mod + f(enemy_count) + difficulty_mod
  - f(enemy_count) v0.1 建議先做：+(enemy_count - 1)（多敵人壓力）
- 擲骰獲得 roll_value（透過 resolveDice）
- 計算 score = roll_value + attacker.accuracy
- 若 score < TN → miss
- 若命中：
  - margin = score - TN
  - weakpoint_margin = max(0, margin - weapon.weakpoint_threshold)
  - weakpoint_bonus = floor(weakpoint_margin / weapon.weakpoint_scale)（或其他你想要的映射）
- 回傳 weakpoint bonus（可視為暴擊等級或傷害倍率加成）

#### Outputs — AttackResult

至少包含：

- hit: bool
- roll: DiceResult（命中用的擲骰細節）
- TN: int
- score: int
- margin: int（若 miss 可為負或 0）
- weakpoint_bonus: int（miss 時為 0）
- breakdown: 可解釋資訊（命中門檻如何組成、弱點如何換算）

### 3) resolveDefense — Defensive Resolution (Evade/Block Profiles + Patterns)

#### Purpose

處理「防禦/閃避」對不同攻擊型態的判定。
v0.1 將防禦與閃避視為同一 resolver 的不同 profile（差在門檻與後果曲線），避免日後擴充時函式爆炸。

#### Function Signature (suggested)

resolveDefense(defender, profile, attackSpec, context, rng) -> DefenseResult

#### Inputs

**A. defender（防禦者面板）**

至少包含：

- evade（閃避相關值）
- block（格檔/防禦相關值）
- hp（目前生命值，可由外部扣或由本函式回傳 damageTaken）

可選（先留欄位但 v0.1 不用）：

- firepower: int
- engine: int
- melee: int

**B. profile（防禦策略）**

profile 用來決定「用哪個面板值」與「失敗後果曲線」：

- type: "evade" 或 "block"
- stat_key: "evade" or "block"（或直接映射）
- tn_base: 基礎門檻（evade 通常較低、block 較高）
- on_success: 成功回饋（例如 block 成功可 extra_actions +1）
- fail_model: 失敗分級模型
  - evade：失敗通常吃全傷
  - block：可有小失敗減傷 / 大失敗額外受傷

**C. attackSpec（攻擊規格）**

至少包含：

- pattern: "multi_hit" 或 "heavy_hit"

若 multi_hit：

- N: 次數（連續多段）
- M: 每段成功門檻
- V: 每次失敗傷害（或每失敗扣血量）

若 heavy_hit：

- M: 門檻（達標免傷/大減傷）
- V: 傷害係數（低於門檻每差 1 點扣 V 傷害）或基礎傷害

可選：damage_base、armor_pierce 等（v0.1 不必）

**D. context（情境）**

- enemy_count（同時敵人數）
- difficulty_mod

多敵人對 defense 的作用：

- v0.1 先做簡單規則即可（例如：增加 N 或提高 M，擇一）。

#### Core Logic (v0.1 baseline)

**Pattern 1: multi_hit（連續多段）**

- 進行 N 次防禦判定
- 每次判定：
  - TN_i = attackSpec.M + profile.tn_base + g(enemy_count) + difficulty_mod
  - score = roll + defender[profile.stat_key]
  - 若 score < TN_i → 記 1 失敗，累積傷害 +V
  - 若成功 → 可記成功數

最終：

- damageTaken = failures * V（evade）
- block 可套 fail_model：例如 failures 少量時減傷、失敗太多觸發破防額外傷

**Pattern 2: heavy_hit（單下重擊 / 門檻轉傷害）**

- 做一次判定：
  - TN = attackSpec.M + profile.tn_base + g(enemy_count) + difficulty_mod
  - score = roll + defender[profile.stat_key]
- 若 score >= TN：
  - evade：免傷（或極低傷）
  - block：免傷 +（可選）回饋 extra_actions
- 若 score < TN：
  - delta = TN - score
  - damageTaken = delta * V（或 min/max 限制）
  - block 可套 fail_model：小失敗 -> 減傷；大失敗 -> 額外傷/失去行動

#### Outputs — DefenseResult

至少包含：

- pattern: "multi_hit" | "heavy_hit"
- profile_type: "evade" | "block"
- rolls: list[DiceResult]（multi_hit）或單一 DiceResult（heavy_hit）
- TN_breakdown: 每次/本次 TN 組成資訊
- successes: int
- failures: int
- damageTaken: int
- extraActions: int（若有）
- breakdown: 可解釋資訊（每段結果、失敗分級觸發原因）

### v0.1 Deliverables / Acceptance Criteria

- 可以用固定 seed 重現同一場 combat log（同樣輸入→同樣輸出）
- 可支援以下最小情境：
  - 一個 multi_hit 攻擊（N=3, M=?, V=?）
  - 一個 heavy_hit 攻擊（M=?, V=?）
  - 同一攻擊對 evade 與 block profile 的結果差異明顯
- resolveAttack 具備「命中→弱點加成」轉換，並在 log 中看得懂 margin 如何轉弱點
- 所有 resolver 回傳結果都包含足夠 breakdown 供文字原型印出戰鬥過程

## Data Structures

### Data Structures Draft — Dice & Resolution Engine (v0.1)

這份是「最小可玩」版本的資料結構草稿，目標：

- 好擴充（proc/模組以後加得進來）
- 好 debug（每次判定的細節留得住）
- 盡量純資料（不要把邏輯塞進資料結構）

#### 0) Common Types

**RNG Interface（概念）**

- 需要能做 randint(a,b)（含端點）
- 建議呼叫端傳入 RNG instance（可 seed）

#### 1) Dice Types

**DieSpec**

- 代表一種骰子規格（不含結果）
- sides: int（例如 6 / 8 / 12 / 16）
- count: int（這種骰子有幾顆）

例：[{sides:6,count:2},{sides:12,count:1}]

**DieRoll**

- 代表「一顆骰子的實際擲骰結果」
- sides: int
- value: int（1..sides）
- tags: list[str]（可選，未來 proc 用）

例如 ["rerolled"]、["upgraded_from_d6"]

**DicePool**

- 展開後的「骰子列表」（比較方便做重擲/取最低等操作）
- dice: list[DieRoll]（擲完後才有）

或者在擲骰前：

- specs: list[DieSpec]

建議：resolveDice 輸入用 specs，輸出回 rolls（展開後 list）。

**DiceRules**

- 描述「這次要怎麼用骰子」
- mode: str
  - "sum" / "max" / "top_n_sum" / "success_count"
- top_n: int | None（for top_n_sum）
- threshold: int | None（for success_count）
- reroll: RerollRule | None

**RerollRule**

- times: int（最多重擲次數）
- strategy: str
  - "lowest"：每次重擲目前最低的那顆
  - "specific_indexes"：重擲指定 index（需要 indexes）
- indexes: list[int] | None

**DiceResult**

resolveDice 的輸出

- rolls: list[DieRoll]（展開後每顆結果）
- final: int（依 mode 而定：sum/max/成功數）
- meta: dict
  - mode, top_n, threshold
- breakdown: list[dict]（建議結構化而非純文字）

例如：

- {step:"initial_roll", rolls:[...]}
- {step:"reroll", target_index:1, before:2, after:5}
- {step:"reduce", mode:"max", final:5}

#### 2) Combat Inputs — Stats / Context

**ActorStats（攻擊者或防禦者的面板）**

最小集合（你可以後續加更多面板，不影響 resolver）

- accuracy: int（索敵/命中面板）
- evade: int（閃避面板）
- block: int（防禦/格檔面板）
- hp: int（目前生命）

可選（先留欄位但 v0.1 不用）：

- firepower: int
- engine: int
- melee: int

**CombatContext**

- enemy_count: int（同時敵人數）
- difficulty_mod: int（全域難度修正，預設 0）
- tags: list[str]（可選，例如 "hard_mode", "six_boss"）

#### 3) Attack Resolution Data

**WeaponSpec**

最小命中→弱點轉換規格

- name: str
- hit_tn_base: int（基礎命中門檻）
- hit_dice: list[DieSpec]（命中擲骰用的骰池，v0.1 可固定 1d6）
- weakpoint_threshold: int（margin 超過多少才開始轉弱點）
- weakpoint_scale: int（每幾點 margin 換 1 級弱點加成）
- weakpoint_cap: int | None（可選，上限）

可選（先不算傷害也行）：

- damage_base: int
- damage_scale: float（或其他）

**TargetSpec（目標影響命中）**

- evasion_mod: int（命中門檻加成，越高越難命中）
- tags: list[str]（可選：例如 boss 類型）

**AttackResult**

resolveAttack 的輸出

- hit: bool
- TN: int（最終命中門檻）
- roll: DiceResult（命中擲骰細節）
- score: int（roll.final + attacker.accuracy）
- margin: int（score - TN）
- weakpoint_bonus: int（miss 時為 0）
- breakdown: dict

例如：

- tn_parts: {base, target_mod, enemy_count_mod, difficulty_mod}
- weakpoint: {threshold, scale, raw_margin, effective_margin}

#### 4) Defense / Evade Resolution Data

**DefenseProfile（策略/姿態）**

用來表達「閃避 vs 防禦」差異，但用同一個 resolver

- type: str："evade" | "block"
- stat_key: str："evade" | "block"（從 ActorStats 取用）
- tn_base: int（這個姿態的基礎門檻偏移）
- success_reward: dict
  - 例如：{extra_actions: 0 or 1}
- fail_model: FailModel

**FailModel（失敗後果曲線）**

最小版先做「分級」即可

- mode: str
  - "all_or_nothing"：失敗就全吃（適合 evade）
  - "graded"：小失敗/大失敗（適合 block）
- graded_rules: GradedFailRules | None

**GradedFailRules**

- minor_fail_max_delta: int
  - 若 delta = TN - score <= 這個值 → 小失敗
- minor_damage_multiplier: float
  - 小失敗時傷害乘數（例如 0.5）
- major_extra_damage: int
  - 大失敗額外傷害（例如 +2）

可選：

- break_guard_on_major: bool（大失敗觸發破防狀態）

v0.1 你也可以先不用 multiplier，直接用「小失敗固定減傷」也行。

**AttackSpec（敵人攻擊規格）**

這是 defense resolver 的關鍵輸入，描述攻擊型態與判定需求

共同欄位：

- name: str
- pattern: str："multi_hit" | "heavy_hit"
- tn_base: int（攻擊自身的門檻基準，配合 profile/敵人數調整）
- dice: list[DieSpec]（防禦擲骰用的骰池，v0.1 可固定 1d6）

Multi-hit 專用：

- N: int（段數）
- M: int（每段需要達到的門檻基準）
- V: int（每次失敗傷害）

Heavy-hit 專用：

- M: int（門檻基準）
- V: int（每差 1 點的傷害係數）

可選：min_damage: int, max_damage: int

注意：這裡的 M 是「攻擊方需求」，最終 TN 還會加上 profile/context 的修正。

**DefenseResult**

resolveDefense 的輸出（同時涵蓋 evade/block）

- pattern: str
- profile_type: str
- TN_breakdown: list[dict] 或 dict
  - multi_hit：每段一個
  - heavy_hit：單一
- rolls: list[DiceResult]（multi_hit）或 DiceResult（heavy_hit）
- successes: int
- failures: int
- damageTaken: int
- extraActions: int
- breakdown: list[dict]

multi_hit 每段：

- {i, TN, roll, score, success, damage_if_fail}

heavy_hit：

- {TN, roll, score, delta, damage}

以及 fail_model（小失敗/大失敗）判斷資訊

#### 5) Minimal Example Objects（幫你對齊直覺）

**Dice pool example**

- 命中：1d6
- 高級 proc：2d6 take max（可用 rules.mode="max" + pool=[d6,d6]）

**Weapon example**

- hit_tn_base=4
- weakpoint_threshold=1（margin>1 才開始轉）
- weakpoint_scale=2（每 +2 margin → +1 弱點等級）

**Defense profiles**

- evade：tn_base=0, fail_model=all_or_nothing
- block：tn_base=2, fail_model=graded（小失敗減傷、大失敗額外傷，成功+1 action）

## Non-goals (v0.1)
- No UI
- No persistence
- No animation / timing
