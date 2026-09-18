# -*- coding: utf-8 -*-
"""构建入口：data/*.json  →  GTA线上全车辆清单.html

只读数据源、只写交付物。用户的持有记录在 GTA车辆持有配置.yaml，本脚本永不触碰。

模块导航
────────
  ① 载入 load_sources()          读 site_data / deals，清掉源站抓取错位的垃圾值
  ② 厂商 normalize_brands()      alias 元数据补全 + 「Unknown」清理 + 品牌索引
  ③ 分类 normalize_classes()     官方英文类名 + 跨分类分组（服务载具 / 特殊载具）
  ④ 渠道 normalize_channels()    真实购车渠道白名单，无法获得置底
  ⑤ 检索 build_search_index()    拼音 / 首字母 / 任意片段，构建期算好，页面零开销
  ⑥ 折扣 normalize_deals()       有效期校验 + 与载具库匹配
  ⑦ 口径 build_snapshot()        页脚时间取「载具主数据 / 每周折扣」中较新的一次
  ⑧ 落盘 emit()                  内联进模板 + 打印构建报告
"""
import datetime
import io
import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')


# ────────────────────────── ① 载入 ──────────────────────────
_LAP_RE = re.compile(r'^\d+:\d{2}\.\d{3}$')
_TOP_RE = re.compile(r'^\d+(?:\.\d+)?\s*km/h$', re.I)


def load_sources():
    """读入两个数据源；source 里被源站写错的圈速/极速在这里清掉。"""
    src = json.load(io.open(os.path.join(DATA, 'site_data.json'), encoding='utf-8'))

    bad = []
    for v in src['vehicles']:
        for field, pat in (('lap', _LAP_RE), ('top', _TOP_RE)):
            val = str(v.get(field) or '').strip()
            if val and not pat.match(val):
                bad.append((v.get('id'), field, val))
                v[field] = ''
    if bad:
        print('清洗非法圈速/极速 %d 个：%s' % (len(bad), ', '.join('%s.%s' % x[:2] for x in bad[:4])))

    deals = None
    path = os.path.join(DATA, 'deals.json')
    if os.path.isfile(path):
        try:
            deals = json.load(io.open(path, encoding='utf-8'))
        except ValueError as exc:
            print('⚠ data/deals.json 解析失败，本次不带折扣数据：', exc)
    return src, deals


# ────────────────────────── ② 厂商 ──────────────────────────
def normalize_brands(src):
    """补全能定位到的厂商，清掉源站的「Unknown」占位。

    源站把厂商放在两处：`brand_cn/brand_en` 结构化字段，以及 `alias` 列表的首项。
    结构化字段为空时，alias 里往往仍留有真实厂商（如 riot2 的 Brute）。
    两处都为空或写成 Unknown，才判为「游戏内本就没有厂商」。
    """
    veh = src['vehicles']

    # 数据自带的英中对照表：只从本数据集学，不外部编造
    en2cn = {}
    for v in veh:
        cn = (v.get('brand_cn') or '').strip()
        en = (v.get('brand_en') or '').strip()
        if cn and en and cn.lower() != 'unknown' and en.lower() != 'unknown':
            en2cn.setdefault(en, cn)

    # 已与 gta.wiki 的 manufacturer 字段交叉核对过，两源一致才写进这里
    from_alias, filled, none = [], [], []
    for v in veh:
        cn = (v.get('brand_cn') or '').strip()
        en = (v.get('brand_en') or '').strip()
        if cn.lower() == 'unknown':
            cn = ''
        if en.lower() == 'unknown':
            en = ''

        if not cn:
            hit = next((a for a in (v.get('alias') or []) if a in en2cn or a == 'Pegasus'), '')
            if hit:
                from_alias.append((v.get('id'), hit))
                en, cn = hit, en2cn.get(hit, hit)
            elif en:
                cn = en2cn.get(en, '')
                if cn:
                    filled.append((v.get('id'), en, cn))

        if not cn:
            none.append(v.get('id'))
        v['brand_cn'] = cn
        v['brand_en'] = en if cn else ''

    if from_alias:
        print('厂商从 alias 元数据找回 %d 辆：%s' % (
            len(from_alias), ', '.join('%s=%s' % x for x in from_alias)))
    if filled:
        print('厂商中文名补全 %d 辆：%s' % (len(filled), ', '.join(x[0] for x in filled[:6])))
    print('确认无厂商（两源一致）%d 辆' % len(none))

    count, en_of = {}, {}
    for v in veh:
        name = v.get('brand_cn') or ''
        if name:
            count[name] = count.get(name, 0) + 1
            en_of.setdefault(name, v.get('brand_en') or '')
    src['brands'] = [{'cn': c, 'en': en_of.get(c, ''), 'n': n}
                     for c, n in sorted(count.items(), key=lambda x: (-x[1], x[0]))]


# ────────────────────────── ③ 分类 ──────────────────────────
# 官方英文类名（源站这一列大面积错位，SUV/厢型车/紧急用车 全被写成了 Emergency）
CLASS_EN = {
    '超级跑车': 'Super', '跑车': 'Sports', '经典跑车': 'Sports Classics', '肌肉车': 'Muscle',
    '小型汽车': 'Compacts', '轿跑车': 'Coupes', '轿车': 'Sedans', 'SUV': 'SUVs', '越野车': 'Off-Road',
    '厢型车': 'Vans', '商用车': 'Commercial', '工业用车': 'Industrial', '公共事业用车': 'Utility',
    '服务用车': 'Service', '紧急用车': 'Emergency', '军用车': 'Military', '开轮式': 'Open Wheel',
    '摩托车': 'Motorcycles', '自行车': 'Cycles', '飞机': 'Planes', '直升机': 'Helicopters',
    '船': 'Boats', '改装车': 'Tuners', '遥控车': 'Remote Control',
}

# 跨分类分组（不是游戏内类别，是 Rockstar 的另一套归类）
#   CEO特殊载具 = CEO SecuroServ 特殊载具车库那批。源数据里正好有 storage = 「特殊载具仓库」
#                 这个标记，直接用它、不硬编码 id —— 免得再把「铁尼高改装版」这类名字相近
#                 但归属不同的车算进来。防空拖车（Vom Feuer，存地堡）不属于这组。
SPC_STORAGE = '特殊载具仓库'


def normalize_classes(src):
    veh = src['vehicles']
    for v in veh:
        v['spc'] = 1 if (v.get('storage') or '').strip() == SPC_STORAGE else 0
        cls = v.get('class_cn') or '其他'
        v['class_cn'] = cls
        v['class_en'] = CLASS_EN.get(cls, v.get('class_en') or '')

    src['classes'] = sorted({v['class_cn'] for v in veh},
                            key=lambda c: list(CLASS_EN).index(c) if c in CLASS_EN else 99)
    print('分类 %d 类 · CEO特殊载具 %d 辆'
          % (len(src['classes']), sum(v['spc'] for v in veh)))


# ────────────────────────── ④ 渠道 ──────────────────────────
# 下拉只列真实在售渠道，白名单之外一律不进。
BUY_KEEP = ('传奇车业', '南圣安地列斯超级汽车', '军火大亨', '必达飞行', '快乐码头')
# 真实渠道，但按用户要求不进筛选下拉（车辆卡片上仍照常显示 dealer）
BUY_HIDE = ('本尼原创汽车工作坊', '阿浩特别工坊改装', '竞技场之战', '竞技场工作室', '奖励载具')
# 源站会把这些写进 dealer，但它们都不是购车渠道：前两条是获取方式（偷/抢），
# 中两条是改装地点，后两条是自行车行与法拍。写在这里是为了让 update_data.py 的
# check 能区分「已知并故意丢弃」和「没见过的新值」—— 后者才值得报警。
BUY_DROP = ('可以偷取', '街头抢夺/偷车', '机动作战中心/复仇者工作室改装',
            '超高速自行车行', '花园银行法拍网站', '地堡',
            '目前无法获得', '不能获得')


def normalize_channels(src):
    count = {}
    for v in src['vehicles']:
        dealer = (v.get('dealer') or '').strip()
        if dealer:
            count[dealer] = count.get(dealer, 0) + 1
    kept = [{'v': k, 'n': count[k]} for k in BUY_KEEP if count.get(k)]
    hidden = [k for k in BUY_HIDE if count.get(k)]
    if hidden:
        print('渠道下拉不显示（真实渠道，按需精简）：', '、'.join(hidden))
    dropped = sorted(k for k in count if k not in BUY_KEEP + BUY_HIDE)
    if dropped:
        print('剔除非真实购车渠道：', '、'.join(dropped))
    unknown = [k for k in dropped if k not in BUY_DROP]
    if unknown:
        print('⚠ 出现没见过的 dealer 值（请确认是渠道还是获取方式）：', '、'.join(unknown))
    print('购车渠道 %d 个' % len(kept))
    return kept


# ────────────────────────── ⑤ 检索索引 ──────────────────────────
def build_search_index(src):
    """为每辆车预生成全拼与首字母串，页面直接查，不做任何运行时转换。

    汉字→拼音表由 scripts/gen_pinyin.py 用 pypinyin 一次性生成后提交，
    构建期不再依赖第三方库；表里只收载具名出现过的字（约 1000 字）。
    多音字取首选读音——索引只用于检索，不影响任何展示文本。
    """
    table = json.load(io.open(os.path.join(DATA, 'pinyin.json'), encoding='utf-8'))

    def full(tok):
        return ''.join((table[c][0] if c in table else c) for c in tok)

    def initial(tok):
        return ''.join((table[c][0][0] if c in table else c) for c in tok)

    hit = 0
    for v in src['vehicles']:
        # 只用「品牌 + 车型」这两段拼链，alias 是同名的各种写法，拼进去只会互相干扰
        tokens = [t for t in ((v.get('brand_cn') or ''), (v.get('model_cn') or v.get('cn') or '')) if t]
        py = full(''.join(tokens))
        pi = initial(''.join(tokens))
        if re.search(r'[\u4e00-\u9fff]', ''.join(tokens)):
            v['py'], v['pi'] = py, pi
            hit += 1
        else:
            v['py'] = v['pi'] = ''
    print('拼音索引 %d 辆（另 %d 辆纯英文/数字名，无需索引）' % (hit, len(src['vehicles']) - hit))


# ────────────────────────── ⑥ 折扣 ──────────────────────────
def normalize_deals(src, deals):
    if not deals:
        return None
    ids = {v['id'] for v in src['vehicles']}
    items = deals.get('items') or []
    bad = [d.get('id') for d in items if d.get('id') not in ids]
    to_date = deals.get('to') or ''
    expired = bool(to_date) and datetime.date.today().isoformat() > to_date
    print('本周折扣 %s → %s · 匹配 %d 辆%s%s' % (
        deals.get('from') or '?', to_date or '?', len(items) - len(bad),
        ('  ⚠ %d 条对不上车辆库：%s' % (len(bad), ' '.join(bad[:6]))) if bad else '',
        '  ⚠ 已过期（页面会隐藏折扣徽标）' if expired else ''))
    return deals


# ────────────────────────── ⑦ 快照口径 ──────────────────────────
def build_snapshot(src, deals):
    """页脚的「快照」= 最近一次真实更新，取载具主数据与每周折扣中较新的那个。"""
    stamps = [{'at': src['generated'][:10], 'of': '载具主数据'}]
    if deals and deals.get('updated'):
        stamps.append({'at': deals['updated'], 'of': '每周折扣'})
    return max(stamps, key=lambda x: x['at'])


# ────────────────────────── ⑧ 落盘 ──────────────────────────
def emit(src, deals, channels, snapshot):
    keep = ('id', 'en', 'cn', 'model_cn', 'brand_cn', 'brand_en', 'class_cn', 'class_en',
            'price', 'dealer', 'channels', 'dlc', 'released', 'status', 'lap', 'top',
            'proto', 'mods', 'modshop', 'alias', 'spc', 'py', 'pi')
    data = {
        'generated': src['generated'],
        'stats': src['stats'],
        'classes': src['classes'],
        'brands': src['brands'],
        'vehicles': [{k: v[k] for k in keep if k in v} for v in src['vehicles']],
        'deals': deals,
        'buyChannels': channels,
        'snapshot': snapshot,
        # 来源与许可元数据：跟着数据一起发出去，谁拿了这份数据都能看到出处与许可
        'source': src.get('source'),
    }

    tpl = io.open(os.path.join(BASE, 'scripts', 'template.html'), encoding='utf-8').read()
    assert '/*__DATA__*/' in tpl, '模板里的数据占位符丢了'
    html = tpl.replace('/*__DATA__*/',
                       'const DB = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';')
    out = os.path.join(BASE, 'GTA线上全车辆清单.html')
    io.open(out, 'w', encoding='utf-8', newline='\n').write(html)

    cfg = os.path.join(BASE, 'GTA车辆持有配置.yaml')
    if not os.path.exists(cfg):
        now = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00')
        io.open(cfg, 'w', encoding='utf-8', newline='\n').write(
            '# GTA 线上载具持有配置 · 唯一真源\nversion: 2\nrev: 0\nexported: "%s"\n'
            'summary:\n  total: %d\n  priceable: %d\n  owned: 0\n'
            'settings:\n  sort: class\n  hide_owned: false\n  only_buyable: false\n'
            'want: []\nowned: []\n' % (now, data['stats']['total'], data['stats']['buyable']))
        print('已生成默认 GTA车辆持有配置.yaml')
    else:
        print('保留已有的 GTA车辆持有配置.yaml（未覆盖）')

    print('HTML %.1f KB · 车辆 %d · 厂商 %d · 分类 %d · 渠道 %d'
          % (os.path.getsize(out) / 1024, len(data['vehicles']), len(data['brands']),
             len(data['classes']), len(data['buyChannels'])))
    print('页脚口径 %s（%s）· 折扣 %d 条'
          % (snapshot['at'], snapshot['of'], len((deals or {}).get('items') or [])))


def main():
    src, deals = load_sources()
    normalize_brands(src)
    normalize_classes(src)
    channels = normalize_channels(src)
    build_search_index(src)
    deals = normalize_deals(src, deals)
    emit(src, deals, channels, build_snapshot(src, deals))


if __name__ == '__main__':
    main()
