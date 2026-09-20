"""ISO 6346 集装箱箱号常量与模 11 校验位计算。

箱号共 11 位：
  位置 0-2  所有人代码（3 个大写字母）
  位置 3    设备类别标识（U/J/Z 等，1 个大写字母）
  位置 4-9  设备注册序号（6 个数字）
  位置 10   校验位（1 个数字）

字母数值映射：A=10, B=12, ..., Z=38；跳过 11 的倍数
（11、22、33），其余数值按字母顺序递增。数字数值即其本身。
"""
from __future__ import annotations

_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

#: 字母 -> ISO 6346 数值（跳过 11 的倍数）
LETTER_VALUE: dict[str, int] = {}
_value = 10
for _ch in _LETTERS:
    LETTER_VALUE[_ch] = _value
    _value += 1
    if _value % 11 == 0:
        _value += 1

#: 数字 -> 数值
DIGIT_VALUE: dict[str, int] = {str(d): d for d in range(10)}

#: 各位置（从左到右 0..9）的权重 = 2 ** i
WEIGHTS: tuple[int, ...] = tuple(2**i for i in range(10))

CODE_LENGTH = 11
PREFIX_LENGTH = 10  # 参与校验位计算的前 10 位


def char_value(ch: str) -> int:
    """返回单个字符的 ISO 6346 数值。"""
    if ch in DIGIT_VALUE:
        return DIGIT_VALUE[ch]
    return LETTER_VALUE[ch]


def weighted_remainder(prefix10: str) -> int:
    """前 10 位加权和对 11 取模，结果范围 0..10。"""
    total = 0
    for i, ch in enumerate(prefix10):
        total += char_value(ch) * WEIGHTS[i]
    return total % 11


def expected_check_digit(prefix10: str) -> int:
    """返回 ISO 6346 校验位。

    余数为 10 时不存在合法的一位校验位（标准中该码即作废），
    此处返回 -1 由调用方判定为无效。
    """
    remainder = weighted_remainder(prefix10)
    if remainder == 10:
        return -1
    return remainder


def is_valid(code: str) -> bool:
    """判断完整 11 位箱号是否通过模 11 校验。"""
    if len(code) != CODE_LENGTH:
        return False
    check = expected_check_digit(code[:PREFIX_LENGTH])
    return check >= 0 and code[PREFIX_LENGTH] == str(check)
