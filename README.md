# INFT2060 Group 6: RAG over University of Newcastle policies

A retrieval-augmented generation (RAG) system that answers questions about 15 UON policies, compared against the same model without retrieval.

## Pipeline

- Chunks: one numbered clause per chunk (with its lists and tables), labelled with the policy and section, at most 200 words.
- Embeddings: `text-embedding-ada-002` through the UON AI Sandbox. `all-MiniLM-L6-v2` (local) is the backup, one line to switch in `src/rag.py`.
- Vector index: Chroma, cosine distance, top 5 chunks per question.
- LLM: `gpt-4o-mini` through the UON AI Sandbox, temperature 0, for both the baseline and RAG.

## Layout

- `data/corpus/` - the 15 policies as clean Markdown, plus `manifest.csv` (id, title, word count, source URL).
- `data/questions/test_set.csv` - 42 test questions: 14 Lookup, 14 Combine, 14 Unanswerable.
- `src/rag.py` - chunking, embedding, retrieval, prompts and the LLM call. Settings are at the top.
- `src/run_experiment.py` - runs the test set through the baseline and RAG, writes `results/results.csv`.
- `src/summarise_results.py` - prints hit rate and score tables from a hand-scored results file.
- `src/clean_policies.py` - downloads the policies from the UON Policy Library and rebuilds `data/corpus/`.
- `src/check_questions.py` - checks every source passage appears word for word in the corpus.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add the group's Sandbox key.
`.env` is ignored by git, so the key never ends up in the repo or in Appendix A.

## Running the experiment

```bash
python src/run_experiment.py --retrieval-only
python src/run_experiment.py --limit 3
python src/run_experiment.py
```

The first command measures the retrieval hit rate without asking the LLM.
The second tries the first 3 questions.
The third runs all 42.

Every embedding is saved in `results/embeddings_text-embedding-ada-002.npz` and every answer in `results/llm_cache.jsonl`, so rerunning only pays for text and prompts that have changed.
The key's budget is shared by the group, so try small runs first.

## Scoring

Fill in `baseline_score` and `rag_score` in `results/results.csv` with one of: correct, partly correct, incorrect, declined.
For unanswerable questions, declining is correct.
For RAG answers that are not correct, set `failure_type` to retrieval (hit is not "yes") or generation (hit is "yes").
Retrieved chunk ids can be looked up in `results/chunks.csv`.

```bash
python src/summarise_results.py results/results.csv
```

`run_experiment.py` refuses to overwrite a results file that has scores in it.
