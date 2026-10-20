"""Evidence-backed printed contents planning for local MinerU EPUB export.

The planner consumes admitted source records before text flattening. Geometry,
body-title coverage and source-page evidence establish entries and targets;
uncertain text remains visible and unlinked. No recognition is performed.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from .cache import CachedBlock, MineruCache

CONTENTS_TITLES = {"contents", "table of contents", "inhaltsverzeichnis", "目录", "目錄"}
SECTION_LABELS = {"anhang", "appendix", "appendices", "references", "bibliography", "附录", "附錄"}


@dataclass(frozen=True)
class TocEntry:
    title: str
    page_label: str
    group: bool = False
    target_block: int | None = None
    match_method: str = "unresolved_target"
    evidence: Mapping[str, Any] = field(default_factory=dict)
    source_spans: tuple[str, ...] = ()
    source_ranges: tuple[tuple[int, int], ...] = ()
    label_range: tuple[int, int] | None = None


@dataclass(frozen=True)
class TocBlock:
    text: str
    entries: tuple[TocEntry, ...]
    method: str
    proof: Mapping[str, Any]
    group: bool = False


@dataclass(frozen=True)
class PrintedToc:
    pages: tuple[int, ...]
    blocks: Mapping[int, TocBlock]
    omitted_images: frozenset[int]


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _raw_text(record):
    return "\n".join(s.get("content", "") for line in record.get("lines", [])
                     for s in line.get("spans", []) if s.get("type") == "text")


def _subsequence(needle, haystack):
    remaining = iter(haystack)
    return all(any(word == token for word in remaining) for token in needle)


def _title_words(value):
    articles = {"der", "die", "das", "den", "dem", "des", "und", "mit"}
    return [word for word in re.findall(r"\w+", _normalized(value)) if word not in articles]


def _recover_entries(record):
    """Recover bounded Arabic-label rows; return None for insufficient evidence."""
    spans = []
    for li, line in enumerate(record.get("lines", [])):
        for si, span in enumerate(line.get("spans", [])):
            box, text = span.get("bbox"), span.get("content")
            if (span.get("type") != "text" or not isinstance(text, str) or "\n" in text
                    or not isinstance(box, list) or len(box) != 4
                    or any(type(v) not in {int, float} or not math.isfinite(v) for v in box)
                    or box[0] >= box[2] or box[1] >= box[3]):
                return None
            parent = record["bbox"]
            if (box[0] < parent[0]-2 or box[1] < parent[1]-2
                    or box[2] > parent[2]+2 or box[3] > parent[3]+2):
                return None
            spans.append({"id": f"{li}:{si}", "text": text.strip(), "bbox": box})
    if not spans:
        return None
    starts = sorted({s["bbox"][0] for s in spans})
    width = max(s["bbox"][2] for s in spans) - starts[0]
    gaps = [(b-a, (a+b)/2) for a, b in zip(starts, starts[1:])]
    gap, cut = max(gaps, default=(0, 0))
    columns = ([s for s in spans if s["bbox"][0] < cut],
               [s for s in spans if s["bbox"][0] >= cut]) if gap > max(24, width*.12) else (spans,)
    if len(columns) == 2 and (any(len(c) < 2 for c in columns)
            or max(s["bbox"][2] for s in columns[0]) >= min(s["bbox"][0] for s in columns[1])):
        return None
    rows, used = [], []
    previous = -1
    for column in columns:
        pending = []
        for span in sorted(column, key=lambda s: (s["bbox"][1], s["bbox"][0])):
            pending.append(span)
            match = re.search(r"\s(\d+)$", span["text"])
            if match is None:
                continue
            label = match[1]
            title = " ".join(s["text"] for s in pending)[:-len(label)].strip()
            if not title or int(label) < previous:
                return None
            previous = int(label)
            ids = [s["id"] for s in pending]
            rows.append({"title": title, "page_label": label, "source_spans": ids})
            used.extend(ids)
            pending = []
        if pending:
            return None
    if Counter(used) != Counter(s["id"] for s in spans):
        return None
    return rows


def _mixed_rows(raw, headings):
    """One bounded exact-cover experiment, returning None when not unique."""
    tokens = [{"text": _normalized(m[0]), "range": [m.start(), m.end()]}
              for m in re.finditer(r"\S+", raw) if not m[0].isdecimal()]
    words = [token["text"] for token in tokens]
    candidates = []
    for key, group in headings.items():
        sequence = key.split()
        if sequence and _subsequence(sequence, words):
            candidates.append({"title": group[0]["title"], "words": sequence,
                               "order": group[0]["order"]})
    # A fixed research budget; unknown inputs remain visible source text.
    if not candidates or len(candidates) > 20 or len(tokens) > 120:
        return None
    solutions = []
    work = 0
    exhausted = False

    def cover(index, left, selected):
        nonlocal work, exhausted
        work += 1
        if work > 50_000:
            exhausted = True
            return
        if len(solutions) > 1:
            return
        if not left:
            solutions.append(selected)
            return
        if index == len(candidates):
            return
        counts = Counter(candidates[index]["words"])
        if not counts - left:
            cover(index + 1, left - counts, selected + [index])
        cover(index + 1, left, selected)

    cover(0, Counter(words), [])
    if exhausted or len(solutions) != 1:
        return None
    chosen = [candidates[i] for i in solutions[0]]
    pins, labels = {}, {}
    for line in re.finditer(r"[^\n]+", raw):
        match = re.fullmatch(r"(.*?)\s+(\d+)\s*", line[0])
        if not match:
            continue
        suffix = _normalized(match[1]).split()
        matches = [i for i, c in enumerate(chosen) if suffix and c["words"][-len(suffix):] == suffix]
        if len(matches) != 1 or matches[0] in labels:
            return None
        owner = matches[0]
        labels[owner] = {"page_label": match[2], "label_range": [
            line.start() + match.start(2), line.start() + match.end(2)]}
        for i, token in enumerate(tokens):
            if line.start() <= token["range"][0] < line.start() + match.end(1):
                pins[i] = owner
    if len(labels) != len(chosen):
        return None

    @lru_cache(None)
    def assign(index, positions):
        nonlocal work, exhausted
        work += 1
        if work > 50_000:
            exhausted = True
            return ()
        if index == len(tokens):
            return ((),) if all(positions[j] == len(c["words"]) for j, c in enumerate(chosen)) else ()
        found = []
        for owner in ([pins[index]] if index in pins else range(len(chosen))):
            pos = positions[owner]
            if pos < len(chosen[owner]["words"]) and chosen[owner]["words"][pos] == words[index]:
                updated = list(positions)
                updated[owner] += 1
                for tail in assign(index + 1, tuple(updated)):
                    found.append((owner, *tail))
                    if len(found) == 2:
                        return tuple(found)
        return tuple(found)

    assignments = assign(0, (0,) * len(chosen))
    if exhausted or len(assignments) != 1:
        return None
    rows = [{"title": candidate["title"], **labels[i],
             "source_ranges": [token["range"] for token, owner in zip(tokens, assignments[0]) if owner == i],
             "body_order": candidate["order"]} for i, candidate in enumerate(chosen)]
    rows.sort(key=lambda row: row["body_order"])
    return rows, {"tokens": len(tokens), "assigned_tokens": len(assignments[0]),
                  "candidate_titles": len(candidates), "title_sets": 1,
                  "disjoint_assignments": 1, "assignment_states": assign.cache_info().currsize}


def _recover(record, headings):
    raw = _raw_text(record)
    if "\n" not in raw and not re.search(r"\d", raw):
        return [], "section label", {"section_label": True}
    rows = _recover_entries(record)
    if rows:
        return rows, "span geometry", {"spans": sum(len(r["source_spans"]) for r in rows)}
    single = re.fullmatch(r"([^\n]+?)\s+(\d+)\s*", raw)
    if single:
        return [{"title": single[1], "page_label": single[2]}], "single line row", {"rows": 1}
    pending, rows = [], []
    for line in raw.splitlines():
        pending.append(line.strip())
        match = re.search(r"\s(\d+)\s*$", line)
        if match:
            title = " ".join(pending)
            title = re.sub(r"\s+\d+\s*$", "", title)
            rows.append({"title": title, "page_label": match[1]})
            pending = []
    if rows and not pending and all(len(headings.get(_normalized(row["title"]), ())) == 1 for row in rows):
        return rows, "newline rows verified against body", {"rows": len(rows), "leftover": 0}
    result = _mixed_rows(raw, headings)
    if result:
        return result[0], "unique title coverage and suffix pairing", result[1]
    return [], "unresolved source text", {"unresolved": raw}


def _contents_page(records: list[dict]) -> bool:
    """Continuation admission requires contents-shaped text throughout the page."""
    rows = 0
    for record in records:
        if record.get("type") == "image":
            continue
        if record.get("type") not in {"text", "title"}:
            return False
        text = _raw_text(record).strip()
        if not text:
            continue
        recovered = _recover_entries(record)
        if recovered:
            rows += len(recovered)
        elif re.search(r"\s\d+\s*$", text):
            rows += sum(bool(re.search(r"\s\d+\s*$", line)) for line in text.splitlines())
        elif ("\n" in text or len(text) > 100 or
              (record.get("type") != "title" and _normalized(text) not in SECTION_LABELS)):
            return False
    return rows >= 2


def _target(row: dict, body: list[CachedBlock], cache: MineruCache) -> tuple[int | None, str, dict]:
    """Only unique targets backed by text and source evidence receive links."""
    key = _normalized(row["title"])
    for kind, compact, method in [("title", False, "exact_heading"),
                                   ("title", True, "whitespace_heading"),
                                   ("paragraph", False, "exact_paragraph")]:
        matches = [b for b in body if b.type == kind and not b.preservation_reason and
                   (_normalized(b.text).replace(" ", "") == key.replace(" ", "") if compact
                    else _normalized(b.text) == key)]
        if matches:
            return (matches[0].index if len(matches) == 1 else None), method, {"candidates": len(matches)}
    words = _title_words(row["title"])
    labels = defaultdict(set)
    for block in cache.blocks:
        if block.type == "page_number":
            labels[block.page_index].add(block.text.strip())
    matches = []
    if len(words) >= 3:
        for block in body:
            candidate = _title_words(block.text)
            if (block.type == "title" and not block.preservation_reason and
                    labels[block.page_index] == {row["page_label"]} and
                    candidate[:2] == words[:2] and candidate[-1:] == words[-1:] and
                    _subsequence(words, candidate)):
                matches.append(block)
    if len(matches) == 1:
        block = matches[0]
        return block.index, "printed_label_and_title_words", {
            "page": cache.pages[block.page_index].source_page, "title": block.text,
            "printed_label": row["page_label"]}
    body_pages = {b.page_index for b in body}
    header_pages = sorted({b.page_index for b in cache.blocks if b.page_index in body_pages
                           and b.type == "page_header" and _normalized(b.text) == key})
    if len(header_pages) >= 2 and header_pages == list(range(header_pages[0], header_pages[-1] + 1)):
        first = next((b for b in body if b.page_index == header_pages[0] and
                      b.type in {"title", "paragraph", "list"} and b.text.strip()
                      and not b.preservation_reason), None)
        if first:
            return first.index, "running_header_section_start", {
                "page": cache.pages[first.page_index].source_page, "first_text": first.text}
    return None, "unresolved_target", {}


def plan_printed_toc(layout: Mapping[str, Any], cache: MineruCache) -> PrintedToc | None:
    """Plan the first bounded contents region; otherwise keep the ordinary path."""
    pages = layout["pdf_info"]
    by_page: dict[int, list[tuple[dict, CachedBlock]]] = {}
    offset = 0
    for pi, page in enumerate(pages):
        records = page.get("para_blocks")
        if records is None:
            records = page.get("preproc_blocks", [])
        by_page[pi] = [(record, cache.blocks[offset + i]) for i, record in enumerate(records)]
        offset += len(records) + len(page.get("discarded_blocks", []))
    root = None
    for pi, pairs in by_page.items():
        for position, (_, block) in enumerate(pairs):
            if (block.type == "title" and _normalized(block.text) in CONTENTS_TITLES and
                    _contents_page([r for r, _ in pairs[position:]])):
                root = block
                break
        if root is not None:
            break
    if root is None:
        return None
    selected = [root.page_index]
    while selected[-1] + 1 in by_page:
        following = selected[-1] + 1
        if not _contents_page([r for r, _ in by_page[following]]):
            break
        future = defaultdict(list)
        for block in cache.blocks:
            if block.page_index > following and block.type in {"title", "paragraph"} and block.text.strip():
                future[_normalized(block.text)].append({"title": block.text, "order": [block.index]})
        verified = sum(_normalized(row["title"]) in future for record, _ in by_page[following]
                       if record.get("type") in {"text", "title"} for row in _recover(record, future)[0])
        if verified < 2:
            break
        selected.append(following)
    if any(b.preservation_reason for pi in selected for _, b in by_page[pi] if b.index > root.index):
        return None
    body = [b for b in cache.blocks if b.page_index > selected[-1]]
    headings = defaultdict(list)
    for block in body:
        if block.type == "title" and not block.preservation_reason:
            headings[_normalized(block.text)].append({"title": block.text,
                                                       "order": [block.page_index, block.index]})
    planned, omitted = {}, set()
    for pi in selected:
        for record, block in by_page[pi]:
            if block.index <= root.index:
                continue
            if block.type == "image":
                if not block.image_caption and not block.image_footnote:
                    omitted.add(block.index)
                continue
            if block.type not in {"title", "paragraph"} or not block.text.strip():
                continue
            rows, method, proof = _recover(record, headings)
            entries = []
            for row in rows:
                target, match_method, evidence = _target(row, body, cache)
                entries.append(TocEntry(
                    title=row["title"], page_label=row["page_label"], group=block.type == "title",
                    target_block=target, match_method=match_method, evidence=evidence,
                    source_spans=tuple(row.get("source_spans", ())),
                    source_ranges=tuple(tuple(r) for r in row.get("source_ranges", ())),
                    label_range=tuple(row["label_range"]) if "label_range" in row else None))
            planned[block.index] = TocBlock(_raw_text(record), tuple(entries), method, proof,
                                                block.type == "title" or method == "section label")
    return PrintedToc(tuple(cache.pages[i].source_page for i in selected), planned, frozenset(omitted))
