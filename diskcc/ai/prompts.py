"""AI 提示词模板（要求严格返回 JSON，便于程序解析）。"""

from __future__ import annotations

from typing import Any, Dict, List

from ..models import human_size

SYSTEM_PF = (
    "你是 Windows 系统软件识别专家。用户会给出 Program Files 下的目录信息，"
    "你需要判断每个目录属于哪个软件、它的作用、是否属于已卸载软件的残留目录。"
    "只输出 JSON，不要输出解释文字。"
)

SYSTEM_AD = (
    "你是 Windows 系统数据目录分析专家。用户会给出 AppData 下的目录信息，"
    "你需要判断每个目录属于哪个软件、它存放的是什么数据、其中的缓存/日志是否可以安全删除。"
    "只输出 JSON，不要输出解释文字。"
)

PF_SCHEMA = (
    '返回格式：{"results":[{"folder":"目录名","software":"归属软件名（中文优先，未知填unknown）",'
    '"purpose":"目录作用一句话说明","installed":"已安装/残留/组件/未知 之一",'
    '"deletable":true或false,"risk":"safe/low/medium/high/dangerous 之一",'
    '"reason":"判断依据一句话","confidence":0到1的小数}]}'
)

AD_SCHEMA = (
    '返回格式：{"results":[{"path":"目录相对路径","software":"归属软件名（中文优先，未知填unknown）",'
    '"purpose":"存放的数据类型说明","data_type":"缓存/日志/配置/用户数据/临时文件/组件 之一",'
    '"deletable":true或false,"risk":"safe/low/medium/high/dangerous 之一",'
    '"reason":"判断依据一句话","confidence":0到1的小数}]}'
)


def _fmt(items: List[Dict[str, Any]]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        parts = [
            f"{i}. 目录: {it.get('folder', '')}",
            f"   大小: {human_size(it.get('size', 0))}",
            f"   文件数: {it.get('file_count', 0)}",
            f"   子目录: {', '.join(it.get('subdirs', [])[:12]) or '无'}",
            f"   可执行文件: {', '.join(it.get('exe_names', [])[:8]) or '无'}",
        ]
        if it.get("pe_product"):
            parts.append(f"   PE ProductName: {it['pe_product']}")
        if it.get("pe_company"):
            parts.append(f"   PE CompanyName: {it['pe_company']}")
        if it.get("parent"):
            parts.append(f"   父目录: {it['parent']}")
        if it.get("last_modified"):
            parts.append(f"   最后修改: {it['last_modified']}")
        lines.append("\n".join(parts))
    return "\n".join(lines)


def build_program_files_prompt(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    body = _fmt(items)
    hint = (
        "判断要求：\n"
        "1. 若目录内有可执行文件且是某个软件的安装目录，installed=已安装，deletable=false，risk=dangerous。\n"
        "2. 若目录属于已被卸载的软件残留（如卸载后遗留的空壳目录、只有卸载程序残留），installed=残留，deletable=true，risk=high。\n"
        "3. 若目录是运行库/更新组件/公共组件，installed=组件，deletable=false，risk=high。\n"
        "4. 无法确定时 installed=未知，deletable=false，risk=high，confidence 取低值。\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PF + PF_SCHEMA},
        {"role": "user", "content": f"{hint}\n以下是待识别目录：\n{body}"},
    ]


def build_appdata_prompt(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. 路径: {it.get('path','')}\n"
            f"   大小: {human_size(it.get('size', 0))}\n"
            f"   文件数: {it.get('file_count', 0)}\n"
            f"   子目录: {', '.join(it.get('subdirs', [])[:12]) or '无'}\n"
            f"   顶层文件示例: {', '.join(it.get('files', [])[:8]) or '无'}\n"
            f"   最后修改: {it.get('last_modified', '未知')}"
        )
    hint = (
        "判断要求：\n"
        "1. 纯缓存/日志/临时目录：data_type=缓存或日志，deletable=true，risk=safe或low。\n"
        "2. 含用户配置、账号信息、聊天记录、笔记、工程数据的目录：deletable=false，risk=medium或high。\n"
        "3. 软件已卸载后残留且无价值的数据：deletable=true，risk=medium。\n"
        "4. 只输出 JSON，results 数量必须与输入条目一致。\n"
    )
    return [
        {"role": "system", "content": SYSTEM_AD + AD_SCHEMA},
        {"role": "user", "content": f"{hint}\n以下是待分析目录：\n" + "\n".join(lines)},
    ]
