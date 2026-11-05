"""Print the report tables from a hand-scored results file.

Scores are one of: correct, partly correct, incorrect, declined.
On an unanswerable question, declining is the right answer, so the tables count
"declined" there as correct. The CSV itself is left as the scorers wrote it.
failure_type is "retrieval" or "generation" for RAG answers that are not correct,
and blank or "none" otherwise.

Usage:
    python src/summarise_results.py results/results.csv
"""

import csv
import sys
from collections import Counter, defaultdict

SCORES = ["correct", "partly correct", "incorrect", "declined"]
COLUMNS = SCORES + ["not scored"]


def score_table(rows: list[dict], column: str) -> None:
    """Print how many answers got each score, per tier and in total."""
    by_tier = defaultdict(Counter)  # tier -> {score: number of answers}
    total = Counter()
    unrecognised = set()
    for row in rows:
        score = row[column].strip().lower() or "not scored"
        if row["tier"] == "3 Unanswerable" and score == "declined":
            score = "correct"  # refusing is the right answer when the policies do not say
        if score not in COLUMNS:
            unrecognised.add(score)
        by_tier[row["tier"]][score] += 1
        total[score] += 1

    print(f"\n{column.replace('_', ' ')}:")
    print(f"  {'tier':<16}" + "".join(f"{name:>16}" for name in COLUMNS))
    for tier in sorted(by_tier):
        print(f"  {tier:<16}" + "".join(f"{by_tier[tier][name]:>16}" for name in COLUMNS))
    print(f"  {'All':<16}" + "".join(f"{total[name]:>16}" for name in COLUMNS))
    if unrecognised:
        print(f"  Unrecognised scores (fix these): {sorted(unrecognised)}")


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

    print('\nOn Unanswerable questions, "declined" is counted as correct.')

    failure_types = [row["failure_type"].strip().lower() for row in rows]
    failures = Counter(failure for failure in failure_types if failure not in ("", "none"))
    print("\nRAG failure types:", dict(failures) or "none recorded")


if __name__ == "__main__":
    main()
