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


def extract_bvid(target):
    target = target.strip()

    # Only standard BV ID supported
    if re.match(r"^BV[0-9A-Za-z]{10}$", target):
        return target

    # Or URLs like https://www.bilibili.com/video/BV1FmqGB8Ef9/
    match = re.match(
        r"^https?://(?:www\.)?bilibili\.com/video/(BV[0-9A-Za-z]{10})/?(?:\?.*)?$",
        target,
    )
    if match:
        return match.group(1)

    raise ValueError(
        "Invalid video target: only BV ID or URLs like https://www.bilibili.com/video/BV.../ are supported."
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

    return data["data"]


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


def get_comments(aid, img_key, sub_key, mode, pagination_str):
    params = {
        "oid": aid,
        "type": 1,
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


def get_sub_comments(aid, root_rpid, preview_replies, rcount, sub_cache, sub_limit=10):
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
            f"?oid={aid}&type=1&root={root_rpid}&ps={ps}&pn=1"
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
    aid,
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
        data = get_comments(aid, img_key, sub_key, mode, pagination_str)

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
                aid,
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
        description="Fetch Bilibili video comments (hot and latest) and export to a YAML file."
    )
    parser.add_argument(
        "target",
        help="Bilibili video BV ID or URL (e.g. BV1FmqGB8Ef9 or https://www.bilibili.com/video/BV1FmqGB8Ef9/)",
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

    bvid = extract_bvid(target)
    video = get_video_info(bvid)
    aid = video["aid"]

    img_key, sub_key = get_wbi_keys()
    sub_cache = {}

    hot_comments, hot_rpids = fetch_comments_by_mode(
        aid,
        img_key,
        sub_key,
        mode=3,
        limit=args.hot,
        sub_cache=sub_cache,
        sub_limit=args.sub,
    )
    latest_comments, _ = fetch_comments_by_mode(
        aid,
        img_key,
        sub_key,
        mode=2,
        limit=args.latest,
        sub_cache=sub_cache,
        exclude_rpids=hot_rpids,
        sub_limit=args.sub,
    )

    output_data = {
        "video": {
            "title": video.get("title", ""),
            "bvid": video.get("bvid", ""),
            "url": f"https://www.bilibili.com/video/{video.get('bvid', '')}/",
        },
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

    print(
        f"Success: fetched {total_main} main comments (hot: {len(hot_comments)}, latest: {len(latest_comments)}) "
        f"and {total_sub} sub-comments.\n"
        f"Output saved to: {abs_output_path}"
    )


if __name__ == "__main__":
    main()
