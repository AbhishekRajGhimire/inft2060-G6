"""The RAG pipeline: chunk the corpus, embed and index the chunks, retrieve, and ask the LLM.

Components (see the AI Project Tool Access Guide):
    - embeddings: text-embedding-ada-002 through the UON AI Sandbox
    - vector index: Chroma, in memory, cosine distance
    - LLM: gpt-4o-mini through the UON AI Sandbox (OpenAI-compatible API)

If the Sandbox is down, embeddings can run locally: change the EMBED_MODEL line
to MINILM (sentence-transformers, free). Use the same LLM for the baseline and
the RAG run.
"""

import hashlib
import re
from pathlib import Path

import chromadb
import numpy as np
import openai

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "data" / "corpus"

SANDBOX_URL = "https://aisandbox-admin.newcastle.edu.au/"
LLM_MODEL = "gpt-4o-mini"

ADA = "text-embedding-ada-002"
MINILM = "all-MiniLM-L6-v2"
EMBED_MODEL = ADA  # change to MINILM to embed locally
# Hosted embeddings are saved here, so each text is only paid for once.
EMBED_CACHE = ROOT / "results" / f"embeddings_{EMBED_MODEL}.npz"

TOP_K = 5
# MiniLM reads only about the first 200 words of a text, so longer chunks are split.
# Both embedding models use the same chunks, so their hit rates can be compared.
MAX_CHUNK_WORDS = 200

DECLINE = "I don't know based on the provided policies."

RAG_PROMPT = """You answer questions about University of Newcastle policies.
Answer the question using only the context below, in at most three sentences, and name the policy your answer comes from.
If the context does not contain the answer, reply exactly: {decline}

Context:
{context}

Question: {question}"""

BASELINE_PROMPT = """You answer questions about University of Newcastle policies.
Answer the question in at most three sentences.
If you do not know the answer, reply exactly: I don't know.

Question: {question}"""


# --- Chunking ---------------------------------------------------------------

def read_policy(path: Path) -> tuple[str, list[str]]:
    """Return (title, body blocks) for a corpus file; blocks are separated by blank lines."""
    _, front_matter, body = path.read_text(encoding="utf-8").split("---", 2)
    title = re.search(r"^title: (.+)$", front_matter, re.M).group(1).strip()
    return title, [block.strip() for block in body.split("\n\n") if block.strip()]


def chunk_policy(path: Path) -> list[dict]:
    """Split one policy into chunks of whole clauses.

    A chunk starts at each paragraph (usually a numbered clause) and keeps the lists
    and tables that follow it, so "(16) Library members have:" stays with its (a), (b),
    (c). Chunks over MAX_CHUNK_WORDS are split between lines. Each chunk is labelled
    with the policy title and the headings it sits under.
    """
    title, blocks = read_policy(path)
    headings = {}   # heading level (2 for ##, 3 for ###, ...) -> heading text
    clauses = []    # each clause: the headings it sits under, and its blocks
    current = None  # the clause being built; None right after a heading

    for block in blocks:
        if block.startswith("# "):
            continue  # the policy title, which is already in every label

        if block.startswith("#"):
            # A new heading replaces any heading at the same or a deeper level.
            level = len(block) - len(block.lstrip("#"))
            headings = {lvl: text for lvl, text in headings.items() if lvl < level}
            headings[level] = block.lstrip("#").strip()
            current = None  # a heading always ends the current clause
            continue

        is_list_or_table = block.startswith("- ") or block.startswith("|")
        if is_list_or_table and current is not None:
            current["blocks"].append(block)  # belongs to the clause above it
        else:
            heading_path = " > ".join(headings[level] for level in sorted(headings))
            current = {"headings": heading_path, "blocks": [block]}
            clauses.append(current)

    chunks = []
    for clause in clauses:
        label = f"{title} > {clause['headings']}" if clause["headings"] else title
        for piece in split_long(clause["blocks"]):
            chunks.append({
                "id": f"{path.stem}#{len(chunks) + 1}",
                "source_document": path.name,
                "label": label,
                "text": piece,
            })
    return chunks


def split_long(blocks: list[str]) -> list[str]:
    """Join a clause's blocks into pieces of at most MAX_CHUNK_WORDS words.

    It only splits between lines, so a single line longer than the limit stays whole.
    """
    pieces = []
    current = []
    current_words = 0
    for line in "\n".join(blocks).split("\n"):
        line_words = len(line.split())
        if current and current_words + line_words > MAX_CHUNK_WORDS:
            pieces.append("\n".join(current))
            current = []
            current_words = 0
        current.append(line)
        current_words += line_words
    pieces.append("\n".join(current))
    return pieces


def load_chunks() -> list[dict]:
    return [chunk for path in sorted(CORPUS_DIR.glob("*.md")) for chunk in chunk_policy(path)]


def chunk_document(chunk: dict) -> str:
    """The text that is embedded and shown to the LLM: label line, then the chunk."""
    return f"[{chunk['label']}]\n{chunk['text']}"


# --- Embedding and retrieval ------------------------------------------------

_embedder = None
_embed_cache = None
_unsaved_embeddings = False


def embed(texts: list[str]) -> list[list[float]]:
    if EMBED_MODEL == MINILM:
        return embed_locally(texts)
    return embed_hosted(texts)


def embed_locally(texts: list[str]) -> list[list[float]]:
    global _embedder
    if _embedder is None:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer(MINILM)
    return _embedder.encode(texts).tolist()


def text_key(text: str) -> str:
    """A short fingerprint of a text, used to look it up in the embedding cache."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_hosted(texts: list[str]) -> list[list[float]]:
    """Embed through the Sandbox, reusing any vectors already saved in EMBED_CACHE.

    New vectors are kept in memory; call save_embeddings() to write them to disk.
    """
    global _embed_cache, _unsaved_embeddings
    if _embed_cache is None:
        _embed_cache = {}  # text_key -> vector
        if EMBED_CACHE.exists():
            saved = np.load(EMBED_CACHE)
            for key, vector in zip(saved["keys"], saved["vectors"]):
                _embed_cache[key] = vector

    # Only texts that are not in the cache yet are sent, each once.
    missing = []
    for text in texts:
        if text_key(text) not in _embed_cache and text not in missing:
            missing.append(text)

    # The Sandbox accepts a list of texts, so send them 64 at a time.
    for start in range(0, len(missing), 64):
        batch = missing[start:start + 64]
        result = sandbox().embeddings.create(model=EMBED_MODEL, input=batch)
        for text, item in zip(batch, result.data):
            _embed_cache[text_key(text)] = np.array(item.embedding, dtype=np.float32)
            _unsaved_embeddings = True
    return [_embed_cache[text_key(text)].tolist() for text in texts]


def save_embeddings() -> None:
    """Write any new Sandbox embeddings to EMBED_CACHE, so they are only paid for once."""
    global _unsaved_embeddings
    if not _unsaved_embeddings:
        return
    EMBED_CACHE.parent.mkdir(exist_ok=True)
    np.savez_compressed(
        EMBED_CACHE,
        keys=np.array(list(_embed_cache.keys())),
        vectors=np.stack(list(_embed_cache.values())),
    )
    _unsaved_embeddings = False


def build_index(chunks: list[dict]):
    """Embed every chunk and add it to a fresh in-memory Chroma collection."""
    documents = [chunk_document(chunk) for chunk in chunks]
    collection = chromadb.Client().get_or_create_collection("policies", metadata={"hnsw:space": "cosine"})
    collection.add(ids=[chunk["id"] for chunk in chunks], embeddings=embed(documents), documents=documents)
    return collection


def retrieve(collection, question: str, k: int = TOP_K) -> list[dict]:
    """Return the k chunks closest to the question, closest first.

    Each result has the chunk's id, its document (label line and text, as embedded)
    and its cosine distance to the question (0 means identical).
    """
    result = collection.query(query_embeddings=embed([question]), n_results=k)
    retrieved = []
    for chunk_id, document, distance in zip(result["ids"][0], result["documents"][0], result["distances"][0]):
        retrieved.append({"id": chunk_id, "document": document, "distance": distance})
    return retrieved


# --- LLM -------------------------------------------------------------------

_client = None


def read_api_key() -> str:
    """The key lives in .env (never in the code), as LLM_API_KEY=..."""
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        name, _, value = line.partition("=")
        if name.strip() == "LLM_API_KEY" and value.strip():
            return value.strip()
    raise SystemExit("No API key: copy .env.example to .env and fill in LLM_API_KEY.")


def sandbox() -> openai.OpenAI:
    """The client for the UON AI Sandbox, which works like the OpenAI API."""
    global _client
    if _client is None:
        _client = openai.OpenAI(
            api_key=read_api_key(),
            base_url=SANDBOX_URL,
            # From the Tool Access Guide: avoids blocks by the university firewall.
            default_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:100.0) Gecko/20100101 Firefox/100.0"},
        )
    return _client


def ask_llm(prompt: str) -> str:
    response = sandbox().chat.completions.create(
        model=LLM_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=300)
    return response.choices[0].message.content.strip()


def rag_prompt(question: str, retrieved: list[dict]) -> str:
    context = "\n\n".join(chunk["document"] for chunk in retrieved)
    return RAG_PROMPT.format(decline=DECLINE, context=context, question=question)


def baseline_prompt(question: str) -> str:
    return BASELINE_PROMPT.format(question=question)
