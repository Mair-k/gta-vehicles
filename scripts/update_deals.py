# -*- coding: utf-8 -*-
"""抓本周折扣载具，产出 data/deals.json。

    python scripts/update_deals.py --dry     只看抓到了什么，不写盘
    python scripts/update_deals.py           写盘（抓不到任何源时保留旧文件并报错退出）

源清单在 data/deals_sources.json，可自己加、自己关。每个源：
    {"name": "gtaboom", "url": "...", "discover": "<regex 或空>", "parse": "auto", "enabled": true}
discover 非空时，先抓 url，用正则取出真正的文章地址（每周换 URL 的站靠它）。

抓取逐级降级：curl（浏览器 TLS 指纹，最不容易被拦）→ 无头 Chrome（JS 渲染）→ urllib。
解析分两路：表格（Item | Discount）优先，其次正文里的「N% off」句式；两路结果合并投票。
折扣价不由源提供，用车辆库里的原价乘折扣算；源若同时给了实际价，用来交叉校验。
"""
import argparse
import datetime
import io
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(BASE, 'data', 'site_data.json')
OUT = os.path.join(BASE, 'data', 'deals.json')
SRC_CFG = os.path.join(BASE, 'data', 'deals_sources.json')
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

DEFAULT_SOURCES = [
    {'name': 'gtaboom', 'enabled': True,
     'url': 'https://www.gtaboom.com/gta-online-weekly-updates',
     'discover': r'href="(/gta-online[^"]*-[a-z0-9-]*20\d\d)"',
     'parse': 'auto'},
    {'name': 'pcquest', 'enabled': False,
     'url': 'https://www.pcquest.com/gaming/',
     'discover': r'href="(https://www\.pcquest\.com/gaming/gta-online-weekly-update[^"]+)"',
     'parse': 'auto'},
    {'name': 'manual', 'enabled': True, 'url': '', 'discover': '', 'parse': 'auto',
     'file': 'data/deals_manual.txt'},
]


def load_sources():
    if not os.path.exists(SRC_CFG):
        io.open(SRC_CFG, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(DEFAULT_SOURCES, ensure_ascii=False, indent=2) + '\n')
        print('已生成源清单:', os.path.relpath(SRC_CFG, BASE))
    with io.open(SRC_CFG, encoding='utf-8') as f:
        return [s for s in json.load(f) if s.get('enabled')]


def fetch(url, timeout=30):
    if not url:
        return ''
    try:
        r = subprocess.run(['curl', '-s', '--compressed', '-A', UA, '-L', '-m', str(timeout), url],
                           capture_output=True)
        html = r.stdout.decode('utf-8', 'ignore')
        if len(html) > 4000:
            return html
    except OSError:
        pass
    chrome = _chrome()
    if chrome:
        try:
            r = subprocess.run([chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
                                '--virtual-time-budget=12000', '--dump-dom', url],
                               capture_output=True, timeout=timeout + 40)
            html = r.stdout.decode('utf-8', 'ignore')
            if len(html) > 4000:
                return html
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'en-US,en;q=0.9'})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read().decode('utf-8', 'ignore')
    except Exception:
        return ''


def _chrome():
    for c in (r'C:\Program Files\Google\Chrome\Application\chrome.exe',
              r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'):
        if os.path.isfile(c):
            return c
    return None


def text_of(html):
    t = re.sub(r'(?is)<(script|style)[^>]*>.*?</\1>', ' ', html)
    t = re.sub(r'(?s)<br\s*/?>|</(p|div|li|tr|h\d)>', '\n', t)
    t = re.sub(r'(?s)<[^>]+>', ' ', t)
    t = (t.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&#39;', "'")
          .replace('&quot;', '"').replace('&gt;', '>').replace('&lt;', '<'))
    return re.sub(r'[ \t]+', ' ', t)


def cells(row):
    out = []
    for c in re.findall(r'(?is)<t[hd][^>]*>(.*?)</t[hd]>', row):
        out.append(re.sub(r'\s+', ' ', re.sub(r'(?s)<[^>]+>', '', c)).strip())
    return out


def parse_table(html):
    hits = []
    for tb in re.findall(r'(?is)<table.*?</table>', html):
        rows = re.findall(r'(?is)<tr.*?</tr>', tb)
        if len(rows) < 3:
            continue
        good = 0
        for r in rows:
            cs = cells(r)
            if len(cs) < 2:
                continue
            name, disc = cs[0], cs[1]
            m = re.search(r'(\d{1,3})\s*%\s*(?:off|discount)', disc, re.I)
            if m:
                hits.append((name, int(m.group(1))))
                good += 1
            elif re.search(r'\b100\s*%\b|free', disc, re.I):
                hits.append((name, 100))
                good += 1
        if good < 3:
            hits = hits[:len(hits) - good]
    return hits


NAME = r"[A-Z][A-Za-z0-9'’.\-]*(?:\s+[A-Z0-9][A-Za-z0-9'’.\-]*){0,4}"
PCT = r'(\d{1,3})\s*%\s*off'


def parse_prose(txt):
    hits = []
    for m in re.finditer(r'(' + PCT + r')[^.\n]{0,60}?(' + NAME + r')', txt):
        hits.append((m.group(3), int(m.group(1))))
    for m in re.finditer(r'(' + NAME + r')[^.\n]{0,60}?(' + PCT + r')', txt):
        hits.append((m.group(1), int(m.group(3))))
    return hits


def parse_prices(txt):
    out = {}
    for m in re.finditer(r'(' + NAME + r')[^.\n]{0,50}?down to GTA\$([\d,]+)', txt):
        out[re.sub(r'\s+', ' ', m.group(1)).strip()] = int(m.group(2).replace(',', ''))
    return out


BACK_PAT = re.compile(r'(return\w*[^.\n]{0,60}?(?:in-game )?(?:store|showroom|website)|'
                      r'(?:removed|delisted)[^.\n]{0,40}?return)', re.I)


def parse_back(txt):
    out = set()
    for m in BACK_PAT.finditer(txt):
        seg = txt[max(0, m.start() - 220):m.end() + 220]
        for n in re.findall(NAME, seg):
            out.add(n.strip())
    return out


def parse_manual(text):
    hits, backs = [], set()
    for line in text.split('\n'):
        line = line.split('#')[0].strip()
        if not line:
            continue
        m = re.match(r'^(.+?)\s*[=＝:：]\s*(\d{1,3})\s*%?$', line)
        if m:
            hits.append((m.group(1).strip(), int(m.group(2))))
            continue
        m = re.match(r'^(.+?)\s*[=＝:：]\s*(回归|back|return)$', line, re.I)
        if m:
            backs.add(m.group(1).strip())
    return hits, backs


MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']


def week_range(txt):
    today = datetime.date.today()
    m = re.search(r'(%s)\s+(\d{1,2})\s*(?:to|through|until|–|-)\s*(?:([A-Za-z]+)\s+)?(\d{1,2})'
                  % '|'.join(MONTHS), txt)
    if m:
        m1, d1, m2, d2 = MONTHS.index(m.group(1)) + 1, int(m.group(2)), None, int(m.group(4))
        m2 = MONTHS.index(m.group(3)) + 1 if m.group(3) in MONTHS else m1
        try:
            start = datetime.date(today.year, m1, d1)
            end = datetime.date(today.year, m2, d2) if m2 >= m1 else datetime.date(today.year + 1, m2, d2)
            if (today - end).days > 60:
                start = start.replace(year=start.year + 1)
                end = end.replace(year=end.year + 1)
            if abs((today - start).days) <= 40:
                return start.isoformat(), end.isoformat()
        except ValueError:
            pass
    wd = today.weekday()
    start = today - datetime.timedelta(days=(wd - 3) % 7)
    return start.isoformat(), (start + datetime.timedelta(days=6)).isoformat()


def norm(s):
    return re.sub(r'[\s\-_·・（）()［］\[\]]', '', str(s or '').lower())


def build_index():
    db = json.load(io.open(SITE, encoding='utf-8'))
    brands = set()
    for v in db['vehicles']:
        brands.add(norm(v.get('brand_cn')))
        brands.add(norm(v.get('brand_en')))
    brands.discard('')
    idx, labels = {}, {}
    for v in db['vehicles']:
        keys = [v.get('id'), v.get('en'), v.get('cn'), v.get('model_cn'),
                (str(v.get('brand_cn') or '') + str(v.get('model_cn') or '')),
                (str(v.get('brand_en') or '') + ' ' + str(v.get('cn') or ''))]
        keys += list(v.get('alias') or [])
        for k in keys:
            n = norm(k)
            if n and len(n) >= 3 and n not in brands and n not in idx:
                idx[n] = v['id']
        labels[v['id']] = '%s %s' % (v.get('brand_cn') or '', v.get('model_cn') or v.get('cn') or '')
    return db, idx, labels


def match(name, idx):
    n = norm(name)
    if not n:
        return None
    if n in idx:
        return idx[n]
    if len(n) < 4:
        return None
    best_len, best = 0, set()
    for k, v in idx.items():
        if k in n or n in k:
            score = len(k) if k in n else len(n)
            if score > best_len:
                best_len, best = score, {v}
            elif score == best_len:
                best.add(v)
    return best.pop() if len(best) == 1 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    args = ap.parse_args()

    db, idx, labels = build_index()
    src_cfg = load_sources()
    votes, price_hint, back_names, used, failed = {}, {}, set(), [], []
    src_info = {}                      # 来源出处：留着做署名与溯源（合规用）
    last_txt = ''

    for s in src_cfg:
        name = s.get('name') or '?'
        if s.get('file'):
            p = os.path.join(BASE, s['file'])
            if not os.path.isfile(p):
                continue
            text = io.open(p, encoding='utf-8').read()
            hits, backs = parse_manual(text)
            prices = {}
            for vid, pct in [(match(n, idx), p) for n, p in hits]:
                if vid:
                    votes.setdefault(vid, {}).setdefault(pct, []).append(name)
            for n in backs:
                vid = match(n, idx)
                if vid:
                    back_names.add(norm(labels.get(vid, n)))
            used.append(name)
            src_info[name] = {'role': 'manual', 'file': s['file'],
                              'note': '人工录入的当周折扣，见该文件'}
            print('  ok %-12s 命中 %d 条（人工）' % (name, len(hits)))
            continue
        raw = fetch(s.get('url'))
        if not raw:
            failed.append(name)
            print('  x %-12s 抓不到' % name)
            continue
        m = re.search(s['discover'], raw) if s.get('discover') else None
        html = (fetch(m.group(1)) or raw) if m else raw
        txt = last_txt = text_of(html)
        hits = parse_table(html) + parse_prose(txt)
        prices = parse_prices(txt)
        back_names |= {norm(x) for x in parse_back(txt)}
        seen_here = set()
        for nm, pct in hits:
            vid = match(nm, idx)
            if not vid or (vid, pct) in seen_here:
                continue
            seen_here.add((vid, pct))
            votes.setdefault(vid, {}).setdefault(pct, []).append(name)
        for nm, pr in prices.items():
            vid = match(nm, idx)
            if vid:
                price_hint[vid] = pr
        used.append(name)
        # 记下这一周实际用的是哪篇文章（署名 / 溯源用；只存事实字段，不存原文）
        art = s.get('url') or ''
        if m:
            art = urllib.parse.urljoin(s.get('url') or '', m.group(1))
        src_info[name] = {'role': 'web', 'url': art,
                          'note': '只取折扣事实（车辆 + 百分比），原文版权归该站'}
        print('  ok %-12s 命中 %d 条' % (name, len(seen_here)))

    if not used:
        print('')
        print('所有源都抓不到。data/deals.json 保持原样，未改动。')
        print('可以人工把当周折扣贴到 data/deals_manual.txt（格式见文件内说明）再跑一次。')
        return 2

    items, low_conf = [], []
    for vid, bypct in votes.items():
        pct = max(bypct, key=lambda p: (len(bypct[p]), p))
        srcs = sorted(set(bypct[pct]))
        base_price = 0
        for v in db['vehicles']:
            if v['id'] == vid:
                base_price = v.get('price') or 0
                break
        calc = round(base_price * (100 - pct) / 100) if base_price and pct else 0
        real = price_hint.get(vid) or 0
        rec = {'id': vid, 'pct': pct, 'tags': ['deal'], 'sources': srcs}
        if calc:
            rec['price'] = calc
        if real and calc and abs(real - calc) > max(5000, calc * 0.06):
            rec['price_warn'] = {'source': real, 'calc': calc}
            print('  ⚠ %s 源给价 %d 与按原价算的 %d 不一致，请核对' % (labels[vid], real, calc))
        if real and not calc:
            rec['price'] = real
        if norm(labels[vid]) in back_names or any(norm(x) in back_names for x in (labels[vid],)):
            rec['tags'].append('back')
        if len(srcs) < 2:
            low_conf.append(labels[vid])
        items.append(rec)

    items.sort(key=lambda r: (-(r.get('pct') or 0), labels.get(r['id'], '')))
    frm, to = week_range(last_txt)
    out = {'updated': time.strftime('%Y-%m-%d'), 'from': frm, 'to': to,
           'sources': used, 'sourceInfo': src_info,
           'note': '折扣为事实性数据（车辆 + 折扣百分比）。原文版权归各来源站所有；'
                   '本文件不含原文文字，只保留事实字段与来源链接。',
           'items': items}

    print('')
    print('源: %s%s' % (', '.join(used), ('　抓不到: ' + ', '.join(failed)) if failed else ''))
    print('有效期: %s → %s · 折扣条目 %d（回归 %d）' % (
        frm, to, len(items), sum(1 for r in items if 'back' in r['tags'])))
    print('只有单一来源（建议人工过一眼）: %d' % len(low_conf))
    for r in items[:8]:
        print('   -%-3d %s' % (r.get('pct') or 0, labels.get(r['id'], r['id'])))

    if args.dry:
        print('')
        print('--dry：未写盘')
        return 0
    io.open(OUT, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print('')
    print('已写入:', os.path.relpath(OUT, BASE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
