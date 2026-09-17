# 开发、测试与 Windows 打包

## Excel 日志桥资源

发布包包含 src/testdata_tool/bridge 下的预构建 excel_bridge.xlsm、Bridge.bas 和哈希清单。修改 VBA 后，在具备 Excel 和开发用 VBA 工程访问权限的环境运行 python scripts/build_excel_bridge.py。脚本生成工作簿后会重新打开并验证宏入口；终端用户无需 VBA 工程访问权限。PyInstaller 构建会校验资源哈希，缺失或不匹配时停止。

Windows 依赖包含 pywin32，桥辅助进程通过 multiprocessing freeze_support 从同一 EXE 启动。运行 python scripts/verify_excel_bridge.py 做本机回环验证；可选 --sharepoint-read-only 只读验证公司 SharePoint 登录，不创建生产列表项。

## 环境

- Windows 10/11 64 位；
- Python 3.11–3.13；
- 建议在全新虚拟环境构建，避免把无关包收进 EXE。

## 安装与测试

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## 本地启动

```powershell
python run_tool.py
```

## 公司电脑一键构建发布 EXE

从 GitHub 拉下源码后，在项目根目录打开 PowerShell，执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_release.ps1
```

脚本会自动完成：

- 检查本机 Python 版本，要求 3.11、3.12 或 3.13；
- 创建独立构建虚拟环境 `.venv-build`；
- 安装运行、测试和 PyInstaller 打包依赖；
- 执行自动测试；
- 清理旧构建产物；
- 生成 Windows 单文件 EXE；
- 输出 EXE 路径、文件大小和 SHA256 校验值。

结果位于：

```text
dist\Testing Data Consolidation Tool.exe
```

同时会生成：

```text
dist\release-info.txt
```

如果只是快速验证打包、不想运行测试，可以执行：

```powershell
.\build_release.ps1 -SkipTests
```

如果想保留 PyInstaller 中间缓存，可以执行：

```powershell
.\build_release.ps1 -KeepBuildCache
```

旧入口仍然可用：

```powershell
.\scripts\build.ps1
```

它会转调用根目录的发布脚本。

## 手动构建单文件 EXE

```powershell
.\scripts\build.ps1
```

结果位于 `dist\Testing Data Consolidation Tool.exe`。配置、网页入口和标准模板被打包进单文件；如果 EXE 同目录存在 `Raw data standard Title`，程序优先使用外部模板，方便业务人员更新模板而不重新打包。

正式发布前，应在没有安装 Python 的干净 Windows 虚拟机上完成：首次启动、中文路径、Pre-check、混合类型合并、图表、下载、浏览器关闭后的空闲退出等验收。

## 增加新格式

解析器必须实现 `probe`、`inspect` 和 `iter_batches`，注册到 `ParserRegistry`，并在 `config/test_types.yaml` 指定 parser ID、扩展名、结构指纹、横轴类型和候选字段。专用格式必须使用脱敏真实样本及人工确认结果建立 golden test，不能仅按扩展名宣称支持。
