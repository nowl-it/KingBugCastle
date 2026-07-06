#!/usr/bin/env python3
"""
Fetch official King God Castle update logs / notices.

Site https://kgcastle-notice.awesomepiece.com/ is a Notion page rendered by OOPY
(oopy.io, CDN cdn.lazyrockets.com). The notices live in a Notion *collection*
(database). We bypass OOPY and read Notion's public unofficial v3 API directly.

How the IDs below were discovered (re-derive if site changes):
  1. GET the site root -> parse <script id="__NEXT_DATA__"> JSON.
     props.pageProps.hostname.spaceId    = Notion workspace id  (SPACE)
     props.pageProps.hostname.rootPageId = landing page id
  2. The landing links to child pages "News"/"공지사항"/"お知らせ".
     loadCachedPageChunk(News id) -> its content has a collection block whose
     value.collection_id = the announcement DB id (COLLECTION) + view_ids[0] (VIEW).

No auth needed: the pages are public.  ponytail: IDs hardcoded; if the notice
page is rebuilt, run step 1-2 again (a dozen lines) instead of generalizing now.
"""
import sys, json, urllib.request

SPACE      = "bc729c5c-eeb4-42da-b216-4d6ccb8cfe96"
COLLECTION = "3db4d56c-c068-4cd9-9e06-9b0465eb0910"  # "Announcement List" DB
VIEW       = "8cd0ad56-352b-472d-8610-1c19d346e0bb"
API = "https://www.notion.so/api/v3"

def _post(path, payload):
    req = urllib.request.Request(
        f"{API}/{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

def _val(b):
    v = b.get("value")
    return (v["value"] if v and isinstance(v.get("value"), dict) else v) or {}

def _text(rich):
    return "".join(seg[0] for seg in rich) if rich else ""

def _query(limit, sort=None, flt=None):
    loader = {"type": "reducer",
              "reducers": {"collection_group_results":
                           {"type": "results", "limit": limit}},
              "searchQuery": "", "userTimeZone": "Asia/Ho_Chi_Minh"}
    if sort: loader["sort"] = sort
    if flt:  loader["filter"] = flt
    d = _post("queryCollection?src=initial_load", {
        "collection": {"id": COLLECTION, "spaceId": SPACE},
        "collectionView": {"id": VIEW, "spaceId": SPACE},
        "loader": loader})
    ids = d["result"]["reducerResults"]["collection_group_results"]["blockIds"]
    return ids, d["recordMap"]["block"]

def _detect_props(B):
    """Find the obfuscated property ids for date + language by sniffing a row's
    values (ids change if Awesomepiece rebuilds the DB, so never hardcode them).
    date prop value = [['‣',[['d',{'type':'date',...}]]]]; lang prop = [['en']] etc."""
    date_id = lang_id = None
    for b in B.values():
        props = _val(b).get("properties") or {}
        for pid, pv in props.items():
            if pid == "title":
                continue
            try:
                segs = pv[0][1]
                if segs and segs[0][0] == "d" and segs[0][1].get("type") == "date":
                    date_id = pid; continue
            except (IndexError, TypeError, AttributeError):
                pass
            try:
                if pv[0][0] in ("en", "kr", "ko", "ja"):
                    lang_id = pid
            except (IndexError, TypeError):
                pass
        if date_id and lang_id:
            break
    return date_id, lang_id

def list_notices(limit=20, lang="en"):
    """Newest-first. The site's default view filters/sorts by language so it
    hides other-language rows; we override with our own date-desc sort + lang
    filter so the genuinely-newest notice always surfaces."""
    # bootstrap: grab a few rows just to learn the date/lang property ids
    _, B0 = _query(5)
    date_id, lang_id = _detect_props(B0)
    if lang == "ko":           # site uses "kr" not "ko"
        lang = "kr"
    sort = [{"property": date_id, "direction": "descending"}] if date_id else None
    flt = None
    if lang and lang_id:
        flt = {"operator": "and", "filters": [{"property": lang_id,
               "filter": {"operator": "enum_is",
                          "value": {"type": "exact", "value": lang}}}]}
    ids, B = _query(limit, sort=sort, flt=flt)
    out = []
    for bid in ids:
        v = _val(B[bid])
        props = v.get("properties", {})
        date = ""
        if date_id and props.get(date_id):
            try: date = props[date_id][0][1][0][1].get("start_date", "")
            except (IndexError, TypeError, AttributeError): pass
        out.append((bid, date, _text(props.get("title"))))
    return out

def page_text(page_id):
    """Dump one notice's body as plain text (headers, paragraphs, lists)."""
    d = _post("loadCachedPageChunk", {
        "page": {"id": page_id}, "limit": 200,
        "cursor": {"stack": []}, "chunkNumber": 0, "verticalColumns": False})
    B = d["recordMap"]["block"]
    root = _val(B[page_id])
    lines = []
    for cid in root.get("content", []):
        if cid not in B:
            continue
        v = _val(B[cid])
        t = _text(v.get("properties", {}).get("title"))
        if t:
            lines.append(t)
    return "\n".join(lines)

if __name__ == "__main__":
    args = sys.argv[1:]
    # dump one notice body:  fetch_notices.py <page-id>
    if args and len(args[0]) >= 32 and "-" in args[0]:
        print(page_text(args[0]))
    else:
        # list newest notices:  fetch_notices.py [lang]   (lang default en; ko/ja)
        lang = args[0] if args else "en"
        for bid, date, title in list_notices(lang=lang):
            print(f"{date}  {bid}  {title}")
