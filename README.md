# GTA 线上载具库 · 洛圣都车库档案

自包含单文件载具清单（**离线、双击即用、零依赖**）+ 每周折扣 + 持有记录配置文件 + Flow Launcher 启动器插件。

---

## 交付物

| 文件 | 说明 |
|---|---|
| `GTA线上全车辆清单.html` | 页面本体。802 辆车 / 23 类 / 63 厂商 / 7 个购买渠道 |
| `GTA车辆持有配置.yaml` | **持有记录的真源**，绑定后页面直接读写它 |
| `update-deals.bat` | 双击更新本周折扣并重建页面 |

## 怎么用

1. 双击打开 `GTA线上全车辆清单.html` —— 完了，就这样
2. **第一次打开会自动初始化**一份空配置（存在浏览器里），标记 / 取消 / 加计划**即时保存**，关闭再开自动恢复
3. 想让数据落到磁盘上的 yaml 文件：点顶栏**「配置文件-未加载」**，选一次 `GTA车辆持有配置.yaml`（权限提示选「允许」，有「每次访问都允许」就一并勾上）——之后每次打开自动读文件、每次改动自动写回同一个文件

装载是三层自动阶梯，全程零点击：文件权限有效 → 直接读文件；权限被浏览器收回 → 自动恢复浏览器里上次的状态（数据不丢）；第一次 → 初始化。重新连接文件时按版本号比较新旧，**断开期间在页面里做的改动不会被旧文件覆盖**。

**换设备**：旧机器「更多 → 导出配置」拿 yaml，新机器「更多 → 导入配置」即可；或者带上 yaml 文件在新机器绑定一次。

## 搜索怎么用

全站只有一个检索入口 `findVehicles()`，主搜索框、批量添加的候选、各抽屉里的筛选走的是同一套。

| 输入 | 命中 |
|---|---|
| `卡林 S95` / `s95` / `zentorno` | 中文名 / 型号 / 英文名 |
| `kalin` `kalins95` `sangtuolao` | **全拼**（可拼车型） |
| `kls95` `kl` `pjx` `msbt` | **首字母**（可与型号连写） |
| `林` `暴徒` | 任意单字 / 片段 |
| `佩嘉西 灵蛇` | 品牌和车型配错时放宽为命中任一词，不留空白 |

汉字→拼音表由 `scripts/gen_pinyin.py` 一次性生成（只收车名用到的约 1000 字，十几 KB），
**构建期不再依赖第三方库**。改车名后重跑一次即可。

## 三条数据线

```
data/site_data.json   车辆主数据  ← update_data.py 独占写（check / merge / snapshot / rollback / all）
data/deals.json       每周折扣    ← update_deals.py（多源抓取 + data/deals_manual.txt 人工兜底）
data/pinyin.json      汉字→拼音   ← gen_pinyin.py（一次性）
        ▼ scripts/build_site.py（只读，八模块：载入 / 厂商 / 分类 / 渠道 / 检索 / 折扣 / 口径 / 落盘）
GTA线上全车辆清单.html
```

`scripts/template.html` 是页面的唯一源文件（含 `/*__DATA__*/` 占位），构建时把数据内联进去。

## 命令

```bash
python scripts/build_site.py                    # 重建页面
python scripts/update_deals.py --dry            # 只看抓到什么折扣，不写盘
python scripts/update_deals.py                  # 抓本周折扣 → data/deals.json
python scripts/update_data.py check             # 车辆主数据校验
python scripts/update_data.py all new.json      # 新 DLC：合并 + 校验 + 重建
python scripts/update_data.py rollback          # 回滚到上一版
python scripts/deploy_plugin.py                 # 部署 Flow 插件

uv run --no-project --with pypinyin scripts/gen_pinyin.py   # 车名新增生僻字后重生成拼音表
```

**每周四更新折扣**：`update_deals.py` → `build_site.py`。
GTA 每周重置在周四 10:00 UTC（北京 18:00），但重置会晚 1–2 小时、聚合站还要几小时才出稿，
所以抓取安排在**周四 22:00**（已配定时任务；也可双击 `update-deals.bat`）。

**时效性**：`deals.json` 带 `from` / `to`。过期后页面隐藏折扣徽标、构建期报警，
旧数据不会冒充本周。抓不到时把当周折扣按 `车名 = 折扣%` 写进 `data/deals_manual.txt` 再跑一次。

**Flow 装在非标准位置**（便携版）时，在工程根目录建 `deploy_plugin.local.json`：
`{"flowRoot": "<FlowLauncher 根目录>"}` —— 该文件已在 `.gitignore` 里，本机路径不会跟着代码走。
优先级：`--dest` > 环境变量 `FLOW_LAUNCHER` > 该文件 > 标准安装位置。

## 目录

```
GTA线上全车辆清单.html   交付物（自包含单文件）
index.html               GitHub Pages 入口（跳转到上面那个文件）
GTA车辆持有配置.yaml     持有记录真源，绝不覆盖
update-deals.bat         手动触发每周更新
README.md
LICENSE                  代码 MIT / 数据 CC BY-NC-SA 4.0（见文末）

scripts/
  template.html     页面唯一源文件
  build_site.py     构建入口
  gen_pinyin.py     生成 data/pinyin.json
  update_data.py    车辆主数据写入口
  update_deals.py   每周折扣抓取
  deploy_plugin.py  部署插件到 Flow

data/
  site_data.json    车辆主数据（只由 update_data.py 写）
  pinyin.json       汉字→拼音表（只由 gen_pinyin.py 写）
  deals.json        本周折扣（只由 update_deals.py 写）
  deals_sources.json  折扣源清单（可加可关）
  deals_manual.txt    折扣人工兜底
  CHANGELOG.md      数据变更记录
  backup/           写盘前的自动备份（本机文件，不入库）

flow-plugin/        Flow Launcher 插件（只做「打开清单页」，不碰用户数据）
```

## 数据来源与许可

本仓库是**混合许可**：**代码 MIT，数据 / 交付页 CC BY-NC-SA 4.0**。

### 代码 —— MIT

`scripts/`、`flow-plugin/`、`scripts/template.html`，见 [LICENSE](LICENSE)。

### 数据 —— CC BY-NC-SA 4.0（**不是 MIT**）

`data/site_data.json`、`data/pinyin.json`、`data/deals*.json`，以及**交付页内嵌的车辆数据**
（`GTA线上全车辆清单.html`）。这些内容来自：

| | |
|---|---|
| **来源** | GTAOL 中文知识库 / GTAOL Knowledge Base |
| **地址** | https://docs.82lf.cn/ |
| **作者** | 来一瓶82年的拉菲好嘛（站长） |
| **许可** | **CC BY-NC-SA 4.0** — https://creativecommons.org/licenses/by-nc-sa/4.0/ |
| **本站改动** | 只取载具 / 折扣 / 设施相关的**数据字段**，重排为结构化 JSON 并做清洗（价格归一、类名映射、存放归类）；未改动其原意 |

源站公开声明（首页原文）：

> 本站原创撰写的攻略、评论、分析等文字内容，均采用 CC BY-NC-SA 4.0 许可。在遵守该协议的前提下，
> 您可以自由分享、改编……

因此这些数据与交付页按 **CC BY-NC-SA 4.0** 分发，三条义务都要守：

- **署名**：保留上表的来源 / 作者 / 许可信息（页面页脚也标了）。
- **非商业**：本项目及其分发版本**不得用于商业用途**（不得加广告、付费墙、收费分发）。
- **相同方式共享**：再分发这些数据或含数据的页面时，**必须继续使用同一许可**，不能改标成 MIT 或私有。

源站 `robots.txt` 允许抓取（`User-agent: *` / `Disallow:` 为空）。仓库内**不含抓取脚本**，数据是离线快照。

### 其它

游戏名称、车辆名称与相关商标归 **Rockstar Games / Take-Two Interactive** 所有；
本项目是非官方粉丝工具，与官方无任何关联。

## 页面结构（改之前先看）

- **状态**：`q / sort / cls / brand / dealer / mods / hideOwned / onlyOwned / wantOnly / buyable / dealOnly / owned / want / wantBack / limit / rev / dirty`
- **回列表首行**：位置交给 CSS 的 `#grid{scroll-margin-top:var(--stick)}`，动作交给浏览器原生
  `scrollIntoView()`。`--stick` 由 `syncStickyOffset()` 实量吸顶控制台高度后写到 `:root`。
  **不要再自己写 rAF 插值滚动** —— 那正是之前「落点歪 / 画面抖」的来源。
- **长列表**：卡片靠原生 `content-visibility:auto` 跳过离屏渲染；滚到列表末尾由
  `IntersectionObserver` 自动补 160 张。补的内容在视口下方，不会顶动正在看的东西。
- **状态变化不许重建 DOM**：勾选 / 取消只改那一张卡（`paintCard`）+ 计数；只有可见集合真的变了
  才整块重渲染，且要按网格顶部位移补偿 `scrollY`。
- **「标记已拥有」**默认零宽收起，靠 `:hover` 的 `transition-delay:.6s` 在悬停 600ms 后展开；
  键盘 `:focus-within` 不延迟。
- **候选下选框**是挂在 `body` 上的 `.sel-panel`（不被抽屉的 overflow 裁掉），
  注册在 `SEL_SKINS` 里，靠 `pruneSel()` 回收 —— 关抽屉时必须成对清理。

## 约定

1. `data/site_data.json` **只由** `update_data.py` 写；`build_site.py` 只读。
2. `GTA车辆持有配置.yaml` **绝不覆盖** —— 那是用户数据，只在文件不存在时写默认值。
3. **不做 Node 构建链**：交付物是手写模板拼出来的单文件，不引框架、不装依赖。
   框架能给的（滚动手势、长列表、下拉定位）用浏览器原生能力解决。
4. **跨分类分组靠元数据推，不硬编码 id**：
   CEO特殊载具 = `storage == '特殊载具仓库'`（8 辆）。硬编码会出错 ——
   `technical3` 是铁尼高改装版，水陆铁尼高其实是 `technical2`。
5. **厂商以元数据为准并交叉校验**：`brand_cn / brand_en` 为空时从 `alias` 列表里找
   （规律 802/802 成立：`alias` 必含 `brand_en`），两处都没有才算「无厂商」，
   且要与 `gta.wiki` 的 `manufacturer` 比对一致。已找回 10 辆、确认 23 辆真无厂商。
6. **分类：官方 Service 类不单列**。源站与 gta.wiki 都把巴士/出租车/垃圾车等 11 辆归在官方
   `Service` 类，但按要求不出现「服务」，故在 `CLASS_MERGE` 里整体并入「商用车」。
   这是刻意的呈现简化，不是数据修正。
7. **购买渠道白名单**：下拉只列到「快乐码头」；`BUY_HIDE` 是真实渠道但不进下拉，
   `BUY_DROP` 是压根不是渠道的值（偷车 / 改装点 / 法拍）。车辆卡片上的 `dealer` 照常显示。
8. **改完自己开一次页面**：这个项目没有自动化测试，靠人眼过一遍筛选 / 搜索 / 标记 / 批量添加。

## 已知待办

- **「回归车辆」的专用源**：现在靠正文里的 `return … in-game store` 句式判定，不稳。
  需要一个稳定的下架车名单（gtaboom 有 Removed Vehicles 指南页，可作候选）。
- **折扣源冗余**：主源 gtaboom 是 JS 渲染站，普通请求只拿到空壳，必须走无头 Chrome。
  再补 1–2 个「结构稳定、非 JS 渲染」的源才真正抗失效。
- **不做**：中英对照表（源数据无独立英文字段）、游艇（不动产，不在载具库里）。
