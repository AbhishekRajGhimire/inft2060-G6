# How to run

A short guide for the group.
Most of you only need Part 1 (scoring), which needs no setup at all.

## Part 1: Score the answers (no setup needed)

1. On the GitHub page, open `results/results.csv` and click the download button, or download the whole repo with **Code > Download ZIP**.
2. Open `results.csv` in Excel.
3. For each question, fill in these three columns:

| Column | What to write |
|---|---|
| `baseline_score` | correct, partly correct, incorrect or declined |
| `rag_score` | correct, partly correct, incorrect or declined |
| `failure_type` | Only when the RAG answer is not correct: retrieval or generation |

- Compare each answer with `reference_answer`.
- For unanswerable questions (tier 3), "declined" is the right outcome.
- `failure_type` is retrieval if the `hit` column is not "yes", and generation if it is "yes" but the answer is still wrong.
- Score the answer itself, not the `hit` column: some answers are right even when `hit` says "partial", because the model found the fact in a nearby clause.
- To see what text was retrieved, look up the ids from `retrieved_chunks` in `results/chunks.csv`.

4. Save with **File > Save As > CSV UTF-8 (Comma delimited)**.
Plain "CSV" can break special characters such as curly quotes.

## Part 2: Run the code yourself (optional)

You only need this to rerun the experiment or make the report tables.

### One-time setup

1. Install Python 3.10 or newer from python.org.
On Windows, tick "Add Python to PATH" during installation.
2. Get the code, either with **Code > Download ZIP** on GitHub (then unzip it), or with:

```bash
git clone https://github.com/AbhishekRajGhimire/inft2060-G6
```

3. Open a terminal in the project folder and install the packages:

```bash
pip install -r requirements.txt
```

4. Only if you will ask the AI new questions: copy `.env.example` to a new file called `.env` and paste the group key after `LLM_API_KEY=`.
Ask Abhishek for the key.
Never put the key on GitHub or anywhere outside the group.

### Make the report tables

After everyone's scores are in `results/results.csv`:

```bash
python src/summarise_results.py results/results.csv
```

This prints the hit rate and how many answers got each score, per tier.
If it lists "Unrecognised scores", fix those typos in the CSV and run it again.

### Ask your own questions

```bash
python src/ask.py
```

Type a question and press Enter to get an answer and the policy sections it came from.
Press Enter on an empty line to quit.
This needs the key (step 4 of the setup), and each question uses a little of the group's budget, so keep it to demos and report examples.
It does not change the experiment results.

### Rerun the experiment

```bash
python src/run_experiment.py
```

All embeddings and answers are saved in the repo, so this costs nothing and needs no key unless you changed a question or a prompt.
It refuses to overwrite a results file that already has scores in it, so your scoring is safe.

## If something goes wrong

| Problem | Fix |
|---|---|
| `python` is not recognised | Try `py` instead of `python`, or reinstall Python with "Add Python to PATH" ticked |
| "No API key" | You need the `.env` file from step 4 of the setup |
| Error 401 | The key in `.env` is wrong; copy it again |
| Error 403 or an HTML page | The university firewall blocked it; try again on campus |
| Anything else | Message Abhishek in the group chat |
