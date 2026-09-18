# -*- coding: utf-8 -*-
"""把 flow 插件部署到 Flow Launcher 的插件目录，并把**绝对路径**写进它的 config.json。

为什么必须有这一步（用户看到的两个错都出在这儿）：

1. 插件被拷进 `FlowLauncher/app-*/UserData/Plugins/GTA-Vehicles/` 之后，
   它眼里的「上级目录」是 `UserData/Plugins`，自动搜索也够不到
   `D:\\Downloads\\workbuddy\\Claw\\gta-vehicles` —— 于是找不到清单页，
   报的就是「找不到指定目录 / 找不到 GTA线上全车辆清单.html」。
   → 修法：部署时把清单页与 YAML 的绝对路径写进它自己的 config.json。

2. Flow 跑的是**副本**，不是仓库里的 `flow-plugin/`。
   仓库改完不部署，Flow 里还是旧代码 —— 实测踩到：旧副本缺 `sys.stdin is None`
   的回退，直接 `TypeError: 'NoneType' object is not iterable` 崩掉。

用法：
  python scripts/deploy_plugin.py                 # 自动找 Flow，复制并写路径
  python scripts/deploy_plugin.py --dry           # 只看会做什么
  python scripts/deploy_plugin.py --dest "D:\\...\\UserData\\Plugins\\GTA-Vehicles"
退出码：0 成功；1 没找到 Flow 目录。
"""
import argparse
import glob
import io
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, 'flow-plugin')
PAGE = os.path.join(BASE, 'GTA线上全车辆清单.html')
PLUG_DIR_NAME = 'GTA-Vehicles'          # Flow 里的目录名（与已装的保持一致）

# 插件只做「打开清单页」，只需要这三个文件 ——
# 不再拷 data/：那是给旧的「插件内搜索」用的，现在搜索在页面里，插件不读任何数据。
COPY = ['main.py', 'plugin.json', 'icon.png']
COPY_DIRS = []


def local_flow_root():
    """本机 Flow 安装位置，从**本地配置文件**读（该文件已 gitignore）。

    便携版装在非标准位置时，别把路径写进代码（那是某台机器特有的信息，不该进仓库）。
    约定：工程根目录的 `deploy_plugin.local.json`，内容如 {"flowRoot": "<FlowLauncher 根目录>"}。
    优先级：--dest > 环境变量 FLOW_LAUNCHER > 本地配置文件 > 标准安装位置。
    """
    cfg = os.path.join(BASE, 'deploy_plugin.local.json')
    if os.path.isfile(cfg):
        try:
            return (json.load(io.open(cfg, encoding='utf-8')) or {}).get('flowRoot', '')
        except ValueError:
            return ''
    return ''


def flow_candidates():
    """Flow Launcher 可能的安装位置（便携版 / Squirrel 版 / 安装版 / scoop）。

    只认「标准安装位置 + 环境变量 + 本地配置文件 + 命令行 --dest」——
    不要把某台机器的路径写进代码。
    """
    home = os.path.expanduser('~')
    cands = [
        os.environ.get('FLOW_LAUNCHER', ''),
        local_flow_root(),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'FlowLauncher'),
        os.path.join(os.environ.get('APPDATA', ''), 'FlowLauncher'),
        r'C:\Program Files\FlowLauncher',
        r'C:\Program Files (x86)\FlowLauncher',
        os.path.join(home, 'FlowLauncher'),
        os.path.join(home, 'scoop', 'apps', 'flow-launcher', 'current'),
    ]
    out = []
    for c in cands:
        if c and os.path.isdir(c):
            out.append(os.path.abspath(c))
    # 版本化目录（app-2.1.3/UserData/Plugins）与扁平目录（UserData/Plugins）都收
    dirs = []
    for c in out:
        for pat in ('UserData/Plugins', 'app-*/UserData/Plugins'):
            for d in glob.glob(os.path.join(c, pat.replace('/', os.sep))):
                if os.path.isdir(d):
                    dirs.append(os.path.abspath(d))
    return out, sorted(set(dirs))


def write_cfg(dest, dry):
    """把清单页 / YAML 的绝对路径写进插件自己的 config.json。"""
    path = os.path.join(dest, 'config.json')
    cfg = {}
    if os.path.isfile(path):
        try:
            cfg = json.load(io.open(path, encoding='utf-8')) or {}
        except ValueError:
            cfg = {}
    cfg.pop('state', None)          # 插件不再读 YAML，旧键顺手清掉
    cfg['_说明'] = ('插件只做「打开清单页」。page 由 scripts/deploy_plugin.py 写成绝对路径 —— '
                    '插件装在 Flow 目录里，自动搜索够不到工程目录。')
    cfg['page'] = PAGE
    if not dry:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(
            json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    return cfg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dest', default='')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    installs, dirs = flow_candidates()
    if a.dest:
        dest = os.path.abspath(a.dest)
    else:
        if not dirs:
            print('没找到 Flow Launcher 的插件目录。已探过的安装位置：')
            for c in installs or ['(一个都没有)']:
                print('   ', c)
            print('三种指定方式（任选其一）：')
            print('   1) 便携版：在工程根目录建 deploy_plugin.local.json，内容')
            print(r'      {"flowRoot": "<FlowLauncher 根目录>"}       ← 这个文件已 gitignore，不会进仓库')
            print('   2) 环境变量：FLOW_LAUNCHER=<FlowLauncher 根目录>')
            print('   3) 命令行：--dest "<.../UserData/Plugins/GTA-Vehicles>"')
            return 1
        if len(dirs) > 1:
            print('找到多个插件目录，取第一个（可用 --dest 指定）：')
            for d in dirs:
                print('   ', d)
        dest = os.path.join(dirs[0], PLUG_DIR_NAME)

    print('源：%s' % SRC)
    print('目标：%s' % dest)
    print('清单页：%s  %s' % (PAGE, '✓ 存在' if os.path.isfile(PAGE) else '✗ 不存在 —— 先跑 build_site.py'))
    if a.dry:
        print('\n（--dry，未改动任何文件）')
        return 0

    os.makedirs(dest, exist_ok=True)
    copied = []
    for f in COPY:
        s = os.path.join(SRC, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, f))
            copied.append(f)
    for d in COPY_DIRS:
        s = os.path.join(SRC, d)
        if os.path.isdir(s):
            t = os.path.join(dest, d)
            if os.path.isdir(t):
                shutil.rmtree(t, ignore_errors=True)
            shutil.copytree(s, t)
            copied.append(d + '/')
    # 关键：旧副本的字节码缓存必须清掉，否则可能还在跑旧逻辑
    shutil.rmtree(os.path.join(dest, '__pycache__'), ignore_errors=True)
    cfg = write_cfg(dest, a.dry)

    print('\n已复制：%s' % '、'.join(copied))
    print('已写 config.json：page=%s' % cfg['page'])
    print('\n接下来在 Flow 里让它生效（二选一）：')
    print('  · 设置 → 插件 → 找到「GTA 载具库」→ Reload Plugin Data')
    print('  · 或重启 Flow Launcher')
    print('（Flow 是把插件当常驻子进程跑的，不重载就还是旧代码。）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
