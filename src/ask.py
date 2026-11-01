"""Ask the RAG system your own questions about UON policies, one at a time.

Each question uses a little of the group's Sandbox budget (one embedding and one
answer). Nothing is saved, so the experiment results are not affected.

Usage:
    python src/ask.py
"""

import rag


def main() -> None:
    print("Loading the policies...")
    collection = rag.build_index(rag.load_chunks())
    print("Ask a question about UON policies. Press Enter on an empty line to quit.")

    while True:
        question = input("\nQuestion: ").strip()
        if not question:
            break
        retrieved = rag.retrieve(collection, question)
        print("\n" + rag.ask_llm(rag.rag_prompt(question, retrieved)))

        # Each retrieved chunk starts with a "[Policy > Section]" label line.
        sources = []
        for chunk in retrieved:
            label = chunk["document"].split("\n")[0].strip("[]")
            if label not in sources:
                sources.append(label)
        print("\nRetrieved from:")
        for label in sources:
            print(f"  - {label}")


if __name__ == "__main__":
    main()
