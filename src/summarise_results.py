"""Print the report tables from a hand-scored results file.

Scores are one of: correct, partly correct, incorrect, declined (for unanswerable
questions, declining is the correct outcome, as in the Week 8 lecture).
failure_type is "retrieval" or "generation" for RAG answers that are not correct.

Usage:
    python src/summarise_results.py results/results.csv
"""

import csv
import sys
from collections import Counter, defaultdict

SCORES = ["correct", "partly correct", "incorrect", "declined"]


def score_table(rows: list[dict], column: str) -> None:
    by_tier = defaultdict(Counter)
    for row in rows:
        by_tier[row["tier"]][row[column].strip().lower() or "not scored"] += 1
    print(f"\n{column.replace('_', ' ')}:")
    print(f"  {'tier':<16}" + "".join(f"{score:>16}" for score in SCORES + ["not scored"]))
    for tier in sorted(by_tier) + ["All"]:
        counts = by_tier[tier] if tier != "All" else sum(by_tier.values(), Counter())
        print(f"  {tier:<16}" + "".join(f"{counts[score]:>16}" for score in SCORES + ["not scored"]))
    other = set().union(*by_tier.values()) - set(SCORES) - {"not scored"}
    if other:
        print(f"  Unrecognised scores (fix these): {sorted(other)}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print("Retrieval hit rate (all source passages retrieved):")
    for tier in sorted({row["tier"] for row in rows if row["hit"] != "n/a"}):
        hits = [row["hit"] for row in rows if row["tier"] == tier]
        print(f"  {tier:<16} {hits.count('yes')}/{len(hits)} ({hits.count('yes') / len(hits):.0%}), "
              f"{hits.count('partial')} partial")

    score_table(rows, "baseline_score")
    score_table(rows, "rag_score")

    failures = Counter(row["failure_type"].strip().lower() for row in rows if row["failure_type"].strip())
    print("\nRAG failure types:", dict(failures) or "none recorded")


if __name__ == "__main__":
    main()
