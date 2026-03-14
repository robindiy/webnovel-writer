#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
State Manager - 状态管理模块 (v5.4)

管理 state.json 的读写操作：
- 实体状态管理
- 进度追踪
- 关系记录

v5.1 变更（v5.4 沿用）:
- 集成 SQLStateManager，同步写入 SQLite (index.db)
- state.json 保留精简数据，大数据自动迁移到 SQLite
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from copy import deepcopy
from pathlib import Path

from runtime_compat import enable_windows_utf8_stdio
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime

try:
    import filelock
except ImportError:  # pragma: no cover
    class _NoOpFileLock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

    class _FileLockCompat:
        FileLock = _NoOpFileLock

        class Timeout(Exception):
            pass

    filelock = _FileLockCompat()

from .config import get_config
from .observability import safe_append_perf_timing, safe_log_tool_call
from .state_validator import (
    FORESHADOWING_STATUS_PENDING,
    FORESHADOWING_STATUS_RESOLVED,
    normalize_foreshadowing_item,
)


logger = logging.getLogger(__name__)

_FORESHADOWING_TEXT_STRIP_RE = re.compile(r"[\s\u3000，,。.!！？?：:；;、\"'“”‘’（）()《》〈〉【】\[\]—-]+")
_CHAPTER_TITLE_RE = re.compile(r"^\s*#\s*第\s*\d+\s*章(?:\s*[-—:：]\s*|\s+)(.+?)\s*$", re.MULTILINE)
_SUMMARY_SECTION_RE = re.compile(r"##\s*(?:剧情摘要|本章摘要)\s*\r?\n(.+?)(?=\r?\n##|$)", re.DOTALL)

try:
    # 当 scripts 目录在 sys.path 中（常见：从 scripts/ 运行）
    from security_utils import atomic_write_json, read_json_safe
except ImportError:  # pragma: no cover
    # 当以 `python -m scripts.data_modules...` 从仓库根目录运行
    from scripts.security_utils import atomic_write_json, read_json_safe

try:
    from chapter_paths import find_chapter_file
except ImportError:  # pragma: no cover
    from scripts.chapter_paths import find_chapter_file


@dataclass
class EntityState:
    """实体状态"""
    id: str
    name: str
    type: str  # 角色/地点/物品/势力
    tier: str = "装饰"  # 核心/重要/次要/装饰
    aliases: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_appearance: int = 0
    last_appearance: int = 0


@dataclass
class Relationship:
    """实体关系"""
    from_entity: str
    to_entity: str
    type: str
    description: str
    chapter: int


@dataclass
class StateChange:
    """状态变化记录"""
    entity_id: str
    field: str
    old_value: Any
    new_value: Any
    reason: str
    chapter: int
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class _EntityPatch:
    """待写入的实体增量补丁（用于锁内合并）"""
    entity_type: str
    entity_id: str
    replace: bool = False
    base_entity: Optional[Dict[str, Any]] = None  # 新建实体时的完整快照（用于填充缺失字段）
    top_updates: Dict[str, Any] = field(default_factory=dict)
    current_updates: Dict[str, Any] = field(default_factory=dict)
    appearance_chapter: Optional[int] = None


class StateManager:
    """状态管理器（v5.1 entities_v3 格式 + SQLite 同步，v5.4 沿用）"""

    # v5.0 引入的实体类型
    ENTITY_TYPES = ["角色", "地点", "物品", "势力", "招式"]

    def __init__(self, config=None, enable_sqlite_sync: bool = True):
        """
        初始化状态管理器

        参数:
        - config: 配置对象
        - enable_sqlite_sync: 是否启用 SQLite 同步 (默认 True)
        """
        self.config = config or get_config()
        self._state: Dict[str, Any] = {}
        # 与 security_utils.atomic_write_json 保持一致：state.json.lock
        self._lock_path = self.config.state_file.with_suffix(self.config.state_file.suffix + ".lock")

        # v5.1 引入: SQLite 同步
        self._enable_sqlite_sync = enable_sqlite_sync
        self._sql_state_manager = None
        if enable_sqlite_sync:
            try:
                from .sql_state_manager import SQLStateManager
                self._sql_state_manager = SQLStateManager(self.config)
            except ImportError:
                pass  # SQLStateManager 不可用时静默降级

        # 待写入的增量（锁内重读 + 合并 + 写入）
        self._pending_entity_patches: Dict[tuple[str, str], _EntityPatch] = {}
        self._pending_alias_entries: Dict[str, List[Dict[str, str]]] = {}
        self._pending_state_changes: List[Dict[str, Any]] = []
        self._pending_structured_relationships: List[Dict[str, Any]] = []
        self._pending_disambiguation_warnings: List[Dict[str, Any]] = []
        self._pending_disambiguation_pending: List[Dict[str, Any]] = []
        self._pending_progress_chapter: Optional[int] = None
        self._pending_progress_words_delta: int = 0
        self._pending_foreshadowing: List[Dict[str, Any]] = []
        self._pending_chapter_meta: Dict[str, Any] = {}

        # v5.1 引入: 缓存待同步到 SQLite 的数据
        self._pending_sqlite_data: Dict[str, Any] = {
            "entities_appeared": [],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "scenes": [],
            "scenes_provided": False,
            "chapter": None,
            "chapter_index": None,
        }

        self._load_state()

    def _now_progress_timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _ensure_state_schema(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """确保 state.json 具备运行所需的关键字段（尽量不破坏既有数据）。"""
        if not isinstance(state, dict):
            state = {}

        state.setdefault("project_info", {})
        state.setdefault("progress", {})
        state.setdefault("protagonist_state", {})

        # relationships: 旧版本可能是 list（实体关系），v5.0 运行态用 dict（人物关系/重要关系）
        relationships = state.get("relationships")
        if isinstance(relationships, list):
            state.setdefault("structured_relationships", [])
            if isinstance(state.get("structured_relationships"), list):
                state["structured_relationships"].extend(relationships)
            state["relationships"] = {}
        elif not isinstance(relationships, dict):
            state["relationships"] = {}

        state.setdefault("world_settings", {"power_system": [], "factions": [], "locations": []})
        state.setdefault("plot_threads", {"active_threads": [], "foreshadowing": []})
        state.setdefault("review_checkpoints", [])
        state.setdefault("chapter_meta", {})
        state.setdefault(
            "strand_tracker",
            {
                "last_quest_chapter": 0,
                "last_fire_chapter": 0,
                "last_constellation_chapter": 0,
                "current_dominant": "quest",
                "chapters_since_switch": 0,
                "history": [],
            },
        )

        entities_v3 = state.get("entities_v3")
        # v5.1 引入: entities_v3, alias_index, state_changes, structured_relationships 已迁移到 index.db
        # 不再在 state.json 中初始化或维护这些字段

        if not isinstance(state.get("disambiguation_warnings"), list):
            state["disambiguation_warnings"] = []

        if not isinstance(state.get("disambiguation_pending"), list):
            state["disambiguation_pending"] = []

        # progress 基础字段
        progress = state["progress"]
        if not isinstance(progress, dict):
            progress = {}
            state["progress"] = progress
        progress.setdefault("current_chapter", 0)
        progress.setdefault("total_words", 0)
        progress.setdefault("last_updated", self._now_progress_timestamp())

        return state

    def _load_state(self):
        """加载状态文件"""
        if self.config.state_file.exists():
            self._state = read_json_safe(self.config.state_file, default={})
            self._state = self._ensure_state_schema(self._state)
        else:
            self._state = self._ensure_state_schema({})

    def save_state(self):
        """
        保存状态文件（锁内重读 + 合并 + 原子写入）。

        解决多 Agent 并行下的“读-改-写覆盖”风险：
        - 获取锁
        - 重新读取磁盘最新 state.json
        - 仅合并本实例产生的增量（pending_*）
        - 原子化写入
        """
        # 无增量时不写入，避免无意义覆盖
        has_pending = any(
            [
                self._pending_entity_patches,
                self._pending_alias_entries,
                self._pending_state_changes,
                self._pending_structured_relationships,
                self._pending_disambiguation_warnings,
                self._pending_disambiguation_pending,
                self._pending_foreshadowing,
                self._pending_chapter_meta,
                self._pending_progress_chapter is not None,
                self._pending_progress_words_delta != 0,
            ]
        )
        if not has_pending:
            return

        self.config.ensure_dirs()

        lock = filelock.FileLock(str(self._lock_path), timeout=10)
        try:
            with lock:
                disk_state = read_json_safe(self.config.state_file, default={})
                disk_state = self._ensure_state_schema(disk_state)

                # progress（合并为 max(chapter) + words_delta 累加）
                if self._pending_progress_chapter is not None or self._pending_progress_words_delta != 0:
                    progress = disk_state.get("progress", {})
                    if not isinstance(progress, dict):
                        progress = {}
                        disk_state["progress"] = progress

                    try:
                        current_chapter = int(progress.get("current_chapter", 0) or 0)
                    except (TypeError, ValueError):
                        current_chapter = 0

                    if self._pending_progress_chapter is not None:
                        progress["current_chapter"] = max(current_chapter, int(self._pending_progress_chapter))

                    if self._pending_progress_words_delta:
                        try:
                            total_words = int(progress.get("total_words", 0) or 0)
                        except (TypeError, ValueError):
                            total_words = 0
                        progress["total_words"] = total_words + int(self._pending_progress_words_delta)

                    progress["last_updated"] = self._now_progress_timestamp()

                # v5.1 引入: 强制使用 SQLite 模式，移除大数据字段
                # 确保 state.json 中不存在这些膨胀字段
                for field in ["entities_v3", "alias_index", "state_changes", "structured_relationships"]:
                    disk_state.pop(field, None)
                # 标记已迁移
                disk_state["_migrated_to_sqlite"] = True

                # disambiguation_warnings（追加去重 + 截断）
                if self._pending_disambiguation_warnings:
                    warnings_list = disk_state.get("disambiguation_warnings")
                    if not isinstance(warnings_list, list):
                        warnings_list = []
                        disk_state["disambiguation_warnings"] = warnings_list

                    def _warn_key(w: Dict[str, Any]) -> tuple:
                        return (
                            w.get("chapter"),
                            w.get("mention"),
                            w.get("chosen_id"),
                            w.get("confidence"),
                        )

                    existing_keys = {_warn_key(w) for w in warnings_list if isinstance(w, dict)}
                    for w in self._pending_disambiguation_warnings:
                        if not isinstance(w, dict):
                            continue
                        k = _warn_key(w)
                        if k in existing_keys:
                            continue
                        warnings_list.append(w)
                        existing_keys.add(k)

                    # 只保留最近 N 条，避免文件无限增长
                    max_keep = self.config.max_disambiguation_warnings
                    if len(warnings_list) > max_keep:
                        disk_state["disambiguation_warnings"] = warnings_list[-max_keep:]

                # disambiguation_pending（追加去重 + 截断）
                if self._pending_disambiguation_pending:
                    pending_list = disk_state.get("disambiguation_pending")
                    if not isinstance(pending_list, list):
                        pending_list = []
                        disk_state["disambiguation_pending"] = pending_list

                    def _pending_key(w: Dict[str, Any]) -> tuple:
                        return (
                            w.get("chapter"),
                            w.get("mention"),
                            w.get("suggested_id"),
                            w.get("confidence"),
                        )

                    existing_keys = {_pending_key(w) for w in pending_list if isinstance(w, dict)}
                    for w in self._pending_disambiguation_pending:
                        if not isinstance(w, dict):
                            continue
                        k = _pending_key(w)
                        if k in existing_keys:
                            continue
                        pending_list.append(w)
                        existing_keys.add(k)

                    max_keep = self.config.max_disambiguation_pending
                    if len(pending_list) > max_keep:
                        disk_state["disambiguation_pending"] = pending_list[-max_keep:]

                if self._pending_foreshadowing:
                    plot_threads = disk_state.get("plot_threads")
                    if not isinstance(plot_threads, dict):
                        plot_threads = {}
                        disk_state["plot_threads"] = plot_threads
                    foreshadowing = plot_threads.get("foreshadowing")
                    if not isinstance(foreshadowing, list):
                        foreshadowing = []
                    plot_threads["foreshadowing"] = self._merge_foreshadowing_rows(
                        foreshadowing,
                        self._pending_foreshadowing,
                    )

                # chapter_meta（新增：按章节号覆盖写入）
                if self._pending_chapter_meta:
                    chapter_meta = disk_state.get("chapter_meta")
                    if not isinstance(chapter_meta, dict):
                        chapter_meta = {}
                        disk_state["chapter_meta"] = chapter_meta
                    chapter_meta.update(self._pending_chapter_meta)

                # 原子写入（锁已持有，不再二次加锁）
                atomic_write_json(self.config.state_file, disk_state, use_lock=False, backup=True)

                # v5.1 引入: 同步到 SQLite（失败时保留 pending 以便重试）
                sqlite_pending_snapshot = self._snapshot_sqlite_pending()
                sqlite_sync_ok = self._sync_to_sqlite()

                # 同步内存为磁盘最新快照
                self._state = disk_state

                # state.json 侧 pending 已写盘，直接清空
                self._pending_disambiguation_warnings.clear()
                self._pending_disambiguation_pending.clear()
                self._pending_foreshadowing.clear()
                self._pending_chapter_meta.clear()
                self._pending_progress_chapter = None
                self._pending_progress_words_delta = 0

                # SQLite 侧 pending：成功后清空，失败则恢复快照（避免静默丢数据）
                if sqlite_sync_ok:
                    self._pending_entity_patches.clear()
                    self._pending_alias_entries.clear()
                    self._pending_state_changes.clear()
                    self._pending_structured_relationships.clear()
                    self._clear_pending_sqlite_data()
                else:
                    self._restore_sqlite_pending(sqlite_pending_snapshot)

        except filelock.Timeout:
            raise RuntimeError("无法获取 state.json 文件锁，请稍后重试")

    def _sync_to_sqlite(self) -> bool:
        """同步待处理数据到 SQLite（v5.1 引入，v5.4 沿用）"""
        if not self._sql_state_manager:
            return True

        # 方式1: 通过 process_chapter_result 收集的数据
        sqlite_data = self._pending_sqlite_data
        chapter = sqlite_data.get("chapter")

        # 记录已处理的 (entity_id, chapter) 组合，避免重复写入 appearances
        processed_appearances = set()

        if chapter is not None:
            try:
                self._sql_state_manager.process_chapter_entities(
                    chapter=chapter,
                    entities_appeared=sqlite_data.get("entities_appeared", []),
                    entities_new=sqlite_data.get("entities_new", []),
                    state_changes=sqlite_data.get("state_changes", []),
                    relationships_new=sqlite_data.get("relationships_new", [])
                )
                # 标记已处理的出场记录
                for entity in sqlite_data.get("entities_appeared", []):
                    if entity.get("id"):
                        processed_appearances.add((entity.get("id"), chapter))
                for entity in sqlite_data.get("entities_new", []):
                    eid = entity.get("suggested_id") or entity.get("id")
                    if eid:
                        processed_appearances.add((eid, chapter))
            except Exception as exc:
                logger.warning("SQLite sync failed (process_chapter_entities): %s", exc)
                return False

        chapter_index = sqlite_data.get("chapter_index")
        if isinstance(chapter_index, dict):
            try:
                self._upsert_chapter_index_snapshot(chapter_index)
            except Exception as exc:
                logger.warning("SQLite sync failed (chapter_index): %s", exc)
                return False

        if sqlite_data.get("scenes_provided"):
            try:
                self._upsert_chapter_scenes(
                    chapter=chapter,
                    scenes=sqlite_data.get("scenes", []),
                )
            except Exception as exc:
                logger.warning("SQLite sync failed (chapter_scenes): %s", exc)
                return False

        # 方式2: 使用 add_entity/update_entity 收集的增量数据。
        # 数据缓存在 _pending_entity_patches 等变量中。
        return self._sync_pending_patches_to_sqlite(processed_appearances)

    def _upsert_chapter_index_snapshot(self, snapshot: Dict[str, Any]) -> None:
        if not self._sql_state_manager:
            return

        from .index_manager import ChapterMeta

        index_manager = self._sql_state_manager._index_manager
        chapter = int(snapshot.get("chapter") or 0)
        if chapter <= 0:
            return

        existing = index_manager.get_chapter(chapter) or {}
        existing_characters = existing.get("characters") if isinstance(existing.get("characters"), list) else []
        incoming_characters = snapshot.get("characters") if isinstance(snapshot.get("characters"), list) else []

        merged_characters: List[str] = []
        seen: set[str] = set()
        for entity_id in [*existing_characters, *incoming_characters]:
            normalized = str(entity_id or "").strip()
            if not normalized or normalized in seen:
                continue
            merged_characters.append(normalized)
            seen.add(normalized)

        title = str(snapshot.get("title") or existing.get("title") or f"第{chapter}章").strip()
        location = str(snapshot.get("location") or existing.get("location") or "").strip()
        summary = str(snapshot.get("summary") or existing.get("summary") or "").strip()

        try:
            word_count = int(snapshot.get("word_count") or existing.get("word_count") or 0)
        except (TypeError, ValueError):
            word_count = int(existing.get("word_count") or 0)

        index_manager.add_chapter(
            ChapterMeta(
                chapter=chapter,
                title=title,
                location=location,
                word_count=word_count,
                characters=merged_characters,
                summary=summary,
            )
        )

    def _upsert_chapter_scenes(self, chapter: Any, scenes: Any) -> None:
        if not self._sql_state_manager:
            return

        from .index_manager import SceneMeta

        try:
            chapter_num = int(chapter or 0)
        except (TypeError, ValueError):
            return
        if chapter_num <= 0:
            return

        if not isinstance(scenes, list):
            scenes = []

        def _to_int(value: Any) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        scene_metas: List[SceneMeta] = []
        for fallback_index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                continue

            raw_index = scene.get("index", scene.get("scene_index"))
            try:
                scene_index = int(raw_index)
            except (TypeError, ValueError):
                scene_index = fallback_index
            if scene_index <= 0:
                scene_index = fallback_index

            raw_characters = scene.get("characters")
            characters: List[str] = []
            seen: set[str] = set()
            if isinstance(raw_characters, list):
                for entity_id in raw_characters:
                    normalized = str(entity_id or "").strip()
                    if not normalized or normalized in seen:
                        continue
                    characters.append(normalized)
                    seen.add(normalized)

            scene_metas.append(
                SceneMeta(
                    chapter=chapter_num,
                    scene_index=scene_index,
                    start_line=_to_int(scene.get("start_line")),
                    end_line=_to_int(scene.get("end_line")),
                    location=str(scene.get("location") or "").strip(),
                    summary=str(scene.get("summary") or "").strip(),
                    characters=characters,
                )
            )

        self._sql_state_manager._index_manager.add_scenes(chapter_num, scene_metas)

    def _sync_pending_patches_to_sqlite(self, processed_appearances: set = None) -> bool:
        """同步 _pending_entity_patches 等到 SQLite（v5.1 引入，v5.4 沿用）

        Args:
            processed_appearances: 已通过 process_chapter_entities 处理的 (entity_id, chapter) 集合，
                                   用于避免重复写入 appearances 表（防止覆盖 mentions）
        """
        if not self._sql_state_manager:
            return True

        if processed_appearances is None:
            processed_appearances = set()

        # 元数据字段（不应写入 current_json）
        METADATA_FIELDS = {"canonical_name", "tier", "desc", "is_protagonist", "is_archived"}

        try:
            from .sql_state_manager import EntityData
            from .index_manager import EntityMeta

            # 同步实体补丁
            for (entity_type, entity_id), patch in self._pending_entity_patches.items():
                if patch.base_entity:
                    # 新实体
                    entity_data = EntityData(
                        id=entity_id,
                        type=entity_type,
                        name=patch.base_entity.get("canonical_name", entity_id),
                        tier=patch.base_entity.get("tier", "装饰"),
                        desc=patch.base_entity.get("desc", ""),
                        current=patch.base_entity.get("current", {}),
                        aliases=[],
                        first_appearance=patch.base_entity.get("first_appearance", 0),
                        last_appearance=patch.base_entity.get("last_appearance", 0),
                        is_protagonist=patch.base_entity.get("is_protagonist", False)
                    )
                    self._sql_state_manager.upsert_entity(entity_data)

                    # 记录首次出场（跳过已处理的，避免覆盖 mentions）
                    if patch.appearance_chapter is not None:
                        if (entity_id, patch.appearance_chapter) not in processed_appearances:
                            self._sql_state_manager._index_manager.record_appearance(
                                entity_id=entity_id,
                                chapter=patch.appearance_chapter,
                                mentions=[entity_data.name],
                                confidence=1.0,
                                skip_if_exists=True  # 关键：不覆盖已有记录
                            )
                else:
                    # 更新现有实体
                    has_metadata_updates = bool(patch.top_updates and
                                                 any(k in METADATA_FIELDS for k in patch.top_updates))

                    # 非元数据的 top_updates 应该当作 current 更新
                    # 例如：realm, layer, location 等状态字段
                    non_metadata_top_updates = {
                        k: v for k, v in patch.top_updates.items()
                        if k not in METADATA_FIELDS
                    } if patch.top_updates else {}

                    # 合并 current_updates 和非元数据的 top_updates
                    effective_current_updates = {**non_metadata_top_updates}
                    if patch.current_updates:
                        effective_current_updates.update(patch.current_updates)

                    if has_metadata_updates:
                        # 有元数据更新：使用 upsert_entity(update_metadata=True)
                        existing = self._sql_state_manager.get_entity(entity_id)
                        if existing:
                            # 合并 current
                            current = existing.get("current_json", {})
                            if isinstance(current, str):
                                import json
                                current = json.loads(current) if current else {}
                            if effective_current_updates:
                                current.update(effective_current_updates)

                            new_canonical_name = patch.top_updates.get("canonical_name")
                            old_canonical_name = existing.get("canonical_name", "")

                            entity_meta = EntityMeta(
                                id=entity_id,
                                type=existing.get("type", entity_type),
                                canonical_name=new_canonical_name or old_canonical_name,
                                tier=patch.top_updates.get("tier", existing.get("tier", "装饰")),
                                desc=patch.top_updates.get("desc", existing.get("desc", "")),
                                current=current,
                                first_appearance=existing.get("first_appearance", 0),
                                last_appearance=patch.appearance_chapter or existing.get("last_appearance", 0),
                                is_protagonist=patch.top_updates.get("is_protagonist", existing.get("is_protagonist", False)),
                                is_archived=patch.top_updates.get("is_archived", existing.get("is_archived", False))
                            )
                            self._sql_state_manager._index_manager.upsert_entity(entity_meta, update_metadata=True)

                            # 如果 canonical_name 改名，自动注册新名字为 alias
                            if new_canonical_name and new_canonical_name != old_canonical_name:
                                self._sql_state_manager.register_alias(
                                    new_canonical_name, entity_id, existing.get("type", entity_type)
                                )
                    elif effective_current_updates:
                        # 只有 current 更新（包括非元数据的 top_updates）
                        self._sql_state_manager.update_entity_current(entity_id, effective_current_updates)

                    # 更新 last_appearance 并记录出场
                    if patch.appearance_chapter is not None:
                        self._sql_state_manager._update_last_appearance(entity_id, patch.appearance_chapter)
                        # 补充 appearances 记录
                        # 使用 skip_if_exists=True 避免覆盖已有记录的 mentions
                        if (entity_id, patch.appearance_chapter) not in processed_appearances:
                            self._sql_state_manager._index_manager.record_appearance(
                                entity_id=entity_id,
                                chapter=patch.appearance_chapter,
                                mentions=[],
                                confidence=1.0,
                                skip_if_exists=True  # 关键：不覆盖已有记录
                            )

            # 同步别名
            for alias, entries in self._pending_alias_entries.items():
                for entry in entries:
                    entity_type = entry.get("type")
                    entity_id = entry.get("id")
                    if entity_type and entity_id:
                        self._sql_state_manager.register_alias(alias, entity_id, entity_type)

            # 同步状态变化
            for change in self._pending_state_changes:
                self._sql_state_manager.record_state_change(
                    entity_id=change.get("entity_id", ""),
                    field=change.get("field", ""),
                    old_value=change.get("old", change.get("old_value", "")),
                    new_value=change.get("new", change.get("new_value", "")),
                    reason=change.get("reason", ""),
                    chapter=change.get("chapter", 0)
                )

            # 同步关系
            for rel in self._pending_structured_relationships:
                self._sql_state_manager.upsert_relationship(
                    from_entity=rel.get("from_entity", ""),
                    to_entity=rel.get("to_entity", ""),
                    type=rel.get("type", "相识"),
                    description=rel.get("description", ""),
                    chapter=rel.get("chapter", 0)
                )

            return True

        except Exception as e:
            # SQLite 同步失败时记录警告（不中断主流程）
            logger.warning("SQLite sync failed: %s", e)
            return False

    def _snapshot_sqlite_pending(self) -> Dict[str, Any]:
        """抓取 SQLite 侧 pending 快照，用于同步失败回滚内存队列。"""
        return {
            "entity_patches": deepcopy(self._pending_entity_patches),
            "alias_entries": deepcopy(self._pending_alias_entries),
            "state_changes": deepcopy(self._pending_state_changes),
            "structured_relationships": deepcopy(self._pending_structured_relationships),
            "sqlite_data": deepcopy(self._pending_sqlite_data),
        }

    def _restore_sqlite_pending(self, snapshot: Dict[str, Any]) -> None:
        """恢复 SQLite 侧 pending 快照，避免同步失败后数据静默丢失。"""
        self._pending_entity_patches = snapshot.get("entity_patches", {})
        self._pending_alias_entries = snapshot.get("alias_entries", {})
        self._pending_state_changes = snapshot.get("state_changes", [])
        self._pending_structured_relationships = snapshot.get("structured_relationships", [])
        self._pending_sqlite_data = snapshot.get("sqlite_data", {
            "entities_appeared": [],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "scenes": [],
            "scenes_provided": False,
            "chapter": None,
            "chapter_index": None,
        })

    def _clear_pending_sqlite_data(self):
        """清空待同步的 SQLite 数据"""
        self._pending_sqlite_data = {
            "entities_appeared": [],
            "entities_new": [],
            "state_changes": [],
            "relationships_new": [],
            "scenes": [],
            "scenes_provided": False,
            "chapter": None,
            "chapter_index": None,
        }

    # ==================== 进度管理 ====================

    def get_current_chapter(self) -> int:
        """获取当前章节号"""
        return self._state.get("progress", {}).get("current_chapter", 0)

    def update_progress(self, chapter: int, words: int = 0):
        """更新进度"""
        if "progress" not in self._state:
            self._state["progress"] = {}
        self._state["progress"]["current_chapter"] = chapter
        if words > 0:
            total = self._state["progress"].get("total_words", 0)
            self._state["progress"]["total_words"] = total + words

        # 记录增量：锁内合并时用 max(chapter) + words_delta 累加
        if self._pending_progress_chapter is None:
            self._pending_progress_chapter = chapter
        else:
            self._pending_progress_chapter = max(self._pending_progress_chapter, chapter)
        if words > 0:
            self._pending_progress_words_delta += int(words)

    # ==================== 实体管理 (v5.1 SQLite-first) ====================

    def get_entity(self, entity_id: str, entity_type: str = None) -> Optional[Dict]:
        """获取实体（v5.1 引入：优先从 SQLite 读取）"""
        # v5.1 引入: 优先从 SQLite 读取
        if self._sql_state_manager:
            entity = self._sql_state_manager._index_manager.get_entity(entity_id)
            if entity:
                return entity

        # 回退到内存 state (兼容未迁移场景)
        entities_v3 = self._state.get("entities_v3", {})
        if entity_type:
            return entities_v3.get(entity_type, {}).get(entity_id)

        # 遍历所有类型查找
        for type_name, entities in entities_v3.items():
            if entity_id in entities:
                return entities[entity_id]
        return None

    def get_entity_type(self, entity_id: str) -> Optional[str]:
        """获取实体所属类型"""
        # v5.1 引入: 优先从 SQLite 读取
        if self._sql_state_manager:
            entity = self._sql_state_manager._index_manager.get_entity(entity_id)
            if entity:
                return entity.get("type")

        # 回退到内存 state
        for type_name, entities in self._state.get("entities_v3", {}).items():
            if entity_id in entities:
                return type_name
        return None

    def get_all_entities(self) -> Dict[str, Dict]:
        """获取所有实体（扁平化视图）"""
        # v5.1 引入: 优先从 SQLite 读取
        if self._sql_state_manager:
            result = {}
            for entity_type in self.ENTITY_TYPES:
                entities = self._sql_state_manager._index_manager.get_entities_by_type(entity_type)
                for e in entities:
                    eid = e.get("id")
                    if eid:
                        result[eid] = {**e, "type": entity_type}
            if result:
                return result

        # 回退到内存 state
        result = {}
        for type_name, entities in self._state.get("entities_v3", {}).items():
            for eid, e in entities.items():
                result[eid] = {**e, "type": type_name}
        return result

    def get_entities_by_type(self, entity_type: str) -> Dict[str, Dict]:
        """按类型获取实体"""
        # v5.1 引入: 优先从 SQLite 读取
        if self._sql_state_manager:
            entities = self._sql_state_manager._index_manager.get_entities_by_type(entity_type)
            if entities:
                return {e.get("id"): e for e in entities if e.get("id")}

        # 回退到内存 state
        return self._state.get("entities_v3", {}).get(entity_type, {})

    def get_entities_by_tier(self, tier: str) -> Dict[str, Dict]:
        """按层级获取实体"""
        # v5.1 引入: 优先从 SQLite 读取
        if self._sql_state_manager:
            result = {}
            for entity_type in self.ENTITY_TYPES:
                entities = self._sql_state_manager._index_manager.get_entities_by_tier(tier)
                for e in entities:
                    eid = e.get("id")
                    if eid and e.get("type") == entity_type:
                        result[eid] = {**e, "type": entity_type}
            if result:
                return result

        # 回退到内存 state
        result = {}
        for type_name, entities in self._state.get("entities_v3", {}).items():
            for eid, e in entities.items():
                if e.get("tier") == tier:
                    result[eid] = {**e, "type": type_name}
        return result

    def add_entity(self, entity: EntityState) -> bool:
        """添加新实体（v5.0 entities_v3 格式，v5.4 沿用）"""
        entity_type = entity.type
        if entity_type not in self.ENTITY_TYPES:
            entity_type = "角色"

        if "entities_v3" not in self._state:
            self._state["entities_v3"] = {t: {} for t in self.ENTITY_TYPES}

        if entity_type not in self._state["entities_v3"]:
            self._state["entities_v3"][entity_type] = {}

        # 检查是否已存在
        if entity.id in self._state["entities_v3"][entity_type]:
            return False

        # 转换为 v3 格式
        v3_entity = {
            "canonical_name": entity.name,
            "tier": entity.tier,
            "desc": "",
            "current": entity.attributes,
            "first_appearance": entity.first_appearance,
            "last_appearance": entity.last_appearance,
            "history": []
        }
        self._state["entities_v3"][entity_type][entity.id] = v3_entity

        # 记录实体补丁（新建：仅填充缺失字段，避免覆盖并发写入）
        patch = self._pending_entity_patches.get((entity_type, entity.id))
        if patch is None:
            patch = _EntityPatch(entity_type=entity_type, entity_id=entity.id)
            self._pending_entity_patches[(entity_type, entity.id)] = patch
        patch.replace = True
        patch.base_entity = v3_entity

        # v5.1 引入: 注册别名到 index.db (通过 SQLStateManager)
        if self._sql_state_manager:
            self._sql_state_manager._index_manager.register_alias(entity.name, entity.id, entity_type)
            for alias in entity.aliases:
                if alias:
                    self._sql_state_manager._index_manager.register_alias(alias, entity.id, entity_type)

        return True

    def _register_alias_internal(self, entity_id: str, entity_type: str, alias: str):
        """内部方法：注册别名到 index.db（v5.1 引入）"""
        if not alias:
            return
        # v5.1 引入: 直接写入 SQLite
        if self._sql_state_manager:
            self._sql_state_manager._index_manager.register_alias(alias, entity_id, entity_type)

    def update_entity(self, entity_id: str, updates: Dict[str, Any], entity_type: str = None) -> bool:
        """更新实体属性（v5.0 引入，v5.4 沿用）"""
        # v5.1+ SQLite-first:
        # - entity_type 可能来自 SQLite（entities 表），但 state.json 不再持久化 entities_v3。
        # - 因此不能假设 self._state["entities_v3"][type][id] 一定存在（issues7 日志曾 KeyError）。
        resolved_type = entity_type or self.get_entity_type(entity_id)
        if not resolved_type:
            return False
        if resolved_type not in self.ENTITY_TYPES:
            resolved_type = "角色"

        # 仅在内存存在 v3 实体时才更新内存快照（不强行创建，避免 state.json 再膨胀）
        entities_v3 = self._state.get("entities_v3")
        entity = None
        if isinstance(entities_v3, dict):
            bucket = entities_v3.get(resolved_type)
            if isinstance(bucket, dict):
                entity = bucket.get(entity_id)

        # SQLite 启用时，即使内存实体缺失，也要记录 patch，确保 current 能增量写回 index.db
        patch = None
        if self._sql_state_manager:
            patch = self._pending_entity_patches.get((resolved_type, entity_id))
            if patch is None:
                patch = _EntityPatch(entity_type=resolved_type, entity_id=entity_id)
                self._pending_entity_patches[(resolved_type, entity_id)] = patch

        if entity is None and patch is None:
            return False

        did_any = False
        for key, value in updates.items():
            if key == "attributes" and isinstance(value, dict):
                if entity is not None:
                    if "current" not in entity:
                        entity["current"] = {}
                    entity["current"].update(value)
                if patch is not None:
                    patch.current_updates.update(value)
                did_any = True
            elif key == "current" and isinstance(value, dict):
                if entity is not None:
                    if "current" not in entity:
                        entity["current"] = {}
                    entity["current"].update(value)
                if patch is not None:
                    patch.current_updates.update(value)
                did_any = True
            else:
                if entity is not None:
                    entity[key] = value
                if patch is not None:
                    patch.top_updates[key] = value
                did_any = True

        return did_any

    def update_entity_appearance(self, entity_id: str, chapter: int, entity_type: str = None):
        """更新实体出场章节"""
        if not entity_type:
            entity_type = self.get_entity_type(entity_id)
        if not entity_type:
            return

        entities_v3 = self._state.get("entities_v3")
        if not isinstance(entities_v3, dict):
            entities_v3 = {t: {} for t in self.ENTITY_TYPES}
            self._state["entities_v3"] = entities_v3
        entities_v3.setdefault(entity_type, {})

        entity = entities_v3[entity_type].get(entity_id)
        if entity:
            if entity.get("first_appearance", 0) == 0:
                entity["first_appearance"] = chapter
            entity["last_appearance"] = chapter

            # 记录补丁：锁内应用 first=min(non-zero), last=max
            patch = self._pending_entity_patches.get((entity_type, entity_id))
            if patch is None:
                patch = _EntityPatch(entity_type=entity_type, entity_id=entity_id)
                self._pending_entity_patches[(entity_type, entity_id)] = patch
            if patch.appearance_chapter is None:
                patch.appearance_chapter = chapter
            else:
                patch.appearance_chapter = max(int(patch.appearance_chapter), int(chapter))

    # ==================== 状态变化记录 ====================

    def record_state_change(
        self,
        entity_id: str,
        field: str,
        old_value: Any,
        new_value: Any,
        reason: str,
        chapter: int
    ):
        """记录状态变化"""
        if "state_changes" not in self._state:
            self._state["state_changes"] = []

        change = StateChange(
            entity_id=entity_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            chapter=chapter
        )
        change_dict = asdict(change)
        self._state["state_changes"].append(change_dict)
        self._pending_state_changes.append(change_dict)

        # 同时更新实体属性
        self.update_entity(entity_id, {"attributes": {field: new_value}})

    def get_state_changes(self, entity_id: Optional[str] = None) -> List[Dict]:
        """获取状态变化历史"""
        changes = self._state.get("state_changes", [])
        if entity_id:
            changes = [c for c in changes if c.get("entity_id") == entity_id]
        return changes

    # ==================== 关系管理 ====================

    def add_relationship(
        self,
        from_entity: str,
        to_entity: str,
        rel_type: str,
        description: str,
        chapter: int
    ):
        """添加关系"""
        rel = Relationship(
            from_entity=from_entity,
            to_entity=to_entity,
            type=rel_type,
            description=description,
            chapter=chapter
        )

        # v5.0 引入: 实体关系存入 structured_relationships，避免与 relationships(人物关系字典) 冲突
        if "structured_relationships" not in self._state:
            self._state["structured_relationships"] = []
        rel_dict = asdict(rel)
        self._state["structured_relationships"].append(rel_dict)
        self._pending_structured_relationships.append(rel_dict)

    def get_relationships(self, entity_id: Optional[str] = None) -> List[Dict]:
        """获取关系列表"""
        rels = self._state.get("structured_relationships", [])
        if entity_id:
            rels = [
                r for r in rels
                if r.get("from_entity") == entity_id or r.get("to_entity") == entity_id
            ]
        return rels

    # ==================== 批量操作 ====================

    def _record_disambiguation(self, chapter: int, uncertain_items: Any) -> List[str]:
        """
        记录消歧反馈到 state.json，便于 Writer/Context Agent 感知风险。

        约定：
        - >= extraction_confidence_medium：写入 disambiguation_warnings（采用但警告）
        - < extraction_confidence_medium：写入 disambiguation_pending（需人工确认）
        """
        if not isinstance(uncertain_items, list) or not uncertain_items:
            return []

        warnings: List[str] = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for item in uncertain_items:
            if not isinstance(item, dict):
                continue

            mention = str(item.get("mention", "") or "").strip()
            if not mention:
                continue

            raw_conf = item.get("confidence", 0.0)
            try:
                confidence = float(raw_conf)
            except (TypeError, ValueError):
                confidence = 0.0

            # 候选：支持 [{"type","id"}...] 或 ["id1","id2"] 两种形式
            candidates_raw = item.get("candidates", [])
            candidates: List[Dict[str, str]] = []
            if isinstance(candidates_raw, list):
                for c in candidates_raw:
                    if isinstance(c, dict):
                        cid = str(c.get("id", "") or "").strip()
                        ctype = str(c.get("type", "") or "").strip()
                        entry: Dict[str, str] = {}
                        if ctype:
                            entry["type"] = ctype
                        if cid:
                            entry["id"] = cid
                        if entry:
                            candidates.append(entry)
                    else:
                        cid = str(c).strip()
                        if cid:
                            candidates.append({"id": cid})

            entity_type = str(item.get("type", "") or "").strip()
            suggested_id = str(item.get("suggested", "") or "").strip()

            adopted_raw = item.get("adopted", None)
            chosen_id = ""
            if isinstance(adopted_raw, str):
                chosen_id = adopted_raw.strip()
            elif adopted_raw is True:
                chosen_id = suggested_id
            else:
                # 兼容字段名：entity_id / chosen_id
                chosen_id = str(item.get("entity_id") or item.get("chosen_id") or "").strip() or suggested_id

            context = str(item.get("context", "") or "").strip()
            note = str(item.get("warning", "") or "").strip()

            record: Dict[str, Any] = {
                "chapter": int(chapter),
                "mention": mention,
                "type": entity_type,
                "suggested_id": suggested_id,
                "chosen_id": chosen_id,
                "confidence": confidence,
                "candidates": candidates,
                "context": context,
                "note": note,
                "created_at": now,
            }

            if confidence >= float(self.config.extraction_confidence_medium):
                self._state.setdefault("disambiguation_warnings", []).append(record)
                self._pending_disambiguation_warnings.append(record)
                chosen_part = f" → {chosen_id}" if chosen_id else ""
                warnings.append(f"消歧警告: {mention}{chosen_part} (confidence: {confidence:.2f})")
            else:
                self._state.setdefault("disambiguation_pending", []).append(record)
                self._pending_disambiguation_pending.append(record)
                warnings.append(f"消歧需人工确认: {mention} (confidence: {confidence:.2f})")

        return warnings

    def process_chapter_result(self, chapter: int, result: Dict) -> List[str]:
        """
        处理 Data Agent 的章节处理结果（v5.1 引入，v5.4 沿用）

        输入格式:
        - entities_appeared: 出场实体列表
        - entities_new: 新实体列表
        - state_changes: 状态变化列表
        - relationships_new: 新关系列表

        返回警告列表
        """
        warnings = []

        # v5.1 引入: 记录章节号用于 SQLite 同步
        self._pending_sqlite_data["chapter"] = chapter
        self._pending_sqlite_data["chapter_index"] = self._build_chapter_index_snapshot(chapter, result)
        self._pending_sqlite_data["scenes"] = []
        self._pending_sqlite_data["scenes_provided"] = False

        # 处理出场实体
        for entity in result.get("entities_appeared", []):
            entity_id = entity.get("id")
            entity_type = entity.get("type")
            if entity_id:
                self.update_entity_appearance(entity_id, chapter, entity_type)
                # v5.1 引入: 缓存用于 SQLite 同步
                self._pending_sqlite_data["entities_appeared"].append(entity)

        # 处理新实体
        for entity in result.get("entities_new", []):
            entity_id = entity.get("suggested_id") or entity.get("id")
            if entity_id and entity_id != "NEW":
                new_entity = EntityState(
                    id=entity_id,
                    name=entity.get("name", ""),
                    type=entity.get("type", "角色"),
                    tier=entity.get("tier", "装饰"),
                    aliases=entity.get("mentions", []),
                    first_appearance=chapter,
                    last_appearance=chapter
                )
                if not self.add_entity(new_entity):
                    warnings.append(f"实体已存在: {entity_id}")
                # v5.1 引入: 缓存用于 SQLite 同步
                self._pending_sqlite_data["entities_new"].append(entity)

        # 处理状态变化
        for change in result.get("state_changes", []):
            self.record_state_change(
                entity_id=change.get("entity_id", ""),
                field=change.get("field", ""),
                old_value=change.get("old"),
                new_value=change.get("new"),
                reason=change.get("reason", ""),
                chapter=chapter
            )
            # v5.1 引入: 缓存用于 SQLite 同步
            self._pending_sqlite_data["state_changes"].append(change)

        # 处理关系
        for rel in result.get("relationships_new", []):
            self.add_relationship(
                from_entity=rel.get("from", ""),
                to_entity=rel.get("to", ""),
                rel_type=rel.get("type", ""),
                description=rel.get("description", ""),
                chapter=chapter
            )
            # v5.1 引入: 缓存用于 SQLite 同步
            self._pending_sqlite_data["relationships_new"].append(rel)

        # 处理消歧不确定项（不影响实体写入，但必须对 Writer 可见）
        warnings.extend(self._record_disambiguation(chapter, result.get("uncertain", [])))

        normalized_foreshadowing: List[Dict[str, Any]] = []
        for item in result.get("foreshadowing", []):
            normalized_item = self._normalize_foreshadowing_row(chapter, item)
            if normalized_item:
                normalized_foreshadowing.append(normalized_item)

        if normalized_foreshadowing:
            plot_threads = self._state.setdefault("plot_threads", {})
            foreshadowing = plot_threads.get("foreshadowing")
            if not isinstance(foreshadowing, list):
                foreshadowing = []
            planned_mode = self._has_outline_foreshadowing(foreshadowing)
            accepted_items: List[Dict[str, Any]] = []
            for item in normalized_foreshadowing:
                if planned_mode and self._find_matching_foreshadowing_index(foreshadowing, item) is None:
                    warnings.append(f"未匹配到规划伏笔，已忽略: {item['content']}")
                    continue
                accepted_items.append(item)

            if accepted_items:
                plot_threads["foreshadowing"] = self._merge_foreshadowing_rows(
                    foreshadowing,
                    accepted_items,
                )
                self._pending_foreshadowing.extend(accepted_items)

        # 写入 chapter_meta（钩子/模式/结束状态）
        chapter_meta = result.get("chapter_meta")
        if isinstance(chapter_meta, dict):
            meta_key = f"{int(chapter):04d}"
            self._state.setdefault("chapter_meta", {})
            self._state["chapter_meta"][meta_key] = chapter_meta
            self._pending_chapter_meta[meta_key] = chapter_meta

        raw_scenes = result.get("scenes")
        if raw_scenes is not None:
            self._pending_sqlite_data["scenes_provided"] = True
            if isinstance(raw_scenes, list):
                self._pending_sqlite_data["scenes"] = [
                    scene for scene in raw_scenes if isinstance(scene, dict)
                ]

        # 更新进度
        self.update_progress(chapter)

        # 同步主角状态（entities_v3 → protagonist_state）
        self.sync_protagonist_from_entity()

        return warnings

    def _build_chapter_index_snapshot(self, chapter: int, result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        chapter_file = find_chapter_file(self.config.project_root, chapter)
        content = ""
        if chapter_file and chapter_file.exists():
            try:
                content = chapter_file.read_text(encoding="utf-8")
            except OSError:
                content = ""

        title = self._extract_chapter_title(chapter, content, chapter_file)
        location = self._resolve_chapter_location(chapter, result)
        word_count = self._count_chapter_words(content)
        characters = self._collect_chapter_character_ids(chapter, result)
        summary = self._load_chapter_summary(chapter, content)

        if not any([title, location, word_count, characters, summary]):
            return None

        return {
            "chapter": int(chapter),
            "title": title,
            "location": location,
            "word_count": word_count,
            "characters": characters,
            "summary": summary,
        }

    def _extract_chapter_title(self, chapter: int, content: str, chapter_file: Optional[Path]) -> str:
        if content:
            match = _CHAPTER_TITLE_RE.search(content)
            if match:
                return str(match.group(1) or "").strip()

            for line in content.splitlines():
                stripped = line.strip()
                if not stripped.startswith("#"):
                    continue
                text = re.sub(r"^\s*#+\s*", "", stripped).strip()
                text = re.sub(r"^第\s*\d+\s*章(?:\s*[-—:：]\s*|\s+)?", "", text).strip()
                if text:
                    return text

        if chapter_file is not None:
            stem = chapter_file.stem
            parts = re.split(r"[-—:：]", stem, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

        return f"第{int(chapter):04d}章"

    def _count_chapter_words(self, content: str) -> int:
        if not content:
            return 0
        text = re.sub(r"```[\s\S]*?```", "", content)
        text = re.sub(r"^\s*#+\s+.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*---+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"\s+", "", text)
        return len(text)

    def _extract_summary_section(self, text: str) -> str:
        if not text:
            return ""
        match = _SUMMARY_SECTION_RE.search(text)
        if not match:
            return ""
        return str(match.group(1) or "").strip()

    def _load_chapter_summary(self, chapter: int, chapter_content: str) -> str:
        summary_path = self.config.webnovel_dir / "summaries" / f"ch{int(chapter):04d}.md"
        if summary_path.exists():
            try:
                summary = self._extract_summary_section(summary_path.read_text(encoding="utf-8"))
                if summary:
                    return summary
            except OSError:
                pass

        return self._extract_summary_section(chapter_content)

    def _collect_chapter_character_ids(self, chapter: int, result: Dict[str, Any]) -> List[str]:
        seen: set[str] = set()
        characters: List[str] = []

        def _append(entity_id: Any) -> None:
            normalized = str(entity_id or "").strip()
            if not normalized or normalized in seen:
                return
            characters.append(normalized)
            seen.add(normalized)

        for entity in result.get("entities_appeared", []):
            if str(entity.get("type") or "").strip() == "角色":
                _append(entity.get("id"))

        for entity in result.get("entities_new", []):
            if str(entity.get("type") or "").strip() == "角色":
                _append(entity.get("suggested_id") or entity.get("id"))

        if characters:
            return characters

        if self._sql_state_manager:
            existing = self._sql_state_manager._index_manager.get_chapter(chapter)
            existing_characters = existing.get("characters") if isinstance(existing, dict) else None
            if isinstance(existing_characters, list):
                for entity_id in existing_characters:
                    _append(entity_id)

            for appearance in self._sql_state_manager._index_manager.get_chapter_appearances(chapter):
                entity_id = appearance.get("entity_id")
                if not entity_id:
                    continue
                entity = self._sql_state_manager._index_manager.get_entity(entity_id)
                if entity and str(entity.get("type") or "").strip() == "角色":
                    _append(entity_id)

        return characters

    def _resolve_chapter_location(self, chapter: int, result: Dict[str, Any]) -> str:
        chapter_meta = result.get("chapter_meta")
        if isinstance(chapter_meta, dict):
            ending = chapter_meta.get("ending")
            if isinstance(ending, dict):
                location = str(ending.get("location") or "").strip()
                if location:
                    return location

        stored_meta = self._state.get("chapter_meta", {})
        if isinstance(stored_meta, dict):
            entry = stored_meta.get(f"{int(chapter):04d}") or stored_meta.get(str(int(chapter)))
            if isinstance(entry, dict):
                ending = entry.get("ending")
                if isinstance(ending, dict):
                    location = str(ending.get("location") or "").strip()
                    if location:
                        return location

        protagonist_location = self._state.get("protagonist_state", {}).get("location")
        if isinstance(protagonist_location, dict):
            location = str(protagonist_location.get("current") or "").strip()
            if location:
                return location
        elif protagonist_location:
            location = str(protagonist_location).strip()
            if location:
                return location

        if self._sql_state_manager:
            existing = self._sql_state_manager._index_manager.get_chapter(chapter)
            if isinstance(existing, dict):
                location = str(existing.get("location") or "").strip()
                if location:
                    return location

        return ""

    def _normalize_foreshadowing_row(self, chapter: int, item: Any) -> Optional[Dict[str, Any]]:
        if isinstance(item, str):
            item = {"content": item}
        if not isinstance(item, dict):
            return None

        raw_action = str(item.get("action") or "").strip().lower()
        normalized = normalize_foreshadowing_item(item)

        content = str(normalized.get("content") or normalized.get("description") or "").strip()
        if not content:
            return None
        normalized["content"] = content

        if raw_action in {"回收", "兑现", "resolve", "resolved"} or normalized.get("status") == FORESHADOWING_STATUS_RESOLVED:
            normalized["status"] = FORESHADOWING_STATUS_RESOLVED
            normalized.setdefault("resolved_chapter", chapter)
        else:
            normalized["status"] = FORESHADOWING_STATUS_PENDING
            normalized.setdefault("planted_chapter", chapter)

        return normalized

    def _normalize_foreshadowing_text(self, text: Any) -> str:
        return _FORESHADOWING_TEXT_STRIP_RE.sub("", str(text or "").strip())

    def _foreshadowing_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        if left in right or right in left:
            return 0.92

        left_bigrams = {left[i : i + 2] for i in range(max(0, len(left) - 1))} or {left}
        right_bigrams = {right[i : i + 2] for i in range(max(0, len(right) - 1))} or {right}
        union = left_bigrams | right_bigrams
        if not union:
            return 0.0
        bigram_score = len(left_bigrams & right_bigrams) / len(union)

        prev_row = [0] * (len(right) + 1)
        longest = 0
        for left_char in left:
            current_row = [0] * (len(right) + 1)
            for idx, right_char in enumerate(right, start=1):
                if left_char == right_char:
                    current_row[idx] = prev_row[idx - 1] + 1
                    longest = max(longest, current_row[idx])
            prev_row = current_row

        lcs_score = longest / max(1, min(len(left), len(right)))
        return max(bigram_score, lcs_score)

    def _find_matching_foreshadowing_index(self, rows: List[Dict[str, Any]], item: Dict[str, Any]) -> Optional[int]:
        content = self._normalize_foreshadowing_text(item.get("content"))
        if not content:
            return None

        best_idx: Optional[int] = None
        best_score = 0.0
        for idx, row in enumerate(rows):
            row_content = self._normalize_foreshadowing_text(row.get("content"))
            score = self._foreshadowing_similarity(content, row_content)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_score >= 0.35:
            return best_idx
        return None

    def _has_outline_foreshadowing(self, rows: List[Dict[str, Any]]) -> bool:
        return any(str(row.get("source") or "").strip() == "outline" for row in rows if isinstance(row, dict))

    def _merge_foreshadowing_rows(self, base_rows: Any, new_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []

        if isinstance(base_rows, list):
            for raw_row in base_rows:
                if not isinstance(raw_row, dict):
                    continue
                normalized = normalize_foreshadowing_item(raw_row)
                content = str(normalized.get("content") or "").strip()
                if not content:
                    continue
                normalized["content"] = content
                rows.append(normalized)

        for raw_row in new_rows:
            if not isinstance(raw_row, dict):
                continue
            normalized = normalize_foreshadowing_item(raw_row)
            content = str(normalized.get("content") or "").strip()
            if not content:
                continue
            normalized["content"] = content

            existing_idx = self._find_matching_foreshadowing_index(rows, normalized)
            if existing_idx is None:
                rows.append(normalized)
                continue

            merged = dict(rows[existing_idx])
            incoming = dict(normalized)
            incoming.pop("content", None)
            if incoming.get("source") != "outline":
                if merged.get("tier"):
                    incoming.pop("tier", None)
                if merged.get("planted_chapter") is not None:
                    incoming.pop("planted_chapter", None)
                if merged.get("target_chapter") is not None:
                    incoming.pop("target_chapter", None)
            merged.update(incoming)
            if "planted_chapter" not in normalized and rows[existing_idx].get("planted_chapter") is not None:
                merged["planted_chapter"] = rows[existing_idx]["planted_chapter"]
            if "resolved_chapter" not in normalized and rows[existing_idx].get("resolved_chapter") is not None:
                merged["resolved_chapter"] = rows[existing_idx]["resolved_chapter"]
            rows[existing_idx] = normalize_foreshadowing_item(merged)

        return rows

    # ==================== 导出 ====================

    def export_for_context(self) -> Dict:
        """导出用于上下文的精简版状态（v5.0 引入，v5.4 沿用）"""
        # 从 entities_v3 构建精简视图
        entities_flat = {}
        for type_name, entities in self._state.get("entities_v3", {}).items():
            for eid, e in entities.items():
                entities_flat[eid] = {
                    "name": e.get("canonical_name", eid),
                    "type": type_name,
                    "tier": e.get("tier", "装饰"),
                    "current": e.get("current", {})
                }

        return {
            "progress": self._state.get("progress", {}),
            "entities": entities_flat,
            # v5.1 引入: alias_index 已迁移到 index.db，这里返回空（兼容性）
            "alias_index": {},
            "recent_changes": [],  # v5.1 引入: 从 index.db 查询
            "disambiguation": {
                "warnings": self._state.get("disambiguation_warnings", [])[-self.config.export_disambiguation_slice:],
                "pending": self._state.get("disambiguation_pending", [])[-self.config.export_disambiguation_slice:],
            },
        }

    # ==================== 主角同步 ====================

    def get_protagonist_entity_id(self) -> Optional[str]:
        """获取主角实体 ID（通过 is_protagonist 标记或 SQLite 查询）"""
        # 方式1: 通过 SQLStateManager 查询 (v5.1)
        if self._sql_state_manager:
            protagonist = self._sql_state_manager.get_protagonist()
            if protagonist:
                return protagonist.get("id")

        # 方式2: 通过 protagonist_state.name 查找别名
        protag_name = self._state.get("protagonist_state", {}).get("name")
        if protag_name and self._sql_state_manager:
            entities = self._sql_state_manager._index_manager.get_entities_by_alias(protag_name)
            for entry in entities:
                if entry.get("type") == "角色":
                    return entry.get("id")

        return None

    def sync_protagonist_from_entity(self, entity_id: str = None):
        """
        将主角实体的状态同步到 protagonist_state (v5.1: 从 SQLite 读取)

        用于确保 consistency-checker 等依赖 protagonist_state 的组件获取最新数据
        """
        if entity_id is None:
            entity_id = self.get_protagonist_entity_id()
        if entity_id is None:
            return

        entity = self.get_entity(entity_id, "角色")
        if not entity:
            return

        current = entity.get("current")
        if not isinstance(current, dict):
            current = entity.get("current_json", {})
        if isinstance(current, str):
            try:
                current = json.loads(current) if current else {}
            except (json.JSONDecodeError, TypeError):
                current = {}
        if not isinstance(current, dict):
            current = {}
        protag = self._state.setdefault("protagonist_state", {})

        # 同步境界
        if "realm" in current:
            power = protag.setdefault("power", {})
            power["realm"] = current["realm"]
            if "layer" in current:
                power["layer"] = current["layer"]

        # 同步位置
        if "location" in current:
            loc = protag.setdefault("location", {})
            loc["current"] = current["location"]
            if "last_chapter" in current:
                loc["last_chapter"] = current["last_chapter"]

    def sync_protagonist_to_entity(self, entity_id: str = None):
        """
        将 protagonist_state 同步到 entities_v3 中的主角实体

        用于初始化或手动编辑 protagonist_state 后保持一致性
        """
        if entity_id is None:
            entity_id = self.get_protagonist_entity_id()
        if entity_id is None:
            return

        protag = self._state.get("protagonist_state", {})
        if not protag:
            return

        updates = {}

        # 同步境界
        power = protag.get("power", {})
        if power.get("realm"):
            updates["realm"] = power["realm"]
        if power.get("layer"):
            updates["layer"] = power["layer"]

        # 同步位置
        loc = protag.get("location", {})
        if loc.get("current"):
            updates["location"] = loc["current"]

        if updates:
            self.update_entity(entity_id, updates, "角色")


def refresh_health_report(project_root: Path) -> Optional[str]:
    try:
        from status_reporter import StatusReporter
    except ImportError:  # pragma: no cover
        try:
            from scripts.status_reporter import StatusReporter
        except ImportError as exc:  # pragma: no cover
            return f"健康报告刷新失败: {exc}"

    try:
        reporter = StatusReporter(str(project_root))
        if not reporter.load_state():
            return "健康报告刷新失败: 无法加载 state.json"
        reporter.scan_chapters()
        report = reporter.generate_report("all")
        output_path = Path(project_root) / ".webnovel" / "health_report.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        return f"健康报告刷新失败: {exc}"

    return None


# ==================== CLI 接口 ====================

def main():
    import argparse
    import sys
    from .cli_output import print_success, print_error
    from .cli_args import normalize_global_project_root, load_json_arg
    from .index_manager import IndexManager

    parser = argparse.ArgumentParser(description="State Manager CLI (v5.4)")
    parser.add_argument("--project-root", type=str, help="项目根目录")

    subparsers = parser.add_subparsers(dest="command")

    # 读取进度
    subparsers.add_parser("get-progress")

    # 获取实体
    get_entity_parser = subparsers.add_parser("get-entity")
    get_entity_parser.add_argument("--id", required=True)

    # 列出实体
    list_parser = subparsers.add_parser("list-entities")
    list_parser.add_argument("--type", help="按类型过滤")
    list_parser.add_argument("--tier", help="按层级过滤")

    # 处理章节结果
    process_parser = subparsers.add_parser("process-chapter")
    process_parser.add_argument("--chapter", type=int, required=True, help="章节号")
    process_parser.add_argument("--data", required=True, help="JSON 格式的处理结果")

    argv = normalize_global_project_root(sys.argv[1:])
    args = parser.parse_args(argv)
    command_started_at = time.perf_counter()

    # 初始化
    config = None
    if args.project_root:
        # 允许传入“工作区根目录”，统一解析到真正的 book project_root（必须包含 .webnovel/state.json）
        from project_locator import resolve_project_root
        from .config import DataModulesConfig

        resolved_root = resolve_project_root(args.project_root)
        config = DataModulesConfig.from_project_root(resolved_root)

    manager = StateManager(config)
    logger = IndexManager(config)
    tool_name = f"state_manager:{args.command or 'unknown'}"

    def _append_timing(success: bool, *, error_code: str | None = None, error_message: str | None = None, chapter: int | None = None):
        elapsed_ms = int((time.perf_counter() - command_started_at) * 1000)
        safe_append_perf_timing(
            manager.config.project_root,
            tool_name=tool_name,
            success=success,
            elapsed_ms=elapsed_ms,
            chapter=chapter,
            error_code=error_code,
            error_message=error_message,
        )

    def emit_success(data=None, message: str = "ok", chapter: int | None = None):
        print_success(data, message=message)
        safe_log_tool_call(logger, tool_name=tool_name, success=True)
        _append_timing(True, chapter=chapter)

    def emit_error(code: str, message: str, suggestion: str | None = None, chapter: int | None = None):
        print_error(code, message, suggestion=suggestion)
        safe_log_tool_call(
            logger,
            tool_name=tool_name,
            success=False,
            error_code=code,
            error_message=message,
        )
        _append_timing(False, error_code=code, error_message=message, chapter=chapter)

    if args.command == "get-progress":
        emit_success(manager._state.get("progress", {}), message="progress")

    elif args.command == "get-entity":
        entity = manager.get_entity(args.id)
        if entity:
            emit_success(entity, message="entity")
        else:
            emit_error("NOT_FOUND", f"未找到实体: {args.id}")

    elif args.command == "list-entities":
        if args.type:
            entities = manager.get_entities_by_type(args.type)
        elif args.tier:
            entities = manager.get_entities_by_tier(args.tier)
        else:
            entities = manager.get_all_entities()

        payload = [{"id": eid, **e} for eid, e in entities.items()]
        emit_success(payload, message="entities")

    elif args.command == "process-chapter":
        try:
            from pydantic import ValidationError
            from .schemas import validate_data_agent_output, format_validation_error, normalize_data_agent_output
        except ModuleNotFoundError as exc:
            emit_error(
                "MISSING_DEPENDENCY",
                f"缺少依赖: {exc.name}",
                suggestion="请安装 state process-chapter 所需依赖（例如 pydantic）后重试",
                chapter=args.chapter,
            )
            return

        data = load_json_arg(args.data)
        validated = None
        last_exc = None
        for _ in range(3):
            try:
                validated = validate_data_agent_output(data)
                break
            except ValidationError as exc:
                last_exc = exc
                data = normalize_data_agent_output(data)
        if validated is None:
            err = format_validation_error(last_exc) if last_exc else {
                "code": "SCHEMA_VALIDATION_FAILED",
                "message": "数据结构校验失败",
                "details": {"errors": []},
                "suggestion": "请检查 data-agent 输出字段是否完整且类型正确",
            }
            emit_error(err["code"], err["message"], suggestion=err.get("suggestion"))
            return

        warnings = manager.process_chapter_result(args.chapter, validated.model_dump(by_alias=True))
        manager.save_state()
        refresh_warning = refresh_health_report(manager.config.project_root)
        if refresh_warning:
            warnings.append(refresh_warning)
        emit_success({"chapter": args.chapter, "warnings": warnings}, message="chapter_processed", chapter=args.chapter)

    else:
        emit_error("UNKNOWN_COMMAND", "未指定有效命令", suggestion="请查看 --help")


if __name__ == "__main__":
    if sys.platform == "win32":
        enable_windows_utf8_stdio()
    main()
