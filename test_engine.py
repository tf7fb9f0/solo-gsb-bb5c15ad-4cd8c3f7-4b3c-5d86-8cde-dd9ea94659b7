"""Engine tests: dynamic program / best-first vs brute-force enumeration.

Run: python3 test_engine.py
"""
from __future__ import annotations

import itertools
import math
import random
import sys

from app import iso6346 as eng

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
CLASSES = ("L", "L", "L", "L", "D", "D", "D", "D", "D", "D", "D")


def brute_force(positions, category, owners, enforce_owners, k):
    """Reference implementation: bounded enumeration + full validation."""
    domains = []
    for p in range(11):
        chars = sorted(c for c in positions[p] if eng._class_allowed(c, p, category))
        domains.append(chars)
    valid = []
    if enforce_owners:
        first3 = sorted(
            code for code in owners
            if code[0] in domains[0] and code[1] in domains[1]
            and code[2] in domains[2]
        )
        prefix_choices = [first3] + domains[3:10]
    else:
        prefix_choices = domains[:10]
    for combo in itertools.product(*prefix_choices):
        if enforce_owners:
            code10 = combo[0] + "".join(combo[1:])
        else:
            code10 = "".join(combo)
        d = eng.check_digit(code10)
        if d == 10 or str(d) not in domains[10]:
            continue
        code = code10 + str(d)
        cost = sum(-math.log(positions[p][code[p]]) for p in range(11))
        valid.append((code, cost))
    valid.sort(key=lambda x: (x[1], x[0]))
    return valid[:min(k, len(valid))], len(valid)


def random_positions(rng, width=3, bad=0.3):
    positions = []
    for p in range(11):
        if CLASSES[p] == "L":
            pool = LETTERS if p < 3 else "UJZ"
        else:
            pool = DIGITS
        n = rng.randint(1, width)
        chars = rng.sample(pool, min(n, len(pool)))
        d = {c: round(rng.uniform(0.2, 1.0), 4) for c in chars}
        # sometimes inject a wrong-class candidate
        if rng.random() < bad:
            wrong_pool = DIGITS if CLASSES[p] == "L" else LETTERS
            d[rng.choice(wrong_pool)] = round(rng.uniform(0.01, 0.5), 4)
        positions.append(d)
    return positions


def main():
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        print(("PASS" if cond else "FAIL"), name, detail)
        if not cond:
            failures += 1

    # 1. Known ISO 6346 check digits.
    check("check CSQU3054383 -> 3", eng.check_digit("CSQU305438") == 3)
    check("check MRKU469195 -> 9", eng.check_digit("MRKU469195") == 9)
    check("check ABCU123456 -> 0", eng.check_digit("ABCU123456") == 0)
    r = eng.adjudicate(
        [{c: 0.99} for c in "CSQU3054383"],
        frozenset("UJZ"), frozenset(), False, 20)
    check("exact CSQU3054383 unique", r.status == "unique" and r.total_candidates == 1)
    check("unique code value", r.ranked[0][0] == "CSQU3054383")
    check("unique score ~ 11*0.01005",
          abs(r.ranked[0][1] - 11 * (-math.log(0.99))) < 1e-9)

    # 2. Randomized differential tests vs brute force.
    rng = random.Random(20260920)
    owners = frozenset(["MSK", "CSQ", "TCL", "HLC", "ABC"])
    for trial in range(400):
        positions = random_positions(rng, width=3)
        enforce = trial % 3 == 0
        k = rng.choice([1, 5, 20])
        result = eng.adjudicate(
            positions, frozenset("UJZ"), owners, enforce, k)
        exp_top, exp_total = brute_force(
            positions, frozenset("UJZ"), owners, enforce, k)
        if result.total_candidates != exp_total:
            check(f"trial {trial} total", False,
                  f"got {result.total_candidates} want {exp_total}")
            failures += 1
            break
        got_top = [(c, round(s, 9)) for c, s, _ in result.ranked]
        want_top = [(c, round(s, 9)) for c, s in exp_top]
        if got_top != want_top:
            check(f"trial {trial} ranking (enforce={enforce}, k={k})", False,
                  f"\n got {got_top[:5]}\nwant {want_top[:5]}")
            failures += 1
            break
        # status consistency
        want_status = ("invalid" if exp_total == 0
                       else "unique" if exp_total == 1 else "ambiguous")
        if result.status != want_status:
            check(f"trial {trial} status", False,
                  f"got {result.status} want {want_status}")
            failures += 1
            break
    else:
        check("400 randomized differential trials", True)

    # 3. Total count must be independent of k (truncation).
    positions = random_positions(random.Random(7), width=4, bad=0.0)
    full = eng.adjudicate(positions, frozenset("UJZ"), owners, False, 2000)
    truncated = eng.adjudicate(positions, frozenset("UJZ"), owners, False, 5)
    check("total unaffected by truncation",
          full.total_candidates == truncated.total_candidates and
          len(truncated.ranked) == min(5, full.total_candidates) and
          full.total_candidates > 5)

    # 4. Tie-break: identical confidences => lexicographic ascending.
    positions = []
    for p in range(11):
        if p < 3:
            chars = list("ABCDE")
        elif p == 3:
            chars = list("UJZ")
        else:
            chars = list("01234")
        positions.append({c: 0.9 for c in chars})
    res = eng.adjudicate(positions, frozenset("UJZ"), frozenset(), False, 20)
    codes = [c for c, _, _ in res.ranked]
    check("tie-break lexicographic", codes == sorted(codes))
    # and the whole ranking cost must be non-decreasing
    costs = [s for _, s, _ in res.ranked]
    check("score non-decreasing", costs == sorted(costs))

    # 5. Category identifier restriction (pos 4).
    res = eng.adjudicate(
        [{c: 0.95} for c in "CSQX3054383"],
        frozenset("U"), frozenset(), False, 20)
    check("wrong category letter -> invalid", res.status == "invalid")
    res = eng.adjudicate(
        [{c: 0.95} for c in "CSQU3054383"],
        frozenset("U"), frozenset(), False, 20)
    check("allowed category U -> unique", res.status == "unique")

    # 6. Registry enforcement.
    res = eng.adjudicate(
        [{c: 0.95} for c in "ZZZZ0000000"],
        frozenset("UJZ"), owners, True, 20)
    check("unregistered owner rejected", res.status == "invalid")
    # build a registered-owner code whose check digit is 0..9
    serial = "000000"
    owner = next(
        code for code in ["MSK", "CSQ", "TCL", "HLC", "ABC"]
        if eng.check_digit(code + "U" + serial) != 10
    )
    prefix10 = owner + "U" + serial
    d = eng.check_digit(prefix10)
    positions = [{c: 0.95} for c in prefix10] + [{str(d): 0.95}]
    res = eng.adjudicate(positions, frozenset("UJZ"), owners, True, 20)
    check("registered owner prefix works",
          res.status == "unique" and res.ranked[0][0] == prefix10 + str(d))

    # 7. Check digit absent from OCR candidates -> invalid.
    good = "CSQU305438"
    d = eng.check_digit(good)
    positions = [{c: 0.95} for c in good]
    positions.append({"0" if d != 0 else "1": 0.95})
    res = eng.adjudicate(positions, frozenset("UJZ"), frozenset(), False, 20)
    check("missing check digit candidate -> invalid", res.status == "invalid")

    # 8. Remainder 10 never yields a valid 11th digit.
    found_ten = False
    rng2 = random.Random(1)
    for _ in range(2000):
        code10 = "".join(rng2.choice("ABCDEFGHIJKLMNPQRSTUVWXYZ" if p < 3
                                     else ("UJZ" if p == 3 else DIGITS))
                         for p in range(10))
        if eng.check_digit(code10) == 10:
            found_ten = True
            positions = [{c: 0.9} for c in code10]
            positions.append({d: 0.9 for d in DIGITS})
            res = eng.adjudicate(positions, frozenset("UJZ"),
                                 frozenset(), False, 20)
            check("remainder 10 excluded", res.status == "invalid")
            break
    check("a remainder-10 fixture exists", found_ten)

    # 9. Class-mismatched candidates are counted as dropped.
    positions = [{"C": 0.9, "3": 0.4}] + [{c: 0.9} for c in "SQU3054383"]
    res = eng.adjudicate(positions, frozenset("UJZ"), frozenset(), False, 20)
    check("dropped count", res.dropped[0] == 1 and res.total_candidates == 1)

    # 10. Duplicate candidate characters: highest confidence wins.
    positions = [{"C": 0.9}] + [{c: 0.9} for c in "SQU3054383"]
    # normalization happens in API; engine just receives maps.
    res = eng.adjudicate(positions, frozenset("UJZ"), frozenset(), False, 20)
    check("single-candidate map", res.total_candidates == 1)

    # 11. Bounded work: many candidates per position stays fast, exact total.
    # 11a. width-4 exhaustive cross-check.
    rng3 = random.Random(3)
    positions = []
    for p in range(11):
        if p < 3:
            pool = LETTERS
        elif p == 3:
            pool = "UJZ"
        else:
            pool = DIGITS
        chars = rng3.sample(pool, min(4, len(pool)))
        positions.append({c: rng3.uniform(0.1, 1.0) for c in chars})
    res = eng.adjudicate(positions, frozenset("UJZ"), owners, False, 20)
    exp = brute_force(positions, frozenset("UJZ"), owners, False, 20)
    check("width-4 exhaustive equality",
          res.total_candidates == exp[1] and
          [(c, round(s, 9)) for c, s, _ in res.ranked] ==
          [(c, round(s, 9)) for c, s in exp[0]],
          f"total={res.total_candidates}")

    # 11b. width-12 engine stress: dense independent DP re-count + invariants.
    rng4 = random.Random(11)
    positions = []
    product_bound = 1
    for p in range(11):
        if p < 3:
            pool = LETTERS
        elif p == 3:
            pool = "UJZ"
        else:
            pool = DIGITS
        chars = rng4.sample(pool, min(12, len(pool)))
        positions.append({c: rng4.uniform(0.1, 1.0) for c in chars})
        product_bound *= len(chars)
    import time
    t0 = time.time()
    res = eng.adjudicate(positions, frozenset("UJZ"), owners, False, 20)
    dt = time.time() - t0

    # Independent dense recount (plain dict transitions, not the engine's DP).
    states = {0: 1}
    for p in range(10):
        nxt: dict[int, int] = {}
        for r, n in states.items():
            for c in positions[p]:
                if eng._class_allowed(c, p, frozenset("UJZ")):
                    key = (r + eng.weighted_residue(c, p)) % 11
                    nxt[key] = nxt.get(key, 0) + n
        states = nxt
    dense_total = 0
    for r, n in states.items():
        d = str(r % 11)
        if d != "10" and d in positions[10] and "0" <= d <= "9":
            dense_total += n
    codes = [c for c, _, _ in res.ranked]
    well_formed = all(
        len(x) == 11 and x[:4].isalpha() and x[4:].isdigit()
        and x[3] in "UJZ" and eng.check_digit(x[:10]) == int(x[10])
        for x in codes
    )
    ordered = all(
        (res.ranked[i][1], res.ranked[i][0]) <=
        (res.ranked[i + 1][1], res.ranked[i + 1][0])
        for i in range(len(res.ranked) - 1)
    )
    check(f"width-12 stress exact+valid+ordered ({dt:.2f}s, "
          f"total={dense_total}, bound={product_bound})",
          res.total_candidates == dense_total and dense_total <= product_bound and
          len(res.ranked) == min(20, dense_total) and well_formed and ordered and
          dt < 5.0)

    print()
    print("FAILURES:", failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
