#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shell-first init wizard backed by upstream skill sources."""

from __future__ import annotations

import builtins
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata
from typing import Any, Optional, Sequence

from init_source_loader import InitWorkflowSpec, load_init_workflow_spec
from init_postprocess import (
    DEFAULT_RAG_ENV,
    patch_master_outline,
    verify_init_outputs,
    write_idea_bank,
    write_project_env,
)
from runtime_compat import resolve_python_executable


SCRIPTS_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = SCRIPTS_DIR.parent
INIT_PROJECT_SCRIPT = SCRIPTS_DIR / "init_project.py"
PROMPT_TOOLKIT_MENU_HELP = "↑/↓ 选择  Enter/Space 确认  Ctrl+C 取消"
PROMPT_TOOLKIT_TEXT_HELP = "Enter 提交  Ctrl+C 取消"
PROMPT_TOOLKIT_MAX_VISIBLE_OPTIONS = 10
CREATIVE_PACKAGE_SYSTEM_RECOMMEND = "系统推荐｜帮我从当前候选里挑最适合的一项"
CREATIVE_PACKAGE_CUSTOM = "自定义｜我提供一句方向，你帮我生成候选"
CREATIVE_PACKAGE_CUSTOM_RETURN = "返回 Step 5"
RAG_ENV_EDIT_FINISH = "完成并继续"
RAG_ENV_USE_DEFAULTS = "直接使用当前配置"


def _ansi_clear_lines(count: int) -> str:
    return "".join("\r\x1b[1A\x1b[2K" for _ in range(count))


def _render_menu_block(lines: list[str]) -> str:
    if not lines:
        return ""
    return "\r" + "\r\n".join(lines) + "\r\n"


def _display_width(text: str) -> int:
    width = 0
    for char in str(text or ""):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def _truncate_display(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    result = []
    width = 0
    for char in str(text or ""):
        char_width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1)
        if width + char_width > max_width:
            suffix = "…"
            if max_width == 1:
                return suffix
            while result and _display_width("".join(result) + suffix) > max_width:
                result.pop()
            return "".join(result) + suffix
        result.append(char)
        width += char_width
    return "".join(result)


def _menu_window(selected_index: int, total: int, max_visible: int) -> tuple[int, int]:
    if max_visible <= 0 or total <= max_visible:
        return 0, total
    start = max(0, selected_index - max_visible // 2)
    end = min(total, start + max_visible)
    start = max(0, end - max_visible)
    return start, end


def _render_fullscreen_menu(
    label: str,
    prompt: str,
    options: list[str],
    *,
    selected_index: int,
    terminal_height: int,
    terminal_width: int,
) -> str:
    width = max(terminal_width - 2, 20)
    header = [
        _truncate_display(label, width),
        _truncate_display(prompt, width),
        "",
    ]
    footer = [
        "",
        _truncate_display("↑/↓ 选择  Enter 确认  Ctrl+C 取消", width),
    ]
    max_visible = max(1, terminal_height - len(header) - len(footer))
    start, end = _menu_window(selected_index, len(options), max_visible)
    visible_options = options[start:end]
    lines = list(header)
    for visible_index, option in enumerate(visible_options, start=start):
        prefix = "❯" if visible_index == selected_index else " "
        lines.append(_truncate_display(f"{prefix} {option}", width))
    if start > 0:
        lines[2] = _truncate_display("↑ 更多选项", width)
    if end < len(options):
        footer[0] = _truncate_display("↓ 更多选项", width)
    return "\x1b[H\x1b[2J\r" + "\r\n".join(lines + footer)


def _render_choice_lines(
    *,
    label: str,
    prompt: str,
    options: Sequence[str],
    selected_index: int,
    max_visible: int = PROMPT_TOOLKIT_MAX_VISIBLE_OPTIONS,
) -> list[str]:
    values = list(options)
    start, end = _menu_window(selected_index, len(values), max_visible)
    visible_options = values[start:end]
    lines = [label, prompt, ""]
    for visible_index, option in enumerate(visible_options, start=start):
        prefix = "❯ " if visible_index == selected_index else "  "
        lines.append(f"{prefix}{option}")
    if start > 0:
        lines.append("↑ 更多选项")
    if end < len(values):
        lines.append("↓ 更多选项")
    return lines


def _prompt_toolkit_shortcuts():
    from prompt_toolkit import shortcuts

    return shortcuts


def _build_cd_command(project_dir: Path) -> str:
    return f'cd "{Path(project_dir).resolve()}"'


def _copy_text_to_clipboard(text: str) -> bool:
    clipboard_commands = [
        ["pbcopy"],
        ["clip"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]
    for command in clipboard_commands:
        executable = command[0]
        if shutil.which(executable) is None:
            continue
        try:
            subprocess.run(
                command,
                input=text,
                text=True,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            continue
    return False


def _prompt_toolkit_text_prompt(
    *,
    title: str,
    message: str,
    default: str = "",
    bottom_toolbar: str = PROMPT_TOOLKIT_TEXT_HELP,
) -> str:
    shortcuts = _prompt_toolkit_shortcuts()
    lines = [line for line in [title.strip(), message.strip()] if line]
    prompt_message = "\n".join(lines)
    if prompt_message:
        prompt_message = f"{prompt_message}\n> "
    else:
        prompt_message = "> "
    return shortcuts.prompt(
        prompt_message,
        default=default,
        mouse_support=False,
        bottom_toolbar=bottom_toolbar,
    )


def _prompt_toolkit_choice_prompt(
    *,
    title: str,
    label: str,
    prompt: str,
    options: Sequence[tuple[Any, str]],
    default: Optional[Any] = None,
    bottom_toolbar: str = PROMPT_TOOLKIT_MENU_HELP,
) -> Any:
    from prompt_toolkit import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl

    values = list(options)
    if not values:
        raise ValueError("choice prompt requires at least one option")

    labels = [str(label_text) for _, label_text in values]
    value_to_index = {value: index for index, (value, _label_text) in enumerate(values)}
    selected_index = value_to_index.get(default, 0 if values else -1)

    kb = KeyBindings()

    @kb.add("enter", eager=True)
    @kb.add(" ")
    def _accept(event) -> None:
        event.app.exit(result=values[selected_index][0])

    @kb.add("up", eager=True)
    def _move_up(event) -> None:
        nonlocal selected_index
        if not values:
            return
        selected_index = (selected_index - 1) % len(values)
        event.app.invalidate()

    @kb.add("down", eager=True)
    def _move_down(event) -> None:
        nonlocal selected_index
        if not values:
            return
        selected_index = (selected_index + 1) % len(values)
        event.app.invalidate()

    @kb.add("c-c", eager=True)
    @kb.add("<sigint>", eager=True)
    def _abort(event) -> None:
        event.app.exit(exception=KeyboardInterrupt())

    def _render_text() -> str:
        screen_lines = []
        if title.strip():
            screen_lines.append(title.strip())
        screen_lines.extend(
            _render_choice_lines(
                label=label.strip(),
                prompt=prompt.strip(),
                options=labels,
                selected_index=selected_index,
            )
        )
        screen_lines.extend(["", bottom_toolbar])
        return "\n".join(screen_lines)

    container = Window(
        FormattedTextControl(_render_text, focusable=True),
        always_hide_cursor=True,
        dont_extend_height=True,
    )

    app = Application(
        layout=Layout(container, focused_element=container),
        full_screen=True,
        mouse_support=False,
        key_bindings=kb,
    )
    return app.run()


def _supports_prompt_toolkit_io() -> bool:
    input_is_tty = bool(getattr(sys.stdin, "isatty", lambda: False)())
    output_is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if not input_is_tty or not output_is_tty:
        return False
    try:
        _prompt_toolkit_shortcuts()
    except Exception:
        return False
    return True


class PromptToolkitIO:
    def __init__(self):
        self._current_step_id = ""
        self._current_step_title = ""

    def show_step(self, step_id: str, title: str) -> None:
        self._current_step_id = step_id
        self._current_step_title = title

    def ask_text(self, field_key: str, label: str, prompt: str, default: Optional[str] = None) -> str:
        text = _prompt_toolkit_text_prompt(
            title=self._step_heading(),
            message="\n".join(line for line in [label, prompt] if line),
            default=default or "",
        )
        text = str(text).strip()
        if not text and default is not None:
            return default
        return text

    def choose(self, field_key: str, label: str, prompt: str, options: list[str], allow_skip: bool = False) -> str:
        values = [(option, option) for option in options]
        if allow_skip:
            values.append(("", "跳过"))
        choice = _prompt_toolkit_choice_prompt(
            title=self._step_heading(),
            label=label,
            prompt=prompt,
            options=values,
            default=values[0][0] if values else None,
            bottom_toolbar=PROMPT_TOOLKIT_MENU_HELP,
        )
        return str(choice)

    def confirm(
        self,
        field_key: str,
        prompt: str,
        default: bool = False,
        yes_label: str = "确认",
        no_label: str = "返回上一步",
    ) -> bool:
        result = _prompt_toolkit_choice_prompt(
            title=self._step_heading(),
            label="确认",
            prompt=prompt,
            options=[("__yes__", yes_label), ("__no__", no_label)],
            default="__yes__" if default else "__no__",
            bottom_toolbar=PROMPT_TOOLKIT_MENU_HELP,
        )
        return result == "__yes__"

    def show_summary(self, summary: str) -> None:
        _prompt_toolkit_choice_prompt(
            title=self._step_heading(),
            label="初始化摘要草案",
            prompt=summary,
            options=[("__continue__", "继续")],
            default="__continue__",
            bottom_toolbar=PROMPT_TOOLKIT_MENU_HELP,
        )

    def show_post_init_handoff(self, project_dir: Path, command: str, copied: bool) -> None:
        output = sys.stdout
        if copied:
            output.write("\n已将进入项目目录的命令复制到剪贴板。\n")
            output.write("请现在按 Cmd+V（或你的终端粘贴快捷键），然后按回车。\n")
        else:
            output.write("\n未能自动复制到剪贴板，请手动复制下面这条命令并回车：\n")
            output.write(f"{command}\n")
        output.flush()

    def _step_heading(self) -> str:
        step_prefix = f"[{self._current_step_id}] " if self._current_step_id else ""
        step_title = self._current_step_title or "初始化"
        return f"{step_prefix}{step_title}"


class ShellIO:
    def __init__(self, input_stream=None, output_stream=None):
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self._line_editing_enabled = False

    def show_step(self, step_id: str, title: str) -> None:
        self.output_stream.write(f"\n[{step_id}] {title}\n")
        self.output_stream.flush()

    def ask_text(self, field_key: str, label: str, prompt: str, default: Optional[str] = None) -> str:
        suffix = f"（默认：{default}）" if default else ""
        self.output_stream.write(f"{label}{suffix}\n{prompt}\n")
        self.output_stream.flush()
        value = self._read_line("> ").strip()
        if not value and default is not None:
            return default
        return value

    def choose(self, field_key: str, label: str, prompt: str, options: list[str], allow_skip: bool = False) -> str:
        return self._choose_with_numbers(label, prompt, options, allow_skip=allow_skip)

    def confirm(
        self,
        field_key: str,
        prompt: str,
        default: bool = False,
        yes_label: str = "确认",
        no_label: str = "返回上一步",
    ) -> bool:
        default_hint = "Y/n" if default else "y/N"
        value = self._read_line(f"{prompt}（y={yes_label} / n={no_label}） [{default_hint}] ").strip().lower()
        if not value:
            return default
        return value in {"y", "yes", "是", "确认"}

    def show_summary(self, summary: str) -> None:
        self.output_stream.write(f"\n{summary}\n")
        self.output_stream.flush()

    def show_post_init_handoff(self, project_dir: Path, command: str, copied: bool) -> None:
        if copied:
            self.output_stream.write("\n已将进入项目目录的命令复制到剪贴板。\n")
            self.output_stream.write("请现在按 Cmd+V（或你的终端粘贴快捷键），然后按回车。\n")
        else:
            self.output_stream.write("\n未能自动复制到剪贴板，请手动复制下面这条命令并回车：\n")
            self.output_stream.write(f"{command}\n")
        self.output_stream.flush()

    def _should_use_builtin_input(self) -> bool:
        if self.input_stream is not sys.stdin or self.output_stream is not sys.stdout:
            return False
        input_is_tty = bool(getattr(self.input_stream, "isatty", lambda: False)())
        output_is_tty = bool(getattr(self.output_stream, "isatty", lambda: False)())
        return input_is_tty and output_is_tty

    def _read_line(self, prompt: str = "") -> str:
        if self._should_use_builtin_input():
            self._enable_line_editing()
            try:
                return builtins.input(prompt)
            except EOFError:
                return ""
        if prompt:
            self.output_stream.write(prompt)
            self.output_stream.flush()
        return self.input_stream.readline()

    def _enable_line_editing(self) -> None:
        if self._line_editing_enabled:
            return
        try:
            import readline  # noqa: F401
        except Exception:
            return
        self._line_editing_enabled = True

    def _choose_with_numbers(self, label: str, prompt: str, options: list[str], allow_skip: bool = False) -> str:
        indexed_options = list(options)
        if allow_skip:
            indexed_options.append("跳过")
        while True:
            self.output_stream.write(f"{label}\n{prompt}\n")
            for index, option in enumerate(indexed_options, start=1):
                self.output_stream.write(f"{index}. {option}\n")
            raw = self._read_line("> ").strip()
            if not raw:
                continue
            if raw.isdigit():
                selected_index = int(raw) - 1
                if 0 <= selected_index < len(indexed_options):
                    choice = indexed_options[selected_index]
                    return "" if allow_skip and choice == "跳过" else choice
            for option in indexed_options:
                if raw == option:
                    return "" if allow_skip and option == "跳过" else option

class InitWizard:
    def __init__(self, *, workspace_root: Path, io: Optional[ShellIO] = None, spec: Optional[InitWorkflowSpec] = None):
        self.workspace_root = Path(workspace_root).expanduser().resolve()
        self.io = io or ShellIO()
        self.spec = spec or load_init_workflow_spec()
        self.fields = {field.key: field for step in self.spec.steps for field in step.fields}
        self._project_cache: dict[str, Any] = {}
        self._protagonist_cache: dict[str, Any] = {}
        self._relationship_cache: dict[str, Any] = {}
        self._world_cache: dict[str, Any] = {}

    def _field(self, field_key: str):
        return self.fields.get(field_key)

    def _safe_project_dir_name(self, title: str) -> str:
        normalized = unicodedata.normalize("NFKC", str(title or "").strip())
        normalized = re.sub(r"\s+", "-", normalized)
        normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", normalized)
        normalized = re.sub(r"[^\w\u4e00-\u9fff.\-]", "", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
        if not normalized:
            return "proj-project"
        if normalized.startswith("."):
            normalized = f"proj-{normalized.lstrip('.') or 'project'}"
        return normalized

    def _project_dir_for_title(self, title: str) -> Path:
        return (self.workspace_root / self._safe_project_dir_name(title)).resolve()

    def _guidance_lines(self, field_key: str, options: list[str]) -> list[str]:
        lines: list[str] = []
        field = self._field(field_key)
        if field and field.note:
            lines.append(f"来源备注：{field.note}")

        genre_tokens = self._selected_genres()
        if field_key == "one_liner" and genre_tokens:
            lines.append(f"当前题材：{' + '.join(genre_tokens)}")
        if field_key == "core_conflict" and genre_tokens:
            lines.append(f"当前题材：{' + '.join(genre_tokens)}")
        if field_key == "social_class_resource":
            lines.append("可先按四层结构去想：顶层势力 / 中层势力 / 底层势力 / 散修平民。")
            lines.append("再补一句：谁掌握核心资源，主角处在哪一层。")
        if field_key == "power_system_type":
            lines.append("尽量写清：力量来源、升级路径、突破代价。")
        if field_key == "factions":
            lines.append("可先写 1 个顶层势力 + 1 个中层势力 + 1 个底层势力。")
            lines.append("重点写清：谁掌握规则、谁在争夺资源、谁会与主角对抗。")

        examples = []
        for option in options:
            text = str(option or "").strip()
            if text and text not in examples:
                examples.append(text)
        if examples:
            lines.append("可参考：")
            lines.extend(f"- {example}" for example in examples[:4])
        return lines

    def _manual_prompt(
        self,
        field_key: str,
        base_prompt: str,
        options: list[str],
        *,
        error: str = "",
    ) -> str:
        lines = [base_prompt]
        if error:
            lines.extend(["", error])
        guidance = self._guidance_lines(field_key, options)
        if guidance:
            lines.extend(["", *guidance])
        if options:
            lines.extend(["", "也可以直接输入你自己的版本。"])
        return "\n".join(lines)

    def _choose_or_enter(
        self,
        field_key: str,
        label: str,
        prompt: str,
        options: list[str],
        *,
        default: Optional[str] = None,
    ) -> str:
        cleaned_options = []
        for option in options:
            text = str(option or "").strip()
            if text and text not in cleaned_options:
                cleaned_options.append(text)
        if cleaned_options:
            choice = self.io.choose(
                field_key,
                label,
                f"{prompt}\n可直接选候选；若都不合适，请选“手动输入”。",
                ["手动输入", *cleaned_options],
            )
            if choice and choice != "手动输入":
                return choice
        return self.io.ask_text(
            field_key,
            label,
            self._manual_prompt(field_key, prompt, cleaned_options),
            default=default,
        )

    def _selected_genres(self) -> list[str]:
        return [genre for genre in str(self._project_cache.get("genre", "")).split("+") if genre]

    def _story_candidates(self, genres: list[str]) -> list[str]:
        candidates: list[str] = []
        for genre in genres:
            guidance = self.spec.genre_guidance.get(genre)
            if not guidance:
                continue
            candidates.extend(guidance.premise_candidates[:2])
            if guidance.selling_point:
                candidates.append(guidance.selling_point)
        return candidates[:4]

    def _conflict_candidates(self, genres: list[str]) -> list[str]:
        candidates: list[str] = []
        for genre in genres:
            guidance = self.spec.genre_guidance.get(genre)
            if guidance:
                candidates.extend(guidance.conflict_candidates[:2])
        return candidates[:4]

    def collect(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "project": {},
            "protagonist": {},
            "relationship": {},
            "golden_finger": {},
            "world": {},
            "constraints": {},
            "confirmed": False,
        }
        step_index = 0
        while step_index < len(self.spec.steps):
            step = self.spec.steps[step_index]
            self.io.show_step(step.id, step.title)
            if step.id == "Step 1":
                self._collect_story_core(payload)
            elif step.id == "Step 2":
                self._collect_protagonist(payload)
            elif step.id == "Step 3":
                self._collect_golden_finger(payload)
            elif step.id == "Step 4":
                self._collect_world(payload)
            elif step.id == "Step 5":
                self._collect_constraints(payload)
            elif step.id == "Step 6":
                self.io.show_summary(self._build_summary(payload))
                payload["confirmed"] = self.io.confirm(
                    "final_confirm",
                    "确认按以上摘要生成项目吗？",
                    default=False,
                    yes_label="确认生成",
                    no_label="返回上一步",
                )
                if payload["confirmed"]:
                    step_index += 1
                    continue
                step_index = max(0, step_index - 1)
                continue
            step_index += 1
        return payload

    def build_init_project_argv(self, payload: dict[str, Any]) -> list[str]:
        project = payload["project"]
        protagonist = payload["protagonist"]
        relationship = payload["relationship"]
        golden_finger = payload["golden_finger"]
        world = payload["world"]
        constraints = payload["constraints"]
        project_dir = self._project_dir_for_title(project["title"])
        argv = [str(project_dir), project["title"], project["genre"]]
        target_words, target_chapters = _parse_story_scale(project.get("story_scale", ""))
        if target_words:
            argv.extend(["--target-words", str(target_words)])
        if target_chapters:
            argv.extend(["--target-chapters", str(target_chapters)])
        option_pairs = [
            ("--protagonist-name", protagonist.get("name", "")),
            ("--protagonist-desire", protagonist.get("desire", "")),
            ("--protagonist-flaw", protagonist.get("flaw", "")),
            ("--protagonist-archetype", protagonist.get("archetype", "")),
            ("--protagonist-structure", relationship.get("structure", "")),
            ("--heroine-config", relationship.get("heroine_config", "")),
            ("--antagonist-level", relationship.get("antagonist_level", "")),
            ("--golden-finger-name", golden_finger.get("name", "")),
            ("--golden-finger-type", golden_finger.get("type", "")),
            ("--golden-finger-style", golden_finger.get("style", "")),
            ("--gf-visibility", golden_finger.get("visibility", "")),
            ("--gf-irreversible-cost", golden_finger.get("irreversible_cost", "")),
            ("--world-scale", world.get("scale", "")),
            ("--power-system-type", world.get("power_system_type", "")),
            ("--factions", world.get("factions", "")),
            ("--social-class", world.get("social_class", "")),
            ("--resource-distribution", world.get("resource_distribution", "")),
            ("--core-selling-points", ",".join(constraints.get("core_selling_points", []))),
            ("--target-reader", project.get("target_reader", "")),
            ("--platform", project.get("platform", "")),
        ]
        for option, value in option_pairs:
            if value:
                argv.extend([option, value])
        return argv

    def _mask_rag_value(self, key: str, value: str) -> str:
        text = str(value or "").strip()
        if "API_KEY" not in key:
            return text
        if not text:
            return "（空）"
        if text.startswith("your_"):
            return text
        if len(text) <= 8:
            return "*" * len(text)
        return f"{text[:4]}***{text[-4:]}"

    def _render_rag_env_summary(self, env_values: dict[str, str]) -> str:
        lines = [
            "已自动生成项目级 `.env` 默认配置：",
            "",
        ]
        for key in DEFAULT_RAG_ENV:
            lines.append(f"- {key}={self._mask_rag_value(key, env_values.get(key, ''))}")
        lines.extend(
            [
                "",
                "请选择下一步：直接使用当前配置，或进入修改。",
            ]
        )
        return "\n".join(lines)

    def _rag_field_prompt(self, key: str) -> str:
        prompts = {
            "EMBED_BASE_URL": "请输入 Embedding 服务的 Base URL。",
            "EMBED_MODEL": "请输入 Embedding 模型名。",
            "EMBED_API_KEY": "请输入 Embedding API Key。",
            "RERANK_BASE_URL": "请输入 Rerank 服务的 Base URL。",
            "RERANK_MODEL": "请输入 Rerank 模型名。",
            "RERANK_API_KEY": "请输入 Rerank API Key。",
        }
        return prompts.get(key, f"请输入 {key}。")

    def _edit_rag_env(self, env_values: dict[str, str]) -> dict[str, str]:
        updated = {key: str(value or "").strip() for key, value in dict(env_values).items()}
        while True:
            option_map = {
                f"{key} = {self._mask_rag_value(key, updated.get(key, ''))}": key for key in DEFAULT_RAG_ENV
            }
            options = [*option_map.keys(), RAG_ENV_EDIT_FINISH]
            selected = self.io.choose(
                "rag_env_edit",
                "RAG 配置",
                "请选择要修改的项；选中后会进入输入步骤。",
                options,
            )
            if selected == RAG_ENV_EDIT_FINISH:
                return updated
            target_key = option_map.get(selected)
            if not target_key:
                continue
            updated[target_key] = self.io.ask_text(
                f"rag_env:{target_key}",
                target_key,
                self._rag_field_prompt(target_key),
                default=updated.get(target_key, ""),
            )

    def _configure_project_outputs(self, project_dir: Path, payload: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
        env_values = dict(DEFAULT_RAG_ENV)
        should_edit = self.io.confirm(
            "rag_env_modify",
            self._render_rag_env_summary(env_values),
            default=False,
            yes_label="修改配置",
            no_label=RAG_ENV_USE_DEFAULTS,
        )
        if should_edit:
            env_values = self._edit_rag_env(env_values)

        write_project_env(project_dir, env_values)
        write_idea_bank(project_dir, payload)
        patch_master_outline(project_dir, payload)
        errors = verify_init_outputs(project_dir)
        return env_values, errors

    def run(self) -> dict[str, Any]:
        payload = self.collect()
        if not payload.get("confirmed"):
            return {"status": "cancelled", "payload": payload}
        argv = self.build_init_project_argv(payload)
        command = [resolve_python_executable(), str(INIT_PROJECT_SCRIPT), *argv]
        result = subprocess.run(command, cwd=str(PACKAGE_ROOT))
        project_dir = Path(argv[0]).resolve()
        if int(result.returncode or 0) == 0:
            env_values, errors = self._configure_project_outputs(project_dir, payload)
            payload["rag_env"] = dict(env_values)
            if errors:
                self.io.show_summary("初始化后处理校验失败：\n" + "\n".join(f"- {error}" for error in errors))
                return {
                    "status": "failed",
                    "returncode": 1,
                    "payload": payload,
                    "command": command,
                    "postprocess_errors": errors,
                }
            cd_command = _build_cd_command(project_dir)
            copied = _copy_text_to_clipboard(cd_command)
            self.io.show_post_init_handoff(project_dir, cd_command, copied)
        return {
            "status": "confirmed" if result.returncode == 0 else "failed",
            "returncode": int(result.returncode or 0),
            "payload": payload,
            "command": command,
        }

    def _collect_story_core(self, payload: dict[str, Any]) -> None:
        project = payload["project"]
        title_prompt = "请输入书名（可先用工作名）。"
        while True:
            title = self.io.ask_text("project_title", self.fields["project_title"].label, title_prompt)
            project_dir = self._project_dir_for_title(title)
            if not project_dir.exists():
                project["title"] = title
                break
            title_prompt = "\n".join(
                [
                    "书名对应的项目目录已存在，请换一个书名。",
                    f"已存在目录：{project_dir}",
                    "请输入书名（可先用工作名）。",
                ]
            )
        category = self.io.choose("genre_category", "题材分类", "请选择主题材分类：", list(self.spec.genre_categories.keys()))
        primary_genre = self.io.choose("genre_primary", "主题材", "请选择主题材：", self.spec.genre_categories[category])
        genres = [primary_genre]
        if self.io.confirm(
            "include_secondary_genre",
            "是否添加第二题材（A+B 复合）？",
            default=False,
            yes_label="添加第二题材",
            no_label="不添加第二题材",
        ):
            all_genres = [value for values in self.spec.genre_categories.values() for value in values if value != primary_genre]
            secondary_genre = self.io.choose("genre_secondary", "第二题材", "请选择第二题材：", all_genres)
            if secondary_genre:
                genres.append(secondary_genre)
        project["genre"] = "+".join(genres)
        project["story_scale"] = self.io.ask_text("story_scale", self.fields["story_scale"].label, "请输入目标规模（如 200万字 / 600章）。")
        project["one_liner"] = self._choose_or_enter(
            "one_liner",
            self.fields["one_liner"].label,
            "请选择一句话故事方向。",
            self._story_candidates(genres),
        )
        project["core_conflict"] = self._choose_or_enter(
            "core_conflict",
            self.fields["core_conflict"].label,
            "请选择核心冲突方向。",
            self._conflict_candidates(genres),
        )
        project["target_reader"] = self._choose_or_enter(
            "target_reader",
            "目标读者",
            "请选择目标读者。",
            self.spec.target_reader_options,
        )
        project["platform"] = self._choose_or_enter(
            "platform",
            "目标平台",
            "请选择目标平台。",
            self.spec.platform_options,
        )
        self._project_cache = dict(project)

    def _collect_protagonist(self, payload: dict[str, Any]) -> None:
        protagonist = payload["protagonist"]
        relationship = payload["relationship"]
        protagonist["name"] = self.io.ask_text("protagonist_name", self.fields["protagonist_name"].label, "请输入主角姓名。")
        protagonist["desire"] = self._choose_or_enter(
            "protagonist_desire",
            self.fields["protagonist_desire"].label,
            "请选择主角欲望。",
            self.spec.protagonist_desire_options,
        )
        protagonist["flaw"] = self._choose_or_enter(
            "protagonist_flaw",
            self.fields["protagonist_flaw"].label,
            "请选择主角缺陷。",
            self.spec.protagonist_flaw_options,
        )
        relationship["structure"] = self.io.choose("protagonist_structure", self.fields["protagonist_structure"].label, "请选择主角结构：", self.fields["protagonist_structure"].options)
        relationship["heroine_config"] = self.io.choose("heroine_config", self.fields["heroine_config"].label, "请选择感情线配置：", self.fields["heroine_config"].options)
        protagonist["archetype"] = self._choose_or_enter(
            "protagonist_archetype",
            self.fields["protagonist_archetype"].label,
            "请选择主角原型标签。",
            self.spec.protagonist_archetype_options,
        )
        relationship["antagonist_level"] = "小/中/大"
        relationship["antagonist_mirror"] = self._choose_or_enter(
            "antagonist_mirror",
            self.fields["antagonist_mirror"].label,
            "请选择反派镜像方向。",
            self.spec.antagonist_mirror_options,
        )
        self._protagonist_cache = dict(protagonist)
        self._relationship_cache = dict(relationship)

    def _collect_golden_finger(self, payload: dict[str, Any]) -> None:
        golden_finger = payload["golden_finger"]
        golden_finger["type"] = self.io.choose("golden_finger_type", self.fields["golden_finger_type"].label, "请选择金手指类型：", self.fields["golden_finger_type"].options)
        golden_finger["name"] = self.io.ask_text("golden_finger_name", self.fields["golden_finger_name"].label, "请输入名称/系统名（无则留空）。", default="")
        golden_finger["style"] = self.io.choose("golden_finger_style", self.fields["golden_finger_style"].label, "请选择金手指风格：", self.fields["golden_finger_style"].options)
        visibility_options = self.fields["gf_visibility"].options or ["明牌", "半明牌", "暗牌"]
        golden_finger["visibility"] = self.io.choose("gf_visibility", self.fields["gf_visibility"].label, "请选择金手指可见度：", visibility_options)
        golden_finger["irreversible_cost"] = self._choose_or_enter(
            "gf_irreversible_cost",
            self.fields["gf_irreversible_cost"].label,
            "请选择不可逆代价方向。",
            self.spec.golden_finger_cost_options,
        )
        golden_finger["growth_pacing"] = self.io.choose("growth_pacing", self.fields["growth_pacing"].label, "请选择成长节奏：", self.fields["growth_pacing"].options)

    def _collect_world(self, payload: dict[str, Any]) -> None:
        world = payload["world"]
        social = self.io.ask_text(
            "social_class_resource",
            self.fields["social_class_resource"].label,
            self._manual_prompt("social_class_resource", "请输入社会阶层与资源分配。", []),
        )
        world["scale"] = self.io.choose("world_scale", self.fields["world_scale"].label, "请选择世界规模：", self.fields["world_scale"].options)
        world["power_system_type"] = self._choose_or_enter(
            "power_system_type",
            self.fields["power_system_type"].label,
            "请选择力量体系类型。",
            self.spec.power_system_options,
        )
        world["factions"] = self._choose_or_enter(
            "factions",
            self.fields["factions"].label,
            "请选择势力格局模板。",
            self.spec.faction_options,
        )
        world["social_class"] = social
        world["resource_distribution"] = social
        self._world_cache = dict(world)

    def _collect_constraints(self, payload: dict[str, Any]) -> None:
        packages = self._build_creative_packages()
        chosen = self._select_creative_package(packages)
        payload["constraints"] = {
            "selected_package": chosen,
            "anti_trope": chosen["anti_trope"],
            "hard_constraints": chosen["hard_constraints"],
            "core_selling_points": [chosen["one_liner"], chosen["anti_trope"], *chosen["hard_constraints"]],
            "opening_hook": chosen["opening_hook"],
        }

    def _creative_package_label(self, package: dict[str, Any]) -> str:
        return f"{package.get('id', '')}｜{package.get('title', package.get('id', '方案'))}｜{package.get('one_liner', '')}"

    def _creative_package_by_label(self, packages: list[dict[str, Any]], label: str) -> Optional[dict[str, Any]]:
        selected_id = str(label or "").split("｜", 1)[0]
        return next((package for package in packages if package["id"] == selected_id), None)

    def _select_creative_package(self, packages: list[dict[str, Any]]) -> dict[str, Any]:
        while True:
            option_labels = [self._creative_package_label(package) for package in packages]
            option_labels.extend([CREATIVE_PACKAGE_SYSTEM_RECOMMEND, CREATIVE_PACKAGE_CUSTOM])
            selected = self.io.choose("creative_package", "创意约束包", "请选择最终采用的创意约束方案：", option_labels)
            if selected == CREATIVE_PACKAGE_SYSTEM_RECOMMEND:
                chosen = self._handle_system_recommend(packages)
                if chosen:
                    return chosen
                continue
            if selected == CREATIVE_PACKAGE_CUSTOM:
                chosen = self._handle_custom_creative_package()
                if chosen:
                    return chosen
                continue
            chosen = self._creative_package_by_label(packages, selected)
            if chosen:
                return chosen

    def _handle_system_recommend(self, packages: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        chosen = max(packages, key=lambda package: int(package.get("score", {}).get("total", 0)))
        self.io.show_summary(self._build_system_recommend_reason(chosen))
        accepted = self.io.confirm(
            "creative_package_recommend",
            "是否采用这个系统推荐？",
            default=True,
            yes_label="采用该推荐",
            no_label="返回 Step 5",
        )
        if accepted:
            return chosen
        return None

    def _build_system_recommend_reason(self, package: dict[str, Any]) -> str:
        genre = self._project_cache.get("genre", "")
        one_liner = self._project_cache.get("one_liner", "")
        conflict = self._project_cache.get("core_conflict", "")
        flaw = self._protagonist_cache.get("flaw", "")
        world_scale = self._world_cache.get("scale", "")
        return "\n".join(
            [
                "系统推荐理由",
                f"- 推荐方案：{package.get('title', package.get('id', '方案'))}",
                f"- 当前题材：{genre}",
                f"- 贴合点 1：它和当前故事方向“{one_liner}”最匹配。",
                f"- 贴合点 2：它能强化当前核心冲突“{conflict}”。",
                f"- 贴合点 3：主角缺陷“{flaw}”与世界规模“{world_scale}”在这个方案里更容易放大。",
                f"- 关键约束：{package.get('anti_trope', '')}",
            ]
        )

    def _handle_custom_creative_package(self) -> Optional[dict[str, Any]]:
        direction = self.io.ask_text(
            "creative_package_custom_direction",
            "自定义创意方向",
            "请输入一句想法/方向，我会基于当前剧情信息生成 2-3 个候选。",
        )
        candidates = self._build_custom_creative_packages(direction)
        option_labels = [self._creative_package_label(package) for package in candidates]
        option_labels.append(CREATIVE_PACKAGE_CUSTOM_RETURN)
        selected = self.io.choose("creative_package_custom", "自定义创意候选", "请选择一个自定义创意约束方案：", option_labels)
        if selected == CREATIVE_PACKAGE_CUSTOM_RETURN:
            return None
        return self._creative_package_by_label(candidates, selected)

    def _build_custom_creative_packages(self, direction: str) -> list[dict[str, Any]]:
        normalized_direction = re.sub(r"\s+", " ", str(direction or "").strip())
        if not normalized_direction:
            normalized_direction = "保留当前题材的核心爽点，但用新的代价与规则去改写剧情"
        conflict = self._project_cache.get("core_conflict", "")
        flaw = self._protagonist_cache.get("flaw", "")
        mirror = self._relationship_cache.get("antagonist_mirror", "")
        world_scale = self._world_cache.get("scale", "")
        variants = [
            {
                "id": "C01",
                "title": "自定义方向候选 1",
                "one_liner": normalized_direction,
                "anti_trope": f"所有收益都必须立刻绑定到“{normalized_direction}”的代价链。",
                "hard_constraints": [f"每次推进都要正面撞上“{conflict}”", f"主角缺陷“{flaw}”必须持续放大"],
                "opening_hook": f"开篇就让主角发现：{normalized_direction}",
                "score": {"total": 44},
            },
            {
                "id": "C02",
                "title": "自定义方向候选 2",
                "one_liner": f"{normalized_direction}｜镜像对抗版",
                "anti_trope": f"反派镜像“{mirror}”会率先走通这条方向。",
                "hard_constraints": [f"同一规则不能连续两次无代价生效", f"世界规模“{world_scale}”必须提前入局"],
                "opening_hook": f"主角第一次尝试这条方向时，镜像敌人已经抢先一步。",
                "score": {"total": 42},
            },
            {
                "id": "C03",
                "title": "自定义方向候选 3",
                "one_liner": f"{normalized_direction}｜失控升级版",
                "anti_trope": "每次突破都会让秩序进一步失控。",
                "hard_constraints": [f"必须不断加码“{conflict}”", "不能用旁白直接解释全部真相"],
                "opening_hook": f"城市第一次出现大规模异象时，源头正是“{normalized_direction}”。",
                "score": {"total": 40},
            },
        ]
        return variants

    def _build_creative_packages(self) -> list[dict[str, Any]]:
        selected_genres = [genre for genre in str(self._project_cache.get("genre", "")).split("+") if genre]
        candidate_sections = self._matching_pack_sections(selected_genres)
        templates = []
        for section in candidate_sections:
            templates.extend(self.spec.constraint_pack_sections.get(section, []))
        templates.extend(self.spec.constraint_pack_sections.get("通用增味包", []))
        deduped_templates = []
        seen = set()
        for template in templates:
            if template.pack_id in seen:
                continue
            seen.add(template.pack_id)
            deduped_templates.append(template)
        return [self._render_package(template) for template in deduped_templates[:3]]

    def _matching_pack_sections(self, genres: list[str]) -> list[str]:
        aliases = {
            "修仙": "玄幻/修真/高武",
            "高武": "玄幻/修真/高武",
            "系统流": "系统流",
            "规则怪谈": "规则怪谈",
            "悬疑脑洞": "悬疑脑洞 / 悬疑灵异",
            "悬疑灵异": "悬疑脑洞 / 悬疑灵异",
            "科幻": "科幻",
            "无限流": "无限流",
            "末世": "末世",
            "都市异能": "都市异能",
            "都市日常": "都市日常",
            "都市脑洞": "都市脑洞",
            "狗血言情": "狗血言情",
            "古言": "古代 / 古言脑洞",
        }
        matches: list[str] = []
        for genre in genres:
            section = aliases.get(genre)
            if section and section not in matches:
                matches.append(section)
        return matches or ["玄幻/修真/高武"]

    def _render_package(self, template) -> dict[str, Any]:
        flaw = self._protagonist_cache.get("flaw", "主角缺陷尚未填写")
        mirror = self._relationship_cache.get("antagonist_mirror", "反派与主角走向相反道路")
        world_scale = self._world_cache.get("scale", "")
        novelty = 8 if "+" in self._project_cache.get("genre", "") else 7
        market_fit = 8 if template.section != "通用增味包" else 7
        writability = 8 if self._protagonist_cache.get("name") else 6
        cool_point_density = 8 if "+" in template.cool_point else 7
        long_term_potential = 8 if world_scale in {"大陆", "多界"} else 7
        return {
            "id": template.pack_id,
            "title": template.title,
            "one_liner": f"{self._project_cache.get('one_liner', '')}｜{template.title}",
            "anti_trope": template.rule_constraint,
            "hard_constraints": [template.rule_constraint, template.character_conflict],
            "protagonist_flaw_drive": f"{flaw} 会在“{template.character_conflict}”里不断放大。",
            "antagonist_mirror": mirror,
            "opening_hook": f"{template.hook}：{self._project_cache.get('core_conflict', '')}",
            "score": {
                "novelty": novelty,
                "market_fit": market_fit,
                "writability": writability,
                "cool_point_density": cool_point_density,
                "long_term_potential": long_term_potential,
                "total": novelty + market_fit + writability + cool_point_density + long_term_potential,
            },
        }

    def _build_summary(self, payload: dict[str, Any]) -> str:
        project = payload["project"]
        protagonist = payload["protagonist"]
        golden_finger = payload["golden_finger"]
        world = payload["world"]
        constraints = payload["constraints"]
        package = constraints.get("selected_package", {})
        return "\n".join(
            [
                "初始化摘要草案",
                f"- 故事核：{project.get('genre', '')}｜{project.get('one_liner', '')}｜{project.get('core_conflict', '')}",
                f"- 主角核：欲望={protagonist.get('desire', '')}｜缺陷={protagonist.get('flaw', '')}",
                f"- 金手指核：{golden_finger.get('type', '')}｜代价={golden_finger.get('irreversible_cost', '')}",
                f"- 世界核：{world.get('scale', '')}｜{world.get('power_system_type', '')}｜{world.get('factions', '')}",
                f"- 创意约束核：{package.get('anti_trope', '')}｜{', '.join(package.get('hard_constraints', []))}",
            ]
        )


def _parse_story_scale(raw: str) -> tuple[int, int]:
    text = str(raw or "").replace(",", "").replace("，", "")
    words = 0
    chapters = 0
    word_match = re.search(r"(\d+(?:\.\d+)?)\s*万\s*字", text)
    if word_match:
        words = int(float(word_match.group(1)) * 10000)
    else:
        plain_word_match = re.search(r"(\d+)\s*字", text)
        if plain_word_match:
            words = int(plain_word_match.group(1))
    chapter_match = re.search(r"(\d+)\s*章", text)
    if chapter_match:
        chapters = int(chapter_match.group(1))
    return words, chapters


def _split_reader_platform(raw: str) -> tuple[str, str]:
    tokens = [token.strip() for token in re.split(r"[,，/|]", str(raw or "")) if token.strip()]
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return tokens[0], ""
    return tokens[0], tokens[1]


def run_shell_init_wizard(workspace_root: Optional[Path] = None) -> dict[str, Any]:
    resolved_workspace = Path(workspace_root or Path.cwd()).expanduser().resolve()
    if not _supports_prompt_toolkit_io():
        raise RuntimeError("webnovel-init 需要在普通终端里以 prompt_toolkit TUI 运行；请确认已安装依赖并在可交互 TTY 中启动。")
    io = PromptToolkitIO()
    wizard = InitWizard(workspace_root=resolved_workspace, io=io)
    return wizard.run()
