#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
import yaml


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32,
    15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19,
    29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63,
    57, 62, 11, 36, 20, 34, 44, 52,
]


def str_presenter(dumper, data):
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter, Dumper=yaml.SafeDumper)


def get_json(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return json.load(resp)


def get_html(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def resolve_short_link(url):
    if "b23.tv" in url:
        try:
            req = Request(url, headers=HEADERS)
            with urlopen(req, timeout=10) as resp:
                return resp.geturl()
        except Exception:
            pass
    return url


def parse_target(target):
    target = target.strip()
    target = resolve_short_link(target)

    # 1. BV ID
    if re.match(r"^BV[0-9A-Za-z]{10}$", target):
        return {"kind": "video", "id": target}

    # 2. Video URL
    m_vid = re.match(
        r"^https?://(?:(?:www|m)\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10})/?(?:\?.*)?$",
        target,
    )
    if m_vid:
        return {"kind": "video", "id": m_vid.group(1)}

    # 3. Opus URL (e.g. https://www.bilibili.com/opus/1244951340878135321)
    m_opus = re.match(
        r"^https?://(?:(?:www|m)\.)?bilibili\.com/opus/([0-9]+)/?(?:\?.*)?$",
        target,
    )
    if m_opus:
        return {"kind": "opus", "id": m_opus.group(1)}

    # 4. t.bilibili.com URL (e.g. https://t.bilibili.com/1244951340878135321)
    m_t = re.match(
        r"^https?://(?:(?:www|m)\.)?t\.bilibili\.com/([0-9]+)/?(?:\?.*)?$",
        target,
    )
    if m_t:
        return {"kind": "opus", "id": m_t.group(1)}

    # 5. Mobile dynamic URL (e.g. https://m.bilibili.com/dynamic/1244951340878135321)
    m_dyn = re.match(
        r"^https?://(?:(?:www|m)\.)?bilibili\.com/dynamic/([0-9]+)/?(?:\?.*)?$",
        target,
    )
    if m_dyn:
        return {"kind": "opus", "id": m_dyn.group(1)}

    # 6. Opus prefix (e.g. opus1244951340878135321 or opus/1244951340878135321)
    m_opus_prefix = re.match(r"^opus/?([0-9]+)$", target, re.IGNORECASE)
    if m_opus_prefix:
        return {"kind": "opus", "id": m_opus_prefix.group(1)}

    # 7. Pure numeric dynamic/opus ID (usually 12+ digits)
    if re.match(r"^[0-9]{12,}$", target):
        return {"kind": "opus", "id": target}

    raise ValueError(
        "Invalid target: only BV ID, video URL, or opus/dynamic URL/ID are supported.\n"
        f"Received: {target}"
    )


def get_video_info(bvid):
    data = get_json(
        "https://api.bilibili.com/x/web-interface/view"
        f"?bvid={quote(bvid)}"
    )

    if data.get("code") != 0:
        raise RuntimeError(
            f"Failed to get video info: {data.get('code')} {data.get('message')}"
        )

    vdata = data["data"]
    return {
        "kind": "video",
        "oid": vdata["aid"],
        "comment_type": 1,
        "title": vdata.get("title", ""),
        "bvid": vdata.get("bvid", ""),
        "url": f"https://www.bilibili.com/video/{vdata.get('bvid', '')}/",
    }


def get_opus_info(opus_id):
    url = f"https://www.bilibili.com/opus/{opus_id}"
    html = get_html(url)

    idx = html.find("__INITIAL_STATE__")
    if idx == -1:
        raise RuntimeError(f"Failed to locate __INITIAL_STATE__ in {url}")

    brace_idx = html.find("{", idx)
    if brace_idx == -1:
        raise RuntimeError(f"Failed to locate JSON start in {url}")

    decoder = json.JSONDecoder()
    state, _ = decoder.raw_decode(html, brace_idx)

    detail = state.get("detail", {})
    basic = detail.get("basic", {})
    comment_type = basic.get("comment_type")
    comment_id = basic.get("comment_id_str") or basic.get("rid_str")

    if not comment_type or not comment_id:
        raise RuntimeError(f"Failed to extract comment_type or comment_id from {url}")

    title = ""
    author = ""
    for mod in detail.get("modules", []):
        if not title and mod.get("module_title") and mod["module_title"].get("text"):
            title = mod["module_title"]["text"].strip()
        if not author and mod.get("module_author") and mod["module_author"].get("name"):
            author = mod["module_author"]["name"].strip()

    if not title:
        title = basic.get("title", "")

    return {
        "kind": "opus",
        "oid": str(comment_id),
        "comment_type": int(comment_type),
        "id": str(opus_id),
        "title": title,
        "author": author,
        "url": url,
    }


def get_target_info(target_spec):
    if target_spec["kind"] == "video":
        return get_video_info(target_spec["id"])
    elif target_spec["kind"] == "opus":
        return get_opus_info(target_spec["id"])
    else:
        raise ValueError(f"Unknown target kind: {target_spec.get('kind')}")


def get_wbi_keys():
    data = get_json(
        "https://api.bilibili.com/x/web-interface/nav"
    )

    wbi = data["data"]["wbi_img"]

    img_key = wbi["img_url"].rsplit("/", 1)[1].split(".", 1)[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[1].split(".", 1)[0]

    return img_key, sub_key


def get_mixin_key(img_key, sub_key):
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_wbi(params, img_key, sub_key):
    params = dict(params)
    params["wts"] = int(time.time())

    for key in params:
        params[key] = "".join(
            c for c in str(params[key])
            if c not in "!'()*"
        )

    query = "&".join(
        f"{quote(str(k), safe='~-._')}="
        f"{quote(str(v), safe='~-._')}"
        for k, v in sorted(params.items())
    )

    mixin_key = get_mixin_key(img_key, sub_key)

    w_rid = hashlib.md5(
        (query + mixin_key).encode()
    ).hexdigest()

    return query + "&w_rid=" + w_rid


def get_comments(oid, comment_type, img_key, sub_key, mode, pagination_str):
    params = {
        "oid": oid,
        "type": comment_type,
        "mode": mode,  # 3 = hot; 2 = latest
        "pagination_str": pagination_str,
        "plat": 1,
        "web_location": 1315875,
    }

    query = sign_wbi(params, img_key, sub_key)

    data = get_json(
        "https://api.bilibili.com/x/v2/reply/wbi/main?"
        + query
    )

    if data.get("code") != 0:
        raise RuntimeError(
            f"Bilibili API error: "
            f"{data.get('code')} {data.get('message')}"
        )

    return data["data"]


def is_emoji_char(ch):
    code = ord(ch)
    return (
        0x1F300 <= code <= 0x1FAFF
        or 0x1F600 <= code <= 0x1F64F
        or 0x1F680 <= code <= 0x1F6FF
        or 0x2600 <= code <= 0x27BF
        or 0xFE00 <= code <= 0xFE0F
        or 0x1F900 <= code <= 0x1F9FF
    )


def clean_comment_text(content_obj):
    if not isinstance(content_obj, dict):
        return ""

    msg = content_obj.get("message", "")
    if not msg:
        return ""

    emotes = content_obj.get("emote") or {}
    for emote_text in emotes:
        msg = msg.replace(emote_text, "")

    msg = "".join(ch for ch in msg if not is_emoji_char(ch))
    return msg.strip()


def get_sub_comments(oid, comment_type, root_rpid, preview_replies, rcount, sub_cache, sub_limit=10):
    if rcount == 0 or sub_limit <= 0:
        return []

    if root_rpid in sub_cache:
        return list(sub_cache[root_rpid][:sub_limit])

    if rcount <= len(preview_replies) and len(preview_replies) <= sub_limit:
        raw_list = preview_replies
    else:
        ps = min(sub_limit, 20)
        url = (
            f"https://api.bilibili.com/x/v2/reply/detail"
            f"?oid={oid}&type={comment_type}&root={root_rpid}&ps={ps}&pn=1"
        )
        try:
            data = get_json(url)
            root_data = (data.get("data", {}) or {}).get("root", {}) or {}
            raw_list = (
                root_data.get("replies")
                or (data.get("data", {}) or {}).get("replies")
                or []
            )
        except Exception:
            raw_list = preview_replies[:sub_limit]
        time.sleep(0.05)

    sub_comments = []
    for sub in raw_list[:sub_limit]:
        cleaned = clean_comment_text(sub.get("content", {}))
        if cleaned:
            sub_comments.append(cleaned)

    sub_cache[root_rpid] = list(sub_comments)
    return list(sub_comments)


def fetch_comments_by_mode(
    oid,
    comment_type,
    img_key,
    sub_key,
    mode,
    limit=50,
    sub_cache=None,
    exclude_rpids=None,
    sub_limit=10,
):
    if sub_cache is None:
        sub_cache = {}

    if limit <= 0:
        return [], set()

    comments = []
    rpids = set()
    offset = ""
    inspected = 0

    while inspected < limit:
        pagination_str = json.dumps({"offset": offset})
        data = get_comments(oid, comment_type, img_key, sub_key, mode, pagination_str)

        replies = data.get("replies") or []
        if not replies:
            break

        for reply in replies:
            cleaned_msg = clean_comment_text(reply.get("content", {}))
            if not cleaned_msg:
                continue

            root_rpid = reply.get("rpid")
            rpids.add(root_rpid)
            inspected += 1

            if exclude_rpids and root_rpid in exclude_rpids:
                if inspected >= limit:
                    break
                continue

            rcount = reply.get("rcount", 0)
            preview_replies = reply.get("replies") or []

            sub_comments = get_sub_comments(
                oid,
                comment_type,
                root_rpid,
                preview_replies,
                rcount,
                sub_cache,
                sub_limit=sub_limit,
            )

            item = {"content": cleaned_msg}
            if sub_comments:
                item["sub_comments"] = sub_comments

            comments.append(item)

            if inspected >= limit:
                break

        cursor = data.get("cursor", {})
        if cursor.get("is_end"):
            break

        pagination = cursor.get("pagination_reply") or {}
        offset = pagination.get("next_offset")
        if not offset:
            break

        time.sleep(0.2)

    return comments, rpids


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Bilibili video or dynamic/opus comments (hot and latest) and export to a YAML file."
    )
    parser.add_argument(
        "target",
        help="Bilibili video BV ID/URL or dynamic/opus URL/ID (e.g. BV1FmqGB8Ef9 or https://www.bilibili.com/opus/1244951340878135321)",
    )
    parser.add_argument(
        "output",
        help="Output YAML file path",
    )
    parser.add_argument(
        "--hot",
        type=int,
        default=50,
        help="Maximum number of hot comments to fetch (default: 50)",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=50,
        help="Maximum number of latest comments to fetch (default: 50)",
    )
    parser.add_argument(
        "--sub",
        type=int,
        default=10,
        help="Maximum number of sub-comments per comment to fetch (default: 10)",
    )

    args = parser.parse_args()

    target = args.target
    output_path = args.output

    target_spec = parse_target(target)
    target_info = get_target_info(target_spec)

    oid = target_info["oid"]
    comment_type = target_info["comment_type"]

    img_key, sub_key = get_wbi_keys()
    sub_cache = {}

    hot_comments, hot_rpids = fetch_comments_by_mode(
        oid,
        comment_type,
        img_key,
        sub_key,
        mode=3,
        limit=args.hot,
        sub_cache=sub_cache,
        sub_limit=args.sub,
    )
    latest_comments, _ = fetch_comments_by_mode(
        oid,
        comment_type,
        img_key,
        sub_key,
        mode=2,
        limit=args.latest,
        sub_cache=sub_cache,
        exclude_rpids=hot_rpids,
        sub_limit=args.sub,
    )

    if target_info["kind"] == "video":
        target_meta = {
            "title": target_info.get("title", ""),
            "bvid": target_info.get("bvid", ""),
            "url": target_info.get("url", ""),
        }
        output_data = {
            "video": target_meta,
            "hot_comments": hot_comments,
            "latest_comments": latest_comments,
        }
    else:
        opus_meta = {
            "title": target_info.get("title", ""),
            "id": target_info.get("id", ""),
            "author": target_info.get("author", ""),
            "url": target_info.get("url", ""),
        }
        output_data = {
            "opus": opus_meta,
            "hot_comments": hot_comments,
            "latest_comments": latest_comments,
        }

    abs_output_path = os.path.abspath(output_path)
    output_dir = os.path.dirname(abs_output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(abs_output_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_data, f, allow_unicode=True, sort_keys=False)

    total_main = len(hot_comments) + len(latest_comments)
    total_sub = sum(len(c.get("sub_comments", [])) for c in hot_comments) + sum(
        len(c.get("sub_comments", [])) for c in latest_comments
    )

    kind_desc = "video" if target_info["kind"] == "video" else "dynamic/opus"
    print(
        f"Success: fetched {total_main} main comments for {kind_desc} "
        f"(hot: {len(hot_comments)}, latest: {len(latest_comments)}) "
        f"and {total_sub} sub-comments.\n"
        f"Output saved to: {abs_output_path}"
    )


if __name__ == "__main__":
    main()
