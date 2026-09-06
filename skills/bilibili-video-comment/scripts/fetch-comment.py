#!/usr/bin/env python3

import hashlib
import json
import re
import sys
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


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


def get_json(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=15) as resp:
        return json.load(resp)


def extract_bvid(value):
    match = re.search(r"BV[0-9A-Za-z]+", value)
    if not match:
        raise ValueError("没有找到 BV 号")
    return match.group(0)


def get_video_info(bvid):
    data = get_json(
        "https://api.bilibili.com/x/web-interface/view"
        f"?bvid={quote(bvid)}"
    )

    if data["code"] != 0:
        raise RuntimeError(data["message"])

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

    # WBI 要求过滤这些字符
    for key in params:
        params[key] = "".join(
            c for c in str(params[key])
            if c not in "!'()*"
        )

    # 按 key 排序，并按照 encodeURIComponent 的方式编码
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


def get_comments(aid, img_key, sub_key, pagination_str):
    params = {
        "oid": aid,
        "type": 1,
        "mode": 3,  # 热度排序；2 = 时间排序
        "pagination_str": pagination_str,
        "plat": 1,
        "web_location": 1315875,
    }

    query = sign_wbi(params, img_key, sub_key)

    data = get_json(
        "https://api.bilibili.com/x/v2/reply/wbi/main?"
        + query
    )

    if data["code"] != 0:
        raise RuntimeError(
            f"Bilibili API 错误: "
            f"{data['code']} {data.get('message')}"
        )

    return data["data"]


def main():
    if len(sys.argv) < 2:
        print(
            f"用法: {sys.argv[0]} <BV号或视频URL> [页数]",
            file=sys.stderr,
        )
        sys.exit(1)

    bvid = extract_bvid(sys.argv[1])

    # 默认抓一页；0 表示一直抓到最后
    max_pages = int(sys.argv[2]) if len(sys.argv) >= 3 else 1

    video = get_video_info(bvid)

    print(f"标题: {video['title']}")
    print(f"BV: {video['bvid']}")
    print(f"AID: {video['aid']}")
    print()

    img_key, sub_key = get_wbi_keys()

    pagination_str = '{"offset":""}'
    page = 0

    while True:
        page += 1

        data = get_comments(
            video["aid"],
            img_key,
            sub_key,
            pagination_str,
        )

        replies = data.get("replies") or []

        for reply in replies:
            member = reply.get("member", {})
            content = reply.get("content", {})

            print(
                f"[{reply.get('like', 0)}赞] "
                f"{member.get('uname', '')}: "
                f"{content.get('message', '')}"
            )

        cursor = data.get("cursor", {})

        if cursor.get("is_end"):
            break

        pagination = cursor.get("pagination_reply") or {}
        next_offset = pagination.get("next_offset")

        if not next_offset:
            break

        pagination_str = next_offset

        if max_pages != 0 and page >= max_pages:
            break

        # 不要连续高速请求
        time.sleep(0.5)


if __name__ == "__main__":
    main()