---
name: webnovel-dashboard
description: 启动可视化小说管理面板（只读 Web Dashboard），实时查看项目状态、实体图谱与章节内容。
allowed-tools: Bash Read
---

# Webnovel Dashboard

## 目标

在本地启动一个 **只读** Web 面板，用于可视化查看当前小说项目的：
- 创作进度与 Strand 节奏分布
- 设定词典（角色/地点/势力等实体）
- 关系图谱
- 章节与大纲内容浏览
- 追读力分析数据

面板通过 `watchdog` 监听 `.webnovel/` 目录变更并实时刷新，不对项目做任何修改。

## 执行步骤

### Step 0：环境确认

```bash
export WORKSPACE_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"

if [ -z "${CLAUDE_PLUGIN_ROOT}" ] || [ ! -d "${CLAUDE_PLUGIN_ROOT}/dashboard" ]; then
  echo "ERROR: 未找到 dashboard 模块: ${CLAUDE_PLUGIN_ROOT}/dashboard" >&2
  exit 1
fi
export DASHBOARD_DIR="${CLAUDE_PLUGIN_ROOT}/dashboard"

if [ -n "${PYTHON_BIN:-}" ]; then
  export PYTHON_EXEC="${PYTHON_BIN}"
elif command -v python3 >/dev/null 2>&1; then
  export PYTHON_EXEC="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  export PYTHON_EXEC="$(command -v python)"
else
  echo "ERROR: 未找到可用的 Python 解释器" >&2
  exit 1
fi
```

### Step 1：安装依赖（首次）

```bash
"${PYTHON_EXEC}" -m pip install -r "${DASHBOARD_DIR}/requirements.txt" --quiet
```

### Step 2：解析项目根目录并准备 Python 模块路径

```bash
export SCRIPTS_DIR="${CLAUDE_PLUGIN_ROOT}/scripts"
export PROJECT_ROOT="$("${PYTHON_EXEC}" "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"
echo "项目路径: ${PROJECT_ROOT}"

# 确保 `${PYTHON_EXEC} -m dashboard.server` 可在任意工作目录下找到插件模块
if [ -n "${PYTHONPATH:-}" ]; then
  export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}:${PYTHONPATH}"
else
  export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}"
fi

# 前端 dist 已随插件发布；若缺失说明安装包异常
if [ ! -f "${DASHBOARD_DIR}/frontend/dist/index.html" ]; then
  echo "ERROR: 缺少前端构建产物 ${DASHBOARD_DIR}/frontend/dist/index.html" >&2
  echo "请重新安装插件或联系维护者修复发布包。" >&2
  exit 1
fi
```

### Step 3：启动 Dashboard

```bash
export WEBNOVEL_DASHBOARD_HOST="${WEBNOVEL_DASHBOARD_HOST:-127.0.0.1}"
export WEBNOVEL_DASHBOARD_PORT="${WEBNOVEL_DASHBOARD_PORT:-5678}"
"${PYTHON_EXEC}" -m dashboard.server --project-root "${PROJECT_ROOT}"
```

启动后会自动打开浏览器访问 `http://127.0.0.1:5678`。

如果需要外网访问，把 `WEBNOVEL_DASHBOARD_HOST` 改成 `0.0.0.0`，例如：

```bash
export WEBNOVEL_DASHBOARD_HOST=0.0.0.0
export WEBNOVEL_DASHBOARD_PORT=5678
"${PYTHON_EXEC}" -m dashboard.server --project-root "${PROJECT_ROOT}" --no-browser
```

如不需要自动打开浏览器，使用：

```bash
export WEBNOVEL_DASHBOARD_HOST="${WEBNOVEL_DASHBOARD_HOST:-127.0.0.1}"
export WEBNOVEL_DASHBOARD_PORT="${WEBNOVEL_DASHBOARD_PORT:-5678}"
"${PYTHON_EXEC}" -m dashboard.server --project-root "${PROJECT_ROOT}" --no-browser
```

## 注意事项

- Dashboard 为纯只读面板，所有 API 仅 GET，不提供任何修改接口。
- 文件读取严格限制在 `PROJECT_ROOT` 范围内，防止路径穿越。
- 如需自定义端口，添加 `--port 9000` 参数。
