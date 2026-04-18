"""LD Institute of Indology manuscripts — Flask app.

Data is loaded once, at startup, into an in-memory DataStore (see
data_store.py). Handlers are thin wrappers around the store's query methods.
"""
from __future__ import annotations

import io
import os
import urllib.parse as up

from flask import (
    Flask, Response, abort, jsonify, render_template, request, send_file, url_for,
)
from flask_compress import Compress

from data_store import get_store

# Vercel enforces a 4.5 MB response body limit. At ~550 bytes/row post-gzip for
# this dataset, 8,000 rows leaves headroom. Locally there is no cap.
ON_VERCEL = bool(os.environ.get("VERCEL"))
EXPORT_MAX_ROWS = 8_000 if ON_VERCEL else 1_000_000

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
app.config["COMPRESS_MIMETYPES"] = [
    "text/html", "text/css", "text/xml", "application/json",
    "application/javascript", "text/javascript", "text/csv",
]
Compress(app)

# Eager-load so the first request is fast and startup cost is visible in logs.
STORE = get_store()
print(
    f"[ldii] loaded {STORE.stats['total_manuscripts']:,} manuscripts in "
    f"{STORE.stats['load_seconds']}s "
    f"(authors={STORE.stats['unique_authors']:,} "
    f"subjects={STORE.stats['unique_subjects']:,} "
    f"languages={STORE.stats['unique_languages']:,})"
)


# ---------- helpers ----------


def parse_int(name: str, default: int | None = None) -> int | None:
    v = request.args.get(name)
    if v in (None, ""):
        return default
    try:
        return int(v)
    except ValueError:
        return default


def parse_bool(name: str) -> bool | None:
    v = request.args.get(name)
    if v in (None, ""):
        return None
    return v.lower() in ("1", "true", "yes", "on")


def shared_filters() -> dict:
    return dict(
        q=request.args.get("q", "").strip(),
        author=request.args.get("author", "").strip(),
        subject=request.args.get("subject", "").strip(),
        language=request.args.get("language", "").strip(),
        condition=request.args.get("condition", "").strip(),
        century=parse_int("century"),
        has_commentary=parse_bool("has_commentary"),
        year_from=parse_int("year_from"),
        year_to=parse_int("year_to"),
        sort=request.args.get("sort", "manuscript_number"),
        order=request.args.get("order", "asc"),
    )


# ---------- page routes ----------


@app.route("/")
def home():
    return render_template("home.html", stats=STORE.stats)


@app.route("/browse")
def browse():
    return render_template("browse.html", facets=STORE.facets())


@app.route("/authors")
def authors():
    return render_template("authors.html")


@app.route("/authors/<path:name>")
def author_detail(name: str):
    detail = STORE.author_detail(name)
    if detail is None:
        abort(404)
    return render_template("author_detail.html", detail=detail)


@app.route("/subjects")
def subjects():
    return render_template("subjects.html", subjects=STORE.subjects_index())


@app.route("/subjects/<path:name>")
def subject_detail(name: str):
    page = parse_int("page", 1) or 1
    detail = STORE.subject_detail(name, page=page, per_page=50)
    if detail is None:
        abort(404)
    return render_template("subject_detail.html", detail=detail)


@app.route("/languages")
def languages():
    return render_template("languages.html", languages=STORE.languages_index())


@app.route("/languages/<path:name>")
def language_detail(name: str):
    page = parse_int("page", 1) or 1
    detail = STORE.language_detail(name, page=page, per_page=50)
    if detail is None:
        abort(404)
    return render_template("language_detail.html", detail=detail)


@app.route("/timeline")
def timeline():
    return render_template("timeline.html", buckets=STORE.timeline_buckets())


@app.route("/manuscript/<manuscript_number>")
def manuscript_detail(manuscript_number: str):
    row = STORE.get_by_number(manuscript_number)
    if row is None:
        abort(404)
    similar = STORE.similar_manuscripts(manuscript_number, limit=12)
    return render_template("manuscript_detail.html", row=row, similar=similar)


# ---------- JSON API ----------


@app.route("/api/stats")
def api_stats():
    return jsonify(STORE.stats)


@app.route("/api/manuscripts")
def api_manuscripts():
    page = parse_int("page", 1) or 1
    per_page = parse_int("per_page", 50) or 50
    res = STORE.query(page=page, per_page=per_page, **shared_filters())
    return jsonify(res)


@app.route("/api/manuscripts/<manuscript_number>")
def api_manuscript(manuscript_number: str):
    row = STORE.get_by_number(manuscript_number)
    if row is None:
        abort(404)
    return jsonify({"row": row, "similar": STORE.similar_manuscripts(manuscript_number)})


@app.route("/api/authors")
def api_authors():
    page = parse_int("page", 1) or 1
    per_page = parse_int("per_page", 60) or 60
    return jsonify(STORE.authors_index(
        q=request.args.get("q", "").strip(),
        sort=request.args.get("sort", "count"),
        order=request.args.get("order", "desc"),
        page=page,
        per_page=per_page,
    ))


@app.route("/api/authors/<path:name>")
def api_author_detail(name: str):
    d = STORE.author_detail(name)
    if d is None:
        abort(404)
    return jsonify(d)


@app.route("/api/subjects")
def api_subjects():
    return jsonify({"rows": STORE.subjects_index()})


@app.route("/api/subjects/<path:name>")
def api_subject_detail(name: str):
    page = parse_int("page", 1) or 1
    per_page = parse_int("per_page", 50) or 50
    d = STORE.subject_detail(name, page=page, per_page=per_page)
    if d is None:
        abort(404)
    return jsonify(d)


@app.route("/api/languages")
def api_languages():
    return jsonify({"rows": STORE.languages_index()})


@app.route("/api/languages/<path:name>")
def api_language_detail(name: str):
    page = parse_int("page", 1) or 1
    per_page = parse_int("per_page", 50) or 50
    d = STORE.language_detail(name, page=page, per_page=per_page)
    if d is None:
        abort(404)
    return jsonify(d)


@app.route("/api/timeline")
def api_timeline():
    return jsonify({"rows": STORE.timeline_buckets()})


@app.route("/api/facets")
def api_facets():
    return jsonify(STORE.facets())


@app.route("/api/random")
def api_random():
    n = parse_int("n", 6) or 6
    return jsonify({"rows": STORE.random_picks(n)})


@app.route("/api/export")
def api_export():
    buf, written, total = STORE.export_csv(max_rows=EXPORT_MAX_ROWS, **shared_filters())
    data = buf.getvalue().encode("utf-8-sig")  # BOM so Excel renders Devanagari
    headers = {"Content-Disposition": 'attachment; filename="manuscripts.csv"'}
    if written < total:
        headers["X-Export-Truncated"] = f"{written}/{total}"
    return Response(
        data,
        mimetype="text/csv; charset=utf-8",
        headers=headers,
    )


# ---------- Jinja helpers ----------


@app.template_filter("thousands")
def thousands_filter(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


@app.template_filter("ordinal_century")
def ordinal_century(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    suffix = "th"
    if n % 100 not in (11, 12, 13):
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} century"


@app.template_filter("urlenc")
def urlenc(value) -> str:
    return up.quote(str(value or ""), safe="")


# ---------- error pages ----------


@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", code=404, message="Not found"), 404


if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000, threaded=True)
