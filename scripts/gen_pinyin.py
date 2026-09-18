# -*- coding: utf-8 -*-
"""生成 data/pinyin.json —— 汉字→拼音表（构建期检索索引用）

只收录载具名里真实出现过的汉字（约 1000 字，十几 KB），因此表很小；
生成一次即可，之后构建不再依赖第三方库（构建脚本只读这个 JSON）。

依赖 pypinyin，用一次性环境跑，不污染工程：

    uv run --no-project --with pypinyin scripts/gen_pinyin.py

改完载具名（例如新 DLC 引入生僻字）后重新跑一次，然后 build_site.py。
"""
import io
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'data', 'pinyin.json')
HANZI = re.compile(r'[\u4e00-\u9fff]')
# 所有可能进入展示或检索的中文字段
FIELDS = ('cn', 'model_cn', 'brand_cn', 'class_cn', 'proto', 'modshop')


def collect_chars(vehicles):
    chars = set()
    for v in vehicles:
        for field in FIELDS:
            chars.update(HANZI.findall(str(v.get(field) or '')))
        for alias in (v.get('alias') or []):
            chars.update(HANZI.findall(str(alias)))
    return chars


def main():
    from pypinyin import Style, pinyin

    src = json.load(io.open(os.path.join(BASE, 'data', 'site_data.json'), encoding='utf-8'))
    chars = collect_chars(src['vehicles'])
    print('载具名用到的不同汉字：%d' % len(chars))

    table, poly = {}, []
    for ch in sorted(chars):
        readings = [r for r in pinyin(ch, style=Style.NORMAL, heteronym=True)[0] if r.isascii()]
        readings = list(dict.fromkeys(readings))
        if not readings:
            continue
        table[ch] = readings
        if len(readings) > 1:
            poly.append(ch)

    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
    print('写入 %s · %d 字 · %.1f KB · 含多音字 %d'
          % (OUT, len(table), os.path.getsize(OUT) / 1024, len(poly)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
