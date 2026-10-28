"""Download University of Newcastle policy pages and convert them to clean Markdown.

Every policy in the UON Policy Library (https://policies.newcastle.edu.au) uses the
same HTML template, so one converter handles all of them:

    - top-level sections ("Section 5 - Conditions of Use")  -> ## headings
    - sub-headings inside a section ("Borrowing")           -> ### headings (and #### below)
    - numbered clauses ("(12) ...")                         -> paragraphs, number kept
    - lists                                                 -> (a), (b) / (i), (ii) items
    - tables                                                -> Markdown tables

Page clutter is dropped: navigation menus, "Top of Page" links, the status banner,
the footer, link targets (only the visible link text is kept) and the hover-only
definition pop-ups (<abbrev title="...">) whose text is not shown on the page.

Raw HTML is cached in data/raw so a rerun converts the exact same pages.
Use --refresh to download them again.

Usage:
    python src/clean_policies.py                 # default: all 15 corpus documents
    python src/clean_policies.py 116 88 --refresh
"""

import argparse
import csv
import datetime as dt
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE_URL = "https://policies.newcastle.edu.au/document/view-current.php?id={doc_id}"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CORPUS_DIR = ROOT / "data" / "corpus"

# The 15 policies in the group corpus
DEFAULT_DOC_IDS = [21, 27, 34, 35, 88, 116, 204, 258, 278, 336, 353, 359, 360, 361, 392]

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
SKIP_CLASSES = {"top-link", "sliph-document-status"}
SKIP_IDS = {"document-top"}


def fetch_html(doc_id: int, refresh: bool) -> Path:
    """Return the path to the cached HTML for a policy, downloading it if needed."""
    path = RAW_DIR / f"{doc_id}.html"
    if refresh or not path.exists():
        response = requests.get(
            BASE_URL.format(doc_id=doc_id),
            headers={"User-Agent": "Mozilla/5.0 (INFT2060 student project)"},
            timeout=30,
        )
        response.raise_for_status()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    return path


def clean_text(text: str) -> str:
    """Normalise whitespace: non-breaking spaces become spaces, runs collapse to one."""
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"\s+", " ", text)
    # Tags split across lines can leave a space before punctuation ("policy ,").
    text = re.sub(r" ([,.;:)])", r"\1", text)
    return text.strip()


def should_skip(tag: Tag) -> bool:
    classes = set(tag.get("class") or [])
    return bool(classes & SKIP_CLASSES) or tag.get("id") in SKIP_IDS


def inline_text(node) -> str:
    """Visible text of an element, ignoring nested lists (they are rendered separately)."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag) or should_skip(node) or node.name in ("ol", "ul"):
        return ""
    if node.name == "br":
        return " "
    return "".join(inline_text(child) for child in node.children)


def to_roman(n: int) -> str:
    numerals = [(10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for value, symbol in numerals:
        while n >= value:
            out += symbol
            n -= value
    return out


def list_label(list_tag: Tag, depth: int, index: int) -> str:
    """Match the website's numbering: (a), (b) at the first level, (i), (ii) below it, plain bullets deeper."""
    if list_tag.name == "ul" or depth > 1:
        return ""
    if depth == 0:
        return f"({chr(ord('a') + index)}) "
    return f"({to_roman(index + 1)}) "


def render_list(list_tag: Tag, depth: int = 0) -> list[str]:
    lines = []
    indent = "  " * depth
    for index, item in enumerate(list_tag.find_all("li", recursive=False)):
        text = clean_text(inline_text(item))
        lines.append(f"{indent}- {list_label(list_tag, depth, index)}{text}")
        for nested in item.find_all(["ol", "ul"], recursive=False):
            lines.extend(render_list(nested, depth + 1))
    return lines


def render_table(table: Tag) -> list[str]:
    rows = []
    for tr in table.find_all("tr"):
        cells = [clean_text(inline_text(cell)).replace("|", "\\|") for cell in tr.find_all(["th", "td"])]
        rows.append(cells)
    if not rows:
        return []
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
    return lines


def heading_map(container: Tag) -> dict[str, str]:
    """Map the heading tags a policy uses to ##, ###, ... by rank.

    Policies differ: some use h1 for sections and h3 below them, others h2 and h3, so
    ranking the levels actually present gives every file the same Markdown structure.
    """
    used = sorted({tag.name for tag in container.find_all(HEADING_TAGS)}, key=HEADING_TAGS.index)
    return {name: "#" * (rank + 2) for rank, name in enumerate(used)}


def render_blocks(container: Tag, headings: dict[str, str]) -> list[str]:
    """Convert the policy body into Markdown blocks (each block is a list of lines)."""
    blocks = []
    for child in container.children:
        if not isinstance(child, Tag) or should_skip(child):
            continue
        if child.name in headings:
            blocks.append([f"{headings[child.name]} {clean_text(inline_text(child))}"])
        elif child.name in ("ol", "ul"):
            blocks.append(render_list(child))
        elif child.name == "table":
            blocks.append(render_table(child))
        elif child.name == "div":
            blocks.extend(render_blocks(child, headings))
        else:
            text = clean_text(inline_text(child))
            if text:
                blocks.append([text])
    return [block for block in blocks if block]


def convert(html_path: Path, doc_id: int) -> tuple[str, str]:
    """Return (title, markdown) for one cached policy page."""
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    title = clean_text(soup.find(id="sliph-document-title").get_text())
    content = soup.find(id="sliph-document-content")
    retrieved = dt.date.fromtimestamp(html_path.stat().st_mtime).isoformat()

    front_matter = [
        "---",
        f"title: {title}",
        f"doc_id: {doc_id}",
        f"source_url: {BASE_URL.format(doc_id=doc_id)}",
        f"retrieved: {retrieved}",
        "---",
    ]
    blocks = [front_matter, [f"# {title}"]] + render_blocks(content, heading_map(content))
    markdown = "\n\n".join("\n".join(block) for block in blocks) + "\n"
    return title, markdown


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def body_word_count(markdown: str) -> int:
    body = markdown.split("---", 2)[-1]
    return len(re.findall(r"[A-Za-z0-9][\w'’-]*", body))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("doc_ids", nargs="*", type=int, default=DEFAULT_DOC_IDS, help="UON Policy Library document ids")
    parser.add_argument("--refresh", action="store_true", help="download the pages again instead of using the cache")
    args = parser.parse_args()

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    for doc_id in args.doc_ids:
        html_path = fetch_html(doc_id, args.refresh)
        title, markdown = convert(html_path, doc_id)
        out_path = CORPUS_DIR / f"{slugify(title)}.md"
        out_path.write_text(markdown, encoding="utf-8")
        words = body_word_count(markdown)
        manifest.append({"doc_id": doc_id, "title": title, "file": out_path.name, "words": words,
                         "source_url": BASE_URL.format(doc_id=doc_id)})
        print(f"{doc_id:>4}  {words:>6} words  {out_path.relative_to(ROOT)}")

    write_manifest(manifest)


def write_manifest(new_rows: list[dict]) -> None:
    """Add or update rows in data/corpus/manifest.csv, keeping documents from earlier runs."""
    path = CORPUS_DIR / "manifest.csv"
    rows = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            rows = {int(row["doc_id"]): row for row in csv.DictReader(f)}
    rows.update({row["doc_id"]: row for row in new_rows})

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_rows[0]))
        writer.writeheader()
        writer.writerows(rows[doc_id] for doc_id in sorted(rows))
    total = sum(int(row["words"]) for row in rows.values())
    print(f"Corpus so far: {total} words in {len(rows)} documents (see {path.relative_to(ROOT)})")


if __name__ == "__main__":
    main()
