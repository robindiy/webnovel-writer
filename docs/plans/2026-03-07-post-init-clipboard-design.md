# Post-Init 剪贴板与 `.env` 指引设计

**背景**

当前初始化完成后，终端只打印：

```text
Project initialized at: /实际项目路径
```

这要求用户自己理解“路径”“cd”“当前目录”等概念。对 Vibe Coding 用户来说，这个认知成本太高，容易卡在初始化后第一步。

用户已明确要求：

- 不要再给 placeholder 路径或让用户自己拼命令
- 初始化成功后自动把 `cd "项目路径"` 复制到剪贴板
- 终端明确告诉用户：程序已经复制好了，直接粘贴 + 回车
- 后续文档不要只解释两个 key，而要解释 `.env` 里 6 个字段：
  - 2 个地址
  - 2 个模型
  - 2 个 API key
- 文案要说明默认值可直接先用，也允许用户替换成自己的 embedding / rerank 服务

## 目标

让初始化完成后的第一步变成“粘贴并回车”，而不是“理解路径并自己 cd”；同时让 `.env` 的配置说明足够小白可读。

## 交互设计

### 初始化成功后

在 `init_project.py` 完成项目生成并返回成功后，由 `init_terminal_ui.py` 负责：

1. 组装命令：
   ```bash
   cd "/实际项目路径"
   ```
2. 尝试复制到系统剪贴板
3. 向用户输出明确提示：
   - 成功时：
     - `已将进入项目目录的命令复制到剪贴板。`
     - `请现在按 Cmd+V，然后按回车。`
   - 失败时：
     - `未能自动复制到剪贴板，请手动复制下面这条命令：`
     - 再打印 `cd "/实际项目路径"`

### 不自动执行 `cd`

不尝试真正修改父 shell 的 cwd，因为当前入口链路是子进程，不能安全可靠地修改父 shell 工作目录。

所以这里的设计目标是：

- **用户不需要理解路径**
- 但仍然通过“复制好的命令 + 粘贴回车”完成目录切换

### `.env` 文档说明

README / 安装文档改成：

1. 初始化成功后，先粘贴刚刚复制好的 `cd` 命令并回车
2. 再执行：
   ```bash
   cp .env.example .env
   open -e .env
   ```
3. 然后明确解释这 6 个字段：
   - `EMBED_BASE_URL`：Embedding 服务地址
   - `EMBED_MODEL`：Embedding 模型名
   - `EMBED_API_KEY`：Embedding 服务密钥
   - `RERANK_BASE_URL`：Rerank 服务地址
   - `RERANK_MODEL`：Rerank 模型名
   - `RERANK_API_KEY`：Rerank 服务密钥

文案要求：

- 默认值已经给好，先保持默认也可以
- 如果要换自己的服务商，要把地址 / 模型 / key 成套改掉
- API key 需要用户自己到对应平台注册申请

## 平台兼容

优先支持 macOS 的 `pbcopy`，同时保留跨平台降级逻辑：

- macOS: `pbcopy`
- Windows: `clip`
- Linux Wayland: `wl-copy`
- Linux X11: `xclip` / `xsel`

只要有任一命令可用，就视为支持自动复制；否则打印可复制命令。

## 验证点

- 成功初始化后会尝试复制 `cd "..."` 到剪贴板
- 剪贴板失败时会打印降级提示和完整命令
- README / 安装文档不再依赖用户自己理解 `Project initialized at: ...`
- `.env` 六个字段的说明完整且可执行
