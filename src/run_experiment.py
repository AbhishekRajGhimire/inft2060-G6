"""Run the test set through the baseline (no retrieval) and the RAG pipeline.

Writes results/results.csv in the course's column layout. The score and failure
columns are left blank for hand scoring. Every LLM answer is saved in
results/llm_cache.jsonl, so a rerun only pays for prompts it has not sent before.

Usage:
    python src/run_experiment.py --retrieval-only   # hit rate only, no LLM calls
    python src/run_experiment.py --limit 3          # try the first 3 questions
    python src/run_experiment.py                    # the full test set
"""

import argparse
import csv
import json
from collections import Counter, defaultdict

import rag

TEST_SET = rag.ROOT / "data" / "questions" / "test_set.csv"
RESULTS_DIR = rag.ROOT / "results"
RESULTS = RESULTS_DIR / "results.csv"
CHUNKS = RESULTS_DIR / "chunks.csv"
CACHE = RESULTS_DIR / "llm_cache.jsonl"
COLUMNS = ["question_id", "tier", "question", "reference_answer", "source_document", "source_passage",
           "retrieved_chunks", "hit", "baseline_answer", "baseline_score", "rag_answer", "rag_score",
           "failure_type", "notes"]
SCORE_COLUMNS = ["baseline_score", "rag_score", "failure_type"]


def hit(question: dict, retrieved: list[dict], chunks: dict) -> str:
    """Did retrieval find the question's source passages?

    A passage counts as found when it appears word for word in a retrieved chunk from
    the right document. Returns 'yes' if all passages were found, 'partial' if some
    were, 'no' if none were, and 'n/a' for unanswerable questions (no passages).
    """
    if question["source_passage"] == "(none)":
        return "n/a"
    documents = question["source_document"].split(" | ")
    passages = question["source_passage"].split(" | ")
    retrieved_chunks = [chunks[result["id"]] for result in retrieved]

    found = 0
    for document, passage in zip(documents, passages):
        for chunk in retrieved_chunks:
            if chunk["source_document"] == document and passage in chunk["text"]:
                found += 1
                break

    if found == len(passages):
        return "yes"
    if found > 0:
        return "partial"
    return "no"


class Cache:
    """LLM answers saved to disk, keyed by model and exact prompt."""

    def __init__(self):
        self.answers = {}
        if CACHE.exists():
            for line in CACHE.read_text(encoding="utf-8").splitlines():
                entry = json.loads(line)
                self.answers[(entry["model"], entry["prompt"])] = entry["answer"]

    def ask(self, prompt: str) -> str:
        key = (rag.LLM_MODEL, prompt)
        if key not in self.answers:
            print(f"  asking {rag.LLM_MODEL}...")
            self.answers[key] = rag.ask_llm(prompt)
            with open(CACHE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"model": rag.LLM_MODEL, "prompt": prompt, "answer": self.answers[key]}) + "\n")
        return self.answers[key]


def check_not_scored() -> None:
    """Stop before overwriting a results file that someone has started scoring."""
    if not RESULTS.exists():
        return
    with open(RESULTS, newline="", encoding="utf-8-sig") as f:
        if any(row.get(column, "").strip() for row in csv.DictReader(f) for column in SCORE_COLUMNS):
            raise SystemExit(f"{RESULTS.name} already has scores in it. Move it elsewhere first, or rerun with --force.")


def print_hit_rate(rows: list[dict]) -> None:
    by_tier = defaultdict(Counter)
    for row in rows:
        if row["hit"] != "n/a":
            by_tier[row["tier"]][row["hit"]] += 1
    print(f"\nRetrieval hit rate (top {rag.TOP_K}):")
    for tier, counts in sorted(by_tier.items()):
        total = sum(counts.values())
        print(f"  {tier:<12} {counts['yes']}/{total} hit ({counts['yes'] / total:.0%}), {counts['partial']} partial, {counts['no']} missed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true", help="measure the hit rate without calling the LLM")
    parser.add_argument("--limit", type=int, help="only run the first N questions")
    parser.add_argument("--force", action="store_true", help="overwrite results.csv even if it has scores")
    args = parser.parse_args()

    with open(TEST_SET, newline="", encoding="utf-8-sig") as f:
        questions = list(csv.DictReader(f))[:args.limit]
    if not args.retrieval_only and not args.force:
        check_not_scored()

    RESULTS_DIR.mkdir(exist_ok=True)
    chunk_list = rag.load_chunks()
    chunks = {chunk["id"]: chunk for chunk in chunk_list}
    print(f"Indexing {len(chunk_list)} chunks with {rag.EMBED_MODEL}...")
    collection = rag.build_index(chunk_list)
    rag.embed([question["question"] for question in questions])  # one batched request
    rag.save_embeddings()
    cache = Cache()

    rows = []
    for question in questions:
        retrieved = rag.retrieve(collection, question["question"])
        row = {column: question.get(column, "") for column in COLUMNS}
        row["retrieved_chunks"] = " | ".join(result["id"] for result in retrieved)
        row["hit"] = hit(question, retrieved, chunks)
        if not args.retrieval_only:
            print(question["question_id"])
            row["baseline_answer"] = cache.ask(rag.baseline_prompt(question["question"]))
            row["rag_answer"] = cache.ask(rag.rag_prompt(question["question"], retrieved))
        rows.append(row)
    print_hit_rate(rows)
    if args.retrieval_only:
        for row in rows:
            if row["hit"] in ("no", "partial"):
                print(f"  {row['hit']:<7} {row['question_id']}: {row['question'][:90]}")
        return

    with open(RESULTS, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    with open(CHUNKS, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "source_document", "label", "text"])
        writer.writeheader()
        writer.writerows(chunk_list)
    print(f"\nWrote {len(rows)} rows to {RESULTS.relative_to(rag.ROOT)} (look up chunk ids in {CHUNKS.name})")


if __name__ == "__main__":
    main()
