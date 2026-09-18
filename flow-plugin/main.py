# -*- coding: utf-8 -*-
"""GTA 载具库 —— Flow Launcher 插件。

**只做一件事：打开清单页。**

为什么不在这里做别的（改配置、搜车、标记已拥有）：
  ① 页面才是唯一真源。标记已拥有、计划购买、筛选与折扣，全在页面里，
     页面自己带一整套校验。在插件里复制那套逻辑，等于维护两份会各自漂移的规则 ——
     以后没时间同步。
  ② 直接改写 `GTA车辆持有配置.yaml` 绕过了页面的校验，属于「不安全」的那类操作。

所以这里**没有** YAML 读写、没有本地数据文件、没有搜索、没有状态同步。
它只负责定位那份自包含的 HTML 并交给浏览器打开（可以把关键词带过去，页面搜索框会自动填上）。

定位顺序（config.json → 同级目录 → 自动搜索），与之前一致：
插件被装到 Flow 目录里时，自动搜索够不到工程目录，所以 `scripts/deploy_plugin.py`
会把清单页的**绝对路径**写进本插件自己的 config.json。
"""
import io
import json
import os
import sys

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(PLUGIN_DIR, 'config.json')
PAGE_NAME = 'GTA线上全车辆清单.html'
ICO = os.path.join(PLUGIN_DIR, 'icon.png')
DEBUG_LOG = os.path.join(PLUGIN_DIR, 'debug.log')
IS_WIN = os.name == 'nt'

_SCAN_SKIP = {'node_modules', 'AppData', 'Windows', 'Program Files', 'Program Files (x86)',
              'System Volume Information', '$Recycle.Bin', 'ProgramData', 'Python', 'python',
              'site-packages', 'Lib', 'Scripts', 'Plugins', 'UserData', '__pycache__'}
_MAX_SCAN = 60000


def _log(text, append=False):
    try:
        with io.open(DEBUG_LOG, 'a' if append else 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError:
        pass


def _cfg():
    try:
        return json.load(io.open(CONFIG_FILE, encoding='utf-8')) or {}
    except (OSError, ValueError):
        return {}


def _search_roots():
    """自动搜索的候选根：插件上级目录 + 用户常见目录 + D/C/E 盘里名字带 gta 的目录。"""
    cfg = _cfg()
    roots = [os.path.dirname(PLUGIN_DIR)]
    home = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    if home:
        roots.append(home)
        for sub in ('Downloads', 'Desktop', 'Documents'):
            roots.append(os.path.join(home, sub))
    for drv in ('C:\\', 'D:\\', 'E:\\'):
        try:
            for d in os.listdir(drv):
                if 'gta' in d.lower():
                    roots.append(os.path.join(drv, d))
        except OSError:
            pass
    roots.extend(cfg.get('search_extra') or [])
    out, seen = [], set()
    for r in roots:
        if not r:
            continue
        r = os.path.abspath(r)
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            out.append(r)
    return out


def _find(name):
    hits, scanned = [], 0
    for root in _search_roots():
        base = root.rstrip('\\/').count(os.sep)
        for cur, dirs, files in os.walk(root):
            if cur.count(os.sep) - base >= 3:      # 深度上限 3，别把整块盘翻一遍
                dirs[:] = []
            dirs[:] = [d for d in dirs if d not in _SCAN_SKIP and not d.startswith('.')]
            scanned += len(files) + len(dirs)
            if scanned > _MAX_SCAN:
                break
            if name in files:
                return os.path.abspath(os.path.join(cur, name))
    return None


def page_path():
    cfg = _cfg()
    p = (cfg.get('page') or '').strip()
    if p and os.path.isfile(p):
        return os.path.abspath(p)
    sib = os.path.join(os.path.dirname(PLUGIN_DIR), PAGE_NAME)
    if os.path.isfile(sib):
        return os.path.abspath(sib)
    found = _find(PAGE_NAME)
    if found:
        try:
            cfg['page'] = found
            io.open(CONFIG_FILE, 'w', encoding='utf-8', newline='\n').write(
                json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
        except OSError:
            pass
        return found
    return os.path.abspath(sib)


def page_missing():
    """页面找不到时给一句能照做的提示（不要弹一个看不懂的异常）。"""
    return ('找不到 %s。把它在 config.json 的 page 写成绝对路径，'
            '或跑一次 scripts/deploy_plugin.py（会自动写好），'
            '或把它放到下载 / 桌面 / 文档目录下让插件自动发现。' % PAGE_NAME)


def open_page(fragment=''):
    path = page_path()
    if not os.path.isfile(path):
        raise RuntimeError('清单页不存在: ' + path)
    if fragment:
        target = 'file:///' + path.replace('\\', '/') + '#' + fragment
    else:
        target = path
    if IS_WIN:
        try:
            os.startfile(target)                                 # noqa: S606
            return True
        except OSError:
            import subprocess
            subprocess.Popen(['cmd', '/c', 'start', '', '"%s"' % target])
            return True
    import webbrowser
    return webbrowser.open(target)


def _q(s):
    from urllib.parse import quote
    return quote(str(s), safe='')


class Plugin:
    """查询只有一条结果：打开清单页（带关键词就顺手把搜索词带过去）。"""

    def _row(self, title, sub, frag='', score=100, method='open_page', params=None):
        return {
            'Title': title,
            'SubTitle': sub,
            'IcoPath': ICO,
            'JsonRPCAction': {'method': method,
                              'parameters': params if params is not None else [frag],
                              'dontHideAfterAction': False},
            'Score': score,
        }

    def query(self, query=''):
        q = (query or '').strip()
        if not os.path.isfile(page_path()):
            return [self._row('⚠ 找不到清单页', page_missing(), method='noop', params=[], score=100)]
        if not q:
            return [self._row('打开 GTA 线上载具清单',
                              '搜索 / 标记已拥有 / 计划购买 / 本周折扣　·　回车打开')]
        # 也只是「打开页面」：把关键词带过去，页面搜索框会自动填上
        return [self._row('在清单页里搜「%s」' % q,
                          '回车打开清单页，搜索框会填上这串关键词',
                          frag='q=' + _q(q))]

    # ---- 动作 ----
    def open_page(self, fragment=''):
        try:
            open_page(fragment)
        except Exception as exc:
            sys.stderr.write('open_page: %s\n' % exc)
            _log('open_page 失败: %r\n' % (exc,), append=True)
        return True

    def noop(self):
        return True

    def contextmenu(self, vid=''):
        """没有右键菜单项 —— 留个空实现，免得 Flow 调用时被记成「未知方法」。"""
        return []


# ───────────────────────── 标准流 / 自诊断 ─────────────────────────
# Flow 用 pythonw.exe 启动插件，某些启动方式下 sys.stdin 会是 None
# （实测报错：for line in sys.stdin → TypeError: 'NoneType' object is not iterable）。
# 所以：① 退回原始文件描述符 ② 兼容「查询走命令行参数」的启动方式 ③ 启动环境写进 debug.log。


def _stream(name, fd, mode):
    s = getattr(sys, name, None)
    if s is not None:
        return s
    try:
        return io.open(fd, mode, encoding='utf-8', errors='replace',
                       closefd=False, buffering=1)
    except Exception:
        pass
    raw = getattr(sys, '__%s__' % name, None)
    if raw is not None:
        try:
            return io.TextIOWrapper(raw, encoding='utf-8', write_through=True)
        except Exception:
            return raw
    return None


def _handle(holder, req):
    method = req.get('method') or ''
    params = req.get('parameters')
    if params is None:
        params = req.get('params') or []
    if not isinstance(params, list):
        params = [params]
    try:
        if method in ('initialize', 'close', 'setting'):
            result = True
        else:
            if holder[0] is None:
                holder[0] = Plugin()
            fn = getattr(holder[0], method, None)
            if fn is None:
                _log('未知方法（插件进程可能是旧版本，重启 Flow 即可）: %s\n' % method, append=True)
                result = []
            else:
                result = fn(*params)
    except Exception as exc:                 # 任何异常都不许让插件退出
        _log('%s: %r\n' % (method, exc), append=True)
        try:
            sys.stderr.write('%s: %s\n' % (method, exc))
        except Exception:
            pass
        result = []
    return {'result': result, 'id': req.get('id'), 'jsonrpc': '2.0', 'method': method}


def main():
    inp = _stream('stdin', 0, 'r')
    out = _stream('stdout', 1, 'w')
    if out is None:
        # 拿不到 stdout 说明 Flow 的启动环境不对，落一条日志便于排查（正常启动不写盘）
        _log('stdout 拿不到\nexecutable=%s\nargv=%r\nresolved_stdin=%r\nresolved_stdout=%r\n'
             % (sys.executable, sys.argv, inp, out))
        return

    holder = [None]

    # 有的启动方式把查询直接塞在命令行里：先答一次，再继续服务标准输入
    for arg in sys.argv[1:]:
        if not arg.lstrip().startswith('{'):
            continue
        try:
            req = json.loads(arg)
        except ValueError:
            continue
        out.write(json.dumps(_handle(holder, req), ensure_ascii=False) + '\n')
        out.flush()

    if inp is None:
        return

    for line in inp:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        out.write(json.dumps(_handle(holder, req), ensure_ascii=False) + '\n')
        out.flush()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:                 # 绝不让异常冒出去弹窗
        _log('\n[fatal] %r\n' % (exc,), append=True)
