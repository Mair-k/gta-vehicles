# -*- coding: utf-8 -*-
"""载具主数据更新入口（唯一入口，其它脚本不要直接改 site_data.json）

设计原则
────────
1. **单一入口**：新 DLC 落库只走这里；构建脚本只读 site_data.json。
2. **幂等**：同一份数据合并两次结果一致（按 id upsert，不重复、不乱序）。
3. **可回溯**：每次写入前自动快照 + 备份，`rollback` 一键回到上一版。
4. **先验后写**：`check` 不过就不许构建，避免把坏数据带给页面。
5. **看不懂就喊**：出现没见过的分类 / 渠道值直接列出来，而不是默默归到「其他」。

用法
────
  python scripts/update_data.py check                  # 只校验
  python scripts/update_data.py merge <new.json>       # 合并新 DLC（先 dry-run 看差异）
  python scripts/update_data.py merge <new.json> --write
  python scripts/update_data.py snapshot               # 手动打快照
  python scripts/update_data.py rollback               # 回滚到上一版
  python scripts/update_data.py build                  # 校验通过后重建页面
  python scripts/update_data.py all <new.json>         # merge --write + build

new.json 支持两种形态
  · {"vehicles":[...]}      —— 与 site_data 同形
  · [ {...}, {...} ]        —— 只给一批载具
  每条只需给 `id`（游戏内模型名）与要改的字段，其余保持原值。
  新载具的厂商如果源站没给，`alias` 里务必带上厂商名 —— 构建脚本会从那里补全。
"""
import argparse
import datetime as dt
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
SITE = os.path.join(DATA, 'site_data.json')
SNAP_DIR = os.path.join(DATA, 'snapshots')
BAK_DIR = os.path.join(DATA, 'backup')
LOG = os.path.join(DATA, 'CHANGELOG.md')

REQUIRED = ('id', 'cn')
OPTIONAL = ('en', 'brand_cn', 'brand_en', 'model_cn', 'class_cn', 'class_en', 'dealer',
            'channels', 'price', 'dlc', 'released', 'lap', 'top', 'proto',
            'mods', 'modshop', 'alias', 'status', 'src')


def _load(path=SITE):
    return json.load(io.open(path, encoding='utf-8'))


def _save(obj, path=SITE):
    io.open(path, 'w', encoding='utf-8', newline='\n').write(
        json.dumps(obj, ensure_ascii=False, separators=(',', ':')))


def backup_and_snapshot(tag):
    os.makedirs(SNAP_DIR, exist_ok=True)
    os.makedirs(BAK_DIR, exist_ok=True)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    for target in (os.path.join(BAK_DIR, 'site_data.%s.json' % stamp),
                   os.path.join(SNAP_DIR, '%s-%s.json' % (stamp, tag))):
        shutil.copy2(SITE, target)
    snaps = sorted(f for f in os.listdir(SNAP_DIR) if f.endswith('.json'))
    return os.path.join(SNAP_DIR, snaps[-1]), snaps


def _build_site_module():
    """按需加载构建脚本，取它的分类 / 渠道白名单做交叉校验。"""
    spec = importlib.util.spec_from_file_location('build_site', os.path.join(BASE, 'scripts', 'build_site.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 校验 ────────────────────────────────────────────────────────────────
def check():
    """返回 (错误列表, 警告列表)。"""
    errs, warns = [], []
    src = _load()
    vehicles = src.get('vehicles') or []
    if not vehicles:
        errs.append('vehicles 为空')

    seen = set()
    for v in vehicles:
        vid = str(v.get('id') or '').strip()
        if not vid:
            errs.append('有载具缺少 id：%r' % (str(v.get('cn') or v)[:60],))
            continue
        if vid in seen:
            errs.append('id 重复：%s' % vid)
        seen.add(vid)
        for field in REQUIRED:
            if not str(v.get(field) or '').strip():
                errs.append('%s 缺少必填字段 %s' % (vid, field))
        if not v.get('class_cn'):
            warns.append('%s 没有分类（新 DLC 常见，页面会归到「其他」）' % vid)

    try:
        mod = _build_site_module()
        known_cls = set(mod.CLASS_EN)
        known_ch = set(mod.BUY_KEEP) | set(mod.BUY_HIDE) | set(mod.BUY_DROP)
        unknown_cls, unknown_ch = {}, {}
        for v in vehicles:
            cls = (v.get('class_cn') or '').strip()
            if cls and cls not in known_cls:
                unknown_cls[cls] = unknown_cls.get(cls, 0) + 1
            dealer = (v.get('dealer') or '').strip()
            if dealer and dealer not in known_ch:
                unknown_ch[dealer] = unknown_ch.get(dealer, 0) + 1
        for cls, n in sorted(unknown_cls.items(), key=lambda x: -x[1]):
            warns.append('未识别的分类 %r（%d 辆）→ 已归到「其他」；'
                         '若是新 DLC 引入的类别，请补 build_site.py 的 CLASS_EN' % (cls, n))
        for dealer, n in sorted(unknown_ch.items(), key=lambda x: -x[1]):
            warns.append('未识别的购买渠道 %r（%d 辆）→ 已从渠道筛选里剔除；'
                         '确认它是真实购车渠道后再补 build_site.py 的 BUY_KEEP，'
                         '若它本来就不是渠道（偷车 / 改装点 / 法拍…）请补进 BUY_DROP' % (dealer, n))
    except Exception as exc:
        errs.append('build_site.py 导入失败：%r' % (exc,))
    return errs, warns


def cmd_check(_args):
    errs, warns = check()
    for w in warns:
        print('WARN ', w)
    for e in errs:
        print('ERROR', e)
    src = _load()
    print('校验：%d 个错误 / %d 个提醒　·　载具 %d 辆'
          % (len(errs), len(warns), len(src.get('vehicles') or [])))
    return 1 if errs else 0


# ── 合并新 DLC ─────────────────────────────────────────────────────────
def _payload_items(payload):
    if isinstance(payload, dict):
        return payload.get('vehicles') or []
    if isinstance(payload, list):
        return payload
    raise ValueError('无法识别的 JSON 结构：需要 {"vehicles":[...]} 或 [...]')


def cmd_merge(args):
    incoming = _payload_items(_load(args.file))
    src = _load()
    current = {v.get('id'): v for v in (src.get('vehicles') or [])}

    added, updated = [], []
    for v in incoming:
        vid = str(v.get('id') or '').strip()
        if not vid:
            print('SKIP  缺少 id 的一条：%r' % (str(v)[:60],))
            continue
        if vid in current:
            diff = sorted(k for k in v if current[vid].get(k) != v.get(k))
            if diff:
                current[vid].update(v)
                updated.append((vid, diff))
        else:
            current[vid] = v
            added.append(vid)

    print('本批：新增载具 %d 辆，更新 %d 辆' % (len(added), len(updated)))
    for vid, keys in updated[:12]:
        print('  ~ %-18s 改了 %s' % (vid, ','.join(keys[:6])))
    if added[:12]:
        print('  + %s' % ', '.join(added[:12]))

    if not args.write:
        print('\n（dry-run，未写入。确认无误后加 --write）')
        return 0

    src['vehicles'] = list(current.values())
    src['generated'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
    snap, _ = backup_and_snapshot('merge')
    _save(src)
    with io.open(LOG, 'a', encoding='utf-8', newline='\n') as f:
        f.write('\n## %s\n- 载具：新增 %d 辆、更新 %d 辆\n- 快照：%s\n- 来源：%s\n'
                % (dt.datetime.now().strftime('%Y-%m-%d'), len(added), len(updated),
                   os.path.basename(snap), args.file))
    print('已写入 %s（备份见 data/backup）' % SITE)

    errs, warns = check()
    if errs:
        print('\n合并后校验不通过，建议修掉再 build：')
        for e in errs[:20]:
            print('  ERROR', e)
        return 1
    for w in warns[:10]:
        print('  WARN', w)
    return 0


def cmd_snapshot(_args):
    if not os.path.isfile(SITE):
        print('没有 site_data.json')
        return 1
    snap, snaps = backup_and_snapshot('manual')
    print('快照：%s（共 %d 份）' % (os.path.basename(snap), len(snaps)))
    return 0


def cmd_rollback(_args):
    if not os.path.isdir(BAK_DIR):
        print('还没有备份')
        return 1
    baks = sorted(f for f in os.listdir(BAK_DIR) if f.endswith('.json'))
    if not baks:
        print('还没有备份')
        return 1
    backup_and_snapshot('before-rollback')
    shutil.copy2(os.path.join(BAK_DIR, baks[-1]), SITE)
    print('已回滚到 %s' % baks[-1])
    return 0


def cmd_build(_args):
    errs, warns = check()
    for w in warns[:10]:
        print('WARN ', w)
    if errs:
        for e in errs[:20]:
            print('ERROR', e)
        print('校验未通过，已中止构建（先修数据，或 python scripts/update_data.py rollback）')
        return 1
    return subprocess.run([sys.executable, os.path.join(BASE, 'scripts', 'build_site.py')],
                          cwd=BASE).returncode


def main():
    ap = argparse.ArgumentParser(description='GTA 载具库 · 载具主数据更新入口')
    sub = ap.add_subparsers(dest='cmd')
    sub.add_parser('check')
    merge = sub.add_parser('merge')
    merge.add_argument('file')
    merge.add_argument('--write', action='store_true')
    sub.add_parser('snapshot')
    sub.add_parser('rollback')
    sub.add_parser('build')
    allp = sub.add_parser('all')
    allp.add_argument('file')
    args = ap.parse_args()

    if args.cmd == 'check':
        return cmd_check(args)
    if args.cmd == 'merge':
        return cmd_merge(args)
    if args.cmd == 'snapshot':
        return cmd_snapshot(args)
    if args.cmd == 'rollback':
        return cmd_rollback(args)
    if args.cmd == 'build':
        return cmd_build(args)
    if args.cmd == 'all':
        args.write = True
        return cmd_merge(args) or cmd_build(args)
    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
