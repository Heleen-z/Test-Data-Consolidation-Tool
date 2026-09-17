# Testing Data Consolidation Tool

这是一个完全在本机运行的测试原始数据检查、合并和趋势查看工具。程序从 Excel 表头模板的黄色或绿色单元格中读取需要合并的字段名称，再按字段名称匹配真实项目文件。真实项目文件不需要带颜色。

## 第一阶段支持范围

- 正式支持 FAKT TXT、GANTER CSV、SEOUL CSV、T13 TXT。
- 支持结构与模板一致的通用 CSV、TXT、XLSX/XLSM。
- T09 TDMS、T12 专用文件和 M+P 二进制格式属于第二阶段；当前 Pre-check 会明确提示尚未支持，不会生成可能错误的数据。
- 当前不进行温度跳变、漂移、上下限或 AI 异常识别。

## 中央配置与模板管理

第一次部署请从 [完整中文逐步部署教学](docs/DEPLOYMENT_STEP_BY_STEP_ZH.md) 开始，按顺序完成本机试点、AI Portal 建表、公共盘发布、用户分发和上传验收。

版本 1.1.0 起支持从统一公共盘读取版本化运营配置和标准模板包。程序、运营配置和模板分别维护版本；支持邮箱、公告和模板更新不再要求重新生成 EXE。公共盘不可用时使用本机最后一次有效缓存。

发布目录采用可携带布局：EXE、`config` 配置目录和 `template` 模板目录必须保持同级；所有可调整的发布路径从 `config/app_settings.yaml` 读取。生产部署方法和生命周期规则见 [docs/MANAGED_CONFIGURATION.md](docs/MANAGED_CONFIGURATION.md)，公共盘文件搭建、JSON 修改、路径检查和回滚的逐步教程见 [docs/PUBLIC_DRIVE_RELEASE_GUIDE.md](docs/PUBLIC_DRIVE_RELEASE_GUIDE.md)。

## 使用方法

1. 双击 `Testing Data Consolidation Tool.exe`。首次运行时，单文件程序解压依赖可能需要几分钟。
2. 浏览器自动打开本地网页，页面仅监听 `127.0.0.1`。原始测试数据在本机处理；使用记录默认本地缓存，启用在线模式后上传成功任务的统计字段到 AI Portal。
3. 指定原始数据输入目录、输出目录和表头模板目录。
4. 点击“开始 Pre-check”。只有“有效”和“有警告但可合并”的文件计入可合并文件数。
5. 可合并文件数大于 0 后点击“开始合并”。
6. 合并完成后选择测试类型、来源文件和通道查看图表，或下载合并文件。

输出工作簿包含 `Summary`、每个测试类型的数据表、`Source_Index` 和 `Validation`。类型表显示必要的时间/循环轴和模板高亮字段；`__source_id`、`__source_row`、`__axis_value`、`__sort_order` 为隐藏追溯字段。

更完整的操作和结果解释见 [docs/USER_GUIDE.md](docs/USER_GUIDE.md)，开发与打包说明见 [docs/BUILD.md](docs/BUILD.md)。

## 源码运行

```powershell
python -m pip install -e ".[dev,build]"
python run_tool.py
```

## 自动测试

```powershell
python -m pytest -q
```

## 公司电脑生成发布版 EXE

GitHub 不直接保存打包后的 EXE，因为单文件产物通常超过 GitHub 普通文件 100 MB 限制。公司电脑拉下源码后，在项目根目录运行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\build_release.ps1
```

脚本会自动创建构建环境、安装依赖、运行测试并生成：

```text
dist\Testing Data Consolidation Tool.exe
```

构建完成后，`dist\release-info.txt` 会记录构建时间、Git 提交号、EXE 大小和 SHA256。
