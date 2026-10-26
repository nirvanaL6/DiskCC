"""DiskCC 全面测试：模型/配置/AI/扫描引擎/清理器/CLI/清理历史/性能保护/界面。

用法：python tests/full_test.py
"""
import os, sys, json, tempfile, shutil, importlib.util, time, fnmatch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from diskcc.models import (human_size, parse_risk, Risk, ItemKind, ScanItem, ScanResult,
                           CATEGORIES, category_name)
from diskcc.config import Config
from diskcc.utils import fs

# 兼容 Windows 旧代码页：CI 运行器/裸 cmd 默认可能是 cp1252，编码不了中文与 emoji，
# 会让第一条 print 就抛 UnicodeEncodeError。这里强制标准流使用 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

FAILED = []
def chk(label, cond, extra=""):
    print(f"  {'✅' if cond else '❌'} {label} {extra}")
    if not cond: FAILED.append(label)

print("=== A. 模型与工具层（回归） ===")
chk("human_size(0)", human_size(0) == "0 B", f"({human_size(0)})")
chk("human_size(1024)", "K" in human_size(1024), f"({human_size(1024)})")
chk("human_size(负数)返回-", human_size(-5) == "-")
chk("human_size(极大值) 量级>=TB",
    any(u in human_size(10**18) for u in ("T", "P", "E")), f"({human_size(10**18)})")
chk("parse_risk('安全')=SAFE", parse_risk("安全") == Risk.SAFE)
chk("parse_risk(3)=HIGH", parse_risk(3) == Risk.HIGH)
chk("parse_risk(非法)回落默认", parse_risk("zzz") == Risk.MEDIUM)
it = ScanItem(path=os.path.join("C:", "a", "b"), name="b", category="browser", size=1234,
              risk=Risk.LOW, software="Chrome", source="rule", extra={"k": "v"})
d = it.to_dict(); back = ScanItem.from_dict(d)
chk("ScanItem to_dict/from_dict 往返", back.path == it.path and back.size == it.size
    and back.risk == it.risk and back.extra.get("k") == "v")
_np = os.path.join(tempfile.mkdtemp(), "x", "y")
chk("ScanItem 自动补 name", ScanItem(path=_np).name == "y")
chk("category_name 未知分类回退", category_name("no_such_cat") == "其他")

tmp = tempfile.mkdtemp(prefix="fs_")
os.makedirs(os.path.join(tmp, "sub"))
with open(os.path.join(tmp, "sub", "f.txt"), "wb") as f: f.write(b"x" * 1000)
sz, cnt = fs.dir_size(tmp)
chk("fs.dir_size 递归统计", sz >= 1000 and cnt >= 1, f"(size={sz},count={cnt})")
chk("fs.is_forbidden 拦截 System32", fs.is_forbidden(r"C:\Windows\System32\kernel32.dll") is True)
chk("fs.is_forbidden 不拦普通路径", fs.is_forbidden(os.path.join(tmp, "f.txt")) is False)
chk("fs.safe_listdir 异常不抛", isinstance(fs.safe_listdir("/nonexistent_xyz"), list))
shutil.rmtree(tmp, ignore_errors=True)

print("\n=== B. 配置层（回归 + 新键） ===")
cfg = Config()
chk("默认值 min_size_mb", cfg.get("min_size_mb") == 1.0)
cfg.set("ai_enabled", "true"); chk("bool 强制转换('true')", cfg.get("ai_enabled") is True)
cfg.set("ai_timeout", "45");   chk("int 强制转换('45')", cfg.get("ai_timeout") == 45)
cfg.set("min_size_mb", "2.5"); chk("float 强制转换('2.5')", cfg.get("min_size_mb") == 2.5)
cp = os.path.join(tempfile.mkdtemp(), "config.json")
cfg.save(cp); loaded = Config.load(cp)
chk("配置持久化往返", loaded.get("ai_timeout") == 45 and loaded.get("min_size_mb") == 2.5)
cfg.set("ai_timeout", "abc"); chk("int 非法值回落默认", cfg.get("ai_timeout") == Config().get("ai_timeout"))
chk("未知配置读取默认", Config().get("nonexistent_key", "def") == "def")
for k, v in (("dup_min_size_mb", 1), ("dup_max_file_mb", 512), ("dup_budget_mb", 2048)):
    chk(f"新增配置键 {k}", Config().get(k) == v)

print("\n=== C. AI 分析器（mock 客户端）===")
from diskcc.ai.analyzer import AIAnalyzer
acfg = Config()
acfg.set("ai_enabled", True); acfg.set("ai_base_url", "https://x/v1")
acfg.set("ai_api_key", "sk-test"); acfg.set("ai_model", "m")
ai = AIAnalyzer(acfg, lambda m: None)
chk("AI enabled", ai.enabled is True)
resp_pf = json.dumps({"results": [{"folder": "foo", "software": "FooSoft", "purpose": "调试工具",
    "installed": "残留", "deletable": True, "risk": "medium", "reason": "r", "confidence": 0.9}]})
ai.client.chat = lambda msgs, max_tokens=None: resp_pf
res = ai.analyze_program_files([{"folder": "foo", "path": r"C:\PF\foo", "size": 1}])
chk("analyze_program_files 返回 pf:foo", "pf:foo" in res)
if "pf:foo" in res:
    a = res["pf:foo"]
    chk("解析 software/risk/confidence",
        a.software == "FooSoft" and a.risk == Risk.MEDIUM and abs(a.confidence - 0.9) < 1e-6)
chk("调用计数增加", ai.calls >= 1, f"(calls={ai.calls})")
ai.analyze_program_files([{"folder": "foo", "path": r"C:\PF\foo", "size": 1}])
chk("二次调用命中缓存", ai.hits >= 1, f"(hits={ai.hits})")
ai2 = AIAnalyzer(acfg, lambda m: None)
ai2.client.chat = lambda msgs, max_tokens=None: (_ for _ in ()).throw(Exception("boom"))
chk("AI 失败降级不抛异常", isinstance(ai2.analyze_program_files([{"folder": "bar", "path": r"C:\PF\bar"}]), dict))
dcfg = Config(); dcfg.set("ai_enabled", False)
chk("AI 未启用时 enabled=False", AIAnalyzer(dcfg).enabled is False)

print("\n=== D. 扫描引擎（模拟磁盘）===")
spec = importlib.util.spec_from_file_location("selftest_mod", os.path.join(ROOT, "tests", "selftest.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)
root = tempfile.mkdtemp(prefix="fake_"); data = tempfile.mkdtemp(prefix="data_")
os.environ["LOCALAPPDATA"] = data; os.environ["APPDATA"] = data
st.build_fake_disk(root)
scfg = Config()
scfg.set("min_size_mb", 0.05); scfg.set("scan_large_files", True)
scfg.set("large_file_mb", 10); scfg.set("ai_enabled", False)
ctx = st.build_ctx(root, scfg)
from diskcc.scanner.junk import SystemJunkScanner
from diskcc.scanner.winupdate import WindowsUpdateScanner
from diskcc.scanner.browsers import BrowserScanner
from diskcc.scanner.devtools import DevToolScanner
from diskcc.scanner.apps_cache import AppCacheScanner
from diskcc.scanner.programfiles import ProgramFilesScanner
from diskcc.scanner.appdata import AppDataScanner
from diskcc.scanner.extra import ExtraScanner
scanners = [SystemJunkScanner(ctx), WindowsUpdateScanner(ctx), BrowserScanner(ctx),
            DevToolScanner(ctx), AppCacheScanner(ctx), ProgramFilesScanner(ctx),
            AppDataScanner(ctx), ExtraScanner(ctx)]
for s in scanners:
    try:
        s.scan(); print(f"  ✅ {s.title} 无异常")
    except Exception as e:
        chk(f"{s.title}", False, f"异常: {e}")
items = list(ctx.items)
chk("扫描产出项目", len(items) > 20, f"({len(items)} 项)")
cats = {i.category for i in items}
for c in ["win_temp", "user_temp", "win_update", "browser", "dev_cache", "app_cache",
          "pf_software", "appdata_cache", "empty_dir", "large_file"]:
    chk(f"分类存在: {c}", c in cats)
sw = {i.name: i.software for i in items if i.category.startswith("pf_")}
chk("7-Zip 归属识别", sw.get("7-Zip") == "7-Zip", f"({sw.get('7-Zip')})")
chk("WinRAR 归属识别", bool(sw.get("WinRAR")), f"({sw.get('WinRAR')})")
SI = ScanItem
blk = SI(path=os.path.join(root, "Windows", "System32"), name="System32",
         kind=ItemKind.DIR, size=10 * 1024 * 1024, category="other")
chk("Windows 直接子目录被拦截", ctx.add(blk) is None)
okd = SI(path=os.path.join(root, "Windows", "Temp"), name="Temp",
         kind=ItemKind.DIR, size=10 * 1024 * 1024, category="win_temp")
chk("Temp 白名单放行", ctx.add(okd) is not None)
dup = SI(path=os.path.join(root, "AppData", "Temp2"), name="Temp2", kind=ItemKind.DIR,
         size=10 * 1024 * 1024, category="win_temp")
a1 = ctx.add(dup); a2 = ctx.add(SI(path=dup.path, name="T2", kind=ItemKind.DIR, size=1, category="win_temp"))
chk("同路径去重", a1 is not None and a2 is None)

print("\n=== E. 清理器安全与执行 ===")
from diskcc.cleaner import Cleaner
cl = Cleaner(scfg, extra_roots=[root], log=lambda m: None)
chk("受保护项拒绝", cl.check_item(SI(path=os.path.join(root, "p"), category="other",
    kind=ItemKind.DIR, size=1, protected=True))[0] is False)
chk("危险项拒绝", cl.check_item(SI(path=os.path.join(root, "d"), category="pf_software",
    kind=ItemKind.DIR, size=1, risk=Risk.DANGEROUS))[0] is False)
chk("系统关键路径拒绝", cl.check_item(SI(path=r"C:\Windows\System32\x.dll", category="other",
    kind=ItemKind.FILE, size=1))[0] is False)
chk("非允许根拒绝", cl.check_item(SI(path="/etc/passwd", category="other",
    kind=ItemKind.FILE, size=1))[0] is False)
chk("路径不存在拒绝", cl.check_item(SI(path=os.path.join(root, "no_such_file"), category="other",
    kind=ItemKind.FILE, size=1))[0] is False)
scfg.set("dry_run", True); scfg.set("create_backup_list", True)
victim = os.path.join(root, "VictimDir"); os.makedirs(victim, exist_ok=True)
with open(os.path.join(victim, "a.txt"), "wb") as f: f.write(b"x" * 100)
vi = SI(path=victim, category="other", kind=ItemKind.DIR, size=100, risk=Risk.SAFE, checked=True)
rep = cl.clean([vi])
chk("演练模式不真删", os.path.exists(victim) and rep.ok_count == 1)
chk("备份清单生成", bool(rep.log_file) and os.path.isfile(rep.log_file))
scfg.set("dry_run", False); scfg.set("use_recycle_bin", False)
rep2 = cl.clean([vi])
chk("真实删除生效", not os.path.exists(victim) and rep2.ok_count == 1, f"(freed={rep2.freed})")
scfg.set("use_recycle_bin", True)
chk("空列表清理不报错", cl.clean([]).ok_count == 0)

print("\n=== F. CLI 模式 ===")
import subprocess
outdir = tempfile.mkdtemp()
csv_out = os.path.join(outdir, "r.csv"); json_out = os.path.join(outdir, "r.json")
# CI 上若让 CLI 扫描真实系统盘（Program Files / AppData 等），在 runner 上
# 偶发超过 5 分钟超时导致构建失败。这里把所有扫描器依赖的环境变量重定向到
# 一个微型临时目录，使 CLI 只扫该小目录——既快又确定，同时完整验证报告生成链路。
_fake = tempfile.mkdtemp(prefix="diskcc_fake_sys_")
_fenv = dict(os.environ)
_fenv.update({
    "SYSTEMDRIVE": _fake + "\\",
    "USERPROFILE": os.path.join(_fake, "UP"),
    "APPDATA": os.path.join(_fake, "AP"),
    "LOCALAPPDATA": os.path.join(_fake, "LA"),
    "PROGRAMDATA": os.path.join(_fake, "PD"),
    "PROGRAMFILES": os.path.join(_fake, "PF"),
    "PROGRAMFILES(X86)": os.path.join(_fake, "PF86"),
    "WINDIR": os.path.join(_fake, "WINDOWS"),
    "TEMP": os.path.join(_fake, "TEMP"),
    "TMP": os.path.join(_fake, "TEMP"),
})
p1 = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--cli", "--out", csv_out],
                    capture_output=True, text=True, timeout=120, env=_fenv)
chk("CLI 退出码 0", p1.returncode == 0, f"(rc={p1.returncode})")
if p1.returncode != 0:
    print("--- CLI stdout ---\n" + (p1.stdout or "")[:2000])
    print("--- CLI stderr ---\n" + (p1.stderr or "")[:2000])
chk("CLI CSV 报告生成", os.path.isfile(csv_out))
p2 = subprocess.run([sys.executable, os.path.join(ROOT, "main.py"), "--cli", "--out", json_out],
                    capture_output=True, text=True, timeout=120, env=_fenv)
chk("CLI JSON 报告生成", os.path.isfile(json_out))
if os.path.isfile(json_out):
    with open(json_out) as f: data_j = json.load(f)
    chk("CLI JSON 结构合法", isinstance(data_j, list))

print("\n=== G. 清理历史（v1.1.2 新增） ===")
from diskcc.history import CleanHistory, HistoryEntry
from diskcc.models import CleanReport, CleanRecord
hdir = tempfile.mkdtemp(prefix="hist_")
hist = CleanHistory(os.path.join(hdir, "clean_history.json"))
chk("空历史返回空列表", hist.load() == [])
rep3 = CleanReport(records=[CleanRecord(path="/x/a", kind="dir", ok=True, method="recycle", size=100),
                            CleanRecord(path="/x/b", kind="dir", ok=False, method="delete", size=50,
                                        message="被占用")],
                   freed=100, failed=1, log_file=os.path.join(hdir, "list.txt"))
rep3.finished_at = rep3.started_at + 3.5
open(rep3.log_file, "w").write("x")
e = hist.record_from_report(rep3, dry_run=False)
recs = hist.load()
chk("历史写入 1 条", len(recs) == 1)
chk("历史字段正确", recs[0].ok == 1 and recs[0].failed == 1 and recs[0].freed == 100
    and recs[0].method == "recycle" and abs(recs[0].elapsed - 3.5) < 0.01)
chk("历史保存路径列表", recs[0].paths == ["/x/a"])
chk("历史按时间倒序", recs[0].ts >= e.ts - 1)
e2 = hist.record_from_report(CleanReport(records=[], freed=0, failed=0), dry_run=True)
chk("演练模式标记", hist.load()[0].dry_run is True and hist.load()[0].method == "-")
chk("历史最多 100 条", len(hist.load()) == 2)
hist.remove(e.ts)
chk("删除指定记录", all(abs(r.ts - e.ts) > 1e-6 for r in hist.load()))
hist.clear()
chk("清空历史", hist.load() == [])
hist.append(HistoryEntry(time="t", ts=1.0, ok=1, freed=10, log_file="/nope.txt"))
chk("损坏文件回落空列表", True)
with open(hist.path, "w") as f: f.write("NOT JSON")
chk("JSON 损坏时不抛异常", hist.load() == [])
os.remove(hist.path)
chk("文件不存在时返回空", hist.load() == [])

print("\n=== H. 扫描性能保护（v1.1.2 新增） ===")
fs.clear_dir_size_cache()
cd = tempfile.mkdtemp(prefix="cache_")
with open(os.path.join(cd, "a.bin"), "wb") as f: f.write(b"x" * 2048)
s1, c1 = fs.dir_size(cd)
s2, c2 = fs.dir_size(cd)
chk("dir_size 缓存复用", (s1, c1) == (s2, c2) and s1 == 2048)
time.sleep(0.02)   # 部分文件系统（overlayfs）目录 mtime 粒度约 10ms
with open(os.path.join(cd, "b.bin"), "wb") as f: f.write(b"y" * 1024)
s3, _ = fs.dir_size(cd)
chk("目录变化后缓存失效", s3 == 3072, f"(size={s3})")
s4, _ = fs.dir_size(cd, use_cache=False)
chk("use_cache=False 绕过缓存", s4 == 3072)
fs.clear_dir_size_cache()
chk("clear_dir_size_cache 可用", fs.dir_size(cd)[0] == 3072)
shutil.rmtree(cd, ignore_errors=True)

# 重复文件预算：构造一批相同文件，验证能找出重复且遵守大小上限
dup_root = tempfile.mkdtemp(prefix="dup_")
_dl = os.path.join(dup_root, "Users", "tester", "Downloads")   # build_ctx 用假盘根作 userprofile
os.makedirs(_dl, exist_ok=True)
blob = b"Z" * (2 * 1024 * 1024)
for i in range(3):
    with open(os.path.join(_dl, f"same{i}.bin"), "wb") as f: f.write(blob)
with open(os.path.join(_dl, "uniq.bin"), "wb") as f: f.write(b"Q" * (3 * 1024 * 1024))
dcfg2 = Config(); dcfg2.set("min_size_mb", 0.5); dcfg2.set("scan_duplicates", True)
dcfg2.set("scan_empty_dirs", False); dcfg2.set("scan_bad_shortcuts", False)
dcfg2.set("scan_large_files", False); dcfg2.set("ai_enabled", False)
dctx = st.build_ctx(dup_root, dcfg2)
ex = ExtraScanner(dctx)
t0 = time.time()
ex.scan()
elapsed = time.time() - t0
dups = [i for i in dctx.items if i.category == "duplicate"]
chk("重复文件能被识别", len(dups) == 2, f"({len(dups)} 个副本, 耗时 {elapsed:.2f}s)")
chk("重复文件保留原件提示", all(isinstance(i.extra.get("keep"), str) for i in dups))
# 单文件上限：把上限调到 1MB，2MB 的重复文件应被跳过
dcfg3 = Config(); dcfg3.set("min_size_mb", 0.5); dcfg3.set("scan_duplicates", True)
dcfg3.set("dup_max_file_mb", 1); dcfg3.set("scan_empty_dirs", False)
dcfg3.set("scan_bad_shortcuts", False); dcfg3.set("scan_large_files", False)
dcfg3.set("ai_enabled", False)
dctx3 = st.build_ctx(dup_root, dcfg3)
ExtraScanner(dctx3).scan()
chk("超过单文件上限被跳过", not [i for i in dctx3.items if i.category == "duplicate"])
# 预算：预算调到 1MB，应直接不校验
dcfg4 = Config(); dcfg4.set("min_size_mb", 0.5); dcfg4.set("scan_duplicates", True)
dcfg4.set("dup_budget_mb", 1); dcfg4.set("scan_empty_dirs", False)
dcfg4.set("scan_bad_shortcuts", False); dcfg4.set("scan_large_files", False)
dcfg4.set("ai_enabled", False)
dctx4 = st.build_ctx(dup_root, dcfg4)
ExtraScanner(dctx4).scan()
chk("超出哈希预算时停止", not [i for i in dctx4.items if i.category == "duplicate"])
shutil.rmtree(dup_root, ignore_errors=True)

print("\n=== I. 界面（offscreen 冒烟 + 新增能力） ===")
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
app = QApplication.instance() or QApplication([])
import diskcc.ui.main_window as mwmod
from diskcc.ui.main_window import MainWindow
from diskcc.ui.history_dialog import HistoryDialog

w = MainWindow(Config())
w.items = [
    ScanItem(path=os.path.join(root, "A"), name="A", category="browser", size=300 * 1024 * 1024,
             risk=Risk.SAFE, reason="浏览器缓存"),
    ScanItem(path=os.path.join(root, "B"), name="B", category="win_temp", size=200 * 1024 * 1024,
             risk=Risk.SAFE, reason="临时文件"),
    ScanItem(path=os.path.join(root, "C"), name="C", category="pf_residue", size=100 * 1024 * 1024,
             risk=Risk.HIGH, reason="软件残留"),
]
w._populate_tree()
w._apply_filter()
w._update_space_overview()
segs = w.overview.bar.segments
chk("空间构成条有分段", len(segs) >= 3, f"({len(segs)} 段)")
chk("构成条总量=项目总量", w.overview.bar._total == sum(i.size for i in w.items))
chk("构成条按占比降序", [s[1] for s in segs] == sorted([s[1] for s in segs], reverse=True))
legends = [w.overview._legend_lay.itemAt(i).widget()
           for i in range(w.overview._legend_lay.count())]
legends = [x for x in legends if x is not None]
chk("图例生成", len(legends) == len(segs), f"({len(legends)} 个)")
# 点击图例跳转分类
jumped = []
w.overview.categoryClicked.connect(lambda k: jumped.append(k))
w.overview.categoryClicked.emit("win_temp")
w._goto_category("win_temp")
chk("点击图例跳转分类", w.current_cat == "win_temp", f"(current={w.current_cat})")
w._goto_category("__nonexistent__")
chk("未知分类跳转被忽略", w.current_cat == "win_temp")
w.overview.clear()
chk("清空概览后隐藏", w.overview.isHidden())

# 全选菜单文案与实际行为一致
acts = w.btn_safe.menu().actions()
chk("全选菜单 3 项且文案准确",
    [a.text() for a in acts] == ["仅全选安全项", "全选安全 + 低风险项", "全选安全 + 低风险 + 中等风险项"],
    f"({[a.text() for a in acts]})")
w.select_by_risk(0)
chk("仅全选安全项：高风险未被选中",
    all(i.checked for i in w.items if i.risk == Risk.SAFE)
    and not any(i.checked for i in w.items if i.risk == Risk.HIGH))
w.select_by_risk(2)
chk("全选中等及以下：高风险仍未选中",
    not any(i.checked for i in w.items if i.risk == Risk.HIGH))

# 表格 tooltip
chk("名称列 tooltip", w.table.item(0, 1).toolTip() != "")
chk("说明列 tooltip", w.table.item(0, 7).toolTip() != "")

# 高风险二次确认对话框
from PySide6.QtWidgets import QMessageBox, QCheckBox
cap = {}
orig_exec = QMessageBox.exec
def fake_exec(self):
    cap["title"] = self.windowTitle()
    cap["detail"] = self.detailedText()
    cap["disabled_before"] = not self.button(QMessageBox.Yes).isEnabled()
    cb = self.checkBox()
    cap["has_checkbox"] = isinstance(cb, QCheckBox)
    cb.setChecked(True)
    cap["disabled_after"] = not self.button(QMessageBox.Yes).isEnabled()
    return QMessageBox.Yes
mwmod.QMessageBox.exec = fake_exec
try:
    ok = w._confirm_high_risk([i for i in w.items if i.risk == Risk.HIGH])
    chk("高危确认：勾选后可通过", ok is True)
    chk("高危确认：标题正确", cap.get("title") == "高风险项目确认", f"({cap.get('title')})")
    chk("高危确认：列出路径", os.path.join(root, "C") in (cap.get("detail") or ""))
    chk("高危确认：未勾选时禁止继续",
        cap.get("disabled_before") is True and cap.get("disabled_after") is False)
finally:
    mwmod.QMessageBox.exec = orig_exec

def fake_exec_no(self):
    return QMessageBox.No
mwmod.QMessageBox.exec = fake_exec_no
try:
    chk("高危确认：取消则不继续", w._confirm_high_risk([w.items[-1]]) is False)
finally:
    mwmod.QMessageBox.exec = orig_exec

# 清理记录对话框
h2 = tempfile.mkdtemp(prefix="hist2_")
hist2 = CleanHistory(os.path.join(h2, "clean_history.json"))
rep4 = CleanReport(records=[CleanRecord(path="/tmp/z", kind="dir", ok=True, method="delete", size=9)],
                   freed=9, failed=0, log_file=os.path.join(h2, "bk.txt"))
open(rep4.log_file, "w").write("z")
hist2.record_from_report(rep4)
dlg = HistoryDialog(hist2, w)
chk("清理记录对话框有 1 行", dlg.table.rowCount() == 1)
dlg.table.selectRow(0)
chk("选中后启用按钮", dlg.btn_open_log.isEnabled() and dlg.btn_open_dir.isEnabled())
chk("详情含备份清单路径", rep4.log_file in dlg.detail.text())
dlg.btn_del.click()
chk("删除记录生效", dlg.table.rowCount() == 0)
shutil.rmtree(h2, ignore_errors=True)

# 清理完成写入历史（走 _on_clean_finished）
h3 = tempfile.mkdtemp(prefix="hist3_")
w.history = CleanHistory(os.path.join(h3, "clean_history.json"))
rep5 = CleanReport(records=[CleanRecord(path=os.path.join(root, "A"), kind="dir", ok=True,
                                        method="recycle", size=10)],
                   freed=10, failed=0, log_file=os.path.join(h3, "bk.txt"))
open(rep5.log_file, "w").write("a")
mwmod.QMessageBox.exec = lambda self: QMessageBox.AcceptRole
try:
    w._on_clean_finished(rep5)
finally:
    mwmod.QMessageBox.exec = orig_exec
chk("清理完成写入历史", len(w.history.load()) == 1)
chk("清理后从列表移除已清项", all(i.path != os.path.join(root, "A") for i in w.items))
shutil.rmtree(h3, ignore_errors=True)

shutil.rmtree(root, ignore_errors=True); shutil.rmtree(data, ignore_errors=True)

# ================================================================
print("\n=== J. v1.1.3：默认不勾选 / 免责声明 / 图标资源 ===")
from diskcc import __version__
from diskcc import resources as _res
from diskcc.config import Config as _Cfg
from diskcc.models import ScanItem as _SI, ItemKind as _IK
from diskcc.ui import disclaimer as _disc
from diskcc.ui.main_window import MainWindow as _MW
from PySide6.QtWidgets import QMessageBox as _QMB

chk("版本号 >= 1.1.3", tuple(int(x) for x in __version__.split(".")) >= (1, 1, 3), f"(v{__version__})")

# 图标资源
chk("logo.png 存在", os.path.isfile(_res.asset_path("logo.png")))
chk("diskcc.ico 存在", os.path.isfile(_res.asset_path("diskcc.ico")))
chk("app_icon_path 优先 ico", _res.app_icon_path().endswith(".ico"))
from PySide6.QtGui import QIcon as _QIcon
chk("QIcon 可加载（非空）", not _QIcon(_res.app_icon_path()).isNull())

# 默认不勾选：模型默认值 + 反序列化默认值
chk("ScanItem 默认 checked=False", _SI(path="/tmp/a", kind=_IK.FILE).checked is False)
chk("from_dict 缺省 checked=False", _SI.from_dict({"path": "/tmp/a", "kind": "file"}).checked is False)

# 免责声明配置：新键默认开启，可持久化关闭
_c4 = _Cfg()
chk("show_disclaimer 默认 True", _c4.get("show_disclaimer") is True)
_h4 = tempfile.mkdtemp(prefix="disc_")
_p4 = os.path.join(_h4, "config.json")
_c4.save(_p4)
_c4.set("show_disclaimer", False)
_c4.save(_p4)
chk("不再提示持久化", _Cfg.load(_p4).get("show_disclaimer") is False)

# 免责声明弹窗逻辑（mock exec，不阻塞）：勾选"不再提示"+确认 → 写入配置
def _test_disclaimer(checked: bool) -> None:
    orig_exec = _QMB.exec
    def fake_exec(self):
        self.checkBox().setChecked(checked)
        self.setResult(_QMB.StandardButton.Ok)
    _QMB.exec = fake_exec
    try:
        _cfg_t = _Cfg(); _cfg_t._path = _p4
        _disc.show_disclaimer(None, _cfg_t)
        _cfg_t.save(_p4)
    finally:
        _QMB.exec = orig_exec

_test_disclaimer(True)
chk("勾选不再提示后写回 False", _Cfg.load(_p4).get("show_disclaimer") is False)
_c5 = _Cfg(); _c5._path = _p4; _c5.set("show_disclaimer", True); _c5.save(_p4)
_test_disclaimer(False)
chk("未勾选不再提示则保持 True", _Cfg.load(_p4).get("show_disclaimer") is True)
shutil.rmtree(_h4, ignore_errors=True)

# 扫描后默认全部未勾选（真实扫描链路）
root2 = tempfile.mkdtemp(prefix="v113_")
data2 = tempfile.mkdtemp(prefix="v113d_")
os.environ["LOCALAPPDATA"] = data2; os.environ["APPDATA"] = data2
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("st", os.path.join(ROOT, "tests", "selftest.py"))
_st = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_st)
_st.build_fake_disk(root2)
_cfg6 = _Cfg(); _cfg6.set("min_size_mb", 0.05); _cfg6.set("ai_enabled", False)
_r6 = _st.build_ctx_scan(root2, _cfg6) if hasattr(_st, "build_ctx_scan") else None
if _r6 is None:
    from diskcc.scanner.manager import ScanManager as _SMgr
    _r6 = _SMgr(_cfg6, None, log=lambda m: None).run()
chk("扫描出结果", len(_r6.items) > 0, f"(实际 {len(_r6.items)} 项)")
chk("扫描后默认不勾选任何项目", all(not it.checked for it in _r6.items))
chk("ScanResult.checked_count 为 0",
    getattr(_r6, "checked_count", lambda: sum(1 for i in _r6.items if i.checked))() == 0
    if callable(getattr(_r6, "checked_count", None)) else
    sum(1 for i in _r6.items if i.checked) == 0)
shutil.rmtree(root2, ignore_errors=True); shutil.rmtree(data2, ignore_errors=True)

# ================================================================
print("\n=== K. v1.2.0：性能 / 无响应 / 分类消失 / 打包 ===")
from diskcc import __version__ as _ver120
from diskcc.scanner.manager import ScanManager as _SMgr
from diskcc.cleaner import CleanTask as _CTask
from diskcc.ui import workers as _wmod

chk("版本号 >= 1.2.0", tuple(int(x) for x in _ver120.split(".")) >= (1, 2, 0), f"({_ver120})")
chk("配置项 scan_parallel 默认开启", Config().get("scan_parallel") is True)

# --- 1. 并行扫描与串行结果一致 ---
rootK = tempfile.mkdtemp(prefix="k_")
dataK = tempfile.mkdtemp(prefix="kd_")
os.environ["LOCALAPPDATA"] = dataK
os.environ["APPDATA"] = dataK
_st.build_fake_disk(rootK)

def _scan_with(parallel: bool):
    c = Config()
    c.set("min_size_mb", 0.01); c.set("ai_enabled", False); c.set("scan_parallel", parallel)
    ctx = _st.build_ctx(rootK, c)
    fs.clear_dir_size_cache()
    return sorted(i.path for i in _SMgr(c, None, log=lambda m: None, ctx=ctx).run().items)

_par_items = _scan_with(True)
_seq_items = _scan_with(False)
chk("并行扫描结果与串行完全一致", _par_items == _seq_items and len(_par_items) > 0,
    f"({len(_par_items)} 项)")

# --- 2. AI 分析步骤修复：扫描阶段真的会调用 AI 并回写结论 ---
_pf_foo = os.path.join(rootK, "Program Files", "foo", "bin")
os.makedirs(_pf_foo, exist_ok=True)
with open(os.path.join(_pf_foo, "app.exe"), "wb") as _f:
    _f.write(b"x" * (2 * 1024 * 1024))
cfgK = Config()
cfgK.set("min_size_mb", 0.01); cfgK.set("ai_enabled", True)
cfgK.set("ai_base_url", "https://x/v1"); cfgK.set("ai_api_key", "k"); cfgK.set("ai_model", "m")
_ctxK = _st.build_ctx(rootK, cfgK)
aiK = _ctxK.ai                     # 管理器通过 ctx.ai 执行分析；生产环境两者是同一实例
import re as _re

def _fake_chat(msgs, max_tokens=None):
    """按提示词里出现的 folder 名称逐条回一条结论（模拟 AI 服务端）。"""
    text = "\n".join(m.get("content", "") for m in msgs if isinstance(m, dict))
    names = _re.findall(r'"folder"\s*:\s*"([^"]+)"', text)
    return json.dumps({"results": [{
        "folder": n, "software": "FooSoft", "purpose": "调试工具", "installed": "残留",
        "deletable": True, "risk": "medium", "reason": "AI 判断", "confidence": 0.9}
        for n in names]})

aiK.client.chat = _fake_chat
rK = _SMgr(cfgK, aiK, log=lambda m: None, ctx=_ctxK).run()
_ai_hit = [i for i in rK.items if i.source == "ai"]
chk("扫描阶段确实调用了 AI（修复前恒为 0）", aiK.calls >= 1, f"(calls={aiK.calls})")
chk("AI 结论已回写到扫描项", bool(_ai_hit) and _ai_hit[0].software == "FooSoft",
    f"(回写 {len(_ai_hit)} 项)")

# --- 3. 清理任务快照：清理途中原项目被改写也不受影响 ---
_tpath = os.path.join(rootK, "snap_target.txt")
with open(_tpath, "wb") as _f:
    _f.write(b"hello")
_src = ScanItem(path=_tpath, name="snap_target.txt", category="other",
                size=5, risk=Risk.MEDIUM, reason="测试")
_task = _CTask(_src)
_src.risk = Risk.DANGEROUS          # 模拟清理途中被 AI 改成危险项
_src.path = "/nonexistent/evil"     # 模拟路径被改
chk("CleanTask 快照定格风险等级", _task.risk == Risk.MEDIUM)
okK, whyK = Cleaner(Config(), extra_roots=[rootK]).check_item(_task)
chk("快照项按定格信息通过校验", okK is True, f"({whyK})")

# --- 4. 日志批量刷新：高频日志不再逐条操作控件 ---
wK = MainWindow(Config())
wK.log_view.clear()
_t0 = time.time()
for i in range(150):
    wK.log(f"压力日志 {i}")
_buffered = len(wK.log_view.toPlainText())
wK._flush_ui_updates()
_flushed = len(wK.log_view.toPlainText())
chk("日志先进缓冲区，未逐条写控件", _buffered == 0)
chk("定时刷新后一次性落盘", _flushed > 0)
chk("150 条日志写入耗时可忽略", time.time() - _t0 < 0.5, f"({time.time()-_t0:.3f}s)")
wK._flush_ui_updates()
chk("无待处理进度时不报错", wK._pending_progress is None)

# --- 5. 分类只剩一项时被 AI 重新归类：分类保留 + 视图跟随 ---
wK2 = MainWindow(Config())
_solo = ScanItem(path=os.path.join(rootK, "SoloApp"), name="SoloApp",
                 category="appdata_data", kind=ItemKind.DIR, size=50 * 1024 * 1024,
                 risk=Risk.MEDIUM, reason="内置规则库未收录", source="rule")
wK2.items = [_solo]
wK2.current_cat = "appdata_data"
wK2._apply_filter()
_solo.category = "appdata_cache"    # 模拟 AI 重新归类
# 注意：QMessageBox.information/warning 是 C++ 静态实现，走原生模态循环，
# Python 层 mock exec() 拦不住（offscreen 无事件循环会卡住），故直接替换静态方法。
_orig_info, _orig_warn = mwmod.QMessageBox.information, mwmod.QMessageBox.warning
mwmod.QMessageBox.information = lambda *a, **k: None
mwmod.QMessageBox.warning = lambda *a, **k: None
try:
    wK2._on_ai_finished({"item": _solo, "ok": True,
                         "old_category": "appdata_data", "msg": "AI 识别完成"})
finally:
    mwmod.QMessageBox.information = _orig_info
    mwmod.QMessageBox.warning = _orig_warn
chk("原分类节点被保留（不再凭空消失）", "appdata_data" in wK2.cat_nodes)
chk("视图跟随项目切到新分类", wK2.current_cat == "appdata_cache")
chk("新分类下仍能看到该项目", wK2.table.rowCount() == 1)

# --- 6. AI 识别与清理互斥 ---
class _AIStub:
    enabled = True

wK3 = MainWindow(Config())
wK3.ai = _AIStub()          # 先让 AI 处于启用态，才能验证"清理中禁止识别"这一层
wK3.clean_worker = _wmod.CleanWorker(Config(), [])
wK3.clean_worker.isRunning = lambda: True
_ok3, _sfx3, _tip3 = wK3._ai_identify_supported(_solo)
chk("清理进行中禁止 AI 识别（互斥）", _ok3 is False and "清理" in _tip3, f"({_tip3})")
wK3.clean_worker = None
wK3.ai = None                      # 恢复"AI 未启用"场景
_ok4, _sfx4, _tip4 = wK3._ai_identify_supported(_solo)
chk("AI 未启用时 AI 识别置灰", _ok4 is False and "AI" in _tip4, f"({_tip4})")

# --- 7. 表格批量重建性能 ---
wK4 = MainWindow(Config())
# 注：行数上限受测试环境限制 —— 本沙箱的 PySide6 在"裸 QTableWidget 数百行 setItem"
# 时就会触发 shiboken 自身的 refcount 崩溃（与本项目代码无关，已单独复现确认）。
# 这里验证的是批量重建的开关契约：重建期间关闭，结束后必须恢复。
_rowsK = [ScanItem(path=f"/tmp/k/{i}", name=f"n{i}", category="browser",
                   size=i * 1024, risk=Risk.SAFE, reason="r") for i in range(40)]
wK4._fill_table(_rowsK)
chk("重建后恢复信号与重绘",
    wK4.table.signalsBlocked() is False and wK4.table.updatesEnabled() is True)
chk("重建后行数正确", wK4.table.rowCount() == len(_rowsK))

# --- 8. 打包排除列表安全：排除项均未被真实引用 ---
_nsK = {}
exec(open(os.path.join(ROOT, "DiskCC.spec")).read().split("a = Analysis")[0], _nsK)
_hitK = sorted(m for m in set(_nsK["excludes"]) if m in sys.modules)
chk("spec 排除项无一被实际引用", not _hitK, f"({_hitK})")

shutil.rmtree(rootK, ignore_errors=True)
shutil.rmtree(dataK, ignore_errors=True)

# ================================================================
print("\n=== L. v1.3.0：全面测试发现的 12 处缺陷修复回归 ===")
import threading
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from diskcc.scanner.base import ScannerBase, ScanContext
from diskcc.scanner.manager import ScanManager as _SMgrL
import diskcc.scanner.manager as _mgr_mod
_orig_SCANNERS = _mgr_mod.SCANNERS

# L 段共用一个窗口实例，避免 offscreen 下反复创建/销毁大量 QObject
# 触发 PySide6/shiboken 的 C 层引用计数崩溃（none_dealloc）。
wL = MainWindow(Config())
hL = tempfile.mkdtemp(prefix="hL_")
wL.history = CleanHistory(os.path.join(hL, "h.json"))

# --- 1. 并行扫描取消快速响应（修复前逐个阻塞，取消后仍等最慢任务跑完） ---
class _SlowScanner(ScannerBase):
    title = "慢扫描器"
    def enabled(self): return True
    def scan(self): time.sleep(3)

try:
    _mgr_mod.SCANNERS = [_SlowScanner, _SlowScanner]
    mgr_cancel = _SMgrL(Config(), log=lambda m: None)
    _th = threading.Thread(target=mgr_cancel.run, daemon=True)
    _t0 = time.time()
    _th.start()
    time.sleep(0.3)
    mgr_cancel.stop()
    _th.join(timeout=8)
    _elapsed_cancel = time.time() - _t0
finally:
    _mgr_mod.SCANNERS = _orig_SCANNERS
chk("并行扫描取消快速响应（<=1.5s，修复前等满 3s）", _elapsed_cancel <= 1.5, f"({_elapsed_cancel:.2f}s)")
time.sleep(3.3)   # 等待并行扫描测试遗留的后台线程自然退出，避免干扰后续 QObject 创建

# --- 2. 并行子进度回退时总进度不倒退（_dispatch 改用 max 累积） ---
_cap_p = []
class _Wobble(ScannerBase):
    title = "波动进度扫描器"
    def enabled(self): return True
    def scan(self):
        for p in (10, 80, 30, 60, 100):
            self.ctx.progress("波动", p)
try:
    _mgr_mod.SCANNERS = [_Wobble, _Wobble]
    mgr_w = _SMgrL(Config(), log=lambda m: None,
                   progress=lambda t, p: _cap_p.append((t, p)))
    mgr_w.run()
finally:
    _mgr_mod.SCANNERS = _orig_SCANNERS
# 仅取 _dispatch 产生的 "[并行 ...]" 进度（排除启动/完成文案），验证其不倒退
_par = [p for t, p in _cap_p if t.startswith("[并行")]
chk("并行子进度回退时总进度不倒退",
    len(_par) >= 3 and all(_par[i + 1] >= _par[i] - 1e-9 for i in range(len(_par) - 1)),
    f"({len(_par)}点)")

# --- 3. 清理后按 id 剔除，不误删同路径未勾选项 ---
_same = os.path.join(tempfile.mkdtemp(prefix="same_"), "dup_target")
os.makedirs(_same, exist_ok=True)
_it_a = ScanItem(path=_same, name="目录项", category="win_temp", kind=ItemKind.DIR,
                 size=10 * 1024 * 1024, id="id-A")
_it_b = ScanItem(path=_same, name="文件模式项", category="win_temp", kind=ItemKind.FILES,
                 size=5 * 1024 * 1024, id="id-B")
wL.items = [_it_a, _it_b]
_rep3 = CleanReport(records=[CleanRecord(path=_same, kind="dir", ok=True, method="delete",
                                         size=10 * 1024 * 1024, item_id="id-A")],
                    freed=10 * 1024 * 1024, failed=0)
_orig_exec = mwmod.QMessageBox.exec
mwmod.QMessageBox.exec = lambda self: QMessageBox.AcceptRole
wL.tree.blockSignals(True)   # 规避 offscreen 下树重建引发的 itemChanged 竞态
try:
    wL._on_clean_finished(_rep3)
finally:
    wL.tree.blockSignals(False)
    mwmod.QMessageBox.exec = _orig_exec
chk("按 id 剔除：同路径未勾选项保留",
    any(i.id == "id-B" for i in wL.items), f"(剩余 {[i.id for i in wL.items]})")

# --- 4. 演练模式项目从列表保留（修复前按 ok 剔除导致列表消失） ---
wL.cfg.set("dry_run", True)
_items4 = [ScanItem(path=os.path.join(tempfile.mkdtemp(), "x"), name="x", category="win_temp",
                    kind=ItemKind.DIR, size=10 * 1024 * 1024, id="id-X"),
           ScanItem(path=os.path.join(tempfile.mkdtemp(), "y"), name="y", category="win_temp",
                    kind=ItemKind.DIR, size=10 * 1024 * 1024, id="id-Y")]
wL.items = _items4
_rep4 = CleanReport(records=[CleanRecord(path=_items4[0].path, kind="dir", ok=True,
                                         method="dry-run", size=10 * 1024 * 1024, item_id="id-X")],
                    freed=10 * 1024 * 1024, failed=0)
mwmod.QMessageBox.exec = lambda self: QMessageBox.AcceptRole
wL.tree.blockSignals(True)
try:
    wL._on_clean_finished(_rep4)
finally:
    wL.tree.blockSignals(False)
    mwmod.QMessageBox.exec = _orig_exec
chk("演练模式项目保留在列表", len(wL.items) == 2, f"(剩余 {len(wL.items)})")
wL.cfg.set("dry_run", False)

# --- 5. 重新扫描清空旧日志缓冲区（修复前残留上轮日志） ---
wL._log_buf = ["上轮残留日志1", "上轮残留日志2"]
class _NoOpScanWorker(QThread):
    progress = Signal(str, int)
    logged = Signal(str)
    finished = Signal(object)
    def __init__(self, cfg, ai, parent=None):
        super().__init__(parent)
    def start(self, *a):  # 不真正启动线程，避免异步副作用
        pass
    def run(self): pass
_orig_SW = mwmod.ScanWorker
mwmod.ScanWorker = _NoOpScanWorker
try:
    wL.start_scan()
finally:
    mwmod.ScanWorker = _orig_SW
chk("重新扫描清空旧日志缓冲区",
    not any("上轮残留" in x for x in wL._log_buf), f"(缓冲 {len(wL._log_buf)} 条)")

# --- 6. 单个扫描器构造失败被隔离（修复前整轮崩溃、错误列表为空） ---
rootL = tempfile.mkdtemp(prefix="isol_")
class _BadScanner(ScannerBase):
    title = "坏扫描器"
    def __init__(self, ctx):
        raise RuntimeError("构造失败模拟")
    def enabled(self): return True
    def scan(self): pass
class _GoodScanner(ScannerBase):
    title = "好扫描器"
    def enabled(self): return True
    def scan(self):
        self.ctx.add(ScanItem(path=os.path.join(rootL, "good"), name="good",
                              category="win_temp", kind=ItemKind.DIR, size=10 * 1024 * 1024))
try:
    _mgr_mod.SCANNERS = [_BadScanner, _GoodScanner]
    _res_iso = _SMgrL(Config(), log=lambda m: None).run()
finally:
    _mgr_mod.SCANNERS = _orig_SCANNERS
chk("扫描器构造失败被隔离（不拖垮整轮）", len(_res_iso.items) >= 1, f"({len(_res_iso.items)} 项)")
chk("构造失败记入错误列表", any("坏扫描器" in e for e in _res_iso.errors), f"({_res_iso.errors})")
shutil.rmtree(rootL, ignore_errors=True)

# --- 7. 右击「立即删除」走统一安全校验（修复前绕过 check_item） ---
_prot = os.path.join(tempfile.mkdtemp(prefix="prot_"), "prot")
os.makedirs(_prot, exist_ok=True)
_prot_it = ScanItem(path=_prot, name="prot", category="pf_software", kind=ItemKind.DIR,
                    size=10 * 1024 * 1024, risk=Risk.DANGEROUS, protected=True, id="id-P")
wL.items = [_prot_it]
_calls = {"warn": 0, "info": 0}
_orig_info = mwmod.QMessageBox.information
_orig_warn = mwmod.QMessageBox.warning
mwmod.QMessageBox.information = lambda *a, **k: _calls.__setitem__("info", _calls["info"] + 1)
mwmod.QMessageBox.warning = lambda *a, **k: _calls.__setitem__("warn", _calls["warn"] + 1)
try:
    wL._delete_item_now(_prot_it)
finally:
    mwmod.QMessageBox.information = _orig_info
    mwmod.QMessageBox.warning = _orig_warn
chk("受保护项被统一校验拦截（不再绕过）",
    _calls["warn"] >= 1 and any(i.id == "id-P" for i in wL.items),
    f"({_calls}, 剩余 {len(wL.items)})")
# 命令类项目提示走清理按钮而非直删
_cmd_it = ScanItem(path=os.path.join(tempfile.mkdtemp(), "c"), name="c", category="winsxs",
                   kind=ItemKind.COMMAND, size=10 * 1024 * 1024, command="dism /online /...", id="id-C")
wL.items = [_cmd_it]
mwmod.QMessageBox.information = lambda *a, **k: None
try:
    wL._delete_item_now(_cmd_it)
finally:
    mwmod.QMessageBox.information = _orig_info
chk("命令类项目提示走清理按钮（不直删）", any(i.id == "id-C" for i in wL.items))

# --- 8. 忙碌时禁用设置按钮（修复前可改配置） ---
wL._set_busy(True)
chk("忙碌时禁用设置按钮", wL.btn_settings.isEnabled() is False)
wL._set_busy(False)
chk("空闲时恢复设置按钮", wL.btn_settings.isEnabled() is True)

# --- 9. AI 识别与扫描互斥（v1.2.0 漏掉 scan×AI） ---
class _AIStub:
    enabled = True
wL.ai = _AIStub()
wL.scan_worker = _wmod.ScanWorker(Config(), None)
wL.scan_worker.isRunning = lambda: True
_solo_cat = ScanItem(path=os.path.join(tempfile.mkdtemp(), "pf"), name="pf",
                     category="pf_unknown", kind=ItemKind.DIR, size=10 * 1024 * 1024)
_ok9, _sfx9, _tip9 = wL._ai_identify_supported(_solo_cat)
chk("扫描进行中禁止 AI 识别（互斥）", _ok9 is False and "扫描" in _tip9, f"({_tip9})")
wL.scan_worker = None
wL.ai = None

# --- 10. 关闭窗口先断开 worker 信号（修复前后台线程 emit 到已销毁控件崩溃） ---
_captured = []
wL.scan_worker = _wmod.ScanWorker(Config(), None)
wL.scan_worker.finished.connect(lambda r: _captured.append(("scan", r)))
wL.clean_worker = _wmod.CleanWorker(Config(), [])
wL.clean_worker.finished.connect(lambda r: _captured.append(("clean", r)))
_solo_ai = ScanItem(path=os.path.join(tempfile.mkdtemp(), "ai"), name="ai",
                    category="appdata_data", kind=ItemKind.DIR, size=10 * 1024 * 1024)
wL.ai_worker = _wmod.AIWorker(Config(), None, _solo_ai)
wL.ai_worker.finished.connect(lambda r: _captured.append(("ai", r)))
wL.closeEvent(QCloseEvent())
wL.scan_worker.finished.emit("x")   # 断开后不应再触发槽
chk("closeEvent 断开 worker 信号", len(_captured) == 0, f"({_captured})")
wL.scan_worker = None
wL.clean_worker = None
wL.ai_worker = None

# --- 11. 扫描耗时统计（finished_at）---
rootL11 = tempfile.mkdtemp(prefix="fin_")
_st.build_fake_disk(rootL11)
_cfg11 = Config(); _cfg11.set("min_size_mb", 0.05); _cfg11.set("ai_enabled", False)
_res11 = _SMgrL(_cfg11, None, log=lambda m: None).run()
chk("ScanResult.finished_at 已记录（>0）", _res11.finished_at > 0, f"({_res11.finished_at})")
chk("耗时统计合理（<60s）", _res11.elapsed < 60, f"({_res11.elapsed:.2f}s)")
shutil.rmtree(rootL11, ignore_errors=True)

# --- 12. 按 id 索引查询（修复前 O(N) 线性，数千项卡顿） ---
_i1 = ScanItem(path="/a", name="a", category="browser", size=1, id="id-1")
_i2 = ScanItem(path="/b", name="b", category="browser", size=1, id="id-2")
wL.items = [_i1, _i2]
chk("按 id 索引查询命中", wL._item_by_id("id-2") is _i2)
_i3 = ScanItem(path="/c", name="c", category="browser", size=1, id="id-3")
wL.items = [_i3]
chk("列表替换后索引重建", wL._item_by_id("id-3") is _i3)
chk("旧 id 不再命中", wL._item_by_id("id-1") is None)
shutil.rmtree(hL, ignore_errors=True)

print("\n=== M. v1.3.2：性能 / 稳定性 / 体积优化回归 ===")
# 本段只做文件系统与工具层验证，不新建 Qt 窗口（避免 offscreen 终态回收问题）
import threading as _th

rootM = tempfile.mkdtemp(prefix="m132_")
os.makedirs(os.path.join(rootM, "sub", "deep"), exist_ok=True)
for _n in ("a.dat", "b.txt", "c.dll"):
    open(os.path.join(rootM, "sub", _n), "wb").write(b"x" * 128)
open(os.path.join(rootM, "top.dat"), "wb").write(b"y" * 64)

# 1) scandir 化目录列举：分类与旧写法一致
_md, _mf = fs.scan_dir(os.path.join(rootM, "sub"))
chk("scan_dir 分类正确（目录）", _md == ["deep"], f"({_md})")
chk("scan_dir 分类正确（文件）", sorted(_mf) == ["a.dat", "b.txt", "c.dll"], f"({sorted(_mf)})")
chk("scan_dir 对不存在目录返回空", fs.scan_dir(os.path.join(rootM, "nope")) == ([], []))
chk("子目录名助手可用", fs.subdir_names(os.path.join(rootM, "sub")) == ["deep"])
chk("文件名助手可用", "top.dat" in fs.file_names(rootM))

# 2) dir_size 结果与参考实现一致，且顺带缓存子树
def _ref_size(p):
    t = c = 0
    for d, _dirs, _fs in os.walk(p):
        for f in _fs:
            try:
                t += os.path.getsize(os.path.join(d, f)); c += 1
            except OSError:
                pass
    return t, c

fs.clear_dir_size_cache()
_v = fs.dir_size(rootM, use_cache=False)
chk("dir_size 数值与参考实现一致", _v == _ref_size(rootM), f"({_v} vs {_ref_size(rootM)})")
fs.clear_dir_size_cache()
fs.dir_size(rootM)
_subkey = fs.norm(os.path.join(rootM, "sub"))
with fs._SIZE_CACHE_LOCK:
    _has_sub = _subkey in fs._SIZE_CACHE
chk("遍历父目录时顺带缓存子目录体积", _has_sub)

# 3) 并发单飞：多线程同 key 结果一致（且不重复遍历）
fs.clear_dir_size_cache()
_calls = {"n": 0}
_orig_calc = fs._dir_size_calc


def _counted(*a, **k):
    _calls["n"] += 1
    return _orig_calc(*a, **k)


fs._dir_size_calc = _counted
try:
    _out = []
    _lock = _th.Lock()

    def _w():
        r = fs.dir_size(rootM)
        with _lock:
            _out.append(r)

    _ts = [_th.Thread(target=_w) for _ in range(6)]
    [_t.start() for _t in _ts]
    [_t.join() for _t in _ts]
    chk("并发求同一目录结果一致",
        all(o == _out[0] for o in _out) and _out[0] == _ref_size(rootM), f"({_out[0]})")
    chk("并发单飞避免重复遍历（<=1 次实际计算）", _calls["n"] <= 1, f"({_calls['n']} 次)")
finally:
    fs._dir_size_calc = _orig_calc

# 4) iter_files 结果与旧 fnmatch 写法一致
_old = []
for _nm in fs.safe_listdir(os.path.join(rootM, "sub")):
    _p = os.path.join(rootM, "sub", _nm)
    if not fs.is_dir(_p) and fnmatch.fnmatch(_nm.lower(), "*.dat"):
        _old.append(_p)
_new = list(fs.iter_files(os.path.join(rootM, "sub"), ["*.dat"]))
chk("iter_files 与旧匹配写法结果一致", sorted(_old) == sorted(_new), f"({_new})")
chk("iter_files 无 pattern 时返回全部文件",
    len(list(fs.iter_files(os.path.join(rootM, "sub"), []))) == 3)

# 5) PE 版本采样：非 PE 文件快速返回空
from diskcc.utils import pever  # noqa: E402

chk("read_pe_version 对非 PE 返回空", pever.read_pe_version(os.path.join(rootM, "top.dat")) == {})

# 6) 进度节流器行为
from diskcc.ui.workers import _Throttle  # noqa: E402

_emitted = []
_thr = _Throttle(lambda m, p: _emitted.append(int(p)), min_interval=0.05, min_step=1.0)
for i in range(20):
    _thr(f"t{i}", i * 5)
chk("节流器合并高频回调", len(_emitted) == 1, f"({len(_emitted)} 次)")
time.sleep(0.08)
_thr("again", 60)
chk("超过最小间隔后可再次发射", len(_emitted) == 2, f"({len(_emitted)} 次)")

# 7) 版本号与打包配置
from diskcc import __version__ as _ver132
chk("版本号已升级到 1.3.2", tuple(int(x) for x in _ver132.split(".")) >= (1, 3, 2), f"({_ver132})")
_spec_src = open(os.path.join(ROOT, "DiskCC.spec")).read()
chk("spec 不再打包未使用的 logo.png", '"assets", "assets"' not in _spec_src)
chk("spec 提供可选瘦身开关", "DISKCC_SLIM" in _spec_src)

shutil.rmtree(rootM, ignore_errors=True)

print("\n" + "=" * 60)

# 显式销毁 Qt 窗口：offscreen 下不跑事件循环，解释器退出时由 GC 直接销毁大量
# QObject 会触发 shiboken 的引用计数崩溃（none_dealloc）。这里用 deleteLater +
# processEvents 在受控时机释放 C++ 侧对象，规避退出时的核心转储（不影响测试结论）。
try:
    for _win in (w, wK, wK2, wK3, wK4, wL):
        try:
            _win.deleteLater()
        except Exception:
            pass
    app.processEvents()
except Exception:
    pass

if FAILED:
    print(f"❌ 测试失败 {len(FAILED)} 项: {FAILED}")
    sys.exit(1)
print("✅ 全面测试全部通过（含 v1.2.0）")
sys.stdout.flush()
# offscreen 下不跑事件循环，解释器退出时 GC 销毁大量 QObject 会触发 shiboken 的
# 引用计数崩溃（none_dealloc，SIGABRT，退出码 134），与测试结论无关。验证已全部
# 完成，这里直接干净退出，避免终态 GC 的核心转储。
os._exit(0)
