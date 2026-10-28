# INFT2060 Group 6: RAG over University of Newcastle policies

A retrieval-augmented generation (RAG) system that answers questions about 15 UON policies, compared against the same model without retrieval.

## Layout

- `data/corpus/` - the 15 policies as clean Markdown, plus `manifest.csv` (id, title, word count, source URL).
- `data/questions/test_set.csv` - 42 test questions: 14 Lookup, 14 Combine, 14 Unanswerable.
- `src/clean_policies.py` - downloads the policies from the UON Policy Library and rebuilds `data/corpus/`.
- `src/check_questions.py` - checks every source passage appears word for word in the corpus.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add the API key.
`.env` is ignored by git, so the key never leaves your machine.

## Usage

```bash
python src/clean_policies.py
python src/check_questions.py data/questions/test_set.csv
```
