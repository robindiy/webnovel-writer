#!/usr/bin/env python3
"""
安全的 state.json 更新脚本

功能：
1. 提供结构化的 state.json 更新接口
2. 自动验证 JSON 格式和数据完整性
3. 自动备份（带时间戳）
4. 支持部分更新（不影响其他字段）
5. 原子性操作（要么全部成功，要么全部回滚）

使用方式：
  # 更新主角状态
  python update_state.py --protagonist-power "金丹" 3 "雷劫"

  # 更新人际关系
  python update_state.py --relationship "李雪" affection 95

  # 记录伏笔
  python update_state.py --add-foreshadowing "神秘玉佩的秘密" "未回收"

  # 回收伏笔
  python update_state.py --resolve-foreshadowing "天雷果的下落" 45

  # 更新进度
  python update_state.py --progress 45 198765

  # 标记卷已规划
  python update_state.py --volume-planned 1 --chapters-range 1-100

  # 组合更新（原子性）
  python update_state.py \
    --protagonist-power "金丹" 3 "雷劫" \
    --progress 45 198765 \
    --relationship "李雪" affection 95 \
    --add-foreshadowing "神秘玉佩" "未回收"

安全特性：
  - 自动备份原文件（.backup_TIMESTAMP.json）
  - JSON 格式验证
  - Schema 完整性检查
  - 原子性操作（失败自动回滚）
  - Dry-run 模式（--dry-run）
"""

import json
import os
import sys
import argparse
import shutil
import re
from pathlib import Path

from runtime_compat import enable_windows_utf8_stdio
from datetime import datetime
from typing import Dict, Any, Optional, List

# ============================================================================
# 安全修复：导入安全工具函数（P1 MEDIUM）
# ============================================================================
from security_utils import create_secure_directory, atomic_write_json, restore_from_backup
from project_locator import resolve_state_file
from data_modules.state_validator import (
    normalize_foreshadowing_status,
    normalize_foreshadowing_tier,
    normalize_state_runtime_sections,
    to_positive_int,
)

# Windows 编码兼容性修复
if sys.platform == "win32":
    enable_windows_utf8_stdio()


_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$")
_FORESHADOWING_ACTION_PLANT = ("埋设", "新钩子", "铺垫")
_FORESHADOWING_ACTION_RESOLVE = ("回收", "兑现", "揭晓")


def _extract_markdown_table(lines: List[str], heading: str) -> List[Dict[str, str]]:
    collecting = False
    table_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            current_heading = stripped.lstrip("#").strip()
            if collecting:
                break
            collecting = current_heading == heading
            continue
        if not collecting:
            continue
        if "|" in line:
            table_lines.append(line.rstrip("\n"))
            continue
        if table_lines and stripped:
            break
        if table_lines and not stripped:
            break

    if len(table_lines) < 2:
        return []

    header_cells = [cell.strip() for cell in table_lines[0].strip().strip("|").split("|")]
    rows: List[Dict[str, str]] = []
    for line in table_lines[1:]:
        if _MARKDOWN_TABLE_SEPARATOR_RE.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not any(cells):
            continue
        if len(cells) < len(header_cells):
            cells.extend([""] * (len(header_cells) - len(cells)))
        row = {header_cells[idx]: cells[idx] for idx in range(len(header_cells))}
        rows.append(row)
    return rows


def _normalize_outline_tier(raw_tier: str) -> str:
    text = str(raw_tier or "").strip()
    if text in {"主线", "暗线"}:
        return "核心"
    if text in {"卷内", "卷级"}:
        return "支线"
    return normalize_foreshadowing_tier(text)


def _is_plant_action(action: str) -> bool:
    return any(token in action for token in _FORESHADOWING_ACTION_PLANT)


def _is_resolve_action(action: str) -> bool:
    return any(token in action for token in _FORESHADOWING_ACTION_RESOLVE)


def _merge_outline_foreshadowing(
    rows: List[Dict[str, Any]],
    item: Dict[str, Any],
) -> List[Dict[str, Any]]:
    content = str(item.get("content") or "").strip()
    if not content:
        return rows

    for existing in rows:
        if str(existing.get("content") or "").strip() != content:
            continue
        for key, value in item.items():
            if value in (None, "", []):
                continue
            if key in {"planted_chapter", "target_chapter"} and existing.get(key):
                if key == "planted_chapter":
                    existing[key] = min(int(existing[key]), int(value))
                else:
                    existing[key] = min(int(existing[key]), int(value))
                continue
            existing[key] = value
        return rows

    rows.append(item)
    return rows


def _collect_outline_foreshadowing(project_root: Path) -> List[Dict[str, Any]]:
    outline_dir = project_root / "大纲"
    planned_rows: List[Dict[str, Any]] = []

    total_outline = outline_dir / "总纲.md"
    if total_outline.exists():
        total_rows = _extract_markdown_table(total_outline.read_text(encoding="utf-8").splitlines(), "伏笔表")
        for row in total_rows:
            content = str(row.get("伏笔内容") or "").strip()
            if not content:
                continue
            item: Dict[str, Any] = {
                "content": content,
                "status": "未回收",
                "tier": _normalize_outline_tier(str(row.get("层级") or "").strip()),
                "source": "outline",
                "origin_file": str(total_outline.relative_to(project_root)),
            }
            planted = to_positive_int(row.get("埋设章"))
            target = to_positive_int(row.get("回收章"))
            if planted is not None:
                item["planted_chapter"] = planted
            if target is not None:
                item["target_chapter"] = target
            planned_rows = _merge_outline_foreshadowing(planned_rows, item)

    for detail_file in sorted(outline_dir.glob("第*卷-详细大纲.md")):
        detail_rows = _extract_markdown_table(detail_file.read_text(encoding="utf-8").splitlines(), "伏笔规划")
        for row in detail_rows:
            content = str(row.get("伏笔内容") or "").strip()
            action = str(row.get("操作") or "").strip()
            chapter = to_positive_int(row.get("章节"))
            if not content:
                continue
            item = {
                "content": content,
                "status": "未回收",
                "tier": "支线",
                "source": "outline",
                "origin_file": str(detail_file.relative_to(project_root)),
                "planned_action": action,
            }
            if chapter is not None:
                if _is_resolve_action(action):
                    item["target_chapter"] = chapter
                elif _is_plant_action(action):
                    item["planted_chapter"] = chapter
            planned_rows = _merge_outline_foreshadowing(planned_rows, item)

    return planned_rows

class StateUpdater:
    """state.json 安全更新器"""

    def __init__(self, state_file: str, dry_run: bool = False):
        self.state_file = state_file
        self.dry_run = dry_run
        self.backup_file = None
        self.state = None

    def _validate_schema(self, state: Dict) -> bool:
        """验证 state.json 的基本结构（v5.0 引入，v5.4 沿用）"""
        required_keys = [
            "project_info",
            "progress",
            "protagonist_state",
            "relationships",
            "world_settings",
            "plot_threads",
            "review_checkpoints"
        ]

        for key in required_keys:
            if key not in state:
                print(f"❌ 缺少必需字段: {key}")
                return False

        # 验证嵌套结构（支持两种格式：嵌套和平铺）
        ps = state["protagonist_state"]
        # power 字段：支持 power.realm 或直接 realm
        has_nested_power = "power" in ps and isinstance(ps.get("power"), dict)
        has_flat_power = "realm" in ps
        if not (has_nested_power or has_flat_power):
            print(f"❌ 缺少 protagonist_state.power 或 protagonist_state.realm 字段")
            return False

        # location 字段：支持 location.current 或直接 location
        has_nested_location = isinstance(ps.get("location"), dict) and "current" in ps.get("location", {})
        has_flat_location = isinstance(ps.get("location"), str)
        if not (has_nested_location or has_flat_location):
            print(f"❌ 缺少 protagonist_state.location 字段")
            return False

        # 验证并补全 strand_tracker 结构（兼容旧 state.json）
        tracker = state.get("strand_tracker")
        if tracker is None or not isinstance(tracker, dict):
            if tracker is None:
                print("⚠️ strand_tracker 缺失，已自动补全默认结构")
            else:
                print("⚠️ strand_tracker 类型异常，已重置默认结构")
            state["strand_tracker"] = {
                "last_quest_chapter": 0,
                "last_fire_chapter": 0,
                "last_constellation_chapter": 0,
                "current_dominant": "quest",
                "chapters_since_switch": 0,
                "history": [],
            }
        else:
            tracker.setdefault("last_quest_chapter", 0)
            tracker.setdefault("last_fire_chapter", 0)
            tracker.setdefault("last_constellation_chapter", 0)
            tracker.setdefault("current_dominant", "quest")
            tracker.setdefault("chapters_since_switch", 0)
            tracker.setdefault("history", [])

        normalize_state_runtime_sections(state)
        return True

    def load(self) -> bool:
        """加载并验证 state.json"""
        if not os.path.exists(self.state_file):
            print(f"❌ 状态文件不存在: {self.state_file}")
            return False

        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                self.state = json.load(f)

            if not self._validate_schema(self.state):
                print("❌ state.json 结构不完整，请检查")
                return False

            return True

        except json.JSONDecodeError as e:
            print(f"❌ JSON 格式错误: {e}")
            return False

    def backup(self) -> bool:
        """备份当前 state.json"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(self.state_file).parent / "backups"
        # ============================================================================
        # 安全修复：使用安全目录创建函数（P1 MEDIUM）
        # 原代码: backup_dir.mkdir(exist_ok=True)
        # 漏洞: 未设置权限，使用OS默认（可能为755，允许同组用户读取）
        # ============================================================================
        create_secure_directory(str(backup_dir))

        self.backup_file = backup_dir / f"state.backup_{timestamp}.json"

        try:
            shutil.copy2(self.state_file, self.backup_file)
            print(f"✅ 已备份: {self.backup_file}")
            return True
        except Exception as e:
            print(f"❌ 备份失败: {e}")
            return False

    def save(self) -> bool:
        """保存更新后的 state.json（原子化写入）"""
        if self.dry_run:
            print("\n⚠️  Dry-run 模式，不执行实际写入")
            print("\n📄 预览更新后的内容：")
            print(json.dumps(self.state, ensure_ascii=False, indent=2))
            return True

        try:
            # 使用集中式原子写入（带 filelock + 自动备份）
            atomic_write_json(self.state_file, self.state, use_lock=True, backup=True)
            print(f"✅ 已保存（原子化）: {self.state_file}")
            return True

        except Exception as e:
            print(f"❌ 保存失败: {e}")
            # 尝试从备份恢复
            if restore_from_backup(self.state_file):
                print(f"✅ 已从备份恢复")
            return False

    def update_protagonist_power(self, realm: str, layer: int, bottleneck: str):
        """更新主角实力（支持嵌套和平铺两种格式）"""
        ps = self.state["protagonist_state"]
        # 检测当前格式
        if "power" in ps and isinstance(ps.get("power"), dict):
            # 嵌套格式
            ps["power"] = {
                "realm": realm,
                "layer": layer,
                "bottleneck": bottleneck if bottleneck != "null" else None
            }
        else:
            # 平铺格式
            ps["realm"] = realm
            ps["layer"] = layer
            ps["bottleneck"] = bottleneck if bottleneck != "null" else None
        print(f"📝 更新主角实力: {realm} {layer}层, 瓶颈: {bottleneck}")

    def update_protagonist_location(self, location: str, chapter: int):
        """更新主角位置（支持嵌套和平铺两种格式）"""
        ps = self.state["protagonist_state"]
        # 检测当前格式
        if isinstance(ps.get("location"), dict):
            # 嵌套格式
            ps["location"] = {
                "current": location,
                "last_chapter": chapter
            }
        else:
            # 平铺格式
            ps["location"] = location
            ps["location_since_chapter"] = chapter
        print(f"📝 更新主角位置: {location}（第{chapter}章）")

    def update_golden_finger(self, name: str, level: int, cooldown: int):
        """更新金手指状态"""
        ps = self.state.setdefault("protagonist_state", {})
        golden_finger = ps.get("golden_finger")
        if not isinstance(golden_finger, dict):
            golden_finger = {}
            ps["golden_finger"] = golden_finger

        golden_finger.setdefault("skills", [])
        golden_finger["name"] = name
        golden_finger["level"] = level
        golden_finger["cooldown"] = cooldown
        print(f"📝 更新金手指: {name} Lv.{level}, 冷却: {cooldown}天")

    def update_relationship(self, char_name: str, key: str, value: Any):
        """更新人际关系"""
        if char_name not in self.state["relationships"]:
            self.state["relationships"][char_name] = {}

        self.state["relationships"][char_name][key] = value
        print(f"📝 更新关系: {char_name}.{key} = {value}")

    def add_foreshadowing(self, content: str, status: str = "未回收"):
        """添加伏笔"""
        if "foreshadowing" not in self.state["plot_threads"]:
            self.state["plot_threads"]["foreshadowing"] = []

        # 检查是否已存在
        for item in self.state["plot_threads"]["foreshadowing"]:
            if item.get("content") == content:
                print(f"⚠️  伏笔已存在: {content}")
                return

        # 归一化状态，避免 "待回收/进行中/active/pending" 等混用导致下游过滤漏掉
        status = normalize_foreshadowing_status(status)

        planted_chapter = int(self.state.get("progress", {}).get("current_chapter", 0) or 0)
        if planted_chapter <= 0:
            planted_chapter = 1
            print("? 未找到有效 progress.current_chapter，默认 planted_chapter=1")

        target_chapter = planted_chapter + 100

        self.state["plot_threads"]["foreshadowing"].append({
            "content": content,
            "status": status,
            "added_at": datetime.now().strftime("%Y-%m-%d"),
            "planted_chapter": planted_chapter,
            "target_chapter": target_chapter,
            "tier": "支线"
        })
        print(f"📝 添加伏笔: {content}（{status}）")

    def resolve_foreshadowing(self, content: str, chapter: int):
        """回收伏笔"""
        if "foreshadowing" not in self.state["plot_threads"]:
            print(f"❌ 未找到伏笔列表")
            return

        for item in self.state["plot_threads"]["foreshadowing"]:
            if item.get("content") == content:
                item["status"] = "已回收"
                item["resolved_chapter"] = chapter
                item["resolved_at"] = datetime.now().strftime("%Y-%m-%d")
                normalize_state_runtime_sections(self.state)
                print(f"📝 回收伏笔: {content}（第{chapter}章）")
                return

        print(f"⚠️  未找到伏笔: {content}")

    def sync_foreshadowing_from_outline(self, project_root: Path):
        """从总纲/卷纲同步规划伏笔到 state.json。"""
        planned_rows = _collect_outline_foreshadowing(project_root)
        if not planned_rows:
            print("⚠️  未从大纲中解析到伏笔规划，跳过同步")
            return

        plot_threads = self.state.setdefault("plot_threads", {})
        existing_rows = plot_threads.get("foreshadowing")
        if not isinstance(existing_rows, list):
            existing_rows = []

        existing_by_content = {}
        for row in existing_rows:
            if not isinstance(row, dict):
                continue
            content = str(row.get("content") or "").strip()
            if content:
                existing_by_content[content] = row

        merged_rows: List[Dict[str, Any]] = []
        for planned in planned_rows:
            content = planned["content"]
            existing = existing_by_content.get(content, {})
            merged = dict(planned)
            for key in [
                "status",
                "resolved_chapter",
                "resolved_at",
                "added_at",
                "last_mentioned_chapter",
                "last_updated",
            ]:
                if existing.get(key) not in (None, "", []):
                    merged[key] = existing[key]
            if existing.get("planted_chapter") and "planted_chapter" not in merged:
                merged["planted_chapter"] = existing["planted_chapter"]
            if existing.get("target_chapter") and "target_chapter" not in merged:
                merged["target_chapter"] = existing["target_chapter"]
            merged_rows.append(merged)

        plot_threads["foreshadowing"] = merged_rows
        print(f"📝 已从大纲同步伏笔: {len(merged_rows)} 条")

    def update_progress(self, current_chapter: int, total_words: int):
        """更新创作进度"""
        self.state["progress"]["current_chapter"] = current_chapter
        self.state["progress"]["total_words"] = total_words
        self.state["progress"]["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"📝 更新进度: 第{current_chapter}章, 总字数: {total_words}")

    def mark_volume_planned(self, volume: int, chapters_range: str):
        """标记卷已规划"""
        if "volumes_planned" not in self.state["progress"]:
            self.state["progress"]["volumes_planned"] = []

        # 检查是否已存在
        for item in self.state["progress"]["volumes_planned"]:
            if item.get("volume") == volume:
                print(f"⚠️  第{volume}卷已规划，更新章节范围")
                item["chapters_range"] = chapters_range
                item["updated_at"] = datetime.now().strftime("%Y-%m-%d")
                return

        self.state["progress"]["volumes_planned"].append({
            "volume": volume,
            "chapters_range": chapters_range,
            "planned_at": datetime.now().strftime("%Y-%m-%d")
        })
        print(f"📝 标记第{volume}卷已规划: 第{chapters_range}章")

    def add_review_checkpoint(self, chapters_range: str, report_file: str):
        """添加审查记录"""
        if "review_checkpoints" not in self.state:
            self.state["review_checkpoints"] = []

        self.state["review_checkpoints"].append({
            "chapters": chapters_range,
            "report": report_file,
            "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        print(f"📝 添加审查记录: 第{chapters_range}章 → {report_file}")

    def update_strand_tracker(self, strand: str, chapter: int):
        """更新主导情节线（Strand Weave系统）"""
        # 验证 strand 参数
        valid_strands = ["quest", "fire", "constellation"]
        if strand.lower() not in valid_strands:
            print(f"❌ 无效的情节线类型: {strand}（有效值: quest, fire, constellation）")
            return False

        strand = strand.lower()

        # 初始化 strand_tracker（如果不存在）
        if "strand_tracker" not in self.state:
            self.state["strand_tracker"] = {
                "last_quest_chapter": 0,
                "last_fire_chapter": 0,
                "last_constellation_chapter": 0,
                "current_dominant": None,
                "chapters_since_switch": 0,
                "history": []
            }

        tracker = self.state["strand_tracker"]

        # 更新对应 strand 的最后章节
        tracker[f"last_{strand}_chapter"] = chapter

        # 判断是否切换 strand
        if tracker.get("current_dominant") != strand:
            tracker["current_dominant"] = strand
            tracker["chapters_since_switch"] = 1
        else:
            tracker["chapters_since_switch"] += 1

        # 添加到历史记录
        tracker["history"].append({
            "chapter": chapter,
            "dominant": strand
        })

        # 只保留最近50章的历史（避免文件过大）
        if len(tracker["history"]) > 50:
            tracker["history"] = tracker["history"][-50:]

        print(f"✅ strand_tracker 已更新")
        print(f"   - 第{chapter}章主导情节线: {strand}")
        print(f"   - 该情节线已连续{tracker['chapters_since_switch']}章")

        return True

def main():
    parser = argparse.ArgumentParser(
        description="安全更新 state.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  # 更新主角实力
  python update_state.py --protagonist-power "金丹" 3 "雷劫"

  # 更新人际关系
  python update_state.py --relationship "李雪" affection 95

  # 添加伏笔
  python update_state.py --add-foreshadowing "神秘玉佩的秘密" "未回收"

  # 回收伏笔
  python update_state.py --resolve-foreshadowing "天雷果的下落" 45

  # 更新进度
  python update_state.py --progress 45 198765

  # 标记卷已规划
  python update_state.py --volume-planned 1 --chapters-range "1-100"

  # 组合更新（原子性）
  python update_state.py \
    --protagonist-power "金丹" 3 "雷劫" \
    --progress 45 198765 \
    --relationship "李雪" affection 95
        """
    )

    parser.add_argument(
        '--project-root',
        default=None,
        help='项目根目录（包含 .webnovel/state.json）。不提供时自动搜索（支持 webnovel-project/ 与父目录）。'
    )

    parser.add_argument(
        '--state-file',
        default=None,
        help='state.json 文件路径（可选）。不提供时从项目根目录自动定位为 .webnovel/state.json。'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='预览模式，不执行实际写入'
    )

    # 主角状态更新
    parser.add_argument(
        '--protagonist-power',
        nargs=3,
        metavar=('REALM', 'LAYER', 'BOTTLENECK'),
        help='更新主角实力（境界 层数 瓶颈）'
    )

    parser.add_argument(
        '--protagonist-location',
        nargs=2,
        metavar=('LOCATION', 'CHAPTER'),
        help='更新主角位置（地点 章节号）'
    )

    parser.add_argument(
        '--golden-finger',
        nargs=3,
        metavar=('NAME', 'LEVEL', 'COOLDOWN'),
        help='更新金手指（名称 等级 冷却天数）'
    )

    # 人际关系更新
    parser.add_argument(
        '--relationship',
        nargs=3,
        action='append',
        metavar=('CHAR_NAME', 'KEY', 'VALUE'),
        help='更新人际关系（角色名 属性 值）'
    )

    # 伏笔管理
    parser.add_argument(
        '--add-foreshadowing',
        nargs=2,
        metavar=('CONTENT', 'STATUS'),
        help='添加伏笔（内容 状态）'
    )

    parser.add_argument(
        '--resolve-foreshadowing',
        nargs=2,
        metavar=('CONTENT', 'CHAPTER'),
        help='回收伏笔（内容 章节号）'
    )

    # 进度更新
    parser.add_argument(
        '--progress',
        nargs=2,
        type=int,
        metavar=('CHAPTER', 'WORDS'),
        help='更新进度（当前章节 总字数）'
    )

    # 卷规划
    parser.add_argument(
        '--volume-planned',
        type=int,
        metavar='VOLUME',
        help='标记卷已规划（卷号）'
    )

    parser.add_argument(
        '--chapters-range',
        metavar='RANGE',
        help='章节范围（如 "1-100"）'
    )

    parser.add_argument(
        '--sync-foreshadowing-from-outline',
        action='store_true',
        help='从 大纲/总纲.md 与 第N卷-详细大纲.md 同步伏笔规划到 state.json'
    )

    # 审查记录
    parser.add_argument(
        '--add-review',
        nargs=2,
        metavar=('CHAPTERS_RANGE', 'REPORT_FILE'),
        help='添加审查记录（章节范围 报告文件）'
    )

    # Strand Tracker 更新
    parser.add_argument(
        '--strand-dominant',
        nargs=2,
        metavar=('STRAND', 'CHAPTER'),
        help='更新主导情节线（quest/fire/constellation 章节号）'
    )

    args = parser.parse_args()

    # 如果没有任何更新参数，显示帮助并退出
    if not any([
        args.protagonist_power,
        args.protagonist_location,
        args.golden_finger,
        args.relationship,
        args.add_foreshadowing,
        args.resolve_foreshadowing,
        args.progress,
        args.volume_planned,
        args.sync_foreshadowing_from_outline,
        args.add_review,
        args.strand_dominant
    ]):
        parser.print_help()
        sys.exit(1)

    # 解析 state.json 路径（支持从仓库根目录运行）
    state_file_path = resolve_state_file(args.state_file, explicit_project_root=args.project_root)

    # 创建更新器
    updater = StateUpdater(str(state_file_path), args.dry_run)

    # 加载状态文件
    if not updater.load():
        sys.exit(1)

    # 备份（除非是 dry-run）
    if not args.dry_run:
        if not updater.backup():
            sys.exit(1)

    print("\n📝 开始更新...")

    # 执行更新操作
    try:
        if args.protagonist_power:
            realm, layer, bottleneck = args.protagonist_power
            updater.update_protagonist_power(realm, int(layer), bottleneck)

        if args.protagonist_location:
            location, chapter = args.protagonist_location
            updater.update_protagonist_location(location, int(chapter))

        if args.golden_finger:
            name, level, cooldown = args.golden_finger
            updater.update_golden_finger(name, int(level), int(cooldown))

        if args.relationship:
            for char_name, key, value in args.relationship:
                # 尝试转换为数字
                try:
                    value = int(value)
                except ValueError:
                    pass
                updater.update_relationship(char_name, key, value)

        if args.add_foreshadowing:
            content, status = args.add_foreshadowing
            updater.add_foreshadowing(content, status)

        if args.resolve_foreshadowing:
            content, chapter = args.resolve_foreshadowing
            updater.resolve_foreshadowing(content, int(chapter))

        if args.progress:
            chapter, words = args.progress
            updater.update_progress(chapter, words)

        if args.volume_planned:
            if not args.chapters_range:
                print("❌ --volume-planned 需要 --chapters-range 参数")
                sys.exit(1)
            updater.mark_volume_planned(args.volume_planned, args.chapters_range)

        if args.sync_foreshadowing_from_outline:
            project_root = state_file_path.parent.parent
            updater.sync_foreshadowing_from_outline(project_root)

        if args.add_review:
            chapters_range, report_file = args.add_review
            updater.add_review_checkpoint(chapters_range, report_file)

        # Strand Tracker 更新
        if args.strand_dominant:
            strand, chapter = args.strand_dominant
            updater.update_strand_tracker(strand, int(chapter))

        # 保存更新
        if not updater.save():
            sys.exit(1)

        print("\n✅ 更新完成！")

        if not args.dry_run:
            print(f"\n💡 提示:")
            print(f"  - 原文件已备份: {updater.backup_file}")
            print(f"  - 如需回滚，可复制备份文件到 {updater.state_file}")

    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        if updater.backup_file and os.path.exists(updater.backup_file):
            print(f"🔄 正在回滚...")
            shutil.copy2(updater.backup_file, updater.state_file)
            print(f"✅ 已回滚到备份版本")
        sys.exit(1)

if __name__ == "__main__":
    main()
