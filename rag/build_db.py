"""把切好的块嵌入后写入 LanceDB。

刻意**不创建任何向量索引**：本语料规模（约 1.4k 块）下，LanceDB 走暴力精确检索，
召回率 100%，延迟已在毫秒级；IVF_PQ 之类的 ANN 索引在这个量级只带来有损召回，
收益接近于零。索引应当由规模驱动 —— 见 INDEX_THRESHOLD 的提示。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from pathlib import Path

import lancedb

from corpus import build_chunks
from embedder import DEFAULT_MODEL, Embedder, resolve

ROOT = Path(__file__).resolve().parent.parent
DB_ROOT = ROOT / "rag" / "db"

# 经验值：低于这个块数，精确检索完全够用，不需要 ANN 索引。
# 参考：2026-10 在 M4/24GB 实测，10 万 x768 无索引精确检索 p50 约 39ms、
# 常驻内存约 0.9GB；20 万 x768 建 IVF_PQ 后 p50 约 3.3ms、常驻 143MB。
INDEX_THRESHOLD = 50_000


def dir_mb(p: Path) -> float:
    if not p.exists():
        return 0.0
    out = subprocess.run(["du", "-sk", str(p)], capture_output=True, text=True).stdout
    return int(out.split()[0]) / 1024


def main() -> None:
    ap = argparse.ArgumentParser(description="构建政府工作报告向量库")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"默认 {DEFAULT_MODEL}")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--device", default=None, help="如 mps / cpu，默认自动")
    ap.add_argument("--rebuild", action="store_true", help="删除已有库后重建")
    args = ap.parse_args()

    spec = resolve(args.model)
    db_path = DB_ROOT / args.model.replace("/", "__")

    if db_path.exists():
        if not args.rebuild:
            raise SystemExit(f"{db_path} 已存在，加 --rebuild 覆盖重建")
        shutil.rmtree(db_path)

    print(f"模型      : {args.model}  ({spec['repo']}, {spec['dim']} 维, {spec['size']})")
    print(f"库路径    : {db_path.relative_to(ROOT)}")
    print(f"镜像      : {os.environ.get('HF_ENDPOINT')}")
    print()

    t0 = time.perf_counter()
    chunks = build_chunks()
    print(f"[1/3] 切块完成: {len(chunks)} 块, 平均 {sum(c.n_chars for c in chunks)/len(chunks):.0f} 字  "
          f"({time.perf_counter()-t0:.2f}s)")

    emb = Embedder(args.model, device=args.device)
    t0 = time.perf_counter()
    _ = emb.model  # 触发权重下载/加载
    load_s = time.perf_counter() - t0
    print(f"[2/3] 模型就绪 ({load_s:.1f}s, 含可能的首次下载)")

    t0 = time.perf_counter()
    vectors = emb.embed_documents([c.embed_text for c in chunks], batch_size=args.batch_size)
    enc_s = time.perf_counter() - t0
    if vectors.shape[1] != spec["dim"]:
        raise SystemExit(f"维度不符: 期望 {spec['dim']}, 实得 {vectors.shape[1]}")
    print(f"[3/3] 嵌入完成: {vectors.shape}  ({enc_s:.1f}s, "
          f"{len(chunks)/enc_s:.0f} 块/秒)")

    db = lancedb.connect(str(db_path))

    # 用 pyarrow 显式建表：向量列必须是 fixed_size_list，列式写入也比 list[dict] 快
    import pyarrow as pa

    schema = pa.schema(
        [
            ("chunk_id", pa.string()),
            ("year", pa.int32()),
            ("section", pa.string()),
            ("text", pa.string()),
            ("n_chars", pa.int32()),
            ("vector", pa.list_(pa.float32(), spec["dim"])),
        ]
    )
    data = pa.table(
        {
            "chunk_id": [c.chunk_id for c in chunks],
            "year": [c.year for c in chunks],
            "section": [c.section for c in chunks],
            "text": [c.text for c in chunks],
            "n_chars": [c.n_chars for c in chunks],
            "vector": pa.FixedSizeListArray.from_arrays(
                pa.array(vectors.reshape(-1), type=pa.float32()), spec["dim"]
            ),
        },
        schema=schema,
    )
    tbl = db.create_table("chunks", data=data, mode="overwrite")
    # 注意：此处刻意不调用 create_index()。
    n = tbl.count_rows()
    size = dir_mb(db_path)

    print()
    print("=" * 72)
    print(f"写入完成  : {n} 行")
    print(f"向量索引  : 无（暴力精确检索，100% 召回）")
    print(f"磁盘占用  : {size:.1f} MB")
    print(f"编码吞吐  : {len(chunks)/enc_s:.0f} 块/秒")
    print("=" * 72)
    if n >= INDEX_THRESHOLD:
        print(f"\n⚠️  块数 {n} 已达 {INDEX_THRESHOLD}，建议改用 ANN 索引:")
        print("   tbl.create_index('vector', config=IvfPq(distance_type='cosine'))")
    else:
        print(f"\n提示: 当前 {n} 块 << {INDEX_THRESHOLD} 阈值，保持精确检索即可。")
        print(f"查询: ./.venv/bin/python rag/search.py \"你的问题\"")


if __name__ == "__main__":
    main()
