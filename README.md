# DiskCC · Windows C 盘智能清理工具

内置规则库 + 可选 AI 识别的 C 盘清理工具。既覆盖「临时文件 / Windows 更新缓存 / 浏览器缓存」等常规垃圾，
也能**识别 `Program Files` 里每个文件夹属于哪个软件**、**分析 `AppData` 中每个目录的作用并挑出可以放心清理的文件**。

> 定位：先「看得懂再删」。所有项目都带作用说明、风险等级与识别来源（规则库 / 注册表 / 文件版本信息 / AI），
> **扫描完成后默认一项都不勾选**，由你逐项确认后手动勾选。

当前版本：**v1.3.3**（版本改动记录见 [第十章](#十版本改动记录)）

---

## 一、快速开始

### 方式 A：下载现成 exe（推荐，无需 Python）

到 [Releases](https://github.com/nirvanaL6/DiskCC/releases) 下载，两种形态任选：

| 文件 | 形态 | 建议 |
|---|---|---|
| `DiskCC-vX.Y.Z-win64.zip` | **onedir 目录模式**（解压得 `DiskCC.exe` + `_internal/`） | **推荐**。启动不解包临时文件，最不容易被杀软拦截 |
| `DiskCC.exe` | 单文件模式（自包含一个 exe） | 想只发一个文件给别人时用 |

两者解压/双击即可运行，无需安装 Python、无需附带其它文件夹。首次启动会请求管理员权限
（清理 `C:\Windows\Temp`、`SoftwareDistribution`、执行 DISM / powercfg 等必须提权）；拒绝提权也能运行，只是这些项目会失败并提示。

> 若被 360 / 火绒拦截，见 [八、常见问题 → exe 被报毒](#八常见问题)；校验值见同页 `DiskCC.exe.sha256.txt`。

### 方式 B：源码运行（需 Python 3.9+，推荐 3.11）

```bat
pip install -r requirements.txt
python main.py
```

### 方式 C：自行打包

```bat
build_exe.bat
```

读取 `DiskCC.spec` 生成**单文件** `dist\DiskCC.exe`，并输出 `dist\DiskCC.exe.sha256.txt`。
如需 onedir 目录模式：`set DISKCC_ONEDIR=1 && python -m PyInstaller --noconfirm --clean DiskCC.spec`，产物在 `dist\DiskCC\`。
另有 `build_exe_docker.sh` / `build_exe_wine.sh` 供 Linux/Docker 环境交叉构建（同样走 `DiskCC.spec`）。

### 命令行模式（不启动界面，适合定时任务 / 排障）

```bat
python main.py --cli --out report.csv          :: 扫描并导出 CSV（.json 则导出 JSON）
python main.py --cli --min-size 5 --out r.json :: 忽略小于 5MB 的项目
python main.py --cli --config D:\my.json       :: 指定配置文件
python main.py --version                       :: 打印版本号
python main.py --selftest                      :: 构造模拟 C 盘跑通扫描引擎（自测）
python main.py --admin                         :: 以管理员权限重新启动
```

---

## 二、功能一览

| 模块 | 说明 | 默认 |
|---|---|---|
| 用户 / 系统临时文件 | `%TEMP%`、`C:\Windows\Temp` 顶层条目（自动跳过 24h 内修改与被占用的） | 可选 |
| 回收站 | `C:\$RECYCLE.BIN` | 可选 |
| 缩略图 / 图标缓存 | `thumbcache_*.db`、`iconcache_*.db`（删除后自动重建） | 可选 |
| 预读取 Prefetch | `*.pf` | 可选 |
| 字体缓存 | LocalService 字体缓存 | 可选 |
| Windows 错误报告 WER | 用户级与系统级 WER 队列 | 可选 |
| 崩溃转储 | `CrashDumps`、`Minidump`、`MEMORY.DMP` | 可选 |
| 系统日志 | CBS / DISM / Panther / 更新日志 | 可选 |
| **Windows 更新缓存** | `SoftwareDistribution\Download` | 可选 |
| 传递优化缓存 | Delivery Optimization | 可选 |
| WinSxS 组件清理 | DISM `StartComponentCleanup`（含 ResetBase 深度项） | ❌ 需手动勾选 |
| 旧系统残留 | `Windows.old`、`$WINDOWS.~BT/WS`（多为数 GB~数十 GB） | ❌ 高风险 |
| 休眠文件 | `powercfg -h off` 删除 `hiberfil.sys` | ❌ 中等风险 |
| 系统还原点 | `vssadmin delete shadows` | ❌ 高风险 |
| 浏览器缓存 | 自动发现全部 Chromium 系（Chrome/Edge/360/QQ/Brave/…）与 Firefox 系 Profile | 可选 |
| 开发工具缓存 | npm/pip/pnpm/yarn/NuGet/Gradle/Maven/Go/Cargo/Flutter/HuggingFace 等 30+ 项 | 可选 |
| 常用软件缓存 | Steam/Adobe/Office/Teams/微信/QQ/钉钉/网易云/NVIDIA 等 50+ 路径 | 可选 |
| **Program Files 归属识别** | 注册表 + 规则库 + PE 版本信息 + AI 四重判定，区分「已安装 / 组件 / 残留 / 未知」 | ❌ 手动勾选 |
| **AppData 目录分析** | 逐目录说明作用（缓存/日志/配置/用户数据），挑出可放心清理项 | ❌ 手动勾选 |
| 空目录 / 失效快捷方式 | 安全项 | ❌ 手动勾选 |
| 大文件 / 重复文件 | 需人工判断，默认不扫描（开启后较慢） | ❌ |

> **「默认」这一列的真实含义**：v1.1.3 起，扫描完成后**所有项目一律不勾选**（含 AI 识别结果），避免误删。
> 表里的「可选 / 手动勾选」表示该项目**允许**被勾选，具体勾选由你决定；高风险、危险与命令类项目还需二次确认。
> 想批量选中，可用工具栏「全选」下拉：仅安全 / 安全+低风险 / 安全+低风险+中等 三档。

界面上还有这些能力：**空间占用构成条**（按分类着色的堆叠条 + 可点击图例）、**清理记录**（历史、备份清单直达）、
**高风险项逐项二次确认**、**右键 AI 识别**、**排除列表**、**深色/浅色主题**、**演练模式**。

---

## 三、AI 识别怎么用

**没有 API Key 也能完整使用**：内置知识库包含数百条软件映射（`Program Files` 目录名 → 软件）、
一百余条 AppData 目录规则、几十条通用缓存目录名规则，配合注册表安装记录与 PE 文件版本信息，
绝大多数目录都能离线判定。AI 只用于处理规则库拿不到的部分。

开启方式：界面【⚙ 设置 → AI 识别】，或手动编辑 `%LOCALAPPDATA%\DiskCC\config.json`：

```jsonc
{
  "ai_enabled": true,
  "ai_base_url": "https://api.deepseek.com/v1",
  "ai_api_key": "sk-xxxx",
  "ai_model": "deepseek-chat"
}
```

* 兼容任意 **OpenAI 格式**接口，设置页内置 DeepSeek、通义千问（兼容模式）、智谱 GLM、Kimi、OpenAI、本地 Ollama 六个预设。
* 点【测试连接】可验证配置（后台线程执行，不卡界面；https 严格校验证书）。
* **上传内容只有元信息**：目录名、大小、文件数、子目录名、可执行文件名、PE 里的 ProductName/CompanyName，
  **不包含任何文件内容、不含你的文档与个人信息**。
* 结果本地缓存（默认 30 天，路径 `%LOCALAPPDATA%\DiskCC\ai_cache.json`），同样的目录不会重复花钱。
* 默认只对规则库无法识别的目录调用 AI（`ai_only_unknown`），省钱提速。
* 规则库识别不出的目录，可右键选「🤖 AI 识别此目录」主动触发（扫描中、清理中、AI 未启用时该项置灰）。

---

## 四、Program Files 归属识别逻辑

按可信度从高到低依次尝试，命中即停止：

1. **注册表**：读取 `Uninstall` 项的 `InstallLocation / DisplayName / Publisher`，与目录做精确、父子关系匹配 → 判定「已安装」，风险=危险（不删，可右键启动卸载程序）。
2. **内置规则库**：数百条「目录名 → 软件名」映射（含版本后缀与前缀模糊匹配），例如 `7-Zip → 7-Zip`、`Adobe Photoshop 2024 → Adobe Photoshop`、`WeChat → 微信`。
3. **PE 文件版本信息**：无第三方依赖地解析目录内 `.exe/.dll` 的 `VS_VERSION_INFO`，取 `ProductName / CompanyName / FileDescription`（纯 Python 实现，`diskcc/utils/pever.py`）。
4. **启发式**：有无可执行文件、子目录数量、最后修改时间 → 区分「厂商容器目录（如 Adobe）」与「卸载残留」。
5. **AI 兜底**：批量提交未识别目录，返回 `归属软件 / 作用 / 已安装·残留·组件 / 是否可删 / 风险 / 置信度`，置信度 ≥0.7 且判定可删才会自动勾选。

结论在表格「归属软件」「来源」「说明」三列直接可见：来源为 `规则库 / 注册表 / 文件信息 / AI`。

---

## 五、AppData 分析逻辑

* **已知路径表**：Chrome/Edge 各级缓存、Explorer 缩略图、WER、pip/npm 等直接命中为「可放心清理」。
* **规则库**：`WeChat → 微信（聊天图片、文件缓存与配置）`、`SomeGame → 游戏` 等，并给出是否可整目录清理。
* **通用缓存目录名**：任意软件目录下出现 `Cache / Code Cache / GPUCache / ShaderCache / logs / Crashpad / temp / Service Worker / blob_storage / Session Storage / …` 一律判定为可放心清理的缓存，且**不再下潜**（避免重复统计）。
* **是否仍在用**：结合注册表安装记录判断目录是否为「软件卸载后的残留」；只有同时满足「未安装」+「超过设定天数（默认 90 天）未更新」才标为残留。
* **AI**：对规则库未收录且体积较大的目录，批量询问「存放什么数据 / 缓存还是配置 / 能否删除 / 风险」。
* **大体积日志文件**：AppData 根下 ≥20MB 的 `.log/.dmp/.tmp/.bak/.etl` 等文件会被单独列出。

**判定为可放心清理的**（删除后软件会自动重建，不影响账号、配置与个人数据）：各类 `Cache*`、`Code Cache`、`GPUCache`、
着色器缓存、`logs`、`Crashpad/CrashDumps`、`temp`、浏览器各类缓存、包管理器缓存、Adobe 媒体缓存、Teams 媒体缓存、
Steam 着色器缓存、AppData 根下的大日志文件等。

**永远不会自动勾选**：含配置/登录态/聊天记录/笔记/工程数据的目录（风险=中等），以及 Program Files 中判定为
「已安装」的程序目录（风险=危险，请走卸载程序）。

---

## 六、安全机制

| 机制 | 说明 |
|---|---|
| 扫描后零勾选 | 扫描完成默认一项都不勾选，含 AI 识别结果，必须由你手动勾选 |
| 风险分级 | 风险等级为「安全/低风险/中等/高风险/危险」，高风险与危险默认不勾选 |
| 高风险二次确认 | 勾选高风险/危险项时逐项列出名称+大小+路径，必须勾选「我已逐项确认」才能继续 |
| 系统路径黑名单 | `System32 / SysWOW64 / WinSxS / Boot / Fonts / WindowsApps` 等一律禁止删除 |
| Windows 子目录保护 | `C:\Windows` 的直接子文件夹默认不列为清理项（仅 `Temp`/`SoftwareDistribution`/`Prefetch`/`Logs`/`Minidump` 等白名单可清理） |
| 允许根校验 | 清理路径必须落在系统盘、用户目录、AppData、ProgramData、Program Files 等允许范围内 |
| 统一校验入口 | 批量清理与右键「立即删除此项」**走同一套 `Cleaner.check_item` 校验**，不存在绕过通道 |
| 回收站优先 | 默认走回收站（可还原）；右键「立即删除此项」会明确提示不可恢复 |
| 备份清单 + 清理记录 | 每次清理前把完整清单写到 `%LOCALAPPDATA%\DiskCC\clean_logs\`，并落一条清理记录（时间/成功/失败/释放/方式/清单路径） |
| 演练模式 | 设置里可开启「只报告不删除」，演练时列表一项都不移除 |
| 排除列表 | 右键某行 → 加入排除列表，后续扫描跳过该路径；设置页可清空 / 去重排序 |
| 占用保护 | 跳过 24 小时内修改过的临时文件与被进程占用的文件 |
| 危险项拦截 | 风险=危险的项目（已安装程序）直接拒绝删除，并提示改用卸载程序 |
| 清理快照 | 清理启动瞬间把项目的路径、风险、命令、模式定格为快照，执行期不受 AI 改写影响 |
| 并发互斥 | 扫描 × 清理 × AI 识别三者互斥，同一项目不会被并发改写 |

---

## 七、目录结构与数据文件

```
DiskCC/
├── main.py                     入口（GUI / --cli / --selftest / --admin / --version）
├── requirements.txt            运行依赖
├── requirements-build.txt      打包依赖
├── build_exe.bat               一键打包成单文件 exe
├── build_exe_docker.sh         在 Docker 中构建（走 spec）
├── build_exe_wine.sh           在 Wine 中构建（走 spec）
├── Dockerfile.wine             Wine 构建镜像
├── DiskCC.spec                 打包配置（Qt 组件裁剪 / 版本资源 / onedir 开关）
├── file_version.txt            exe 版本资源（公司名、产品名、版本号）
├── LICENSE
├── assets/                     diskcc.ico（应用图标）+ logo.png
├── README.md
├── tests/
│   ├── full_test.py            全量回归（181 项断言）
│   ├── selftest.py             内置自测（构造模拟磁盘树）
│   └── bench.py                性能基准
├── .github/workflows/build.yml CI：回归 → 双形态构建 → 冒烟 → 发布 Release
└── diskcc/
    ├── __init__.py             版本号（__version__ = "1.3.3"）
    ├── models.py               扫描项 / 分类 / 风险等级 / 清理记录 / 大小格式化
    ├── config.py               配置持久化与默认值
    ├── history.py              清理历史（clean_history.json，最多 100 条）
    ├── cleaner.py              清理执行器（安全校验→备份→删除/命令→审计）
    ├── resources.py            资源路径定位（兼容 exe 内 _MEIPASS）
    ├── ai/
    │   ├── client.py           OpenAI 兼容客户端（标准库 urllib，无依赖）
    │   ├── prompts.py          识别/分析提示词与 JSON 输出约定
    │   └── analyzer.py         批量调用 + 本地缓存 + 离线降级
    ├── knowledge/
    │   ├── software_map.py     Program Files 目录名 → 软件（数百条）
    │   └── appdata_rules.py    AppData 目录作用 + 通用缓存目录名
    ├── scanner/
    │   ├── base.py             扫描上下文 / 基类（去重、过滤、日志）
    │   ├── junk.py             系统垃圾与临时文件
    │   ├── winupdate.py        Windows 更新、WinSxS、休眠、还原点、旧系统残留
    │   ├── programfiles.py     Program Files 归属识别
    │   ├── appdata.py          AppData 作用分析
    │   ├── browsers.py         浏览器缓存（自动发现 Chromium/Firefox 系）
    │   ├── devtools.py         开发工具缓存
    │   ├── apps_cache.py       常用软件缓存
    │   ├── extra.py            空目录 / 大文件 / 重复文件 / 失效快捷方式
    │   └── manager.py          扫描调度（并行、取消、进度加权）
    ├── utils/
    │   ├── fs.py               跨平台文件工具（体积统计+缓存、安全删除、路径校验）
    │   ├── win.py              UAC / 回收站 / 磁盘信息 / 注册表 / 进程
    │   └── pever.py            轻量 PE 版本资源解析（无依赖）
    └── ui/
        ├── main_window.py      主界面
        ├── workers.py          扫描/清理后台线程（进度节流）
        ├── settings_dialog.py  设置（AI 识别 / 扫描选项 / 清理策略 / 界面）
        ├── history_dialog.py   清理记录
        ├── charts.py           空间占用构成条（自绘，不依赖 QtCharts）
        ├── disclaimer.py       启动免责声明弹窗
        └── style.py            深色/浅色主题
```

运行时数据都在 `%LOCALAPPDATA%\DiskCC\`：

| 文件 / 目录 | 内容 |
|---|---|
| `config.json` | 配置（AI、扫描选项、清理策略、界面） |
| `ai_cache.json` | AI 识别结果缓存 |
| `clean_history.json` | 清理记录（最多 100 条） |
| `clean_logs\` | 每次清理的完整备份清单 |

---

## 八、常见问题

**Q：为什么默认一项都没勾选？**
A：v1.1.3 起为防止误删，扫描完成后所有项目一律不勾选（含 AI 识别结果）。请按「说明」列的作用与风险自行甄别，
或用「全选」下拉按安全等级批量勾选。

**Q：为什么有些项目删不掉？**
A：多为权限不足或文件被占用。请以管理员身份运行；浏览器、微信等软件退出后重试；`Windows.old` 若失败请用
【设置 → 系统 → 存储 → 临时文件 → 以前的 Windows 安装】清理。

**Q：清理会不会影响已安装的软件？**
A：默认勾选的缓存类项目删除后软件会自动重建。Program Files 中判定为「已安装」的目录风险等级为「危险」，
程序会拒绝删除并建议你走卸载程序。

**Q：AI 会不会把我的文件内容传出去？**
A：不会。只发送目录名、大小、文件数、子目录名、可执行文件名等元信息，不发送文件内容、文档、聊天记录或个人信息。

**Q：扫描很慢？**
A：v1.2.0 起默认开启**并行扫描**（多类目录同时扫描，机械硬盘收益最大）；可在【设置 → 扫描选项】关闭。
首次扫描需遍历大量目录（尤其 AppData 与 Program Files），通常几分钟；也可关闭「大文件」「重复文件」扫描、
调大「忽略小于 N MB」阈值进一步提速。重复文件扫描另有单文件上限（默认 512MB）与哈希总预算（默认 2GB）保护。

**Q：删除几个 GB 的大文件时窗口显示"未响应"？**
A：v1.2.0 已修复。原因是日志与进度条每条都同步刷新控件、表格逐行重排重绘，主线程被高频 UI 操作占满。
现在日志/进度按 120ms 合并刷新、进度信号节流、表格批量重建；删除大体积文件前会在日志明确提示"体积较大，
可能耗时较久，界面仍可操作"。

**Q：exe 被 360 / 火绒报毒或拦截？**
A：这是 PyInstaller 程序的常见**启发式误报**（"未知程序 / 未签名"），不是真病毒。已做的缓解：
① 禁用 UPX 压缩（最强误报特征）；② 写入完整的 exe 版本资源；③ 附带应用图标；④ 提供 onedir 目录模式
（不解包临时文件，被拦截概率明显更低）；⑤ 发布附带 `DiskCC.exe.sha256.txt`，可用
`certutil -hashfile DiskCC.exe SHA256` 核对。
若仍被拦截，把该文件加入**白名单 / 信任区**即可。想彻底解决需要代码签名证书（个人开发者可酌情购买或自签名）。

**Q：单文件 exe 双击报 `Failed to load Python DLL ... LoadLibrary: 错误 998`？**
A：这是 v1.3.3 之前 CI 构建的单文件 exe 在部分机器上的问题（杀软实时拦截 `%TEMP%\_MEIxxxx` 下的新版无签名 DLL）。
请改用 Release 里的 **`DiskCC-vX.Y.Z-win64.zip`（onedir 目录模式）**，它不写临时目录，从根上绕开该故障。

**Q：清理后想还原？**
A：默认走回收站，去回收站还原即可；命令类项目（DISM、关闭休眠、删除还原点）属于系统配置变更，不可还原。
每次清理的完整清单在 `%LOCALAPPDATA%\DiskCC\clean_logs\`。

---

## 九、免责声明

本工具提供的是「识别 + 建议 + 执行」能力，最终是否删除由你决定。命令类项目（DISM ResetBase、关闭休眠、
删除系统还原点、删除 Windows.old）会改变系统配置且不可轻易回滚，请确认系统状态正常后再执行。
清理前建议备份重要数据。

---

## 十、版本改动记录

> 按版本倒序，只记「对用户有感知」的改动；逐行细节见 git log。
> 全量回归 `python tests/full_test.py` 当前 **181 项断言全部通过**（A–H 为逻辑段，I–M 含界面/性能段）。

### v1.3.3（当前版本）

**主题：修复 CI 构建的 exe 无法启动，并让 CI 真正验证产物。**

| 改动 | 说明 |
|---|---|
| **新增 onedir 目录模式** | Release 附 `DiskCC-vX.Y.Z-win64.zip`（**推荐下载**）：不写临时目录、直接从程序目录加载，规避单文件解包被杀软拦截（错误 998） |
| 单文件 exe 保留 | 供偏好单文件的场景；个别机器仍被拦截时请改用 onedir 包 |
| CI 回归测试可用 CLI 模拟盘 | `main.py --fake-disk` 让 CI 扫模拟盘，消除"扫真实盘偶发超时"导致的构建失败 |
| CI 冒烟测试 | 构建后运行 `--version` 校验 bootloader/Python 初始化/退出码；onedir 为发布门槛，单文件尽力而为 |
| 打包配置修正 | `strip=False`（Windows 上 strip 会损坏 DLL 导致加载器弹窗挂死）、`uac_admin=False`（改 asInvoker，程序内按需提权，避免非交互环境提权阻塞） |
| 入口健壮性 | 窗口化冻结 exe 下保证 `sys.stdout/stderr` 存在（修复 `--version` 崩溃）；入口异常落盘便于排障 |
| 其它 | 修复双击文件名/右键「打开目录」偶发错位、文件大小按字符串排序（`17.82MB < 18.15MB < 178.78MB` 错序）等问题 |

### v1.3.2

**主题：扫描速度 / 运行稳定性 / 程序体积，不改变功能与判定结果。**

| 指标 | v1.3.1 | v1.3.2 | 变化 |
|---|---|---|---|
| 全扫描（串行） | 346 ms | **257 ms** | **-26%** |
| 全扫描（并行，默认） | 695 ms | **535 ms** | **-23%** |
| `iter_files`（文件筛遍历） | 28.4 ms | **4.7 ms** | **-83%** |
| 单文件 exe 体积 | 69.9 MB | **68.5 MB** | **-1.38 MB** |
| 单文件 exe 体积（`DISKCC_SLIM=1`） | 69.9 MB | **59.1 MB** | **-10.8 MB（-15.5%）** |

- **提速**：目录体积缓存顺带写入子树；并发单飞（后到线程复用首个结果）；用 `os.scandir` 取代逐个 `stat`；`iter_files` 预编译匹配；PE 版本先读 64KB 头部校验再决定是否读满。
- **稳定性**：扫描/清理进度信号节流（最快 80ms 且变化 ≥1% 才发射），消除"扫描时界面卡住"。
- **体积**：未使用的 `assets/logo.png` 不再打进 exe；新增可选瘦身开关 `DISKCC_SLIM=1`（Linux 侧已验证，Windows 侧仍默认关闭）。
- **工具**：新增 `tests/bench.py` 可复现基准；新增 M 段 17 项断言。

### v1.3.0

**主题：全面回归测试，修复 12 处缺陷（含 1 处高危安全缺口）。**

- **高危**：右键「立即删除此项」原为直删，绕过 `Cleaner` 全部校验；现与批量清理走同一套校验。
- **扫描控制**：取消响应对齐（≤0.5s，原需等最慢扫描器跑完）；进度条不再倒退；单个扫描器构造失败不再拖垮整轮。
- **清理一致性**：按 `item_id` 精确剔除已清理项（原按 path 会误删同路径未勾选项）；演练模式不再把项目从列表移除；重新扫描不混入上轮日志。
- **界面并发**：忙碌时禁用设置按钮；补上「扫描 × AI 识别」互斥（v1.2.0 漏改）；关闭窗口前断开后台信号，避免崩溃；`_item_by_id` 改为 O(1) 索引查找。
- **统计**：`ScanResult.finished_at` 正确写入，耗时统计准确。

### v1.2.0

**主题：性能、稳定性与分发可信度。**

- **并行扫描**：各扫描器由 `ThreadPoolExecutor` 并行执行，进度按完成度加权；实测约 1.7 倍速，且**并行与串行结果完全一致**，可在设置关闭。
- **修复 AI 分析步骤从未执行**：原在扫描前判断候选队列（必为空），AI 分析是死代码；改为扫描后执行。
- **修复偶发"未响应"**：日志/进度 120ms 合并刷新、表格与分类树批量重建、清理与 AI 互斥、`CleanTask` 不可变快照、大文件删除前提示。
- **修复「某分类只剩一个文件时 AI 识别导致整个分类消失」**：保留旧分类空节点并置灰，项目始终可见。
- **降低误报**：禁用 UPX、写入 exe 版本资源、带图标 + 无控制台、提供 SHA256 校验值。
- **exe 瘦身**：新增 `DiskCC.spec`，裁掉 63 个未使用的 Qt 模块（PySide6 依赖库 499MB → 可裁 335MB，67%）。
- 扫描器线程安全加固（`installed`/`processes`/`error`/去重/AI 队列全部加锁）。

### v1.1.3

- **软件 Logo**：标题栏 / 任务栏 / exe 文件图标（`assets/diskcc.ico`）。
- **扫描后默认不勾选任何项目**：含 AI 识别结果，防误删。
- **启动免责声明**：首次启动弹窗提醒查看待清理内容、做好备份，勾选"不再提示"后不再显示。

### v1.1.2

结合 CCleaner / Dism++ / BleachBit / Wise Disk Cleaner / TreeSize 等工具的优缺点改进：

| # | 改动 | 解决的痛点 |
|---|---|---|
| 1 | **空间占用构成条**：顶部按分类着色的堆叠条 + 可点击图例 | 只给一个"可释放 XX MB"，不知道 C 盘被什么占满 |
| 2 | **清理记录**：每条记录含时间/成功/失败/释放/方式/备份清单路径 | "清理前务必备份"但清单散落各处、用户找不到 |
| 3 | **高风险项二次确认**：逐项列出名称+大小+路径，需勾选确认 | 被投诉最多的就是误删 |
| 4 | **扫描提速**：目录体积带失效校验的缓存；进度条显示已耗时 | 深度扫描慢且没有时间预期 |
| 5 | **重复文件性能闸**：单文件上限 512MB、哈希总预算 2GB | 对几个 GB 的视频做全文 SHA256 会拖十几分钟 |
| 6 | **「全选」下拉改 3 档**：仅安全 / +低风险 / +中等 | 文案与实际行为不一致会让人误以为只删安全项 |
| 7 | **表格悬停提示**：名称/说明/路径列悬停显示完整文本 | 说明被截断后无法判断"为什么推荐删除" |
| 8 | **排除列表管理**：设置→清理策略新增「清空 / 去重并排序」 | 只能加不能管 |
| 9 | 其它：无结果时给排查建议；关窗时清理/AI 线程一并停止 | 细节体验 |

另修：主表格隔行发白、设置对话框对比不足（深色主题）。

### v1.1.1

- 修复首次扫描阶段右上角未显示 AI 调用次数与缓存命中次数。
- 右键 AI 识别后就地刷新该行，不再跳回"全部"；分类内清理/排除后停留在当前分类。
- 「全选▼」文案改为「全选」；AI 识别成功后会完整替换「来源/说明/风险/分类/归属软件」。
- 不支持 AI 识别的项目改为菜单置灰，不再弹窗。

### v1.1.0

- **AI 手动识别**：右键「🤖 AI 识别此目录」主动触发。
- **进度分步显示**：`[步骤/总步骤]` 前缀，扫描与 AI 分析拆分。
- **Windows 子目录保护**：`C:\Windows` 下直接子文件夹默认不列为清理项（白名单除外）。
- **「全选」下拉**：一键选安全项 / 安全+低风险项。
- **单文件打包**：改 `--onefile`，可直接发给他人。
- 修：双击文件名 / 右键「打开所在目录」错位；按大小排序时按字符串比较导致错序。

### v1.0.x

首个可用版本：系统垃圾、浏览器缓存、开发工具缓存、常用软件缓存、Program Files 归属识别、AppData 分析、空目录 / 大文件 / 重复文件 / 失效快捷方式扫描 + 安全校验与清理。
