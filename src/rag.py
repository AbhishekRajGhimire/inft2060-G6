"""The RAG pipeline: chunk the corpus, embed and index the chunks, retrieve, and ask the LLM.

Components (see the AI Project Tool Access Guide):
    - embeddings: text-embedding-ada-002 through the UON AI Sandbox
    - vector index: Chroma, in memory, cosine distance
    - LLM: gpt-4o-mini through the UON AI Sandbox (OpenAI-compatible API)

Both can run locally instead if the Sandbox is down: change the EMBED_MODEL line
to MINILM (sentence-transformers, free) and the LLM line to OLLAMA (needs
`ollama pull qwen2.5:7b`). Use the same LLM for the baseline and the RAG run.
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
SANDBOX = (SANDBOX_URL, "gpt-4o-mini")
OLLAMA = ("http://localhost:11434/v1", "qwen2.5:7b")
LLM_BASE_URL, LLM_MODEL = SANDBOX  # change to OLLAMA to run locally

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
    (c). Chunks over MAX_CHUNK_WORDS are split at block boundaries. Each chunk is
    labelled with the policy title and the headings it sits under.
    """
    title, blocks = read_policy(path)
    headings = {}  # heading level -> text
    groups = []    # (heading path, [blocks])
    for block in blocks:
        if block.startswith("# "):
            continue
        if block.startswith("#"):
            level = len(block) - len(block.lstrip("#"))
            headings = {lvl: text for lvl, text in headings.items() if lvl < level}
            headings[level] = block.lstrip("#").strip()
            groups.append(None)  # a heading always ends the current chunk
            continue
        attaches = block.startswith(("- ", "|")) and groups and groups[-1] is not None
        if attaches:
            groups[-1][1].append(block)
        else:
            groups.append((" > ".join(headings[lvl] for lvl in sorted(headings)), [block]))

    chunks = []
    for group in filter(None, groups):
        heading, parts = group
        for piece in split_long(parts):
            chunks.append({
                "id": f"{path.stem}#{len(chunks) + 1}",
                "source_document": path.name,
                "label": f"{title} > {heading}" if heading else title,
                "text": piece,
            })
    return chunks


def split_long(blocks: list[str]) -> list[str]:
    """Join blocks into pieces of at most MAX_CHUNK_WORDS (a single longer block stays whole)."""
    pieces, current = [], []
    for line in "\n".join(blocks).split("\n"):
        if current and len(" ".join(current + [line]).split()) > MAX_CHUNK_WORDS:
            pieces.append("\n".join(current))
            current = []
        current.append(line)
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


def embed_hosted(texts: list[str]) -> list[list[float]]:
    """Embed through the Sandbox, 64 texts per request, reusing vectors saved in EMBED_CACHE."""
    global _embed_cache
    if _embed_cache is None:
        _embed_cache = {}
        if EMBED_CACHE.exists():
            saved = np.load(EMBED_CACHE)
            _embed_cache = dict(zip(saved["keys"], saved["vectors"]))

    def key(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    missing = [text for text in dict.fromkeys(texts) if key(text) not in _embed_cache]
    for start in range(0, len(missing), 64):
        batch = missing[start:start + 64]
        result = client(SANDBOX_URL).embeddings.create(model=EMBED_MODEL, input=batch)
        for text, item in zip(batch, result.data):
            _embed_cache[key(text)] = np.array(item.embedding, dtype=np.float32)
    if missing:
        EMBED_CACHE.parent.mkdir(exist_ok=True)
        np.savez_compressed(EMBED_CACHE, keys=np.array(list(_embed_cache)), vectors=np.stack(list(_embed_cache.values())))
    return [_embed_cache[key(text)].tolist() for text in texts]


def build_index(chunks: list[dict]):
    """Embed every chunk and add it to a fresh in-memory Chroma collection."""
    documents = [chunk_document(chunk) for chunk in chunks]
    collection = chromadb.Client().get_or_create_collection("policies", metadata={"hnsw:space": "cosine"})
    collection.add(ids=[chunk["id"] for chunk in chunks], embeddings=embed(documents), documents=documents)
    return collection


def retrieve(collection, question: str, k: int = TOP_K) -> list[tuple[str, str, float]]:
    """Return the k closest chunks as (id, document text, cosine distance)."""
    result = collection.query(query_embeddings=embed([question]), n_results=k)
    return list(zip(result["ids"][0], result["documents"][0], result["distances"][0]))


# --- LLM -------------------------------------------------------------------

_clients = {}


def read_api_key() -> str:
    """The key lives in .env (never in the code), as LLM_API_KEY=..."""
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        name, _, value = line.partition("=")
        if name.strip() == "LLM_API_KEY" and value.strip():
            return value.strip()
    raise SystemExit("No API key: copy .env.example to .env and fill in LLM_API_KEY.")


def client(base_url: str) -> openai.OpenAI:
    """An OpenAI-compatible client for the Sandbox or for a local Ollama server."""
    if base_url not in _clients:
        _clients[base_url] = openai.OpenAI(
            api_key="ollama" if base_url == OLLAMA[0] else read_api_key(),
            base_url=base_url,
            # From the Tool Access Guide: avoids blocks by the university firewall.
            default_headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:100.0) Gecko/20100101 Firefox/100.0"},
        )
    return _clients[base_url]


def ask_llm(prompt: str) -> str:
    response = client(LLM_BASE_URL).chat.completions.create(
        model=LLM_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=300)
    return response.choices[0].message.content.strip()


def rag_prompt(question: str, retrieved: list[tuple[str, str, float]]) -> str:
    context = "\n\n".join(document for _, document, _ in retrieved)
    return RAG_PROMPT.format(decline=DECLINE, context=context, question=question)


def baseline_prompt(question: str) -> str:
    return BASELINE_PROMPT.format(question=question)
