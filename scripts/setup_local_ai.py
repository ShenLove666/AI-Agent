from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.infra_ai.providers.sentence_transformer import SentenceTransformerEmbeddingModel
from app.modules.vector.contracts import VectorRecord
from app.modules.vector.milvus import MilvusVectorStore


MODEL_ID = "BAAI/bge-small-zh-v1.5"


async def verify(root: Path) -> None:
    model_path = root / "models" / "bge-small-zh-v1.5"
    model = SentenceTransformerEmbeddingModel(str(model_path), device="cpu")
    vectors = await model.embed_documents(["七天无理由退货", "牛奶与面包的购物篮搭配"])
    if len(vectors[0]) != 512:
        raise RuntimeError(f"unexpected embedding dimension: {len(vectors[0])}")
    store = MilvusVectorStore(
        uri=str(root / "data" / "milvus-ragent.db"), dimension=512,
        collection_name="ragent_setup_check",
    )
    await store.upsert([
        VectorRecord("setup-policy", vectors[0], "七天无理由退货", 0, 0, 0, "setup", {"position": 0, "chunk_id": "setup-policy"}),
        VectorRecord("setup-basket", vectors[1], "牛奶与面包的购物篮搭配", 0, 0, 0, "setup", {"position": 0, "chunk_id": "setup-basket"}),
    ])
    matches = await store.search(await model.embed_query("退货期限"), owner_id=0, limit=1)
    if not matches or matches[0].record.id != "setup-policy":
        raise RuntimeError("Milvus semantic search smoke test failed")
    print(f"[local-ai] model={model_path} dimension=512")
    print(f"[local-ai] milvus={root / 'data' / 'milvus-ragent.db'} hit={matches[0].record.id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the pinned local embedding model and verify Milvus Lite")
    parser.add_argument("--offline", action="store_true", help="skip download and verify existing project files")
    args = parser.parse_args()
    root = PROJECT_ROOT
    target = root / "models" / "bge-small-zh-v1.5"
    if not args.offline:
        snapshot_download(repo_id=MODEL_ID, local_dir=target)
    if not target.is_dir():
        raise SystemExit(f"model is missing: {target}")
    asyncio.run(verify(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
