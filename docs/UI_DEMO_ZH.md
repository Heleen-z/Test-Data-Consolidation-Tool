# 本地网页 UI 模拟验收

此目录用于本工具的 Pre-check、合并和图表验收，不是 AI Portal 统计页面。数据均为合成值，不代表真实试验结果。

## 打开

在项目的 `outputs/ui-demo` 中运行 `start_ui_demo.ps1`（右键使用 PowerShell 运行），浏览器自动打开本地网页。也可在项目根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\outputs\ui-demo\start_ui_demo.ps1
```

输入、输出和模板路径已预填。独立的 `local-config.yaml` 设置 `usage_logging.mode: off`；启动脚本把偏好和缓存放入演示目录的 `profile`，不修改正式配置和正式使用记录队列。请通过启动脚本打开，以保持偏好隔离。

## 检验顺序

1. 点击“开始 Pre-check”：扫描 8 个文件，预计 5 个可合并。其余为缺少时间轴、空文件和完全重复文件。重复文件保留哪一份取决于扫描顺序。
2. 检查长文件名、警告和错误提示是否易读。在有效文件列表取消勾选一个文件，确认选择数量变化；再勾选回来。
3. 点击“开始合并”：全部有效文件被选择时输出 5,301 行，其中 GANTER 2,700 行、FAKT 600 行、T09 2,001 行。检查三个下载按钮。
4. GANTER 默认前四个通道包括两条温度与 SPEED/TORQUE，可直接检查两图分组。拖动底部范围预览验证横轴联动，拖动右侧手柄验证纵轴独立缩放。
5. GANTER 第一个连续区间在第 617 秒有单点温度尖峰，TCK_02 在第 850–859 秒为空。增加 `Toal Flow` 检查常量通道，再增加 POWER/ACCELERATION 检查小幅数据。
6. 切换到 T09：横轴从 0 到 20，间隔 0.01，共 2,001 点。使用图旁快捷截图按钮，检查 10 轮次导出。

所有生成的行都会交给现有数据流程，不做降采样。预检中故意缺陷文件被排除，与图表降采样无关。

## 文件与重新生成

- `input`：模拟输入文件。
- `templates`：仅供演示的高亮表头模板，不替换生产模板。
- `output`：本次验收生成的工作簿和中间文件。
- `expected.json`：预期文件数和输出行数。

生成器为 `scripts/build_ui_demo.mjs`，需要 Node.js 和 `@oai/artifact-tool`。它拒绝覆盖已有 `outputs/ui-demo`，重新生成前请先把旧演示目录改名保留。生成后运行 `python scripts/normalize_ui_demo.py` 补齐 Excel 只读解析所需的范围元数据，再用构建环境运行 `python scripts/verify_ui_demo.py` 验证实际 UI。启动脚本首次从 `dist` 复制现有 EXE。本次只增加验收文件，不修改应用功能。
