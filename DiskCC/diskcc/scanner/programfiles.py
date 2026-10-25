"""Program Files 目录归属识别：注册表 + 内置规则库 + PE 版本信息 + AI 兜底。"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from ..knowledge import software_map
from ..models import ItemKind, Risk, ScanItem
from ..utils import fs
from ..utils.pever import sample_pe_info
from .base import ScannerBase


class ProgramFilesScanner(ScannerBase):
    key = "programfiles"
    title = "Program Files 软件识别"

    def enabled(self) -> bool:
        return bool(self.ctx.cfg.get("scan_program_files", True))

    # ---------------------------------------------------------------- 注册表匹配
    def _match_installed(self, folder: str) -> Tuple[Optional[Dict[str, str]], str]:
        """在注册表安装记录中查找该目录，返回 (记录, 匹配类型)。"""
        f = fs.norm(folder)
        best: Tuple[Optional[Dict[str, str]], str] = (None, "")
        best_len = -1
        for loc, info in self.ctx.installed.items():
            l = fs.norm(loc)
            if not l:
                continue
            if f == l:
                return info, "exact"
            if f.startswith(l + "\\") and len(l) > best_len:
                best, best_len = (info, "parent"), len(l)
            elif l.startswith(f + "\\") and len(f) > best_len:
                best, best_len = (info, "child"), len(f)
        return best

    # ---------------------------------------------------------------- 目录特征
    @staticmethod
    def _features(folder: str) -> Dict:
        size, cnt = fs.dir_size(folder, max_files=60000)
        # v1.3.2：scandir 直出类型，省掉逐项 is_dir 的额外 stat
        subdirs, files_top = fs.scan_dir(folder)
        exe_names = [n for n in files_top if n.lower().endswith((".exe", ".dll"))]
        return {
            "folder": os.path.basename(folder),
            "path": folder,
            "size": size,
            "file_count": cnt,
            "subdirs": sorted(subdirs)[:15],
            "exe_names": sorted(exe_names)[:10],
            "last_modified": fs.mtime_text(folder),
            "age_days": round(fs.days_since(fs.get_mtime(folder)), 1),
            "parent": os.path.basename(os.path.dirname(folder)),
        }

    def _candidates(self, root: str) -> List[Tuple[str, int]]:
        """产生待识别目录（含一层下潜，处理 Adobe/Microsoft 这类厂商容器目录）。"""
        out: List[Tuple[str, int]] = []
        if not fs.is_dir(root):
            return out
        for name in sorted(fs.subdir_names(root)):   # v1.3.2：scandir 直出类型
            if self.ctx.stopped():
                break
            p = os.path.join(root, name)
            if software_map.is_protected_dir(name):
                continue
            subdirs, files_top = fs.scan_dir(p)     # v1.3.2：替代 count_entries + listdir
            has_exe = any(n.lower().endswith(".exe") for n in files_top)
            if has_exe or not subdirs:
                out.append((p, 1))
                continue
            # 容器目录：自身也纳入，同时下潜一层
            out.append((p, 1))
            for n2 in sorted(subdirs):
                if len(out) > 400:
                    break
                p2 = os.path.join(p, n2)   # n2 来自 subdirs，无需再判 is_dir
                out.append((p2, 2))
        return out[:500]

    # ---------------------------------------------------------------- 主流程
    def scan(self) -> List[ScanItem]:
        ctx = self.ctx
        ctx.log("[扫描] Program Files 软件归属识别...")

        roots = list(ctx.program_files)
        if fs.is_dir(ctx.user_programs):
            roots.append(ctx.user_programs)

        candidates: List[Tuple[str, int]] = []
        for r in roots:
            candidates += self._candidates(r)
        ctx.log(f"[扫描] Program Files 共 {len(candidates)} 个候选目录")

        features: List[Dict] = []
        known: Dict[str, Dict] = {}       # path -> 本地判定结果
        unknown: List[str] = []
        pe_budget = 80                    # PE 采样次数上限，避免过慢

        for pi, (path, depth) in enumerate(candidates, 1):
            if ctx.stopped():
                break
            if ctx.is_excluded(path):
                continue
            if pi % 10 == 1:
                ctx.progress(f"识别目录 {pi}/{len(candidates)}", pi / max(1, len(candidates)) * 100)
            feat = self._features(path)
            if feat["size"] < max(ctx.min_size, 64 * 1024) and not feat["exe_names"]:
                continue
            name = os.path.basename(path)

            info, match_type = self._match_installed(path)
            rule_name = software_map.lookup(name)
            pe: Dict[str, str] = {}
            if not info and not rule_name and pe_budget > 0:
                pe = sample_pe_info(path)
                pe_budget -= 1

            software = ""
            source = "rule"
            if info and info.get("name"):
                software = info["name"]
                source = "registry"
            elif rule_name:
                software = rule_name
                source = "rule"
            elif pe.get("product"):
                software = pe["product"]
                source = "pe"
            elif pe.get("company"):
                software = pe["company"]
                source = "pe"

            feat["pe_product"] = pe.get("product", "")
            feat["pe_company"] = pe.get("company", "")
            feat["pe_description"] = pe.get("description", "")
            known[path] = {
                "feat": feat,
                "registry": info,
                "match_type": match_type,
                "rule": rule_name,
                "pe": pe,
                "software": software,
                "source": source,
                "depth": depth,
            }
            if not software:
                unknown.append(path)
            features.append(feat)

        # ---------------- 收集 AI 候选（实际分析推迟到 manager 的独立“AI 分析”步骤） ----------------
        if unknown:
            ctx.log(f"[规则库] {len(unknown)} 个目录未能识别"
                    + ("（将在后续的 AI 分析步骤中处理）" if ctx.ai.enabled else
                       "（未开启 AI 增强，保持规则库判断）"))

        items: List[ScanItem] = []
        for path, data in known.items():
            if ctx.stopped():
                break
            feat: Dict = data["feat"]
            info = data["registry"]
            size = feat["size"]
            name = os.path.basename(path)
            software = data["software"]
            reason_parts: List[str] = []
            risk = Risk.HIGH
            category = "pf_unknown"
            extra: Dict[str, object] = {
                "subdirs": feat["subdirs"][:10],
                "exe_count": len(feat["exe_names"]),
                "age_days": feat["age_days"],
                "pe_product": feat.get("pe_product", ""),
                "pe_company": feat.get("pe_company", ""),
                "depth": data["depth"],
            }

            if info:
                extra["uninstall_string"] = info.get("uninstall", "")
                extra["publisher"] = info.get("publisher", "")
                extra["version"] = info.get("version", "")
                if data["match_type"] == "exact":
                    category = "pf_software"
                    risk = Risk.DANGEROUS
                    reason_parts.append("注册表中存在该软件的安装记录（已安装）")
                elif data["match_type"] == "child":
                    category = "pf_software"
                    risk = Risk.DANGEROUS
                    reason_parts.append(f"该目录下包含已安装软件「{info.get('name','')}」")
                else:
                    category = "pf_software"
                    risk = Risk.HIGH
                    reason_parts.append(f"位于已安装软件「{info.get('name','')}」的安装目录内")
            elif software:
                # 规则库 / PE 版本信息判定（无注册表）
                if software_map.looks_like_component(name):
                    category = "pf_software"
                    reason_parts.append(f"疑似「{software}」的运行库/组件目录")
                elif feat["exe_names"]:
                    category = "pf_software"
                    risk = Risk.DANGEROUS
                    reason_parts.append(f"按目录特征归属「{software}」，目录内含可执行程序，判定为已安装")
                elif feat["subdirs"]:
                    category = "pf_software"
                    risk = Risk.HIGH
                    reason_parts.append(
                        f"归属「{software}」的厂商/容器目录，包含 {len(feat['subdirs'])} 个子目录，"
                        "具体软件需展开子目录判断，删除会影响其下所有组件")
                else:
                    category = "pf_residue"
                    risk = Risk.HIGH
                    reason_parts.append(f"归属「{software}」，但目录内无可执行程序且注册表中无安装记录，疑似卸载残留")
            else:
                # 无注册表、无规则库：启发式判断（AI 启用时会覆盖）
                if feat["age_days"] > ctx.idle_days and not feat["exe_names"]:
                    category = "pf_residue"
                    reason_parts.append(f"未知目录，{int(feat['age_days'])} 天未修改且无可执行文件，疑似残留")
                elif feat["exe_names"]:
                    category = "pf_unknown"
                    reason_parts.append("未能识别归属，目录内含可执行程序，可能是绿色版或未注册软件")
                else:
                    category = "pf_unknown"
                    reason_parts.append("未能识别归属，建议开启 AI 识别或手动确认")

            # 标记 AI 候选：无注册表匹配的项，交给 manager 的“AI 分析”步骤处理
            if ctx.ai.enabled and not info:
                only_unknown = bool(ctx.cfg.get("ai_only_unknown", True))
                if (not only_unknown) or (not software):
                    ai_key = f"pf:{name.lower()}"
                    item_extra = extra
                    item_extra["ai_key"] = ai_key
                    ctx.queue_ai_pf(feat, ai_key)

            if software_map.is_protected_dir(name):
                reason_parts.append("系统受保护目录，禁止删除")

            item = ScanItem(
                path=path,
                name=name,
                category=category,
                kind=ItemKind.DIR,
                size=size,
                file_count=feat["file_count"],
                risk=risk,
                reason="；".join([p for p in reason_parts if p]) or "未提供说明",
                software=software,
                source=data["source"],
                protected=software_map.is_protected_dir(name),
                mtime=fs.get_mtime(path),
                extra=extra,
            )
            added = ctx.add(item)
            if added:
                items.append(added)

        return items


def _apply_ai_pf(item: "ScanItem", ai: "AIAnalysis") -> None:
    """用 AI 结论覆盖 Program Files 项的归属与风险判断（被 manager 与右键识别共用）。"""
    from ..ai.analyzer import AIAnalysis
    from ..models import Risk

    software = ai.software or item.software
    item.software = software
    installed = (ai.installed or "").strip()
    reason_parts = [f"AI 判断：{ai.purpose}（{installed}）"]
    if ai.reason:
        reason_parts.append(ai.reason)
    item.reason = "；".join(reason_parts)
    item.risk = ai.risk if ai.risk is not None else Risk.HIGH
    if installed == "残留":
        item.category = "pf_residue"
    elif installed in ("组件", "已安装"):
        item.category = "pf_software"
        if installed == "已安装":
            item.risk = Risk.DANGEROUS
    else:
        item.category = "pf_unknown"
    item.checked = bool(ai.deletable) and (ai.confidence or 0) >= 0.7
    item.extra["ai_confidence"] = round(ai.confidence or 0, 2)
    item.source = "ai"
