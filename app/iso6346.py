"""ISO 6346 container-number fuzzy adjudication engine.

A container number has 11 positions:

    positions 1-3 : owner prefix,       capital letters (registered BIC code)
    position  4   : category identifier, capital letter U / J / Z
    positions 5-10: serial number,      digits
    position  11  : check digit,        digit 0-9 (remainder 10 is discarded)

Check digit rule (ISO 6346 / BIC):

    S = sum(value(c_i) * 2**(i-1)) for the first ten characters (i = 1..10)
    check digit = S mod 11            # 10 has no single-digit representation

Letter values run 10..38 in alphabetical order, skipping multiples of 11
(11, 22, 33); digit d has value d.

Search strategy — the OCR candidate product is never expanded blindly:

* total valid count ... exact dynamic program over the 11 residue states,
                        so truncation of the ranked list cannot affect it;
* ranked top-k ........ best-first branch-and-bound search ordered by
                        accumulated -log(confidence), with the lexicographically
                        smallest reachable complete code as the deterministic
                        tie-breaker. Only the nodes needed for k answers are
                        touched;
* the owner prefix forms one bounded block (the three OCR candidate sets only),
  optionally intersected with the registered-owner registry.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# ISO 6346 constants
# ---------------------------------------------------------------------------

_LETTER_VALUES: dict[str, int] = {}
_next = 10
for _ord in range(ord("A"), ord("Z") + 1):
    if _next % 11 == 0:
        _next += 1
    _LETTER_VALUES[chr(_ord)] = _next
    _next += 1

# Weight of 0-based position p: 2**p mod 11.
_POSITION_WEIGHTS = tuple(pow(2, p, 11) for p in range(11))

# Expected position classes: L = capital letter, D = digit.
POSITION_CLASSES = ("L", "L", "L", "L", "D", "D", "D", "D", "D", "D", "D")


def char_value(char: str) -> int:
    """ISO 6346 numeric value of an upper-case letter or digit."""
    if "0" <= char <= "9":
        return int(char)
    return _LETTER_VALUES[char]


def weighted_residue(char: str, position: int) -> int:
    """value(char) * 2**position (mod 11); position is 0-based."""
    return char_value(char) * _POSITION_WEIGHTS[position] % 11


def check_digit(code10: str) -> int:
    """Official check digit (0..9) of a 10-character container number."""
    return sum(weighted_residue(c, p) for p, c in enumerate(code10)) % 11


def _neg_log(conf: float) -> float:
    return -math.log(conf) if conf > 0.0 else math.inf


# ---------------------------------------------------------------------------
# Option / layer model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Option:
    """One concrete choice for a layer (a single position or the owner block)."""
    chars: tuple[str, ...]           # characters fixed by this option
    costs: tuple[float, ...]         # -log confidence per char, aligned
    residue: int                     # summed weighted residue mod 11
    confidences: tuple[float, ...]   # confidences aligned with `chars`

    @property
    def cost(self) -> float:
        return math.fsum(self.costs)


def _class_allowed(char: str, position: int,
                   category_letters: frozenset[str]) -> bool:
    if POSITION_CLASSES[position] == "L":
        return "A" <= char <= "Z" and (
            position != 3 or char in category_letters
        )
    return "0" <= char <= "9"


def build_layers(
    positions: list[dict[str, float]],
    category_letters: frozenset[str],
    registered_owners: frozenset[str],
    enforce_owner_registry: bool,
):
    """Build the option layers for the first ten positions.

    Returns ``(layers, check_for, allowed_digits, dropped, empty_positions)``:

    * ``layers``       — ordered options per layer, lex-sorted;
    * ``check_for(r)`` — returns the position-11 ``Option`` satisfying the
                         mod-11 rule for prefix residue ``r`` (remainder 10 /
                         an unobserved digit yields ``None``);
    * ``allowed_digits`` — digits present among class-valid position-11 OCR
                         candidates;
    * ``dropped``      — ``dropped[p]`` counts raw OCR candidates at position
                         p rejected for the position's character class;
    * ``empty_positions`` — 1-based positions with no class-valid candidate.
    """
    per_position: list[list[Option]] = []
    dropped = [0] * 11
    empty: list[int] = []

    for p in range(11):
        opts: list[Option] = []
        for char, conf in positions[p].items():
            if not _class_allowed(char, p, category_letters):
                dropped[p] += 1
                continue
            opts.append(Option(
                chars=(char,),
                costs=(_neg_log(conf),),
                residue=weighted_residue(char, p),
                confidences=(conf,),
            ))
        opts.sort(key=lambda o: o.chars[0])
        per_position.append(opts)
        if not opts:
            empty.append(p + 1)

    check_candidates = {o.chars[0]: o for o in per_position[10]}
    allowed_digits = frozenset(check_candidates)

    def check_for(residue: int) -> Option | None:
        digit = str(residue % 11)  # remainder 10 cannot match a single digit
        return check_candidates.get(digit)

    if enforce_owner_registry:
        # Bounded block: only the Cartesian product of the three observed
        # candidate sets, intersected with registered codes — no wildcard
        # expansion over the alphabet.
        by_char = [{o.chars[0]: o for o in per_position[p]} for p in range(3)]
        block: list[Option] = []
        for code in registered_owners:
            picks = [by_char[i].get(ch) for i, ch in enumerate(code)]
            if any(pick is None for pick in picks):
                continue
            block.append(Option(
                chars=tuple(code),
                costs=tuple(pick.costs[0] for pick in picks),
                residue=sum(pick.residue for pick in picks) % 11,
                confidences=tuple(pick.confidences[0] for pick in picks),
            ))
        block.sort(key=lambda o: o.chars)
        layers = [block] + per_position[3:10]
    else:
        layers = per_position[:10]

    return layers, check_for, allowed_digits, dropped, empty


# ---------------------------------------------------------------------------
# Exact valid-count dynamic program — independent of any truncation
# ---------------------------------------------------------------------------

def count_valid(layers: list[list[Option]], check_for) -> int:
    """Exact number of complete codes passing class, owner and mod-11 rules."""
    dp = [0] * 11
    dp[0] = 1
    for layer in layers:
        nxt = [0] * 11
        for r, n in enumerate(dp):
            if n:
                for opt in layer:
                    nxt[(r + opt.residue) % 11] += n
        dp = nxt
    return sum(n for r, n in enumerate(dp) if check_for(r) is not None)


# ---------------------------------------------------------------------------
# Best-first top-k search
# ---------------------------------------------------------------------------

# A table entry is (cost_terms, chars): the individual -log terms of a
# complete suffix plus its character tuple. Terms are only combined with
# math.fsum at comparison time so totals are bit-for-bit identical no matter
# how the prefix was accumulated (plain `a+b` grouping introduces ~1e-15
# noise that corrupts the lexicographic tie-break).
SuffixEntry = tuple[tuple[float, ...], tuple[str, ...]]


def _suffix_best(
    layers: list[list[Option]], check_for
) -> list[dict[int, SuffixEntry]]:
    """Reverse DP: best suffix per layer boundary and accumulated residue."""
    terminal: dict[int, SuffixEntry] = {}
    for r in range(11):
        opt = check_for(r)
        if opt is not None:
            terminal[r] = (opt.costs, opt.chars)

    table: list[dict[int, SuffixEntry]] = [
        {} for _ in range(len(layers) + 1)
    ]
    table[len(layers)] = terminal
    for t in range(len(layers) - 1, -1, -1):
        cur: dict[int, SuffixEntry] = {}
        nxt = table[t + 1]
        for r_prefix in range(11):
            best_key: tuple[float, tuple[str, ...]] | None = None
            best_value: SuffixEntry | None = None
            for opt in layers[t]:
                tail = nxt.get((r_prefix + opt.residue) % 11)
                if tail is None:
                    continue
                tail_terms, tail_chars = tail
                terms = opt.costs + tail_terms
                chars = opt.chars + tail_chars
                key = (math.fsum(terms), chars)
                if best_key is None or key < best_key:
                    best_key, best_value = key, (terms, chars)
            if best_value is not None:
                cur[r_prefix] = best_value
        table[t] = cur
    return table


def top_k(
    layers: list[list[Option]],
    check_for,
    k: int,
) -> list[tuple[str, float, tuple[float, ...]]]:
    """Up to k ranked ``(code, neg_log_cost, per_position_confidences)``.

    Ordering: ascending total -log confidence; ties broken by ascending full
    code lexicographically — stable regardless of OCR input ordering.

    Each heap node carries the best complete solution reachable through it
    (canonical total cost, best full code). Expanding a node replaces it with
    its children, so leaves leave the heap in exact global ranked order. Only
    O(k * depth * width) nodes are touched; the candidate Cartesian product
    is never materialized.
    """
    if k <= 0:
        return []

    best = _suffix_best(layers, check_for)
    root = best[0].get(0)
    if root is None:
        return []

    # (total, code, seq, boundary, residue, prefix, prefix_terms, confidences)
    root_terms, root_chars = root
    heap: list[tuple] = [
        (math.fsum(root_terms), "".join(root_chars), 0, 0, 0, "", (), ())
    ]
    seq = 0
    results: list[tuple[str, float, tuple[float, ...]]] = []

    while heap and len(results) < k:
        total, _, _, t, residue, prefix, prefix_terms, confs = \
            heapq.heappop(heap)
        if t == len(layers):
            final = check_for(residue)  # never None for a queued leaf
            results.append((
                prefix + final.chars[0],
                total,
                confs + final.confidences,
            ))
            continue
        for opt in layers[t]:
            nr = (residue + opt.residue) % 11
            tail = best[t + 1].get(nr)
            if tail is None:
                continue
            tail_terms, tail_chars = tail
            child_terms = prefix_terms + opt.costs
            seq += 1
            heapq.heappush(heap, (
                math.fsum(child_terms + tail_terms),
                prefix + "".join(opt.chars) + "".join(tail_chars),
                seq, t + 1, nr,
                prefix + "".join(opt.chars),
                child_terms,
                confs + opt.confidences,
            ))

    return results


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

@dataclass
class Adjudication:
    total_candidates: int
    ranked: list[tuple[str, float, tuple[float, ...]]]
    dropped: list[int]
    status: str                       # unique | ambiguous | invalid
    empty_positions: list[int]


def adjudicate(
    positions: list[dict[str, float]],
    category_letters: frozenset[str],
    registered_owners: frozenset[str],
    enforce_owner_registry: bool,
    k: int = 20,
) -> Adjudication:
    """Joint search over character class, owner-code and mod-11 constraints."""
    layers, check_for, _allowed_digits, dropped, empty = build_layers(
        positions, category_letters, registered_owners, enforce_owner_registry
    )

    if any(not layer for layer in layers):
        return Adjudication(0, [], dropped, "invalid", empty)

    total = count_valid(layers, check_for)
    if total == 0:
        return Adjudication(0, [], dropped, "invalid", empty)

    ranked = top_k(layers, check_for, min(k, total))
    status = "unique" if total == 1 else "ambiguous"
    return Adjudication(total, ranked, dropped, status, empty)
