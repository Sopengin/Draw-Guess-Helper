# Draw & Guess 辅助绘画插件

为 Steam 游戏 **Draw & Guess**（Acureus / Unity 6 Mono）做的注入式辅助绘画工具：

1. **读题**：注入插件 Hook `IngameDrawModule.SetWord`，直接拿到本轮中文题面；
2. **搜图**：Python 侧搜对应简笔画/线稿（默认免 Key 抓取必应，也可配官方 API）；
3. **预览选择**：在**游戏内**弹出候选参考画 UI，点选一张作画，或点「跳过」自己画；
4. **自动作画**：OpenCV 把图片转成线条，插件通过 `DrawModule` 的绘制链路把线条自动画到游戏画布上（渲染、撤销、网络同步全部走游戏原生路径）。

> 仅用于与朋友私下娱乐 / 学习逆向。请勿用于违反游戏条款或影响他人体验的用途。

---

## 目录结构

```
draw&guess/
├── plugin/DrawGuessAssistant/   # C# BepInEx 注入插件
│   ├── DrawGuessAssistant.csproj
│   ├── Plugin.cs                # 入口 + Harmony Hook
│   ├── WordHook.cs              # Hook SetWord 读题
│   ├── AssistantBehaviour.cs    # 主线程轮询 + 播放笔画
│   ├── DrawInjector.cs          # 通过 DrawModule 注入作画
│   └── Models.cs                # strokes.json 数据模型
├── helper/                      # Python 搜图 + 图像转线稿
│   ├── main.py                  # 轮询 word.txt -> 写 strokes.json
│   ├── search.py                # Google / Bing 图片搜索
│   ├── translate.py             # 中译英（可选）
│   ├── image_to_strokes.py      # OpenCV 图像转线条
│   └── requirements.txt
├── tools/                       # 逆向辅助脚本（游戏更新后核对签名用）
│   ├── extract_signatures.py
│   └── disasm_il.py
├── config.json                  # 搜图 API Key 等配置
└── runtime/                     # 插件与 helper 的文件握手目录
```

---

## 部署步骤

### 1. 安装 BepInEx 6（Mono）

1. 下载 **BepInEx 6.0.0-be**（BepInEx 6 bleeding edge，选 **Unity Mono x64** 版本）：
   https://builds.bepis.io/projects/bepinex_be
2. 解压到游戏 `beta` 目录（即 `D:\Steam\steamapps\common\Draw & Guess\beta\`），
   解压后应出现 `winhttp.dll`、`doorstop_config.ini`、`BepInEx\` 等。
3. 启动一次游戏，确认生成 `beta\BepInEx\LogOutput.log`，即注入成功。
   - 若 BepInEx 6 在 Unity 6 上加载失败，改用 **MelonLoader**（自带 Harmony）。

### 2. 编译插件

需要 .NET SDK（`dotnet build`），或 Visual Studio / Rider：

```bash
cd plugin/DrawGuessAssistant
dotnet build -c Release
```

编译产物 `bin/Release/netstandard2.1/DrawGuessAssistant.dll` 拷到
`beta\BepInEx\plugins\` 下。

> 没有 dotnet SDK 时，可用系统自带的 `csc.exe` 手动编译（需把目标框架换成
> net472 并调整引用），或直接安装 .NET 8 SDK。

### 3. 安装 Python 依赖

```bash
pip install -r helper/requirements.txt
```

### 4. 配置

编辑 `config.json`：

- **搜图**：默认**免 Key**（`search.api_key` 留空即自动用必应图片网页抓取，零注册）。
  若要更稳定/更高质量，可填 `search.api_key` 走官方 API：
  - `search.provider`：`bing` 或 `google`
  - `search.api_key`：搜索 API Key（Google 还需要 `search.cx`）
- `translate.enabled`：是否中译英（英文查询词通常能搜到更干净的简笔画）
- `preview.enabled`：是否在**游戏内**弹出候选图选择 UI（默认开）；`preview.num_candidates` 候选张数
- `runtime_dir`：握手目录（与插件 `Plugin.cs` 里的 `DefaultRuntimeDir` 保持一致）

> 预览流程：搜到 N 张候选后，**游戏内**弹 UI，**点选一张自动作画**，或点「**跳过 · 我自己画**」不画。
> 想回到「全自动、不预览」，运行 helper 时加 `--no-preview`，或在 `config.json` 把 `preview.enabled` 设为 `false`。

### 5. 运行

1. 启动游戏，进入一局并成为**画手**。
2. 另开一个终端：`python helper/main.py --config config.json`
3. 题目出现后，插件写 `runtime/word.txt` → helper 搜图转线稿写 `runtime/strokes.json`
   → 插件自动在画布上画出来。

---

## 握手协议

- `runtime/word.txt`：纯文本题面（如 `苹果`），插件 Hook `SetWord` 时写入。
- `runtime/candidates.json`：`{word, count, queries}`，helper 搜图后写入，触发插件弹游戏内选择 UI。
- `runtime/preview/0.png … n.png`：候选参考图（helper 转成的 PNG，供插件 UI 显示）。
- `runtime/choice.txt`：插件 UI 点选后写入 `"0"…"n"` 或 `"skip"`，helper 据此转线稿。
- `runtime/strokes.json`：

```json
{
  "word": "苹果",
  "query": "apple clipart",
  "aspect": 1.0,
  "strokes": [
    { "points": [[0.12, 0.34], [0.15, 0.38]], "width": 4, "color": [0, 0, 0] }
  ]
}
```

`points` 为归一化坐标：x ∈ [0,1] 左→右，y ∈ [0,1] 下→上；插件按图片宽高比等比
居中映射到画布。

---

## 逆向结论（关键注入点）

| 用途 | 类/成员 | 说明 |
|---|---|---|
| 读题 | `IngameDrawModule.SetWord(string, bool)` | protected，Harmony Hook 取 `__args[0]` |
| 单例 | `DrawModule.DrawModuleInstance` | public static property |
| 画布 | `DrawModule.DrawSurface`（`DrawableSurface`） | public property |
| 画布边界 | `DrawableSurface.MinX/MaxX/MinY/MaxY` | public float |
| 建笔画 | `DrawModule.CreateNewLine()` | private，反射调用 |
| 加点 | `DrawModule.TryAddNewPointToCurrentLine(Vector2, bool)` | private，反射调用 |
| 收笔 | `DrawModule.FinishLine(bool)` | protected，反射调用（传 false 避免追加鼠标点） |

## 游戏更新后如何修复

游戏更新若改动了 `Assembly-CSharp.dll`，用 `tools/` 里的脚本重新核对签名：

```bash
python tools/extract_signatures.py <新Assembly-CSharp.dll> --type DrawModule
python tools/disasm_il.py <新Assembly-CSharp.dll> --type DrawModule --method CreateNewLine
```

确认方法名/参数/可见性是否变化，再对应改 `DrawInjector.cs` / `WordHook.cs`。

---

## 常见问题

- **搜不到图 / 转线稿质量差**：调 `config.json` 里 `draw.canny_low/high`、`approx_eps`、
  `min_area`；或换搜索词风格（`image_to_strokes` 已按「clipart / 线稿」偏好组织）。
- **画出来位置/比例不对**：确认 `image_to_strokes` 输出了 `aspect`，且插件读到的
  `DrawSurface` 边界正确。
- **画不出来**：看 `BepInEx\LogOutput.log` 是否有异常；确认 `runtime_dir` 两侧一致。
