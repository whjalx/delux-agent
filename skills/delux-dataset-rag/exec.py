#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

DELUX_HOME = Path(os.environ.get("DELUX_HOME", Path.home() / ".delux"))


def main():
    from delux_agent.dataset_rag import DatasetRAG

    ds = DatasetRAG(DELUX_HOME)

    if len(sys.argv) < 2:
        print("Usage: delux-dataset-rag <command> [args...]")
        print("Commands: import, search, few-shot, status, clear")
        return 1

    cmd = sys.argv[1]

    if cmd == "status":
        print(ds.status())

    elif cmd == "clear":
        ds.clear()
        print("Dataset RAG cleared.")

    elif cmd == "import":
        project_root = Path(__file__).resolve().parent.parent.parent
        total = 0

        hermes_kimi = project_root / "dataset_hermes" / "data" / "kimi" / "train.parquet"
        hermes_glm = project_root / "dataset_hermes" / "data" / "glm-5.1" / "train.parquet"
        multiturn = project_root / "dataset_multiturn" / "data" / "train-00000-of-00001.parquet"

        if hermes_kimi.exists():
            n = ds.import_hermes_parquet(str(hermes_kimi), DatasetRAG.SOURCE_HERMES_KIMI)
            total += n
            print(f"  Hermes Kimi: {n} new entries")

        if hermes_glm.exists():
            n = ds.import_hermes_parquet(str(hermes_glm), DatasetRAG.SOURCE_HERMES_GLM)
            total += n
            print(f"  Hermes GLM:  {n} new entries")

        if multiturn.exists():
            n = ds.import_hermes_parquet(str(multiturn), DatasetRAG.SOURCE_MULTITURN)
            total += n
            print(f"  Multiturn:   {n} new entries")

        if "--glaive" in sys.argv:
            glaive = project_root / "dataset_glaive" / "glaive-function-calling-v2.json"
            if glaive.exists():
                n = ds.import_glaive_json(str(glaive))
                total += n
                print(f"  Glaive:      {n} new entries")

        print(f"\nTotal imported: {total}")
        print(f"Manifest entries: {len(ds.manifest)}")

    elif cmd == "search":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Usage: delux-dataset-rag search <query>")
            return 1
        print(ds.search_formatted(query, top_k=5))

    elif cmd == "few-shot":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Usage: delux-dataset-rag few-shot <query>")
            return 1
        results = ds.search(query, top_k=3)
        formatted = ds.format_few_shot(results, max_turns=6)
        if not formatted:
            print(f"No dataset examples found for: {query}")
            return 0
        print("--- Dataset RAG Few-Shot Examples ---\n")
        print(formatted)

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: import, search, few-shot, status, clear")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
