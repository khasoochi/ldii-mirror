"""In-memory data layer for the LD Institute of Indology manuscript browser.
Everything here runs once, at Flask import time. Aggregates are precomputed into
plain Python dicts so the API handlers are thin lookups, not repeated scans.
"""
from __future__ import annotations

import csv
import io
import math
import os
import random
import re
import time
import unicodedata
from collections import Counter, defaultdict
from typing import Any

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_csv_path() -> str:
    """Find manuscripts.csv across dev and serverless layouts.

    Vercel bundles the project into an opaque function root; depending on how
    the file is included the CSV can end up beside the module, one level up,
    or under /var/task. Probing a short list keeps both environments working
    without per-env config.
    """
    candidates = [
        os.environ.get("LDII_CSV_PATH"),
        os.path.join(HERE, "manuscripts.csv"),
        os.path.join(HERE, "..", "manuscripts.csv"),
        os.path.join(os.getcwd(), "manuscripts.csv"),
        "/var/task/manuscripts.csv",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return os.path.join(HERE, "manuscripts.csv")


CSV_PATH = _resolve_csv_path()

STRING_COLUMNS = [
    "manuscript_number",
    "title",
    "title_url",
    "author",
    "condition",
    "folio_number",
    "language",
    "subject",
    "year_of_writing",
    "commentator",
    "commentary_name",
]


def _to_year_int(raw: str) -> int | None:
    """Convert a year_of_writing string into a best-guess numeric year.

    The source catalogue mixes concrete years (e.g. "1723") and century
    numbers (e.g. "19" meaning 19th century). No manuscript predates the
    10th century, so anything resolving earlier is treated as a data error
    and discarded. Values 10..21 are centuries; 901..2100 are concrete years.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    if 10 <= n <= 21:
        return n * 100 - 50
    if 901 <= n <= 2100:
        return n
    return None


# ---- language normalization -------------------------------------------------
# The raw catalogue mixes full names, dotted abbreviations, and multi-language
# entries separated by commas, slashes, dashes, spaces, or periods. We
# canonicalize everything to a small set of full-form names.

_COMPOUND_LANGS: list[tuple[str, str]] = [
    # compound abbreviations with internal periods — must be handled before
    # period-based splitting
    ("मा.गु.", "मारु गुर्जर"),
    ("मा.गु",  "मारु गुर्जर"),
    ("जू.गु.", "जूनी गुजराती"),
    ("जू.गु",  "जूनी गुजराती"),
    ("पु.हिं.", "पूर्वीय हिन्दी"),
    ("पु.हिं",  "पूर्वीय हिन्दी"),
]

_SINGLE_LANGS: dict[str, str] = {
    "प्रा": "प्राकृत", "प्रा.": "प्राकृत", "प्राकृत": "प्राकृत",
    "सं": "संस्कृत",  "सं.": "संस्कृत",  "संस्कृत": "संस्कृत",
    "गु": "गुजराती",  "गु.": "गुजराती",  "गुजराती": "गुजराती",
    "व्र": "ब्रज",    "व्र.": "ब्रज",    "ब्र": "ब्रज",  "ब्र.": "ब्रज",
    "व्रज": "ब्रज",   "व्रज.": "ब्रज",   "ब्रज": "ब्रज",
    "हिं": "हिन्दी", "हिं.": "हिन्दी",
    "हि": "हिन्दी",  "हि.": "हिन्दी",
    "हिंदी": "हिन्दी", "हिन्दी": "हिन्दी",
    "रा": "राजस्थानी", "रा.": "राजस्थानी",
    "राज": "राजस्थानी", "राज.": "राजस्थानी",
    "राजस्थानी": "राजस्थानी",
    "मा": "मारवाडी", "मा.": "मारवाडी", "मारवाडी": "मारवाडी", "मारवाड़ी": "मारवाडी",
    "अप": "अपभ्रंश", "अप.": "अपभ्रंश", "अपभ्रंश": "अपभ्रंश",
    "फा": "फारसी",   "फा.": "फारसी",   "फारसी": "फारसी",
    "english": "English", "English": "English", "ENGLISH": "English",
    "मिश्र": "मिश्र",
}

_SPLIT_RE = re.compile(r"[,/\-\s.]+")
_TRAIL_PUNCT = ".।|,"
_SEP = "\u00a7"  # § — sentinel that survives _SPLIT_RE


def _normalize_languages(raw: str) -> list[str]:
    """Split a raw language string into a canonical list of language names.

    Separators: comma, slash, dash, whitespace, period. Compound abbreviations
    with internal periods (मा.गु., जू.गु., पु.हिं.) are preserved.
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    # Replace compound abbreviations with sentinel-bracketed placeholders,
    # so the subsequent period split doesn't shred them.
    work = raw
    subs: dict[str, str] = {}
    for i, (src, dst) in enumerate(_COMPOUND_LANGS):
        if src in work:
            key = f"{_SEP}C{i}{_SEP}"
            subs[key] = dst
            work = work.replace(src, f" {key} ")

    out: list[str] = []
    seen: set[str] = set()
    for tok in _SPLIT_RE.split(work):
        tok = tok.strip()
        if not tok:
            continue
        if tok in subs:
            canonical = subs[tok]
        else:
            while tok and tok[-1] in _TRAIL_PUNCT:
                tok = tok[:-1]
            if not tok:
                continue
            canonical = _SINGLE_LANGS.get(tok, tok)
        if canonical and canonical not in seen:
            out.append(canonical)
            seen.add(canonical)
    return out


def _to_century(year_int: int | None) -> int | None:
    if year_int is None:
        return None
    return (year_int - 1) // 100 + 1


def _normalize_search(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "").strip()).lower()


class DataStore:
    def __init__(self, csv_path: str = CSV_PATH):
        t0 = time.perf_counter()
        self.df = self._load(csv_path)
        self._derive_columns()
        self._build_indexes()
        self._build_counts()
        self._build_stats()
        self._build_search_blob()
        self.load_seconds = time.perf_counter() - t0

    # ---------- load & normalize ----------

    def _load(self, path: str) -> pd.DataFrame:
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            na_values=[],
            encoding="utf-8",
        )
        for col in STRING_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        for col in STRING_COLUMNS:
            df[col] = df[col].fillna("").astype(str).str.strip()
        return df.reset_index(drop=True)

    def _derive_columns(self) -> None:
        self.df["year_int"] = self.df["year_of_writing"].map(_to_year_int)
        self.df["century"] = self.df["year_int"].map(_to_century)
        self.df["has_commentary"] = (self.df["commentator"] != "") | (
            self.df["commentary_name"] != ""
        )
        folio_numeric = pd.to_numeric(self.df["folio_number"], errors="coerce")
        self.df["folio_int"] = folio_numeric

        # canonicalize languages — each row gets a list (may be multi-valued)
        self.df["language_raw"] = self.df["language"]
        self.df["languages_set"] = self.df["language"].map(_normalize_languages)
        self.df["language"] = self.df["languages_set"].map(lambda xs: ", ".join(xs))

    def _build_indexes(self) -> None:
        """Dicts of key -> list[row index]. O(1) per-view lookups."""
        self.by_author: dict[str, list[int]] = defaultdict(list)
        self.by_subject: dict[str, list[int]] = defaultdict(list)
        self.by_language: dict[str, list[int]] = defaultdict(list)
        self.by_condition: dict[str, list[int]] = defaultdict(list)
        self.by_century: dict[int, list[int]] = defaultdict(list)
        self.by_commentator: dict[str, list[int]] = defaultdict(list)

        authors = self.df["author"].tolist()
        subjects = self.df["subject"].tolist()
        lang_sets = self.df["languages_set"].tolist()
        conds = self.df["condition"].tolist()
        cents = self.df["century"].tolist()
        comms = self.df["commentator"].tolist()

        for i in range(len(self.df)):
            if authors[i]:
                self.by_author[authors[i]].append(i)
            if subjects[i]:
                self.by_subject[subjects[i]].append(i)
            for lang in lang_sets[i]:
                self.by_language[lang].append(i)
            if conds[i]:
                self.by_condition[conds[i]].append(i)
            if cents[i] is not None and not (isinstance(cents[i], float) and math.isnan(cents[i])):
                self.by_century[int(cents[i])].append(i)
            if comms[i]:
                self.by_commentator[comms[i]].append(i)

    def _build_counts(self) -> None:
        self.author_counts: dict[str, int] = {k: len(v) for k, v in self.by_author.items()}
        self.subject_counts: dict[str, int] = {k: len(v) for k, v in self.by_subject.items()}
        self.language_counts: dict[str, int] = {k: len(v) for k, v in self.by_language.items()}
        self.condition_counts: dict[str, int] = {k: len(v) for k, v in self.by_condition.items()}
        self.century_counts: dict[int, int] = {k: len(v) for k, v in self.by_century.items()}

    def _build_stats(self) -> None:
        total = len(self.df)
        with_comm = int(self.df["has_commentary"].sum())
        missing_author = int((self.df["author"] == "").sum())
        known_year = self.df.dropna(subset=["year_int"])
        oldest = known_year.nsmallest(20, "year_int")
        newest = known_year.nlargest(20, "year_int")

        self.stats: dict[str, Any] = {
            "total_manuscripts": total,
            "unique_authors": len(self.by_author),
            "unique_subjects": len(self.by_subject),
            "unique_languages": len(self.by_language),
            "unique_commentators": len(self.by_commentator),
            "with_commentary": with_comm,
            "missing_author": missing_author,
            "top_authors": top_n(self.author_counts, 15),
            "top_subjects": top_n(self.subject_counts, 15),
            "top_languages": top_n(self.language_counts, 10),
            "top_commentators": top_n(
                {k: len(v) for k, v in self.by_commentator.items()}, 10
            ),
            "condition_distribution": top_n(self.condition_counts, 20),
            "century_distribution": sorted(
                [{"century": int(k), "count": v} for k, v in self.century_counts.items()],
                key=lambda d: d["century"],
            ),
            "oldest_manuscripts": rows_to_dicts(oldest),
            "newest_manuscripts": rows_to_dicts(newest),
            "load_seconds": None,  # filled later
        }

    def _build_search_blob(self) -> None:
        parts = (
            self.df["title"].map(_normalize_search)
            + " | "
            + self.df["author"].map(_normalize_search)
            + " | "
            + self.df["subject"].map(_normalize_search)
            + " | "
            + self.df["commentator"].map(_normalize_search)
            + " | "
            + self.df["commentary_name"].map(_normalize_search)
        )
        self.search_blob = parts

    # ---------- public query API ----------

    def query(
        self,
        q: str = "",
        author: str = "",
        subject: str = "",
        language: str = "",
        condition: str = "",
        century: int | None = None,
        has_commentary: bool | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str = "manuscript_number",
        order: str = "asc",
        page: int = 1,
        per_page: int = 50,
    ) -> dict[str, Any]:
        df = self.df
        mask = pd.Series(True, index=df.index)

        if q:
            q_norm = _normalize_search(q)
            mask &= self.search_blob.str.contains(q_norm, regex=False, na=False)
        if author:
            mask &= df["author"] == author
        if subject:
            mask &= df["subject"] == subject
        if language:
            idxs = self.by_language.get(language, [])
            lang_mask = pd.Series(False, index=df.index)
            if idxs:
                lang_mask.iloc[idxs] = True
            mask &= lang_mask
        if condition:
            mask &= df["condition"] == condition
        if century is not None:
            mask &= df["century"] == century
        if has_commentary is True:
            mask &= df["has_commentary"]
        elif has_commentary is False:
            mask &= ~df["has_commentary"]
        if year_from is not None:
            mask &= df["year_int"].fillna(-10_000) >= year_from
        if year_to is not None:
            mask &= df["year_int"].fillna(10_000) <= year_to

        filtered = df[mask]
        total = len(filtered)

        sort_col = sort if sort in df.columns else "manuscript_number"
        ascending = order != "desc"
        if sort_col == "manuscript_number":
            sort_key = pd.to_numeric(filtered["manuscript_number"], errors="coerce")
            filtered = filtered.assign(_sk=sort_key).sort_values(
                "_sk", ascending=ascending, kind="mergesort"
            ).drop(columns=["_sk"])
        elif sort_col in ("year_int", "year_of_writing"):
            filtered = filtered.sort_values(
                "year_int", ascending=ascending, kind="mergesort", na_position="last"
            )
        elif sort_col == "folio_number":
            filtered = filtered.sort_values(
                "folio_int", ascending=ascending, kind="mergesort", na_position="last"
            )
        else:
            filtered = filtered.sort_values(sort_col, ascending=ascending, kind="mergesort")

        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        start = (page - 1) * per_page
        slice_df = filtered.iloc[start : start + per_page]

        return {
            "total": int(total),
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "rows": rows_to_dicts(slice_df),
        }

    def get_by_number(self, manuscript_number: str) -> dict[str, Any] | None:
        match = self.df[self.df["manuscript_number"] == str(manuscript_number)]
        if match.empty:
            return None
        row = match.iloc[0]
        return row_to_dict(row)

    def similar_manuscripts(self, manuscript_number: str, limit: int = 12) -> list[dict[str, Any]]:
        base = self.df[self.df["manuscript_number"] == str(manuscript_number)]
        if base.empty:
            return []
        r = base.iloc[0]
        picks: list[int] = []
        seen: set[int] = set()
        base_idx = int(base.index[0])
        seen.add(base_idx)

        if r["author"]:
            for i in self.by_author.get(r["author"], []):
                if i not in seen:
                    picks.append(i)
                    seen.add(i)
                    if len(picks) >= limit:
                        break
        if len(picks) < limit and r["subject"]:
            for i in self.by_subject.get(r["subject"], []):
                if i not in seen:
                    picks.append(i)
                    seen.add(i)
                    if len(picks) >= limit:
                        break
        return rows_to_dicts(self.df.iloc[picks])

    def author_detail(self, name: str) -> dict[str, Any] | None:
        idxs = self.by_author.get(name)
        if not idxs:
            return None
        sub = self.df.iloc[idxs]
        subject_breakdown = Counter(sub["subject"])
        language_breakdown: Counter = Counter()
        for xs in sub["languages_set"]:
            for lang in xs:
                language_breakdown[lang] += 1
        century_breakdown = Counter(int(c) for c in sub["century"].dropna())
        years = sub["year_int"].dropna()
        return {
            "name": name,
            "total": len(idxs),
            "subject_breakdown": top_n(dict(subject_breakdown), 20),
            "language_breakdown": top_n(dict(language_breakdown), 10),
            "century_breakdown": sorted(
                [{"century": k, "count": v} for k, v in century_breakdown.items()],
                key=lambda d: d["century"],
            ),
            "earliest": int(years.min()) if not years.empty else None,
            "latest": int(years.max()) if not years.empty else None,
            "rows": rows_to_dicts(sub.sort_values("year_int", na_position="last")),
        }

    def subject_detail(self, name: str, page: int = 1, per_page: int = 50) -> dict[str, Any] | None:
        idxs = self.by_subject.get(name)
        if not idxs:
            return None
        sub = self.df.iloc[idxs]
        total = len(sub)
        language_breakdown: Counter = Counter()
        for xs in sub["languages_set"]:
            for lang in xs:
                language_breakdown[lang] += 1
        century_breakdown = Counter(int(c) for c in sub["century"].dropna())
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        start = (page - 1) * per_page
        return {
            "name": name,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
            "page": page,
            "per_page": per_page,
            "language_breakdown": top_n(dict(language_breakdown), 10),
            "century_breakdown": sorted(
                [{"century": k, "count": v} for k, v in century_breakdown.items()],
                key=lambda d: d["century"],
            ),
            "rows": rows_to_dicts(
                sub.sort_values("year_int", na_position="last").iloc[start : start + per_page]
            ),
        }

    def language_detail(self, name: str, page: int = 1, per_page: int = 50) -> dict[str, Any] | None:
        idxs = self.by_language.get(name)
        if not idxs:
            return None
        sub = self.df.iloc[idxs]
        total = len(sub)
        subject_breakdown = Counter(sub["subject"])
        century_breakdown = Counter(int(c) for c in sub["century"].dropna())
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        start = (page - 1) * per_page
        return {
            "name": name,
            "total": total,
            "pages": max(1, (total + per_page - 1) // per_page),
            "page": page,
            "per_page": per_page,
            "subject_breakdown": top_n(dict(subject_breakdown), 15),
            "century_breakdown": sorted(
                [{"century": k, "count": v} for k, v in century_breakdown.items()],
                key=lambda d: d["century"],
            ),
            "rows": rows_to_dicts(
                sub.sort_values("year_int", na_position="last").iloc[start : start + per_page]
            ),
        }

    def authors_index(
        self, q: str = "", sort: str = "count", order: str = "desc",
        page: int = 1, per_page: int = 60,
    ) -> dict[str, Any]:
        items = list(self.author_counts.items())
        if q:
            q_norm = _normalize_search(q)
            items = [it for it in items if q_norm in _normalize_search(it[0])]
        reverse = order != "asc"
        if sort == "name":
            items.sort(key=lambda x: x[0], reverse=reverse)
        else:
            items.sort(key=lambda x: (x[1], x[0]), reverse=reverse)
        total = len(items)
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        start = (page - 1) * per_page
        page_items = items[start : start + per_page]
        # enrich with a top subject per author (cheap — idx list is already there)
        enriched = []
        for name, count in page_items:
            idxs = self.by_author[name][:500]  # cap
            top_subject = ""
            if idxs:
                subj_counts = Counter(self.df["subject"].iloc[idxs])
                subj_counts.pop("", None)
                if subj_counts:
                    top_subject = subj_counts.most_common(1)[0][0]
            enriched.append({"name": name, "count": count, "top_subject": top_subject})
        return {
            "total": total,
            "page": page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "per_page": per_page,
            "rows": enriched,
        }

    def subjects_index(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        lang_sets = self.df["languages_set"]
        for name, idxs in self.by_subject.items():
            sub_langs: Counter = Counter()
            for xs in lang_sets.iloc[idxs]:
                for lang in xs:
                    sub_langs[lang] += 1
            top_lang = sub_langs.most_common(1)[0][0] if sub_langs else ""
            items.append({"name": name, "count": len(idxs), "top_language": top_lang})
        items.sort(key=lambda d: (-d["count"], d["name"]))
        return items

    def languages_index(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for name, idxs in self.by_language.items():
            sub_subjects = Counter(self.df["subject"].iloc[idxs])
            sub_subjects.pop("", None)
            top_subject = sub_subjects.most_common(1)[0][0] if sub_subjects else ""
            items.append({"name": name, "count": len(idxs), "top_subject": top_subject})
        items.sort(key=lambda d: (-d["count"], d["name"]))
        return items

    def timeline_buckets(self) -> list[dict[str, Any]]:
        return sorted(
            [{"century": int(k), "count": v} for k, v in self.century_counts.items()],
            key=lambda d: d["century"],
        )

    def facets(self) -> dict[str, list[str]]:
        return {
            "languages": sorted(self.by_language.keys()),
            "subjects": sorted(self.by_subject.keys()),
            "conditions": sorted(self.by_condition.keys()),
            "centuries": sorted(int(c) for c in self.by_century.keys()),
            "authors": sorted(self.by_author.keys()),
        }

    def random_picks(self, n: int = 6) -> list[dict[str, Any]]:
        n = max(1, min(n, 24))
        idx = random.sample(range(len(self.df)), n)
        return rows_to_dicts(self.df.iloc[idx])

    def export_csv(self, max_rows: int = 1_000_000, **filters) -> tuple[io.StringIO, int, int]:
        """Return (buffer, written_rows, total_rows). `written_rows` may be
        less than `total_rows` when capped by `max_rows`."""
        res = self.query(page=1, per_page=max_rows, **filters)
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=[
                "manuscript_number", "title", "author", "language", "subject",
                "condition", "folio_number", "year_of_writing", "commentator",
                "commentary_name", "title_url",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        for row in res["rows"]:
            writer.writerow(row)
        buf.seek(0)
        return buf, len(res["rows"]), int(res["total"])


# ---------- helpers ----------


def top_n(counts: dict[str, int], n: int) -> list[dict[str, Any]]:
    items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [{"name": k, "count": v} for k, v in items[:n] if k]


def row_to_dict(row: pd.Series) -> dict[str, Any]:
    d = {
        "manuscript_number": row["manuscript_number"],
        "title": row["title"],
        "title_url": row["title_url"],
        "author": row["author"],
        "condition": row["condition"],
        "folio_number": row["folio_number"],
        "language": row["language"],
        "subject": row["subject"],
        "year_of_writing": row["year_of_writing"],
        "commentator": row["commentator"],
        "commentary_name": row["commentary_name"],
    }
    yi = row.get("year_int")
    d["year_int"] = None if pd.isna(yi) else int(yi)
    ce = row.get("century")
    d["century"] = None if pd.isna(ce) else int(ce)
    d["has_commentary"] = bool(row.get("has_commentary", False))
    return d


def rows_to_dicts(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [row_to_dict(r) for _, r in df.iterrows()]


# ---------- module-level singleton ----------

STORE: DataStore | None = None


def get_store() -> DataStore:
    global STORE
    if STORE is None:
        STORE = DataStore()
        STORE.stats["load_seconds"] = round(STORE.load_seconds, 3)
    return STORE
