"""裁决引擎算法测试：校验位、总数/截断、字典序决胜、类别纠正，
以及与 itertools 穷举结果的随机交叉验证。"""
from __future__ import annotations

import itertools
import math
import random

from app.adjudication import adjudicate, normalize_position
from app.iso6346 import is_valid


def _positions_from_lists(lists: list[list[str]], conf: float = 0.9) -> list:
    return [[(ch, conf) for ch in chars] for chars in lists]


def test_iso6346_check_digit_mscu_example():
    # MSCU + 123456 的加权和模 11 = 6，完整合法码为 MSCU1234566
    assert is_valid("MSCU1234566")
    result = adjudicate(_positions_from_lists([
        ["M"], ["S"], ["C"], ["U"],
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"], ["6"],
    ]))
    assert result.status == "unique"
    assert result.valid_count == 1
    assert result.results[0]["code"] == "MSCU1234566"


def test_wrong_check_digit_is_invalid():
    result = adjudicate(_positions_from_lists([
        ["M"], ["S"], ["C"], ["U"],
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"], ["0"],
    ]))
    assert result.status == "invalid"
    assert result.valid_count == 0
    # 结构合法的前缀仍可统计（1 个），只是校验位不匹配
    assert result.admissible_count == 1


def test_multiple_valid_codes_are_ambiguous_and_counted_fully():
    # 序号位给 2 个候选 => 至多 2^6 个前缀，其中能通过校验的全部计入总数
    result = adjudicate(_positions_from_lists([
        ["M"], ["S"], ["C"], ["U"],
        ["1", "7"], ["2", "8"], ["3", "9"], ["4", "0"], ["5", "1"], ["6", "2"],
        ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
    ]))
    # 与穷举对拍
    expected = 0
    for combo in itertools.product(
        *[[ch for ch, _ in p] for p in _positions_from_lists([
            ["M"], ["S"], ["C"], ["U"],
            ["1", "7"], ["2", "8"], ["3", "9"], ["4", "0"], ["5", "1"], ["6", "2"],
        ])]
    ):
        prefix = "".join(combo)
        from app.iso6346 import expected_check_digit
        d = expected_check_digit(prefix)
        if d >= 0:
            expected += 1
    assert result.valid_count == expected
    assert result.status == "ambiguous"
    assert len(result.results) == min(20, expected)


def test_sorting_by_negative_log_likelihood():
    # 第一位 M(高置信度) vs W(低置信度)，两条都可通过校验时 M 在前
    result = adjudicate([
        [("M", 0.95), ("W", 0.40)],
        [("S", 0.9)], [("C", 0.9)], [("U", 0.9)],
        [("1", 0.9)], [("2", 0.9)], [("3", 0.9)],
        [("4", 0.9)], [("5", 0.9)], [("6", 0.9)],
        [("0", 0.9), ("1", 0.9), ("2", 0.9), ("3", 0.9), ("4", 0.9),
         ("5", 0.9), ("6", 0.9), ("7", 0.9), ("8", 0.9), ("9", 0.9)],
    ])
    assert result.results[0]["code"].startswith("MSCU")
    # 分数等于 -Σln(conf)
    first = result.results[0]
    assert math.isclose(first["score"],
                        -sum(math.log(p["confidence"]) for p in first["positions"]),
                        rel_tol=1e-9, abs_tol=1e-6)


def test_tie_break_is_lexicographic_on_full_code():
    # 等置信度下结果必须按完整箱号字典序排列
    result = adjudicate(_positions_from_lists([
        ["A", "B"], ["A", "B"], ["A", "B"], ["U"],
        ["1", "2"], ["1", "2"], ["1", "2"],
        ["1", "2"], ["1", "2"], ["1", "2"],
        ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
    ], conf=0.8))
    codes = [r["code"] for r in result.results]
    assert codes == sorted(codes)


def test_top_n_truncation_does_not_affect_total():
    # 构造大量有效码：前 3 位各 3 候选，序号固定，校验位全给
    result = adjudicate(_positions_from_lists([
        ["A", "B", "C"], ["A", "B", "C"], ["A", "B", "C"], ["U"],
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"],
        ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"],
    ]), top_n=5)
    assert len(result.results) == 5
    assert result.valid_count >= 5  # 总数精确，不受 top_n=5 截断影响
    assert result.results[0]["score"] <= result.results[-1]["score"]


def test_category_id_must_be_allowed():
    # 第 4 位给 X，没有任何 U/J/Z 候选 => invalid
    result = adjudicate(_positions_from_lists([
        ["M"], ["S"], ["C"], ["X"],
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"], ["6"],
    ]))
    assert result.status == "invalid"
    assert result.admissible_count == 0


def test_ocr_category_correction_digit_position_letter_input():
    # 数字位出现字母 O，应纠正为 0 并带惩罚
    cands = normalize_position(4, [("O", 0.8)])
    assert len(cands) == 1
    assert cands[0].char == "0"
    assert cands[0].corrected is True
    assert math.isclose(cands[0].cost, -math.log(0.8) * 2.0, rel_tol=1e-12)

    # 完整例子：MSCU 123456 中数字位被 OCR 成字母，纠正后仍能得到合法码
    result = adjudicate([
        [("M", 0.9)], [("S", 0.9)], [("C", 0.9)], [("U", 0.9)],
        [("1", 0.9)], [("2", 0.9)], [("3", 0.9)], [("4", 0.9)],
        [("5", 0.9)], [("6", 0.9)], [("6", 0.9)],
    ])
    assert result.results[0]["code"] == "MSCU1234566"

    result2 = adjudicate([
        [("M", 0.9)], [("S", 0.9)], [("C", 0.9)], [("U", 0.9)],
        [("1", 0.9)], [("Z", 0.9)], [("3", 0.9)], [("A", 0.9)],
        [("5", 0.9)], [("G", 0.9)], [("6", 0.9)],
    ])
    assert result2.results[0]["code"] == "MSCU1234566"
    assert result2.results[0]["positions"][5]["corrected"] is True
    assert result2.results[0]["positions"][9]["corrected"] is True


def test_category_correction_on_letter_positions():
    # 字母位出现数字 0，应纠正为 O；第 4 位要求类别标识，0->O 不是 U/J/Z 故丢弃
    cands = normalize_position(0, [("0", 0.7)])
    assert cands[0].char == "O"
    cands_cat = normalize_position(3, [("0", 0.7)])
    assert cands_cat[0].char == "O"  # 归一化本身产生候选
    # adjudicate 中再按类别标识集合过滤
    # O 的 ISO 数值为 26（M 为 24），故 OSCU123456 的校验位是 8
    result = adjudicate(_positions_from_lists([
        ["0"], ["S"], ["C"], ["U"],
        ["1"], ["2"], ["3"], ["4"], ["5"], ["6"], ["8"],
    ]))
    assert result.results[0]["code"] == "OSCU1234568"
    assert result.results[0]["positions"][0]["corrected"] is True


def test_duplicate_candidate_keeps_highest_confidence():
    cands = normalize_position(0, [("a", 0.5), ("A", 0.9)])
    assert len(cands) == 1
    assert math.isclose(cands[0].confidence, 0.9)


def test_invalid_confidence_filtered():
    cands = normalize_position(4, [("1", 0.0), ("1", 1.01), ("1", 0.5)])
    assert len(cands) == 1
    assert math.isclose(cands[0].confidence, 0.5)


def _brute_force(positions, allowed_category_ids, penalty_scale, top_n):
    """穷举参考实现。"""
    from app.adjudication import normalize_position

    normalized = []
    for pos, raws in enumerate(positions):
        cands = normalize_position(
            pos, raws, enable_correction=True, penalty_scale=penalty_scale
        )
        if pos == 3:
            cands = [c for c in cands if c.char in allowed_category_ids]
        normalized.append(cands)
    valid = {}
    for combo in itertools.product(*normalized):
        code = "".join(c.char for c in combo)
        if not is_valid(code):
            continue
        score = sum(c.cost for c in combo)
        valid[code] = min(score, valid.get(code, math.inf))
    ordered = sorted(valid.items(), key=lambda kv: (kv[1], kv[0]))
    return len(valid), ordered[:top_n]


def test_randomized_cross_check_against_bruteforce():
    rng = random.Random(20260920)
    letter_pool = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    digit_pool = "0123456789OIZEASGBTP"
    for trial in range(60):
        positions = []
        for pos in range(11):
            pool = letter_pool if pos < 4 else digit_pool
            k = rng.randint(1, 3)
            cands = [(rng.choice(pool), round(rng.uniform(0.2, 1.0), 4))
                     for _ in range(k)]
            positions.append(cands)
        top_n = rng.choice([1, 5, 20])
        result = adjudicate(positions, top_n=top_n)
        exp_count, exp_top = _brute_force(positions, "UJZ", 1.0, top_n)
        assert result.valid_count == exp_count, f"trial {trial} count mismatch"
        got_top = [(r["code"], r["score"]) for r in result.results]
        exp_top_rounded = [(code, round(score, 6)) for code, score in exp_top]
        assert got_top == exp_top_rounded, (
            f"trial {trial} ranking mismatch:\n{got_top}\n{exp_top_rounded}"
        )
        if exp_count == 0:
            assert result.status == "invalid"
        elif exp_count == 1:
            assert result.status == "unique"
        else:
            assert result.status == "ambiguous"
