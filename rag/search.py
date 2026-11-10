"""查询向量库。

用法:
    ./.venv/bin/python rag/search.py "新能源汽车产量"
    ./.venv/bin/python rag/search.py "减税降费" -k 5 --year-from 2020
    ./.venv/bin/python rag/search.py --interactive
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import lancedb

from embedder import DEFAULT_MODEL, Embedder

ROOT = Path(__file__).resolve().parent.parent
DB_ROOT = ROOT / "rag" / "db"


def open_table(model: str):
    db_path = DB_ROOT / model.replace("/", "__")
    if not db_path.exists():
        raise SystemExit(f"库不存在: {db_path}\n先运行: ./.venv/bin/python rag/build_db.py --model {model}")
    db = lancedb.connect(str(db_path))
    return db.open_table("chunks")


def search(tbl, emb: Embedder, query: str, k: int, year_from=None, year_to=None, section=None):
    q = emb.embed_query(query)
    s = tbl.search(q, vector_column_name="vector").distance_type("cosine").limit(k)

    where = []
    if year_from:
        where.append(f"year >= {int(year_from)}")
    if year_to:
        where.append(f"year <= {int(year_to)}")
    if section:
        # 简单的 LIKE 过滤，够用；复杂条件可直接改 SQL 表达式
        where.append(f"section LIKE '%{section}%'")
    if where:
        s = s.where(" AND ".join(where), prefilter=True)

    rows = s.to_list()
    for r in rows:
        r["score"] = 1.0 - r.pop("_distance", 0.0)  # cosine 距离 -> 相似度
        r.pop("vector", None)
    return rows


def render(rows, query, width=160):
    if not rows:
        print("(无结果)")
        return
    print(f"\n查询: {query}")
    print("─" * 78)
    for i, r in enumerate(rows, 1):
        text = r["text"].replace("\n", " ")
        if len(text) > width:
            text = text[:width] + " …"
        print(f"\n[{i}] 相似度 {r['score']:.4f}  ·  {r['year']}年  ·  {r['section']}")
        print(f"    id={r['chunk_id']}  {r['n_chars']}字")
        print(f"    {text}")


def main() -> None:
    ap = argparse.ArgumentParser(description="检索政府工作报告")
    ap.add_argument("query", nargs="*", help="查询文本；留空则配合 --interactive")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--year-from", type=int)
    ap.add_argument("--year-to", type=int)
    ap.add_argument("--section", help="章节标题关键词过滤")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--interactive", "-i", action="store_true")
    args = ap.parse_args()

    tbl = open_table(args.model)
    emb = Embedder(args.model)

    def run(q: str):
        rows = search(tbl, emb, q, args.k, args.year_from, args.year_to, args.section)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            render(rows, q)

    if args.interactive:
        print(f"库: {args.model} ({tbl.count_rows()} 块) · 输入问题，Ctrl-D 退出")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if q:
                run(q)
        return

    if not args.query:
        ap.error("请提供查询文本，或使用 --interactive")
    run(" ".join(args.query))


if __name__ == "__main__":
    sys.exit(main())
