#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取历年《国务院政府工作报告》全文 -> 每年一个 Markdown + 索引。

来源优先级：中国政府网（公报 / 总理页 / 要闻）为主；
中国政府网已下线、公报数字库缺失的年份（2001、2008-2012）用辽宁省人民政府
「国务院政府工作报告」专栏的官方转载补齐。

用法：
    python3 fetch_reports.py            # 全量抓取
    python3 fetch_reports.py 2025 2024  # 只抓指定年份
"""
import csv
import html
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
MD_DIR = os.path.join(ROOT, "md")
RAW_DIR = os.path.join(ROOT, "raw")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# (年份, URL, 来源标签, 来源类型)
MANIFEST = [
    (2000, "http://www.gov.cn/gongbao/content/2000/content_60060.htm", "中国政府网·国务院公报", "central"),
    (2001, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/8BD467B917514980B80B9AA2687A1E0A/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2002, "http://www.gov.cn/gongbao/content/2002/content_69957.htm", "中国政府网·国务院公报", "central"),
    (2003, "http://www.gov.cn/gongbao/content/2003/content_62011.htm", "中国政府网·国务院公报", "central"),
    (2004, "http://www.gov.cn/gongbao/content/2004/content_62715.htm", "中国政府网·国务院公报", "central"),
    (2005, "http://www.gov.cn/gongbao/content/2005/content_158717.htm", "中国政府网·国务院公报", "central"),
    (2006, "http://www.gov.cn/gongbao/content/2006/content_268721.htm", "中国政府网·国务院公报", "central"),
    (2007, "http://www.gov.cn/gongbao/content/2007/content_595132.htm", "中国政府网·国务院公报", "central"),
    (2008, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/6EA20F6B7195449EB6B7CE131A37F226/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2009, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/047B28824E5449EDA9035BD0FD4F5A76/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2010, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/23FF4FDBC8EC47F8A1DC260EECD29C7C/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2011, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/3878D30AA499476187E6A79C564C0DBF/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2012, "https://www.ln.gov.cn/web/zwgkx/zfgzbg/zyzfgzbg/AFB05369D30B4A36A0F6B8056EB44B28/index.shtml", "辽宁省人民政府（转载）", "mirror"),
    (2013, "https://www.gov.cn/2014lhrd/content_2627985.htm", "中国政府网", "central"),
    (2014, "https://www.gov.cn/guowuyuan/2014-03/14/content_2638989.htm", "中国政府网·国务院", "central"),
    (2015, "https://www.gov.cn/guowuyuan/2015-03/16/content_2835101.htm", "中国政府网·国务院", "central"),
    (2016, "https://www.gov.cn/guowuyuan/2016-03/17/content_5054901.htm", "中国政府网·国务院", "central"),
    (2017, "https://www.gov.cn/guowuyuan/2017-03/16/content_5177940.htm", "中国政府网·国务院", "central"),
    (2018, "https://www.gov.cn/premier/2018-03/22/content_5276608.htm", "中国政府网·总理", "central"),
    (2019, "https://www.gov.cn/premier/2019-03/16/content_5374314.htm", "中国政府网·总理", "central"),
    (2020, "https://www.gov.cn/premier/2020-05/29/content_5516072.htm", "中国政府网·总理", "central"),
    (2021, "https://www.gov.cn/premier/2021-03/12/content_5592671.htm", "中国政府网·总理", "central"),
    (2022, "https://www.gov.cn/premier/2022-03/12/content_5678750.htm", "中国政府网·总理", "central"),
    (2023, "http://www.gov.cn/gongbao/content/2023/content_5747260.htm", "中国政府网·国务院公报", "central"),
    (2024, "https://www.gov.cn/gongbao/2024/issue_11246/202403/content_6941846.html", "中国政府网·国务院公报", "central"),
    (2025, "https://www.gov.cn/gongbao/2025/issue_11946/202503/content_7015861.html", "中国政府网·国务院公报", "central"),
    (2026, "https://www.gov.cn/gongbao/2026/issue_12646/202603/content_7064134.html", "中国政府网·国务院公报", "central"),
]

NOISE_PATTERNS = [
    r"^字号[：:]", r"^打印$", r"^打印本页$", r"^关闭窗口$", r"^分享$", r"^分享到",
    r"^扫一扫在手机打开当前页$", r"^【我要纠错】", r"^我要纠错", r"^责任编辑[：:]",
    r"^相关稿件$", r"^相关链接$", r"^相关阅读$", r"^上一篇", r"^下一篇", r"^返回顶部$",
    r"^网站地图$", r"^联系我们$", r"^版权声明$", r"^法律顾问$", r"^微博$", r"^微信$",
    r"^邮箱$", r"^无障碍$", r"^登录$", r"^注册$", r"^EN$", r"^简$", r"^繁$",
    r"^浏览字号[：:]", r"^来源[：:]", r"^中经视觉", r"^视频$", r"^图解$", r"^首页$",
    r"^中国政府网$", r"^国务院公报$", r"^辽宁省人民政府$", r"^【字体[：:]",
    r"^政策解读$", r"^媒体报道$", r"^访谈$", r"^评论$", r"^新华网$", r"^人民网$",
    r"^附件[：:]?$", r"^点击下载", r"^下载$", r"^上一篇[：:]", r"^下一篇[：:]",
    r"^最新\|", r"^相关链接", r"^相关新闻", r"^相关阅读", r"^（新华社[^）]{0,30}电）$",
]
NOISE_RE = [re.compile(p) for p in NOISE_PATTERNS]

# 正文结束后混进来的「相关新闻 / 延伸阅读」区块
TAIL_JUNK_RE = re.compile(
    r"责任编辑|扫一扫|相关稿件|相关链接|相关新闻|上一篇|下一篇|网站地图|版权所有|"
    r"返回顶部|详细阅读|^最新\|"
)
# 一旦命中即判定正文结束，后面的行（相关新闻、链接列表）全部丢弃
HARD_STOP_RE = re.compile(r"详细阅读|^最新\||^相关链接|^相关新闻|^责任编辑|^扫一扫|^【?相关稿件")


def fetch(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            with urllib.request.urlopen(req, timeout=40) as r:
                raw = r.read()
            for enc in ("utf-8", "gb18030"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def pick_content(soup):
    """挑出正文容器，按可靠性排序。"""
    for sel in ["#UCAP-CONTENT", ".dlist_con", ".pages_content",
                ".TRS_Editor", ".trs_editor_view", "#zoom", ".article-content"]:
        node = soup.select_one(sel)
        if node and len(node.get_text(strip=True)) > 800:
            return node
    # 兜底：找文字最多的 div
    best, best_len = None, 0
    for div in soup.find_all("div"):
        if div.find("div") is not None:
            continue
        n = len(div.get_text(strip=True))
        if n > best_len:
            best, best_len = div, n
    if best is not None and best_len > 800:
        return best
    return soup.body or soup


BLOCK_TAGS = ["p", "div", "h1", "h2", "h3", "h4", "li", "tr", "table", "section", "blockquote"]
TERM_RE = re.compile(r"[。！？…”\"）】]$")


def to_paragraphs(node):
    """把正文容器转成段落列表（<br>/块级标签作为段落边界，内联标签不打断句子）。"""
    for bad in node.select("script, style, iframe, form, noscript, "
                           ".share, .share-icon-fx, .print, .xgxw, .fjxx, .editor"):
        bad.decompose()
    for br in node.find_all("br"):
        br.replace_with("\n")
    for tag in node.find_all(BLOCK_TAGS):
        tag.append("\n")
    text = html.unescape(node.get_text(""))

    lines = []
    for ln in text.split("\n"):
        ln = ln.replace("\u3000", " ").replace("\xa0", " ").strip()
        ln = re.sub(r"^[\s…·。．.\-—_]{3,}", "", ln)   # 公报的省略号引导
        ln = re.sub(r"[\s…]{4,}$", "", ln)
        ln = re.sub(r"\s{2,}", " ", ln).strip()
        ln = ln.replace("!", "！").replace("?", "？")
        ln = re.sub(r"[\"'`]+$", "", ln).strip()
        if not ln or len(ln) <= 1:
            continue
        if HARD_STOP_RE.search(ln):      # 正文到此结束
            break
        if any(p.match(ln) for p in NOISE_RE):
            continue
        lines.append(ln)

    # 按句号/小标题归并：<span> 等内联切分产生的半句拼回整段
    merged, buf = [], ""
    for ln in lines:
        if HEAD_RE.match(ln) and len(ln) < 60:
            if buf:
                merged.append(buf)
                buf = ""
            merged.append(ln)
            continue
        buf = (buf + ln) if buf else ln
        if TERM_RE.search(buf) or (buf.endswith(("：", ":")) and len(buf) <= 12):
            merged.append(buf)
            buf = ""
    if buf:
        merged.append(buf)
    return merged


HEAD_RE = re.compile(r"^[（(]?[一二三四五六七八九十]+[）)]?[、．.](?=\S)")


def paras_to_markdown(paras):
    out = []
    for p in paras:
        if HEAD_RE.match(p) and len(p) < 60:
            out.append("## " + p)
        else:
            out.append(p)
    return out


SPEAKERS = ["周恩来", "华国锋", "赵紫阳", "李鹏", "朱镕基", "温家宝", "李克强", "李强"]
SESSION_RE = re.compile(r"第[一二三四五六七八九十]+届全国人民代表大会第[一二三四五六七八九十]+次会议")
DATE_RE = re.compile(r"((?:19|20)\d{2})年(\d{1,2})月(\d{1,2})日")


def find_meta(blobs, year):
    """从正文开头 + 页面标题区里抽取 会议/日期/报告人。"""
    joined = " ".join(blobs)
    joined = re.sub(r"(?<=[\u4e00-\u9fa5])\s+(?=[\u4e00-\u9fa5])", "", joined)  # 去掉「李 强」这类字间距

    session = None
    # 优先取「YYYY年M月D日在第N届全国人大第M次会议上」这种和报告日期绑定的会议名，
    # 避免正文里提到的往届会议名（如 2008 年报告回顾「第十届全国人大第一次会议以来」）被误选
    m = re.search(r"(?:19|20)\d{2}年\d{1,2}月\d{1,2}日在(" + SESSION_RE.pattern + r")上", joined)
    if not m:
        m = SESSION_RE.search(joined)
    if m:
        session = m.group(1) if m.re.groups else m.group(0)

    date = None
    for m in DATE_RE.finditer(joined):
        if m.group(1) == str(year) or date is None:
            date = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if m.group(1) == str(year):
            break

    speaker = None
    for name in SPEAKERS:
        if re.search(r"(?:国务院总理|总理|代总理)" + name, joined) or (
                name in joined and re.search(r"(?:国务院)?总理[^。]{0,8}" + name, joined)):
            speaker = "国务院总理 " + name
            break
    return session, date, speaker


def clean_title(paras, year):
    head = " ".join(paras[:4])
    m = SESSION_RE.search(head)
    if m:
        return f"{year}年国务院政府工作报告 ——{m.group(0)}"
    return f"{year}年国务院政府工作报告"


def build(year, url, source, kind, raw_html):
    soup = BeautifulSoup(raw_html, "lxml")
    node = pick_content(soup)
    paras = to_paragraphs(node)

    # 页面标题区（辽宁等模板把 会议/日期/报告人 放在正文容器之外）
    head_zone = soup.get_text(" ", strip=True)[:1200]

    # 报文头（「政 府 工 作 报 告 ——… 各位代表：」）单独拆出来供元信息使用
    header_blob = ""
    if paras:
        first = paras[0]
        m = re.search(r"各位代表", first)
        if m:
            header_blob = first[:m.start()]
            paras[0] = first[m.start():]

    session, date, speaker = find_meta([header_blob, " ".join(paras[:3]), head_zone], year)
    title = clean_title([header_blob] + paras, year)

    # 截断尾部杂项（责任编辑 / 扫一扫 / 相关稿件 / 相关新闻块 …）
    for i, p in enumerate(paras):
        if TAIL_JUNK_RE.search(p):
            paras = paras[:i]
            break

    # 丢弃正文前的图片说明（「3月5日，第N届全国人大第M次会议在北京开幕…新华社记者 摄」）
    for i, p in enumerate(paras[:6]):
        if "各位代表" in p:
            if i:
                paras = paras[i:]
            break

    # 「各位代表：」与紧随其后的正文拆成两段（公报排版常挤在一行）
    expanded = []
    for p in paras:
        m = re.match(r"^(各位代表)\s*[：:！!]\s*(\S.*)$", p)
        if m:
            expanded.append(m.group(1) + "：")
            expanded.append(m.group(2))
        else:
            expanded.append(p)
    paras = expanded

    body = paras_to_markdown(paras)
    nchar = len(re.sub(r"\s", "", "".join(body)))

    now = datetime.now().strftime("%Y-%m-%d")
    md = [f"# {title}", ""]
    md.append("| 项目 | 内容 |")
    md.append("| --- | --- |")
    if date:
        md.append(f"| 报告时间 | {date} |")
    if session:
        md.append(f"| 会议 | {session} |")
    if speaker:
        md.append(f"| 报告人 | {speaker} |")
    md.append(f"| 来源 | [{source}]({url}) |")
    md.append(f"| 正文（去空白） | {nchar} 字 |")
    md.append(f"| 抓取时间 | {now} |")
    md.append("")
    md.append("---")
    md.append("")
    md.extend(body)
    md.append("")
    text = "\n".join(md)

    return {
        "year": year, "url": url, "source": source, "kind": kind,
        "session": session or "", "date": date or "", "speaker": speaker or "",
        "chars": nchar, "title": title, "markdown": text,
    }


def valid(rec, year):
    problems = []
    if rec["chars"] < 4000:
        problems.append(f"字数偏少({rec['chars']})")
    if "各位代表" not in rec["markdown"] and "政府工作报告" not in rec["markdown"]:
        problems.append("缺『各位代表』/标题")
    if rec["date"] and not rec["date"].startswith(str(year)):
        problems.append(f"日期与年份不符({rec['date']})")
    if not rec["date"]:
        problems.append("未识别到日期")
    return problems


def main():
    os.makedirs(MD_DIR, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    offline = "--offline" in sys.argv
    want = {int(a) for a in args} if args else None

    records = []
    for year, url, source, kind in MANIFEST:
        if want and year not in want:
            continue
        raw_path = os.path.join(RAW_DIR, f"{year}.html")
        print(f"[{year}] {url}")
        if offline:
            if not os.path.exists(raw_path):
                print("    !! 无本地快照，跳过")
                continue
            raw = open(raw_path, encoding="utf-8").read()
        else:
            try:
                raw = fetch(url)
            except Exception as e:  # noqa: BLE001
                print(f"    !! 抓取失败: {e}")
                continue
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(raw)
        rec = build(year, url, source, kind, raw)
        problems = valid(rec, year)
        flag = "OK " if not problems else "WARN"
        print(f"    {flag} {rec['chars']}字 date={rec['date']} session={rec['session']} "
              f"speaker={rec['speaker']}" + (f" | {problems}" if problems else ""))
        rec["problems"] = "; ".join(problems)
        with open(os.path.join(MD_DIR, f"{year}-国务院政府工作报告.md"), "w", encoding="utf-8") as f:
            f.write(rec["markdown"])
        records.append(rec)
        time.sleep(0.8)

    # 索引
    records.sort(key=lambda r: r["year"])
    with open(os.path.join(ROOT, "index.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["年份", "报告时间", "会议", "报告人", "正文字数", "来源", "来源URL", "校验"])
        for r in records:
            w.writerow([r["year"], r["date"], r["session"], r["speaker"], r["chars"],
                        r["source"], r["url"], r["problems"] or "OK"])

    idx = ["# 历年《国务院政府工作报告》全文（2000–2026）", "",
           f"- 共 {len(records)} 份，每年一个 Markdown 文件，位于 `md/`",
           "- 来源为中国政府网（国务院公报 / 总理页 / 要闻）；其数字库缺失的年份用辽宁省人民政府官方转载补齐",
           f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
           "| 年份 | 报告时间 | 会议 | 报告人 | 字数 | 来源 |", "| --- | --- | --- | --- | --- | --- |"]
    for r in records:
        idx.append(f"| [{r['year']}](md/{r['year']}-国务院政府工作报告.md) | {r['date']} | "
                   f"{r['session']} | {r['speaker']} | {r['chars']} | {r['source']} |")
    idx.append("")
    with open(os.path.join(ROOT, "index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(idx))
    with open(os.path.join(ROOT, "index.json"), "w", encoding="utf-8") as f:
        json.dump([{k: v for k, v in r.items() if k != "markdown"} for r in records],
                  f, ensure_ascii=False, indent=2)

    bad = [r for r in records if r["problems"]]
    print(f"\n完成：{len(records)} 份，校验异常 {len(bad)} 份")
    for r in bad:
        print(f"  - {r['year']}: {r['problems']}")


if __name__ == "__main__":
    main()
