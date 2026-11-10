"""语料解析与切块。

把 md/ 下的政府工作报告解析成带元数据的文本块。
切块策略面向中文公文：按 ## 标题分节 → 段落贪心装箱 → 超长段落按句切分 → 携带重叠。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "md"
INDEX_JSON = ROOT / "index.json"

# 切块参数：中文公文的段落粒度较粗，450 字左右一块比较合适
TARGET_CHARS = 450
MAX_CHARS = 700
OVERLAP_CHARS = 80
MIN_CHARS = 120

SENT_END = re.compile(r"(?<=[。！？；])")


@dataclass
class Chunk:
    chunk_id: str
    year: int
    section: str
    text: str          # 供展示的正文（不含标题前缀）
    embed_text: str    # 供嵌入的文本（带章节上下文）
    n_chars: int


def load_meta() -> dict[int, dict]:
    """读取 index.json，拿到每年报告的权威元数据（来源/日期/报告人）。"""
    rows = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    return {int(r["year"]): r for r in rows}


def parse_report(path: Path) -> tuple[str, str]:
    """拆出 (标题, 正文)。丢掉 YAML 风格的元信息表和分隔线。"""
    raw = path.read_text(encoding="utf-8")

    title = ""
    m = re.match(r"^#\s+(.+)$", raw, flags=re.M)
    if m:
        title = m.group(1).strip()

    body = raw
    # 去掉元信息表（连续的 | ... | 行）
    body = re.sub(r"^\|.*\|\s*$", "", body, flags=re.M)
    # 去掉标题行与分隔线
    body = re.sub(r"^#\s+.*$", "", body, flags=re.M)
    body = re.sub(r"^\s*-{3,}\s*$", "", body, flags=re.M)
    return title, body


def split_sections(body: str) -> list[tuple[str, str]]:
    """按 '## 一、xxx' 切分，返回 [(章节标题, 该节正文)]。文首无标题的部分归入 '引言'。"""
    parts = re.split(r"^##\s+(.+)$", body, flags=re.M)
    out: list[tuple[str, str]] = []
    if parts[0].strip():
        out.append(("引言", parts[0]))
    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        content = parts[i + 1] if i + 1 < len(parts) else ""
        out.append((heading, content))
    return out


def split_long(para: str, limit: int) -> list[str]:
    """超长段落按句号切分后再装箱，避免单块过大。"""
    if len(para) <= limit:
        return [para]
    pieces, buf = [], ""
    for sent in SENT_END.split(para):
        if not sent:
            continue
        if len(buf) + len(sent) > limit and buf:
            pieces.append(buf)
            buf = sent
        else:
            buf += sent
    if buf:
        pieces.append(buf)
    return pieces


def chunk_section(heading: str, content: str) -> list[str]:
    """段落贪心装箱，块之间保留 OVERLAP_CHARS 字重叠以免切断上下文。"""
    paras = [p.strip() for p in content.split("\n") if p.strip()]
    units: list[str] = []
    for p in paras:
        units.extend(split_long(p, MAX_CHARS))

    chunks: list[str] = []
    buf = ""
    for u in units:
        if buf and len(buf) + len(u) > TARGET_CHARS + OVERLAP_CHARS:
            chunks.append(buf)
            # 用上一块的尾部做重叠，衔接跨块语义
            buf = (buf[-OVERLAP_CHARS:] if OVERLAP_CHARS else "") + u
        else:
            buf += u
    if buf.strip():
        chunks.append(buf)
    return [c.strip() for c in chunks if c.strip()]


def merge_tiny(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """把过短的碎片块（如只有'各位代表：'的引言）并入相邻块，避免产生无信息量的向量。"""
    out: list[tuple[str, str]] = []
    for heading, text in pairs:
        if out and len(text) < MIN_CHARS:
            prev_h, prev_t = out[-1]
            out[-1] = (prev_h, prev_t + text)
        else:
            out.append((heading, text))
    # 若首块仍过短且存在后继，向后合并
    if len(out) > 1 and len(out[0][1]) < MIN_CHARS:
        h0, t0 = out.pop(0)
        h1, t1 = out[0]
        out[0] = (h1, t0 + t1)
    return out


def build_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(MD_DIR.glob("*.md")):
        m = re.match(r"(\d{4})-", path.name)
        if not m:
            continue
        year = int(m.group(1))
        _, body = parse_report(path)

        pairs: list[tuple[str, str]] = []
        for heading, content in split_sections(body):
            for text in chunk_section(heading, content):
                pairs.append((heading, text))

        # 每年内部编号，保证 chunk_id 全局唯一且稳定
        for i, (heading, text) in enumerate(merge_tiny(pairs)):
            chunks.append(
                Chunk(
                    chunk_id=f"{year}-{i:03d}",
                    year=year,
                    section=heading,
                    text=text,
                    # 嵌入时带上章节标题，显著改善"哪一年的哪项工作"这类查询
                    embed_text=f"{year}年国务院政府工作报告 · {heading}\n{text}",
                    n_chars=len(text),
                )
            )
    return chunks


if __name__ == "__main__":
    cs = build_chunks()
    print(f"总块数: {len(cs)}")
    print(f"平均块长: {sum(c.n_chars for c in cs)/len(cs):.0f} 字")
    print(f"最长块: {max(c.n_chars for c in cs)} 字 / 最短块: {min(c.n_chars for c in cs)} 字")
    print(f"覆盖年份: {min(c.year for c in cs)}–{max(c.year for c in cs)}")
    print("\n--- 抽样 ---")
    for c in cs[:2]:
        print(f"\n[{c.chunk_id}] {c.section} ({c.n_chars}字)")
        print(c.text[:180] + "...")
