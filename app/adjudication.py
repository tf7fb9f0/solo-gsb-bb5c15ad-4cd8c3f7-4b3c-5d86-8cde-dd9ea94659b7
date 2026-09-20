"""模糊箱号联合裁决引擎（仅依赖标准库）。

联合约束：
1. 字符类别约束 —— 位置 0-3 只能是大写字母，位置 4-10 只能是数字；
   OCR 识别出的越类字符按固定形近混淆表纠正后继续参与搜索。
2. 所有人代码 / 设备类别规则 —— 位置 3 必须属于允许的类别标识集合（默认 U/J/Z）。
3. ISO 6346 模 11 校验 —— 校验位必须等于前 10 位加权和对 11 取模的结果，
   余数为 10 不存在合法校验位。

搜索策略：按位置做 DP，状态为 `(已处理层数, 加权累计和 mod 11)`。
每个状态仅保留累计代价最小的 K 条前缀（K = 需要返回的条数，默认 20），
**从不实例化完整笛卡尔积**；同时维护每个状态的精确路径总数，
因此“有效候选总数”不受任何截断影响。

代价定义为各字符置信度负对数之和：score = -Σ ln(conf)。
被类别纠正的形近字符附加惩罚：score *= (1 + penalty_scale)。
最终同分时按完整 11 位箱号字典序稳定决胜。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .iso6346 import CODE_LENGTH, PREFIX_LENGTH, WEIGHTS

# ------------------------------------------------------------------ 形近混淆表
# 仅在严格限定字符类别的箱号位使用：字母位出现的数字、数字位出现的字母。
_DIGIT_TO_LETTER: dict[str, str] = {
    "0": "O",
    "1": "I",
    "2": "Z",
    "3": "E",
    "4": "A",
    "5": "S",
    "6": "G",
    "7": "T",
    "8": "B",
    "9": "P",
}
# 未列入的字母（如 C/K/L/M/N/R/V/W/X/Y）与数字形近关系不稳定，
# 不做猜测，直接丢弃。
_LETTER_TO_DIGIT: dict[str, str] = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "E": "3",
    "A": "4",
    "S": "5",
    "G": "6",
    "b": "8",
    "B": "8",
    "P": "9",
}

#: 位置类别
LETTER = "letter"
DIGIT = "digit"


def position_category(pos: int) -> str:
    """返回箱号某位置（0-10）要求的字符类别。"""
    return LETTER if pos < 4 else DIGIT


@dataclass(frozen=True)
class Candidate:
    """归一化后的单位置候选字符。"""

    char: str               # 已按位置类别归一化后的 A-Z / 0-9
    confidence: float       # OCR 原始置信度，0 < conf <= 1
    cost: float             # 该字符贡献的负对数代价（含纠正惩罚）
    raw: str                 # OCR 原始输出（保留大小写）
    corrected: bool = False  # 是否经过类别形近纠正


@dataclass
class _Node:
    """DP 状态中的一条前缀。"""

    prefix: str
    cost: float


@dataclass
class AdjudicationResult:
    """裁决结果。"""

    valid_count: int
    status: str  # unique | ambiguous | invalid
    results: list[dict] = field(default_factory=list)
    admissible_count: int = 0  # 通过类别/所有人规则（未必通过校验）的候选总数


def normalize_position(
    pos: int,
    raw_candidates: list[tuple[str, float]],
    *,
    enable_correction: bool = True,
    penalty_scale: float = 1.0,
) -> list[Candidate]:
    """把某一位置的 OCR 候选归一化为该位置要求的字符类别。

    - 小写字母统一转大写；
    - 重复字符取最高置信度；
    - 越类字符在开关打开时按形近表纠正，并附加惩罚；
    - 无法归一化或置信度非法的候选丢弃。
    """
    category = position_category(pos)
    merged: dict[str, Candidate] = {}

    for raw_ch, conf in raw_candidates:
        if not isinstance(raw_ch, str) or len(raw_ch) != 1:
            continue
        ch = raw_ch.upper()
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            continue
        if not (0.0 < conf <= 1.0):
            continue

        corrected = False
        if category == LETTER and ch.isdigit():
            if not enable_correction:
                continue
            mapped = _DIGIT_TO_LETTER.get(ch)
            if mapped is None:
                continue
            ch, corrected = mapped, True
        elif category == DIGIT and ch.isalpha():
            if not enable_correction:
                continue
            mapped = _LETTER_TO_DIGIT.get(ch)
            if mapped is None:
                continue
            ch, corrected = mapped, True
        elif category == LETTER and ch.isalpha():
            pass
        elif category == DIGIT and ch.isdigit():
            pass
        else:
            continue  # 非字母数字，箱号中不允许

        cost = -math.log(conf)
        if corrected:
            cost *= 1.0 + penalty_scale

        existing = merged.get(ch)
        if existing is None or cost < existing.cost:
            merged[ch] = Candidate(
                char=ch,
                confidence=conf,
                cost=cost,
                raw=raw_ch,
                corrected=corrected,
            )

    return list(merged.values())


def _keep_best_k(nodes: list[_Node], k: int) -> list[_Node]:
    """保留代价最小的 K 条前缀；同分按前缀字典序，保证稳定。"""
    if len(nodes) <= k:
        nodes.sort(key=lambda n: (n.cost, n.prefix))
        return nodes
    nodes.sort(key=lambda n: (n.cost, n.prefix))
    return nodes[:k]


def adjudicate(
    positions: list[list[tuple[str, float]]],
    *,
    allowed_category_ids: str = "UJZ",
    enable_correction: bool = True,
    penalty_scale: float = 1.0,
    top_n: int = 20,
) -> AdjudicationResult:
    """对 11 个位置的 OCR 候选做联合约束裁决。

    ``positions`` 为长度 11 的列表，每个元素是 ``(字符, 置信度)`` 对。
    """
    if len(positions) != CODE_LENGTH:
        raise ValueError(f"expected {CODE_LENGTH} positions, got {len(positions)}")
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    # 1) 逐位置归一化 + 类别规则过滤 -------------------------------
    normalized: list[list[Candidate]] = []
    for pos, raws in enumerate(positions):
        cands = normalize_position(
            pos,
            raws,
            enable_correction=enable_correction,
            penalty_scale=penalty_scale,
        )
        if pos == 3:  # 设备类别标识规则
            cands = [c for c in cands if c.char in allowed_category_ids]
        normalized.append(cands)
        if not cands:
            # 任一位置无合法候选，不存在任何通过结构约束的箱号
            return AdjudicationResult(
                valid_count=0,
                status="invalid",
                results=[],
                admissible_count=0,
            )

    # 2) 前 10 位做余数 DP；状态键为加权累计和 mod 11 ---------------
    #    states[remainder] = 保留下来的最优前缀（至多 top_n 条）
    #    counts[remainder] = 该余数下前缀的【精确】总数（不受截断影响）
    first = normalized[0]
    states: dict[int, list[_Node]] = {}
    counts: dict[int, int] = {}
    w0 = WEIGHTS[0]
    for cand in first:
        r = _char_value(cand.char) * w0 % 11
        states.setdefault(r, []).append(_Node(cand.char, cand.cost))
        counts[r] = counts.get(r, 0) + 1
    for r in states:
        states[r] = _keep_best_k(states[r], top_n)

    for pos in range(1, PREFIX_LENGTH):
        weight = WEIGHTS[pos]
        next_states: dict[int, list[_Node]] = {}
        next_counts: dict[int, int] = {}
        for remainder, nodes in states.items():
            for cand in normalized[pos]:
                new_r = (remainder + _char_value(cand.char) * weight) % 11
                bucket = next_states.setdefault(new_r, [])
                for node in nodes:
                    bucket.append(
                        _Node(node.prefix + cand.char, node.cost + cand.cost)
                    )
                # 精确计数：对端余数的每条完整前缀都有 len(cands) 种延伸。
                # counts 记录的是精确前缀数（截断不影响它），故这里用 counts。
                next_counts[new_r] = (
                    next_counts.get(new_r, 0) + counts[remainder]
                )
        states = {r: _keep_best_k(nodes, top_n) for r, nodes in next_states.items()}
        counts = next_counts

    admissible_count = sum(counts.values())

    # 3) 末位校验：对每个前缀余数 r，要求校验位数字等于 r；
    #    r == 10 不存在一位合法校验位，直接排除。 --------------------
    check_candidates = normalized[PREFIX_LENGTH]
    check_by_char = {c.char: c for c in check_candidates}

    valid_count = 0
    complete: list[_Node] = []  # (11 位完整箱号, 总代价)，截断规模有限
    for remainder, prefix_nodes in states.items():
        if remainder >= 10:
            continue
        check_cand = check_by_char.get(str(remainder))
        if check_cand is None:
            continue
        # 该余数下【全部】前缀都满足校验，而不只是保留下来的 top_n 条
        valid_count += counts[remainder]
        for node in prefix_nodes:
            complete.append(
                _Node(
                    node.prefix + check_cand.char,
                    node.cost + check_cand.cost,
                )
            )

    if valid_count == 0:
        return AdjudicationResult(
            valid_count=0,
            status="invalid",
            results=[],
            admissible_count=admissible_count,
        )

    complete.sort(key=lambda n: (n.cost, n.prefix))
    top = complete[:top_n]

    # 4) 组装输出 --------------------------------------------------
    results = [
        {
            "code": node.prefix,
            "score": round(node.cost, 6),
            "positions": _position_details(node.prefix, normalized),
        }
        for node in top
    ]
    return AdjudicationResult(
        valid_count=valid_count,
        status="unique" if valid_count == 1 else "ambiguous",
        results=results,
        admissible_count=admissible_count,
    )


def _char_value(ch: str) -> int:
    """ISO 6346 字符数值查询。"""
    from .iso6346 import DIGIT_VALUE, LETTER_VALUE

    if "0" <= ch <= "9":
        return DIGIT_VALUE[ch]
    return LETTER_VALUE[ch]


def _position_details(
    code: str, normalized: list[list[Candidate]]
) -> list[dict]:
    """回填每个入选字符的原始 OCR 字符、置信度与是否经过纠正。"""
    details: list[dict] = []
    for pos, ch in enumerate(code):
        cand = next(c for c in normalized[pos] if c.char == ch)
        details.append(
            {
                "position": pos,
                "char": ch,
                "raw_char": cand.raw,
                "confidence": cand.confidence,
                "corrected": cand.corrected,
                "negative_log_likelihood": round(cand.cost, 6),
            }
        )
    return details
