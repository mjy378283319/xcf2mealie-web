#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xcf2mealie.py —— 把「下厨房」菜谱搬进 Mealie，尽量不用手工改。

为什么不用 Mealie 自带的 URL 导入：
  下厨房没有标准的 schema.org/Recipe JSON-LD（只有百度 cambrian 版本，配料写成
  "150克1、玉米粒" 这种串，步骤没有图片），Mealie 的 recipe-scrapers 也不支持该站点，
  所以直接贴网址会丢步骤图、配料拆不开、营养全空。

本脚本直接按下厨房的页面结构解析，再通过 Mealie 的 REST API 写入：
  用料（数量 / 单位 / 食材拆成三个字段，可缩放、可进购物清单）
  步骤（文字 + 每步配图，图片作为 recipe asset 上传并渲染在步骤里）
  营养（11 项，对照 Mealie 的 Nutrition 字段，值由你或 AI 提供）
  成品图、分类、标签、作者、原文链接、时间

用法：
  # 1) 只抓取，产出结构化 JSON + 图片，先看看对不对
  python xcf2mealie.py fetch <url> [<url>...] --out ./data
  python xcf2mealie.py fetch --file urls.txt --out ./data

  # 2) 推送到 Mealie（可先 --dry-run 预览 payload）
  python xcf2mealie.py push ./data/106493601.json --mealie http://192.168.1.10:9925 --token xxxx

  # 3) 一步到位
  python xcf2mealie.py run <url> --mealie http://192.168.1.10:9925 --token xxxx

营养数据的两种给法：
  a) 在 JSON 里直接填 "nutrition" 字段（fetch 后会生成 11 个空键的模板）；
  b) 用 --nutrition nutrition.json，文件结构 {"<菜谱URL或ID>": { nutrition 对象 }}。

只依赖 Python 3 标准库。
"""

from __future__ import annotations

import argparse
import gzip
import html as htmllib
import http.cookiejar
import json
import zlib
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

BLOCK_MARKS = ("滑动验证", "验证码", "访问异常")

NUTRITION_KEYS = [
    "calories",              # 卡路里
    "carbohydrateContent",   # 碳水化合物
    "cholesterolContent",    # 胆固醇
    "fatContent",            # 脂肪
    "fiberContent",          # 纤维
    "proteinContent",        # 蛋白质
    "saturatedFatContent",   # 饱和脂肪
    "sodiumContent",         # 钠
    "sugarContent",          # 糖
    "transFatContent",       # 反式脂肪
    "unsaturatedFatContent", # 不饱和脂肪
]

NUTRITION_LABELS = {
    "calories": "卡路里",
    "carbohydrateContent": "碳水化合物",
    "cholesterolContent": "胆固醇",
    "fatContent": "脂肪",
    "fiberContent": "纤维",
    "proteinContent": "蛋白质",
    "saturatedFatContent": "饱和脂肪",
    "sodiumContent": "钠",
    "sugarContent": "糖",
    "transFatContent": "反式脂肪",
    "unsaturatedFatContent": "不饱和脂肪",
}

# 单位标准化（下厨房写法 -> Mealie 里显示的单位）
UNIT_MAP = {
    "g": "克", "克": "克", "gram": "克", "grams": "克",
    "kg": "千克", "千克": "千克", "公斤": "千克",
    "ml": "毫升", "毫升": "毫升", "cc": "毫升",
    "l": "升", "L": "升", "升": "升",
    "大勺": "大勺", "汤匙": "汤匙", "勺": "勺", "小勺": "小勺", "茶匙": "茶匙",
    "个": "个", "只": "只", "根": "根", "片": "片", "瓣": "瓣", "块": "块",
    "条": "条", "杯": "杯", "碗": "碗", "把": "把", "滴": "滴", "支": "支",
    "枚": "枚", "张": "张", "包": "包", "袋": "袋", "盒": "盒", "罐": "罐",
    "瓶": "瓶", "撮": "撮", "截": "截", "段": "段", "把儿": "把",
}

# 模糊用量：不进 quantity，改为 note
VAGUE_WORDS = ("适量", "少许", "若干", "少量", "一点点", "随意", "按需", "optional", "to taste")

CN_NUM = {"半": 0.5, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

# --------------------------------------------------------------------------- #
# 抓取
# --------------------------------------------------------------------------- #


class Fetcher:
    """带 cookie 的最小 HTTP 客户端。每个实例一套独立 cookie，避免风控 cookie 串味。"""

    def __init__(self, timeout: int = 25):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj)
        )
        self.timeout = timeout

    def get(self, url: str, ua: str = UA_DESKTOP, referer: str | None = None,
            binary: bool = False):
        req = urllib.request.Request(url)
        req.add_header("User-Agent", ua)
        req.add_header("Accept-Language", "zh-CN,zh;q=0.9")
        req.add_header("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
        req.add_header("Accept-Encoding", "gzip, deflate")
        req.add_header("Upgrade-Insecure-Requests", "1")
        if referer:
            req.add_header("Referer", referer)
        with self.opener.open(req, timeout=self.timeout) as resp:
            data = resp.read()
            enc = (resp.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            data = gzip.decompress(data)
        elif enc == "deflate":
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompress(data, -zlib.MAX_WBITS)
        return data if binary else data.decode("utf-8", errors="replace")

    def download(self, url: str, dest: str) -> bool:
        try:
            data = self.get(url, ua=UA_DESKTOP, referer="https://www.xiachufang.com/", binary=True)
        except Exception as exc:
            print(f"    [warn] 图片下载失败 {url} -> {exc}")
            return False
        if not data or len(data) < 1024:
            print(f"    [warn] 图片过小/为空，跳过 {url}")
            return False
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        return True


def recipe_id_from_url(url: str) -> str:
    m = re.search(r"/recipe/(\d+)", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-12:]


def looks_blocked(h: str) -> bool:
    if any(mark in h for mark in BLOCK_MARKS):
        return True
    return ('class="ing' not in h) and ('class="ings' not in h) and ('<div class="ings"' not in h)


def fetch_recipe_html(url: str) -> tuple[str, str]:
    """返回 (html, 来源标记)。下厨房的滑块风控会拦桌面版，移动端站点更稳，所以先走移动端。"""
    rid = recipe_id_from_url(url)
    errors = []

    # 1) 移动端（结构完整：用料 / 步骤图 / 小贴士 / JSON-LD 都有）
    try:
        h = Fetcher().get(f"https://m.xiachufang.com/recipe/{rid}/", ua=UA_MOBILE)
        if not looks_blocked(h):
            return h, "mobile"
        errors.append("移动端被风控拦截")
    except Exception as exc:
        errors.append(f"移动端：{exc}")

    # 2) 桌面版兜底（首页 cookie + Referer）
    try:
        f = Fetcher()
        f.get("https://www.xiachufang.com/", ua=UA_DESKTOP)
        h = f.get(url, ua=UA_DESKTOP, referer="https://www.xiachufang.com/")
        if not looks_blocked(h):
            return h, "desktop"
        errors.append("桌面版被风控拦截")
    except Exception as exc:
        errors.append(f"桌面版：{exc}")

    raise RuntimeError("；".join(errors) + "。可稍后重试，或浏览器打开后另存 HTML 用 --html 导入")


# --------------------------------------------------------------------------- #
# 解析
# --------------------------------------------------------------------------- #

def strip_tags(s: str) -> str:
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</p>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = htmllib.unescape(s)
    s = re.sub(r"[ \t\u3000]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def orig_image(url: str | None) -> str | None:
    """去掉下厨房的 imageView2 缩放参数，拿原图。"""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    return url.split("?")[0] or None


def parse_ld_json(h: str) -> dict:
    out: dict = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', h, re.S):
        try:
            data = json.loads(m.group(1).strip())
        except Exception:
            continue
        if isinstance(data, list):
            data = data[0] if data else {}
        if data.get("@type") == "Recipe":
            out = data
            break
    return out


def _parse_amount(amount: str) -> tuple[float | None, str | None, str]:
    """把 '150克' / '200-250ml' / '1/2个' / '适量' 拆成 (数量, 单位, 备注)。"""
    amount = (amount or "").strip()
    if not amount:
        return None, None, ""

    for word in VAGUE_WORDS:
        if word in amount:
            return None, None, amount

    # 分数：1/2 个
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*(.*)$", amount)
    if m:
        try:
            qty = int(m.group(1)) / int(m.group(2))
        except ZeroDivisionError:
            qty = None
        unit = m.group(3).strip()
        return qty, UNIT_MAP.get(unit, unit) or None, ""

    # 数字（含区间）
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:[-~—－至]\s*\d+(?:\.\d+)?)?\s*(.*)$", amount)
    if m:
        qty = float(m.group(1))
        unit = (m.group(2) or "").strip().strip("。 ")
        unit = UNIT_MAP.get(unit, unit)
        return qty, unit or None, ""

    # 中文数字开头：半勺 / 一个
    m = re.match(r"^\s*([一二两三四五六七八九十半])\s*(.*)$", amount)
    if m:
        qty = CN_NUM.get(m.group(1))
        unit = (m.group(2) or "").strip()
        unit = UNIT_MAP.get(unit, unit)
        return qty, unit or None, ""

    return None, None, amount


def clean_food_name(name: str) -> str:
    name = strip_tags(name)
    name = re.sub(r"^\s*\d+\s*[、.．:：）)]\s*", "", name)   # 去掉 "1、"
    name = re.sub(r"^\s*[-*·•]\s*", "", name)
    return name.strip().strip("：:，,、").strip()


def is_section_heading(raw_name: str, amount: str) -> bool:
    """下厨房的分组标题：有名字、有用量栏为空（如 "油酥："）。"""
    return (not amount.strip()) and bool(re.search(r"[：:]\s*$", strip_tags(raw_name)))


def build_ingredient(name: str, amount: str) -> dict:
    food = clean_food_name(name)
    qty, unit, note = _parse_amount(amount)

    # 名称里可能自带用量，例如 "鸡蛋 2个"（用量栏写"适量"时）
    if qty is None and not unit:
        m = re.search(r"(\d+(?:\.\d+)?)\s*(克|毫升|ml|ML|g|G|千克|kg|个|只|片|根|瓣|勺|大勺|小勺|杯|碗|块|张|枚|包|袋|瓶|罐)\s*$", food)
        if m:
            qty = float(m.group(1))
            unit = UNIT_MAP.get(m.group(2), m.group(2))
            food = food[: m.start()].strip(" ：:，,")

    item = {
        "food": food,
        "quantity": qty,
        "unit": unit,
        "note": note,
        "section": "",
        "original": f"{clean_food_name(name)} {amount}".strip(),
    }
    # 无数量、无单位、无备注 → 多半是「分组标题 / 准备备注」一行，转成标题而非食材，
    # 避免导入后一堆空食材行需要手删。
    if qty is None and not unit and not note:
        item["_heading"] = True
    return item


def apply_sections(ingredients: list[dict]) -> list[dict]:
    """把分组标题从食材列表里提出来，转成 Mealie 的 title 字段（连续的同一 title 会显示为一组）。"""
    out, current = [], ""
    for ing in ingredients:
        if ing.get("_heading"):
            current = ing["food"].strip("：: ")
            continue
        ing["section"] = current
        out.append(ing)
    return out


def parse_desktop(h: str) -> dict:
    res: dict = {"ingredients": [], "steps": [], "tips": ""}

    m = re.search(r'<div class="ings">(.*?)</table>', h, re.S)
    if m:
        for tr in re.finditer(r"<tr[^>]*>(.*?)</tr>", m.group(1), re.S):
            name = re.search(r'<td class="name">(.*?)</td>', tr.group(1), re.S)
            unit = re.search(r'<td class="unit">(.*?)</td>', tr.group(1), re.S)
            if not name:
                continue
            raw_name, amount = name.group(1), strip_tags(unit.group(1)) if unit else ""
            item = build_ingredient(raw_name, amount)
            if is_section_heading(raw_name, amount):
                item["_heading"] = True
            res["ingredients"].append(item)

    m = re.search(r'<div class="steps">(.*?)</ol>', h, re.S)
    if m:
        for li in re.finditer(r"<li[^>]*>(.*?)</li>", m.group(1), re.S):
            block = li.group(1)
            t = re.search(r'<p class="text"[^>]*>(.*?)</p>', block, re.S)
            img = re.search(r'<img[^>]+src="([^"]+)"', block)
            text = strip_tags(t.group(1)) if t else ""
            if not text and not img:
                continue
            res["steps"].append({"text": text, "image": orig_image(img.group(1)) if img else None})

    m = re.search(r'<div class="tip"[^>]*>(.*?)</div>', h, re.S)
    if m:
        res["tips"] = strip_tags(m.group(1))
    return res


def parse_mobile(h: str) -> dict:
    res: dict = {"ingredients": [], "steps": [], "tips": ""}

    for m in re.finditer(
        r'<div class="ing-name"[^>]*>(.*?)</div>\s*<div class="ing-amount"[^>]*>(.*?)</div>',
        h, re.S,
    ):
        raw_name, amount = m.group(1), strip_tags(m.group(2))
        item = build_ingredient(raw_name, amount)
        if is_section_heading(raw_name, amount):
            item["_heading"] = True
        res["ingredients"].append(item)

    i = h.find("recipe-steps")
    if i >= 0:
        j = h.find('<section id="tips"', i)
        seg = h[i: j if j > i else i + 500000]
        imgs = [orig_image(u) for u in re.findall(r'<img src="([^"]+)"', seg)]
        texts = [strip_tags(t) for t in re.findall(r'<p class="step-text"[^>]*>(.*?)</p>', seg, re.S)]
        for k in range(max(len(imgs), len(texts))):
            res["steps"].append({
                "text": texts[k] if k < len(texts) else "",
                "image": imgs[k] if k < len(imgs) else None,
            })

    m = re.search(r'<div class="tips-text"[^>]*>(.*?)</div>\s*</section>', h, re.S)
    if m:
        res["tips"] = strip_tags(m.group(1))
    return res


def parse_recipe(h: str, source_url: str, via: str) -> dict:
    ld = parse_ld_json(h)
    body = parse_desktop(h) if via == "desktop" else parse_mobile(h)
    if not body["ingredients"]:  # 兜底换一种解析
        body = parse_mobile(h) if via == "desktop" else parse_desktop(h)
    body["ingredients"] = apply_sections(body["ingredients"])

    name = ""
    m = re.search(r"<title>【(.*?)的做法", h)
    if m:
        name = re.sub(r"\s+", " ", m.group(1)).strip()
    elif ld.get("name"):
        name = ld["name"]
    else:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
        name = strip_tags(m.group(1)) if m else "未命名菜谱"

    # 下厨房页面（标题 / JSON-LD / h1）常在名字里掺入大量空格，统一压成单个空格。
    name = re.sub(r"\s+", " ", name).strip()

    author = ""
    if isinstance(ld.get("author"), dict):
        author = ld["author"].get("name", "")
    if not author:
        m = re.search(r'class="author[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([^<>]{2,20})\s*<', h)
        author = strip_tags(m.group(1)) if m else ""

    description = (ld.get("description") or "").strip()
    if not description:
        m = re.search(r'<meta name="description" content="([^"]*)"', h)
        description = htmllib.unescape(m.group(1)).strip() if m else ""
    if not description:
        m = re.search(r'<div class="desc"[^>]*>(.*?)</div>', h, re.S)
        description = strip_tags(m.group(1)) if m else ""

    main_image = orig_image(ld.get("image"))
    if not main_image:
        m = re.search(r'<meta property="og:image" content="([^"]+)"', h)
        main_image = orig_image(m.group(1)) if m else None
    if not main_image:
        first = next((s["image"] for s in body["steps"] if s.get("image")), None)
        main_image = first

    categories = []
    if ld.get("recipeCategory"):
        cats = ld["recipeCategory"]
        categories = [cats] if isinstance(cats, str) else list(cats)
    if not categories:
        m = re.search(r'<div class="recipe-categories"[^>]*>(.*?)</div>', h, re.S)
        if m:
            categories = [strip_tags(x) for x in re.findall(r"<a[^>]*>(.*?)</a>", m.group(1), re.S)]
    categories = [c for c in categories if c][:3]

    tags = []
    kw = ld.get("keywords")
    if isinstance(kw, list):
        # 只要短的、像标签的关键词，过滤掉 "xxx的做法" 这类 SEO 串
        tags = [k for k in kw if len(k) <= 6 and "做法" not in k and "怎么" not in k][:5]

    rid = recipe_id_from_url(source_url)
    return {
        "source": "xiachufang",
        "source_url": source_url,
        "id": rid,
        "name": name,
        "author": author,
        "main_image": main_image,
        "description": description,
        "categories": categories,
        "tags": tags,
        "servings": None,
        "times": {"prep": None, "cook": None, "total": None},
        "ingredients": body["ingredients"],
        "steps": body["steps"],
        "tips": body["tips"],
        "nutrition": {k: "" for k in NUTRITION_KEYS},
    }


# --------------------------------------------------------------------------- #
# 营养 / 时间 估算（源页面通常不提供，靠食材表凑）
# 数据来源：《中国食物成分表》常见食材的「每 100g」近似值。
# 数值顺序与 NUTRITION_KEYS 对齐：
# [kcal, carb(g), protein(g), fat(g), fiber(g), sugar(g), sodium(mg),
#  cholesterol(mg), satfat(g), unsatfat(g)]
# --------------------------------------------------------------------------- #

FOOD_DB = {
    # 主食 / 粉面
    "面粉": [349, 73.6, 11.2, 1.5, 2.7, 1.0, 5, 0, 0.3, 1.0],
    "小麦粉": [349, 73.6, 11.2, 1.5, 2.7, 1.0, 5, 0, 0.3, 1.0],
    "全麦粉": [340, 70.0, 13.2, 2.5, 7.0, 1.0, 5, 0, 0.4, 1.8],
    "大米": [346, 77.2, 7.4, 0.8, 0.7, 0.4, 4, 0, 0.2, 0.4],
    "稻米": [346, 77.2, 7.4, 0.8, 0.7, 0.4, 4, 0, 0.2, 0.4],
    "小米": [358, 75.1, 9.0, 3.1, 1.6, 1.5, 4, 0, 0.6, 2.0],
    "挂面": [348, 74.4, 11.4, 0.9, 1.0, 1.0, 150, 0, 0.2, 0.5],
    "面条": [348, 74.4, 11.4, 0.9, 1.0, 1.0, 150, 0, 0.2, 0.5],
    # 蛋 / 奶
    "鸡蛋": [144, 2.8, 13.3, 8.8, 0, 0.6, 131, 372, 2.6, 5.5, 50],
    "全蛋": [144, 2.8, 13.3, 8.8, 0, 0.6, 131, 372, 2.6, 5.5, 50],
    "牛奶": [54, 3.4, 3.0, 3.2, 0, 3.4, 37, 15, 1.9, 1.2],
    "全脂牛奶": [54, 3.4, 3.0, 3.2, 0, 3.4, 37, 15, 1.9, 1.2],
    # 糖 / 油 / 调味
    "冰糖": [397, 99.0, 0, 0, 0, 99.0, 2, 0, 0, 0],
    "黄冰糖": [397, 99.0, 0, 0, 0, 99.0, 2, 0, 0, 0],
    "白砂糖": [400, 99.9, 0, 0, 0, 99.9, 1, 0, 0, 0],
    "盐": [0, 0, 0, 0, 0, 0, 39311, 0, 0, 0],
    "食用油": [900, 0, 0, 100, 0, 0, 0, 0, 12, 85],
    "玉米油": [900, 0, 0, 100, 0, 0, 0, 0, 12, 85],
    "植物油": [900, 0, 0, 100, 0, 0, 0, 0, 12, 85],
    "橄榄油": [899, 0, 0, 99.9, 0, 0, 2, 0, 14, 83],
    "黄油": [717, 0, 0.9, 81.1, 0, 0.1, 11, 215, 51, 24],
    # 蔬菜 / 果
    "番茄": [18, 3.9, 0.9, 0.2, 0.5, 2.6, 5, 0, 0.03, 0.1],
    "西红柿": [18, 3.9, 0.9, 0.2, 0.5, 2.6, 5, 0, 0.03, 0.1],
    "胡萝卜": [39, 8.8, 1.0, 0.2, 2.8, 4.7, 71, 0, 0.04, 0.1],
    "红萝卜": [39, 8.8, 1.0, 0.2, 2.8, 4.7, 71, 0, 0.04, 0.1],
    "菠菜": [24, 3.6, 2.6, 0.3, 2.2, 0.4, 85, 0, 0.05, 0.2],
    "葱": [31, 6.5, 1.7, 0.2, 2.6, 1.6, 11, 0, 0.03, 0.1],
    "姜": [41, 9.5, 1.8, 0.5, 1.4, 1.0, 6, 0, 0.08, 0.3],
    "蒜": [128, 26.5, 4.5, 0.2, 2.4, 1.0, 6, 0, 0.04, 0.1],
    "洋葱": [40, 9.3, 1.1, 0.1, 1.7, 4.2, 4, 0, 0.02, 0.05],
    "土豆": [77, 17.2, 2.0, 0.1, 2.2, 0.8, 5, 0, 0.02, 0.06],
    "雪梨": [44, 13.3, 0.1, 0.2, 2.0, 9.0, 1, 0, 0.03, 0.1],
    "梨": [44, 13.3, 0.1, 0.2, 2.0, 9.0, 1, 0, 0.03, 0.1],
    "苹果": [52, 13.5, 0.2, 0.2, 1.2, 10.4, 1, 0, 0.03, 0.1],
    "柠檬": [29, 9.3, 1.1, 0.3, 2.9, 2.5, 1, 0, 0.03, 0.1],
    "山楂": [98, 22.0, 0.5, 0.6, 3.1, 1.0, 1, 0, 0.1, 0.4],
    "桂圆肉": [313, 71.5, 5.0, 0.2, 4.6, 65.0, 4, 0, 0, 0.1],
    "罗汉果": [169, 40.0, 6.0, 0.5, 10.0, 2.0, 3, 0, 0.1, 0.3],
    # 肉
    "五花肉": [395, 2.4, 13.2, 37.0, 0, 0, 59, 80, 13.0, 20.0],
    "猪肉末": [395, 2.4, 13.2, 37.0, 0, 0, 59, 80, 13.0, 20.0],
    "猪肉馅": [395, 2.4, 13.2, 37.0, 0, 0, 59, 80, 13.0, 20.0],
    "瘦肉": [143, 1.5, 20.3, 6.2, 0, 0, 57, 81, 2.3, 3.2],
    "鸡胸肉": [133, 2.5, 19.4, 5.0, 0, 0, 63, 82, 1.5, 2.6],
    # 其他
    "水": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "豆浆": [31, 1.1, 3.0, 1.6, 1.1, 0.7, 3, 0, 0.2, 1.1],
}

# 名称里带「汁」按对应蔬菜算（纤维减半，其它近似）
_JUICE_MAP = {"红萝卜汁": "红萝卜", "胡萝卜汁": "胡萝卜", "菠菜汁": "菠菜",
              "西红柿汁": "西红柿", "番茄汁": "番茄", "苹果汁": "苹果",
              "梨汁": "梨", "雪梨汁": "雪梨"}


def _match_food(name: str) -> tuple[str, list] | None:
    n = (name or "").strip().strip("：: ").replace("（", "(").replace("）", ")")
    if not n:
        return None
    if n in FOOD_DB:
        return n, FOOD_DB[n]
    if n in _JUICE_MAP:
        base = _JUICE_MAP[n]
        vals = list(FOOD_DB[base])
        vals[4] = round(vals[4] * 0.5, 2)   # 纤维减半
        return base, vals
    # 去掉「面/汁/碎/末/丁/块」等后缀再试
    for suf in ("面", "汁", "碎", "末", "丁", "块", "片", "丝"):
        if n.endswith(suf) and n[:-1] in FOOD_DB:
            return n[:-1], FOOD_DB[n[:-1]]
    # 包含匹配：仅当名称较短，避免「不加鸡蛋水量…」误命中「鸡蛋」
    for key in FOOD_DB:
        if len(n) <= len(key) + 3 and (key in n or n in key):
            return key, FOOD_DB[key]
    return None


def estimate_nutrition(rec: dict) -> dict:
    """把用量累加 → 整锅营养；按质量折算成每份（约 100g）营养，并返回建议份数。

    返回 {key: 数值(每份)} 与 servings 建议。源页面无营养数据时调用。
    """
    total = [0.0] * 10
    mass_g = 0.0
    for ing in rec.get("ingredients", []):
        qty = ing.get("quantity")
        if qty in (None, ""):
            continue
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            continue
        unit = (ing.get("unit") or "")
        food = ing.get("food") or ""
        m = _match_food(food)
        if not m:
            # 油脂类「适量」无法量化，跳过
            continue
        name, vals = m
        # 克 / 千克 / 毫升（≈克）
        if unit in ("克", "毫升", "g", "ml", "G", "ML", "cc"):
            grams = qty
        elif unit in ("千克", "kg", "KG", "升", "L"):
            grams = qty * 1000
        elif unit in ("个", "只", "枚", "颗", "粒"):
            piece_g = vals[10] if len(vals) > 10 else 50.0
            grams = qty * piece_g
        else:
            grams = qty  # 未知单位按克兜底
        grams = max(0.0, grams)
        mass_g += grams
        for i in range(10):
            total[i] += vals[i] * grams / 100.0

    if mass_g <= 0:
        return {k: "" for k in NUTRITION_KEYS}, 1

    servings = max(1, round(mass_g / 100.0))   # 约每 100g 一份
    per = [t / servings for t in total]
    out = {
        "calories": f"{round(per[0])} kcal",
        "carbohydrateContent": _r(per[1], 1),
        "cholesterolContent": _r(per[7], 0),
        "fatContent": _r(per[3], 1),
        "fiberContent": _r(per[4], 1),
        "proteinContent": _r(per[2], 1),
        "saturatedFatContent": _r(per[8], 1),
        "sodiumContent": _r(per[6], 0),
        "sugarContent": _r(per[5], 1),
        "transFatContent": "0",
        "unsaturatedFatContent": _r(per[9], 1),
    }
    return out, servings


def _r(v: float, nd: int):
    return f"{round(v, nd)} g" if nd else f"{round(v)} mg"


# 时间估算：从步骤文本里抓时长，再按动词归类为准备/烹饪。
_PREP_VERBS = ("揉", "和面", "混合", "搅拌", "醒", "腌", "泡", "发", "静置", "冷藏", "冷冻",
               "剁", "切", "洗", "削", "去皮", "焯", "榨", "打泥", "准备", "备")
_COOK_VERBS = ("煮", "炖", "炒", "煎", "蒸", "烤", "炸", "熬", "焖", "烧", "煲", "卤",
               "压面", "机器", "下锅", "收汁", "烘")


def _parse_durations(text: str) -> list[float]:
    mins = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*分钟", text):
        mins.append(float(m.group(1)))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*小时", text):
        mins.append(float(m.group(1)) * 60)
    if "半小时" in text:
        mins.append(30)
    if "一刻钟" in text or "15分钟" in text:
        mins.append(15)
    return mins


def estimate_times(rec: dict) -> dict:
    prep = cook = detected = 0.0
    prep_steps = cook_steps = 0
    for s in rec.get("steps", []):
        text = (s.get("text") or "")
        durs = _parse_durations(text)
        is_prep = any(v in text for v in _PREP_VERBS)
        is_cook = any(v in text for v in _COOK_VERBS) or "压" in text
        if durs:
            detected += sum(durs)
            if is_prep and not is_cook:
                prep += sum(durs)
            elif is_cook and not is_prep:
                cook += sum(durs)
            else:
                prep += sum(durs) * 0.5
                cook += sum(durs) * 0.5
        else:
            if is_prep:
                prep_steps += 1
            if is_cook:
                cook_steps += 1
    if detected == 0:
        # 没抓到任何时长：给一个保守基线
        prep = max(15, prep_steps * 5)
        cook = max(10, cook_steps * 5)
    else:
        prep += prep_steps * 4
        cook += cook_steps * 4
    total = max(prep + cook, detected)
    return {
        "prep": _iso(prep),
        "cook": _iso(cook),
        "total": _iso(total),
        "_estimated": True,
    }


def _iso(minutes: float) -> str:
    minutes = max(0, int(round(minutes)))
    h, m = divmod(minutes, 60)
    if h:
        return f"PT{h}H{m}M" if m else f"PT{h}H"
    return f"PT{m}M"


def fill_estimates(rec: dict) -> dict:
    """就地填空 nutrition 与 times（仅在仍为空时）。返回 rec。"""
    if all(rec.get("nutrition", {}).get(k) in (None, "") for k in NUTRITION_KEYS):
        nut, servings = estimate_nutrition(rec)
        rec["nutrition"] = nut
        if not rec.get("servings"):
            rec["servings"] = servings
            rec["servings_text"] = f"{servings} 份（约每 100g）"
    if not rec.get("times", {}).get("total"):
        rec["times"] = estimate_times(rec)
    return rec


# --------------------------------------------------------------------------- #
# fetch 子命令
# --------------------------------------------------------------------------- #

def cmd_fetch(args) -> int:
    urls = list(args.urls)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            urls += [line.strip() for line in fh if line.strip() and not line.startswith("#")]
    if not urls:
        print("没有给任何 URL"); return 1

    os.makedirs(args.out, exist_ok=True)
    fetcher = Fetcher()
    ok = 0
    for url in urls:
        try:
            print(f"[fetch] {url}")
            if os.path.exists(url) and url.lower().endswith((".html", ".htm")):
                # 本地另存的页面：浏览器里右键"另存为"后直接解析
                with open(url, encoding="utf-8", errors="replace") as fh:
                    h = fh.read()
                via = "desktop" if '<div class="ings"' in h else "mobile"
            else:
                h, via = fetch_recipe_html(url)
            rec = parse_recipe(h, url, via)
            if args.estimate:
                fill_estimates(rec)
            base = os.path.join(args.out, rec["id"])
            if args.images:
                img_dir = os.path.join(args.out, "images", rec["id"])
                for i, step in enumerate(rec["steps"], 1):
                    if not step.get("image"):
                        continue
                    ext = (os.path.splitext(urllib.parse.urlparse(step["image"]).path)[1] or ".jpg").lower()
                    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                        ext = ".jpg"
                    dest = os.path.join(img_dir, f"step-{i:02d}{ext}")
                    if fetcher.download(step["image"], dest):
                        step["local_image"] = os.path.relpath(dest, args.out).replace("\\", "/")
            # 已存在则保留 nutrition / times / servings 的人工修改（仅当旧值非空）
            out_path = base + ".json"
            if os.path.exists(out_path):
                with open(out_path, encoding="utf-8") as fh:
                    old = json.load(fh)
                for key in ("nutrition", "times", "servings", "categories", "tags"):
                    if key not in old:
                        continue
                    ov = old[key]
                    if key in ("nutrition", "times"):
                        # 仅当旧值里确有实际数值/时长才保留，否则用本次新估算的
                        if any(v not in (None, "") for v in ov.values()):
                            rec[key] = ov
                    elif ov:
                        rec[key] = ov
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False, indent=2)
            print(f"    -> {out_path}  （{via}）用料 {len(rec['ingredients'])} 条 / 步骤 {len(rec['steps'])} 步"
                  f" / 步骤图 {sum(1 for s in rec['steps'] if s.get('image'))} 张")
            ok += 1
        except Exception as exc:
            print(f"    [error] {url} 失败：{exc}")
    print(f"\n完成：{ok}/{len(urls)}")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# Mealie 客户端
# --------------------------------------------------------------------------- #

class Mealie:
    def __init__(self, base: str, token: str, timeout: int = 30):
        self.base = base.rstrip("/").rstrip("/api")
        self.base = self.base.rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        self._foods: dict[str, str] = {}
        self._units: dict[str, str] = {}
        self._foods_loaded = False
        self._units_loaded = False
        self._tags: dict = None          # name -> {"id","name","slug"}
        self._cats: dict = None

    # -- 基础请求 -------------------------------------------------------- #
    def _url(self, path: str) -> str:
        return f"{self.base}/api{path}"

    def _req(self, method: str, path: str, payload=None, body: bytes | None = None,
             content_type: str = "application/json", expect_json=True):
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        elif body is not None:
            data = body
        req = urllib.request.Request(self._url(path), data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        if data is not None:
            req.add_header("Content-Type", content_type)
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        if not expect_json:
            return text
        try:
            return json.loads(text)
        except Exception:
            return text

    @staticmethod
    def _multipart(fields: dict, files: list[tuple[str, str, bytes, str]]) -> tuple[bytes, str]:
        boundary = "----xcf2mealie" + uuid.uuid4().hex
        buf = bytearray()
        for k, v in fields.items():
            buf += f"--{boundary}\r\n".encode()
            buf += f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode()
            buf += f"{v}\r\n".encode("utf-8")
        for field, filename, content, ctype in files:
            buf += f"--{boundary}\r\n".encode()
            buf += (
                f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode()
            buf += content + b"\r\n"
        buf += f"--{boundary}--\r\n".encode()
        return bytes(buf), f"multipart/form-data; boundary={boundary}"

    # -- 业务方法 -------------------------------------------------------- #
    def about(self) -> dict | None:
        try:
            return self._req("GET", "/app/about")
        except Exception as exc:
            print(f"  [warn] 无法连接 Mealie：{exc}")
            return None

    # -- 食材 / 单位：先建好再按 id 引用 ----------------------------- #
    # 直接把 {"name": "xxx"} 塞进 recipeIngredient 让 Mealie 自动创建，在 nightly 会抛
    # ValueError（已复现）；同名食材还容易被重复创建。统一走 /foods、/units，
    # 并保证「幂等」：已存在就复用 id，新建失败也回查拿 id，绝不给 PATCH 传无 id 的食材。
    def _load_all(self, kind: str, cache: dict) -> None:
        try:
            page, per = 1, 200
            while True:
                data = self._req("GET", f"/{kind}?page={page}&perPage={per}") or {}
                items = data.get("items", []) if isinstance(data, dict) else []
                for it in items:
                    if it.get("name"):
                        cache.setdefault(it["name"], it["id"])
                total = data.get("total", 0) if isinstance(data, dict) else 0
                if len(items) < per or (total and page * per >= total):
                    break
                page += 1
        except Exception as exc:
            print(f"  [warn] 读取已有 {kind} 失败：{str(exc)[:80]}")

    def _find_one(self, kind: str, name: str) -> str | None:
        try:
            data = self._req("GET", f"/{kind}?search=" + urllib.parse.quote(name)
                             + "&perPage=20") or {}
            for it in data.get("items", []) if isinstance(data, dict) else []:
                if it.get("name") == name:
                    return it["id"]
        except Exception:
            pass
        return None

    def _ensure(self, kind: str, name: str, cache: dict, loaded_flag: str) -> dict:
        if not name:
            return None
        if not getattr(self, loaded_flag):
            self._load_all(kind, cache)
            setattr(self, loaded_flag, True)
        if name in cache:
            return {"id": cache[name], "name": name}
        # 先尝试新建
        try:
            created = self._req("POST", f"/{kind}", payload={"name": name})
            cid = created.get("id") if isinstance(created, dict) else None
            if cid:
                cache[name] = cid
                return {"id": cid, "name": name}
        except Exception:
            pass
        # 新建失败（多半已存在但没进缓存）→ 回查
        cid = self._find_one(kind, name)
        if cid:
            cache[name] = cid
            return {"id": cid, "name": name}
        print(f"  [warn] 无法解析{kind}「{name}」的 id，将仅用名称")
        return {"name": name}

    def ensure_food(self, name: str) -> dict | None:
        return self._ensure("foods", name, self._foods, "_foods_loaded")

    def ensure_unit(self, name: str) -> dict | None:
        return self._ensure("units", name, self._units, "_units_loaded")

    # -- 标签 / 分类：v3.24 路径是 /api/organizers/{tags,categories} --------
    # 直接把 "xxx" 字符串塞进 recipe 的 tags 让 Mealie 自动建，会触发「同名已存在」
    # 的 already-exists 400（已复现）。正确做法：先用 get-or-create 拿到 id+slug，
    # 再以 {"id","name","slug"} 对象引用。绝不给 PATCH 传无 id 的标签。
    def _load_organizers(self, kind: str) -> dict:
        ep = "tags" if kind == "tags" else "categories"
        cache: dict = {}
        page = 1
        while True:
            data = self._req("GET", f"/organizers/{ep}?page={page}&perPage=200") or {}
            items = data.get("items", []) if isinstance(data, dict) else []
            for it in items:
                if it.get("name"):
                    cache[it["name"]] = {
                        "id": it["id"], "name": it["name"],
                        "slug": it.get("slug") or "",
                    }
            if not data.get("next") or len(items) < 200:
                break
            page += 1
        return cache

    def ensure_organizer(self, kind: str, name: str) -> dict:
        attr = "_tags" if kind == "tags" else "_cats"
        cache = getattr(self, attr)
        if cache is None:
            cache = self._load_organizers(kind)
            setattr(self, attr, cache)
        if name in cache:
            return cache[name]
        ep = "tags" if kind == "tags" else "categories"
        try:
            created = self._req("POST", f"/organizers/{ep}", payload={"name": name})
            if isinstance(created, dict) and created.get("id"):
                obj = {"id": created["id"], "name": name,
                       "slug": created.get("slug") or ""}
                cache[name] = obj
                return obj
        except Exception:
            pass
        # 新建失败（多半已存在但没进缓存）→ 重新拉全量回查
        cache = self._load_organizers(kind)
        setattr(self, attr, cache)
        if name in cache:
            return cache[name]
        print(f"  [warn] 无法解析{kind}「{name}」，将仅用名称（可能导入后会缺标签）")
        return {"name": name}

    def ensure_tag(self, name: str) -> dict:
        return self.ensure_organizer("tags", name)

    def ensure_category(self, name: str) -> dict:
        return self.ensure_organizer("categories", name)

    def create(self, name: str) -> str:
        # 同名食谱视为「更新」而非报错：先查是否存在，存在则直接返回其 slug。
        existing = self._find_by_name(name)
        if existing:
            return existing
        slug = self._req("POST", "/recipes", payload={"name": name})
        if isinstance(slug, str):
            return slug.strip('"')
        raise RuntimeError(f"创建食谱失败：{slug}")

    def _find_by_name(self, name: str) -> str | None:
        try:
            data = self._req("GET", "/recipes?search=" + urllib.parse.quote(name)
                             + "&perPage=10") or {}
        except Exception:
            return None
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if item.get("name", "").strip() == name.strip():
                return item.get("slug")
        return None

    def get(self, slug: str) -> dict:
        return self._req("GET", f"/recipes/{slug}")

    def update(self, slug: str, payload: dict):
        # 用 PATCH 而非 PUT：PUT 是全量 Recipe 模型，nightly 会做 name 唯一性校验，
        # 在刚创建的食谱上整本 PUT 容易误报 "already exists"；PATCH 局部合并更稳。
        # 个别实例删除是异步的，刚删完立刻重推可能短暂报 already exists，重试一次即可。
        for attempt in range(3):
            try:
                return self._req("PATCH", f"/recipes/{slug}", payload=payload)
            except RuntimeError as exc:
                if attempt < 2 and "already exists" in str(exc):
                    import time
                    time.sleep(2)
                    continue
                raise

    def set_image_from_url(self, slug: str, url: str) -> bool:
        try:
            self._req("POST", f"/recipes/{slug}/image", payload={"url": url})
            return True
        except Exception as exc:
            print(f"  [info] 用 URL 设置封面失败（{str(exc)[:80]}），改为上传文件")
            return False

    def upload_image(self, slug: str, data: bytes, ext: str):
        body, ctype = self._multipart(
            {"extension": ext}, [("image", f"image.{ext}", data, f"image/{ext}")]
        )
        return self._req("PUT", f"/recipes/{slug}/image", body=body, content_type=ctype)

    def upload_asset(self, slug: str, path: str, name: str, icon: str = "mdi-image") -> dict:
        ext = os.path.splitext(path)[1].lstrip(".").lower() or "jpg"
        with open(path, "rb") as fh:
            data = fh.read()
        ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                 "webp": "image/webp"}.get(ext, "application/octet-stream")
        body, ctype_hdr = self._multipart(
            {"name": name, "icon": icon, "extension": ext},
            [("file", f"{name}.{ext}", data, ctype)],
        )
        return self._req("POST", f"/recipes/{slug}/assets", body=body, content_type=ctype_hdr)


def image_bytes(fetcher: Fetcher, path_or_url: str, out_dir: str) -> str | None:
    """本地文件直接返回；URL 先下载。返回本地路径。"""
    if os.path.exists(path_or_url):
        return path_or_url
    if path_or_url.startswith("http"):
        os.makedirs(out_dir, exist_ok=True)
        name = re.sub(r"\W+", "_", os.path.basename(urllib.parse.urlparse(path_or_url).path)) or "img"
        if not os.path.splitext(name)[1]:
            name += ".jpg"
        dest = os.path.join(out_dir, name)
        return dest if fetcher.download(path_or_url, dest) else None
    return None


# --------------------------------------------------------------------------- #
# 组装 Mealie payload
# --------------------------------------------------------------------------- #

def build_payload(rec: dict, *, extra_tags: list[str], extra_categories: list[str],
                  step_images: dict[int, str], recipe_id_for_assets: str | None,
                  mealie: "Mealie | None" = None) -> dict:
    ingredients = []
    for ing in rec.get("ingredients", []):
        item = {
            "quantity": ing.get("quantity"),
            "note": ing.get("note") or "",
            "originalText": ing.get("original") or "",
            "referenceId": str(uuid.uuid4()),
            "title": ing.get("section") or "",
            "display": "",
        }
        if ing.get("unit"):
            item["unit"] = mealie.ensure_unit(ing["unit"]) if mealie else {"name": ing["unit"]}
        if ing.get("food"):
            item["food"] = mealie.ensure_food(ing["food"]) if mealie else {"name": ing["food"]}
        ingredients.append(item)

    steps = []
    for i, st in enumerate(rec.get("steps", []), 1):
        text = (st.get("text") or "").strip()
        asset = step_images.get(i)
        if asset and recipe_id_for_assets:
            url = f"/api/media/recipes/{recipe_id_for_assets}/assets/{asset}"
            text = (text + "\n\n" + f'<img src="{url}" width="100%"/>').strip()
        steps.append({
            "id": str(uuid.uuid4()),
            "title": "",
            "summary": "",
            "text": text,
            "ingredientReferences": [],
        })

    payload: dict = {
        "name": rec.get("name"),
        "description": rec.get("description") or "",
        "orgURL": rec.get("source_url"),
        "recipeIngredient": ingredients,
        "recipeInstructions": steps,
    }

    times = rec.get("times") or {}
    if times.get("prep"):
        payload["prepTime"] = times["prep"]
    if times.get("cook"):
        payload["cookTime"] = times["cook"]
    if times.get("total"):
        payload["totalTime"] = times["total"]

    servings = rec.get("servings")
    if servings:
        try:
            payload["recipeServings"] = float(servings)
        except (TypeError, ValueError):
            pass
    if rec.get("servings_text"):
        payload["recipeYield"] = rec["servings_text"]
    elif servings:
        payload["recipeYield"] = f"{servings} 份"

    # 注意：tags / recipeCategory 不在主 payload 里——Mealie v3.24 对 recipe 打
    # PATCH 时，纯字符串标签会误报 already-exists 400；正确做法是用 id+slug 引用，
    # 且单独发一次 PATCH（见 cmd_push 的「标签 / 分类」步骤）。
    nutrition = {k: v for k, v in (rec.get("nutrition") or {}).items() if v not in (None, "")}
    if nutrition:
        payload["nutrition"] = nutrition
        payload["settings"] = {"showNutrition": True}
    return payload


# --------------------------------------------------------------------------- #
# estimate 子命令
# --------------------------------------------------------------------------- #

def cmd_estimate(args) -> int:
    paths: list[str] = []
    for t in args.target:
        if os.path.isdir(t):
            paths += [os.path.join(t, f) for f in sorted(os.listdir(t)) if f.endswith(".json")]
        else:
            paths.append(t)
    if not paths:
        print("没有找到 JSON"); return 1
    for path in paths:
        rec = json.load(open(path, encoding="utf-8"))
        before = rec.get("nutrition", {})
        was_empty = all(before.get(k) in (None, "") for k in NUTRITION_KEYS)
        fill_estimates(rec)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
        flag = "（已估算）" if was_empty else "（原已有，保留）"
        print(f"[estimate] {rec.get('name')} {flag}  营养={'有' if rec['nutrition'].get('calories') else '无'} "
              f" 时间={rec.get('times', {}).get('total') or '无'}  份数={rec.get('servings')}")
    print("完成")
    return 0


# --------------------------------------------------------------------------- #
# push 子命令
# --------------------------------------------------------------------------- #

def load_records(target: str) -> list[dict]:
    if os.path.isdir(target):
        files = sorted(
            os.path.join(target, f) for f in os.listdir(target) if f.endswith(".json")
        )
    else:
        files = [target]
    return [json.load(open(f, encoding="utf-8")) for f in files]


def cmd_push(args) -> int:
    recs = load_records(args.target)
    if not recs:
        print("没有找到可导入的 JSON"); return 1

    if args.nutrition:
        with open(args.nutrition, encoding="utf-8") as fh:
            table = json.load(fh)
        for rec in recs:
            nut = table.get(rec.get("source_url")) or table.get(rec.get("id"))
            if nut:
                rec["nutrition"] = nut

    if args.dry_run:
        for rec in recs:
            step_images = {
                i: f"step-{i:02d}.jpg"
                for i, s in enumerate(rec.get("steps", []), 1)
                if s.get("image") or s.get("local_image")
            }
            print(json.dumps(build_payload(
                rec, extra_tags=args.tag, extra_categories=args.category,
                step_images=step_images,
                recipe_id_for_assets="<RECIPE_ID>" if step_images else None,
            ), ensure_ascii=False, indent=2))
            _names = list(dict.fromkeys(list(rec.get("tags") or []) + list(args.tag)))
            _cnames = list(dict.fromkeys(list(rec.get("categories") or []) + list(args.category)))
            if _names or _cnames:
                print(f"  # 标签(将按 id 引用): {_names}  分类: {_cnames}")
        return 0

    mealie = Mealie(args.mealie, args.token)
    about = mealie.about()
    if about:
        print(f"[mealie] 已连接，版本 {about.get('version', '?')}\n")
    fetcher = Fetcher()
    base_dir = args.target if os.path.isdir(args.target) else os.path.dirname(args.target) or "."

    ok = 0
    for rec in recs:
        name = rec.get("name") or "未命名"
        try:
            print(f"[push] {name}")
            slug = mealie.create(name)
            print(f"    created slug = {slug}")
            recipe_id = (mealie.get(slug) or {}).get("id")
            print(f"    recipe id   = {recipe_id}")

            # 0) 标签 / 分类在「正文写完后」单独发（见下方步骤 2.5），
            #    这里先准备好要解析的标签名列表。
            _tag_names = list(dict.fromkeys(list(rec.get("tags") or []) + list(args.tag)))
            _cat_names = list(dict.fromkeys(list(rec.get("categories") or []) + list(args.category)))

            # 1) 步骤图 -> recipe assets
            step_images: dict[int, str] = {}
            if args.step_images:
                for i, st in enumerate(rec.get("steps", []), 1):
                    src = st.get("local_image") or st.get("image")
                    if not src:
                        continue
                    local = image_bytes(
                        fetcher,
                        src if os.path.isabs(src) else os.path.join(base_dir, src),
                        os.path.join(base_dir, "_cache"),
                    )
                    if not local:
                        continue
                    asset_name = f"step-{i:02d}"
                    try:
                        asset = mealie.upload_asset(slug, local, asset_name)
                        step_images[i] = asset.get("fileName") or f"{asset_name}.jpg"
                        print(f"    asset {i}: {step_images[i]}")
                    except Exception as exc:
                        print(f"    [warn] 步骤图 {i} 上传失败：{str(exc)[:100]}")

            # 2) 写入正文（tags/category 已在上一步单独处理，这里移除避免 v3.24 同批 400）
            payload = build_payload(rec, extra_tags=args.tag,
                                    extra_categories=args.category,
                                    step_images=step_images,
                                    recipe_id_for_assets=recipe_id,
                                    mealie=mealie)
            payload.pop("tags", None)
            payload.pop("recipeCategory", None)
            try:
                mealie.update(slug, payload)
            except RuntimeError as exc:
                msg = str(exc)
                # 两类常见兼容问题，统一回退到「最兼容写法」重试一次：
                #  - 500：部分 Mealie 版本写结构化食材(food/unit 对象)会崩；
                #  - already exists：PATCH 里带的 name 与实例中同名食谱撞车。
                # 回退：去掉 name 字段 + 食材退为 originalText 纯文本（所有版本都接受）。
                if ("500" in msg or "already exists" in msg) and payload.get("recipeIngredient"):
                    print("    [info] 首次写入失败，回退为兼容写法（去 name/orgURL + 纯文本食材）重试")
                    safe = dict(payload)
                    safe.pop("name", None)
                    safe.pop("orgURL", None)
                    safe["recipeIngredient"] = [
                        {"originalText": i.get("originalText") or i.get("food") or ""}
                        for i in payload["recipeIngredient"]
                    ]
                    mealie.update(slug, safe)
                    payload = safe
                else:
                    raise
            print(f"    用料 {len(payload['recipeIngredient'])} / 步骤 {len(payload['recipeInstructions'])}"
                  f" / 营养 {'有' if payload.get('nutrition') else '无'}")

            # 2.5) 标签 / 分类：用 id+slug 引用，单独 PATCH（避开 v3.24 同批 400 的坑）
            _label_payload: dict = {}
            _tag_objs = [mealie.ensure_tag(t) for t in _tag_names if t]
            _cat_objs = [mealie.ensure_category(c) for c in _cat_names if c]
            if _tag_objs:
                _label_payload["tags"] = _tag_objs
            if _cat_objs:
                _label_payload["recipeCategory"] = _cat_objs
            if _label_payload:
                try:
                    mealie.update(slug, _label_payload)
                    print(f"    标签: {[t['name'] for t in _tag_objs]}  "
                          f"分类: {[c['name'] for c in _cat_objs]}")
                except RuntimeError as exc:
                    print(f"    [warn] 标签写入失败（非致命，可在 Mealie 界面手动勾选）：{str(exc)[:90]}")

            # 3) 封面图
            if rec.get("main_image"):
                if not mealie.set_image_from_url(slug, rec["main_image"]):
                    local = image_bytes(fetcher, rec["main_image"], os.path.join(base_dir, "_cache"))
                    if local:
                        ext = os.path.splitext(local)[1].lstrip(".").lower() or "jpg"
                        with open(local, "rb") as fh:
                            mealie.upload_image(slug, fh.read(), "jpg" if ext == "jpeg" else ext)
                print("    封面图已设置")

            print(f"    -> {mealie.base}/g/home/r/{slug}")
            ok += 1
        except Exception as exc:
            print(f"    [error] {name}: {exc}")
    print(f"\n完成：{ok}/{len(recs)}")
    return 0 if ok else 1


def cmd_run(args) -> int:
    args.out = args.out or os.path.join(os.getcwd(), "mealie_data")
    rc = cmd_fetch(args)
    if rc != 0:
        return rc
    args.target = args.out
    args.dry_run = False
    return cmd_push(args)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="xcf2mealie",
        description="把下厨房菜谱导入 Mealie（用料 / 步骤 / 步骤图 / 营养）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="抓取菜谱为结构化 JSON")
    f.add_argument("urls", nargs="*", help="下厨房菜谱链接")
    f.add_argument("--file", help="每行一个链接的文本文件")
    f.add_argument("--out", default="./mealie_data", help="输出目录（默认 ./mealie_data）")
    f.add_argument("--no-images", dest="images", action="store_false", help="不下载步骤图")
    f.add_argument("--estimate", action="store_true", help="自动估算营养与时间（源页面无数据时）")
    f.set_defaults(images=True, func=cmd_fetch)

    pu = sub.add_parser("push", help="把 JSON 推送到 Mealie")
    pu.add_argument("target", help="单个 JSON 文件，或 fetch 的 --out 目录")
    pu.add_argument("--mealie", default=os.environ.get("MEALIE_URL", ""), help="如 http://192.168.1.10:9925")
    pu.add_argument("--token", default=os.environ.get("MEALIE_TOKEN", ""), help="API Token")
    pu.add_argument("--nutrition", help="营养对照 JSON：{url|id: {nutrition}}")
    pu.add_argument("--tag", action="append", default=[], help="追加标签，可重复")
    pu.add_argument("--category", action="append", default=[], help="追加分类，可重复")
    pu.add_argument("--no-step-images", dest="step_images", action="store_false", help="跳过步骤图")
    pu.add_argument("--dry-run", action="store_true", help="只打印 payload，不写入")
    pu.set_defaults(step_images=True, func=cmd_push)

    es = sub.add_parser("estimate", help="给已抓取的 JSON 补算营养与时间")
    es.add_argument("target", nargs="+", help="JSON 文件或目录")
    es.set_defaults(func=cmd_estimate)

    r = sub.add_parser("run", help="抓取并直接推送")
    r.add_argument("urls", nargs="*")
    r.add_argument("--file", help="每行一个链接的文本文件")
    r.add_argument("--out", default="./mealie_data")
    r.add_argument("--no-images", dest="images", action="store_false")
    r.add_argument("--estimate", action="store_true", help="自动估算营养与时间")
    r.add_argument("--mealie", default=os.environ.get("MEALIE_URL", ""))
    r.add_argument("--token", default=os.environ.get("MEALIE_TOKEN", ""))
    r.add_argument("--nutrition")
    r.add_argument("--tag", action="append", default=[])
    r.add_argument("--category", action="append", default=[])
    r.add_argument("--no-step-images", dest="step_images", action="store_false")
    r.set_defaults(images=True, step_images=True, func=cmd_run)

    args = p.parse_args(argv)

    if args.cmd in ("push", "run") and not args.dry_run:
        if not args.mealie or not args.token:
            p.error("需要 --mealie 和 --token（也可设环境变量 MEALIE_URL / MEALIE_TOKEN）")

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
