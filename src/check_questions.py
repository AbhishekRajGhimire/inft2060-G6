"""Check a test-question CSV against the cleaned corpus.

For every answerable question, each source passage must appear word for word in the
Markdown file named in source_document, otherwise the retrieval hit rate cannot be
measured. Multiple documents and passages are separated by " | " and paired in order.
Unanswerable questions must use "(none)" for both columns. The file must have the
seven columns in COLUMNS.

Usage:
    python src/check_questions.py data/questions/test_set.csv
"""

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus"
NONE = "(none)"
# The columns people fill in; the pipeline adds its own result columns later.
COLUMNS = ["question_id", "tier", "question", "reference_answer", "source_document", "source_passage", "notes"]


def split_field(value: str) -> list[str]:
    return [part.strip() for part in value.split(" | ")]


def check_row(row: dict) -> list[str]:
    """Return a list of problems with one question (empty if it is fine)."""
    documents = split_field(row["source_document"])
    passages = split_field(row["source_passage"])
    if row["tier"].lower().endswith("unanswerable"):
        if documents != [NONE] or passages != [NONE]:
            return ["unanswerable question should use (none) for source_document and source_passage"]
        return []
    if len(documents) != len(passages):
        return [f"{len(documents)} documents but {len(passages)} passages"]

    problems = []
    for document, passage in zip(documents, passages):
        path = CORPUS_DIR / document
        if not path.exists():
            problems.append(f"document not found: {document}")
        elif passage not in path.read_text(encoding="utf-8"):
            problems.append(f"passage not found verbatim in {document}: {passage[:60]}...")
    return problems


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [column for column in COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"Missing columns: {', '.join(missing)}. Expected: {', '.join(COLUMNS)}.")
        rows = list(reader)

    failures = 0
    for row in rows:
        problems = check_row(row)
        failures += bool(problems)
        status = "OK  " if not problems else "FAIL"
        print(f"{status} {row['question_id']:<8} {row['tier']}")
        for problem in problems:
            print(f"       - {problem}")

    print("Questions per tier:", dict(Counter(row["tier"] for row in rows)))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
