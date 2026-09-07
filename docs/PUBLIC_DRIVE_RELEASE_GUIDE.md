# 公共盘发布、配置、模板与路径检查教程

本文面向 `Testing Data Consolidation Tool` 的发布管理员。普通用户只需要从公共盘复制 EXE 到本机并运行，不应修改公共盘上的配置、模板或发布清单。

首次部署（含 AI Portal 使用记录）请优先按 [完整逐步部署教学](DEPLOYMENT_STEP_BY_STEP_ZH.md) 操作，本文作为公共盘部分的详细参考。

## 1. 正式公共盘地址

标准 UNC 地址是：

```text
\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool
```

注意：UNC 地址开头是两个反斜杠 `\\`，不是三个。不要使用 `Z:`、`Y:` 等个人映射盘符，因为不同用户的盘符可能不同。

程序 `1.1.0` 以后已经把这个地址作为打包 EXE 的默认中央配置根目录。源码开发运行不会自动连接生产公共盘；开发测试时需要显式设置 `TESTDATA_TOOL_CONFIG_ROOT`。

## 2. 公共盘最终目录结构

第一次发布前，在公共盘根目录创建以下结构：

```text
Test Data Consolidation Tool\
├─ release-manifest.json
├─ configs\
│  └─ 2026.09.001\
│     └─ operations.yaml
├─ templates\
│  └─ 2026.09.001\
│     └─ TemplateBundle.zip
└─ app\
   └─ 1.1.0\
      └─ Testing Data Consolidation Tool.exe
```

目录含义：

- `release-manifest.json`：程序启动时首先读取的当前发布清单。
- `configs`：运营配置历史版本。邮箱或公告变化也必须创建新版本目录。
- `templates`：标准模板整包历史版本。
- `app`：正式 EXE 历史版本。

版本目录一旦发布不得覆盖或改写。需要修改时创建新版本，例如 `2026.09.002`，然后更新根目录的 `release-manifest.json`。

## 3. 第一次准备运营配置

从仓库中的 `deployment/example-operations.yaml` 复制一份到：

```text
configs\2026.09.001\operations.yaml
```

建议内容：

```yaml
schema_version: 1

contact:
  owner: Data Tool Support
  email: jing.pei@Forvia.com
  phone: "+86-1522-173-4487"
  note: 如程序报错，请截图并附上 Processing Log.txt 联系支持人员。

defaults:
  input_folder: ''
  output_folder: ''

ui:
  brand_title: Testing Raw Data Consolidation
  announcement: ''
  help_text: ''

managed_templates:
  required: true
  download_label: 下载当前标准模板包
  update_message: 正在更新标准模板，请勿关闭程序……
  success_message: 标准模板已更新至版本 {version}

support_links:
  user_guide: ''
  issue_form: ''
```

维护规则：

- YAML 使用空格缩进，不使用 Tab。
- 电话建议放在引号内，避免被解析成数字。
- 空路径写成 `''`。
- `user_guide` 和 `issue_form` 目前只接受 `http://` 或 `https://` 链接。
- 不得加入 `test_types`、parser、扩展名、横轴、Python 代码、命令、密码或令牌。
- 字段名拼错或出现未知字段时，程序会拒绝激活该配置。

## 4. 第一次准备模板整包

模板 ZIP 可以把 XLSX 文件直接放在 ZIP 根目录，也可以只包含一个 `Raw data standard Title` 子目录。推荐结构：

```text
TemplateBundle.zip
└─ Raw data standard Title\
   ├─ FAKT 原始记录文件表头.xlsx
   ├─ GANTER 原始记录文件表头.xlsx
   ├─ Seoul 原始记录文件表头.xlsx
   ├─ T09 Diesel burner 原始记录文件表头.xlsx
   ├─ T12 原始记录文件表头.xlsx
   ├─ T13 原始记录文件表头.xlsx
   └─ M+P shaker 导出数据 表头.xlsx
```

将 ZIP 放到：

```text
templates\2026.09.001\TemplateBundle.zip
```

可以用 PowerShell 创建：

```powershell
$templateSource = 'C:\Path\To\Raw data standard Title'
$templateZip = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool\templates\2026.09.001\TemplateBundle.zip'
Compress-Archive -Path "$templateSource\*" -DestinationPath $templateZip
```

发布前打开 ZIP，确认：

- 至少包含一个 `.xlsx` 文件；
- 没有临时文件 `~$*.xlsx`；
- 没有其他项目的原始测试数据；
- 每个模板能用 Excel 正常打开；
- 文件名包含程序能够识别的测试类型关键词。

## 5. 放置正式 EXE

将经过测试的 `1.1.0` EXE 放到：

```text
app\1.1.0\Testing Data Consolidation Tool.exe
```

不要直接把新版 EXE 覆盖在 `app\1.1.0` 中。如果代码有变化，应生成新程序版本目录，例如：

```text
app\1.1.1\Testing Data Consolidation Tool.exe
```

## 6. 计算配置和模板 SHA256

打开 PowerShell，执行：

```powershell
$releaseRoot = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool'
$configPath = Join-Path $releaseRoot 'configs\2026.09.001\operations.yaml'
$templatePath = Join-Path $releaseRoot 'templates\2026.09.001\TemplateBundle.zip'

Get-FileHash -LiteralPath $configPath -Algorithm SHA256
Get-FileHash -LiteralPath $templatePath -Algorithm SHA256
```

复制输出中的完整 64 位 `Hash`。配置文件只要改变一个字符，SHA256 就会变化，因此每次修改后必须重新计算。

## 7. 创建 release-manifest.json

根目录的清单应类似：

```json
{
  "schema_version": 1,
  "channel": "production",
  "published_at": "2026-09-03T10:00:00+08:00",
  "published_by": "Jing Pei",
  "config": {
    "version": "2026.09.001",
    "path": "configs/2026.09.001/operations.yaml",
    "sha256": "在这里填写 operations.yaml 的完整 SHA256"
  },
  "templates": {
    "version": "2026.09.001",
    "path": "templates/2026.09.001/TemplateBundle.zip",
    "sha256": "在这里填写 TemplateBundle.zip 的完整 SHA256",
    "display_name": "FORVIA Test Data Standard Templates"
  },
  "application": {
    "latest_version": "1.1.0",
    "minimum_supported_version": "1.1.0",
    "download_path": "app/1.1.0/Testing Data Consolidation Tool.exe",
    "release_note": "新增中央配置、模板自动更新和版本检查"
  }
}
```

JSON 修改规则：

- JSON 不允许写注释。
- 最后一项后面不能有逗号。
- 字符串必须使用双引号。
- `config.path`、`templates.path` 和 `download_path` 必须是相对于公共盘根目录的路径。
- 相对路径建议统一使用 `/`，不要在 JSON 中写完整 UNC。
- `schema_version` 保持数字 `1`，不要写成字符串 `"1"`。
- `latest_version` 是推荐使用的最新 EXE。
- `minimum_supported_version` 是仍允许处理数据的最低 EXE。
- 普通升级时可以只提高 `latest_version`；必须强制升级时才提高 `minimum_supported_version`。

保存前可以检查 JSON 语法：

```powershell
$manifestPath = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool\release-manifest.json'
Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
```

如果 PowerShell 显示解析错误，不要发布该文件。

## 8. 完整路径和哈希检查

推荐直接在项目根目录运行只读检查脚本：

```powershell
.\scripts\validate_managed_release.ps1
```

脚本默认检查本文的正式 UNC 地址，也可以检查 staging 或测试目录：

```powershell
.\scripts\validate_managed_release.ps1 -ReleaseRoot 'C:\Temp\TestDataToolRelease'
```

该脚本不会创建、修改或删除公共盘文件。它检查 JSON、版本格式、相对路径、文件存在性、SHA256 和模板 ZIP 中的 XLSX 数量。

如需手工检查，可运行：

```powershell
$releaseRoot = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool'
$manifestPath = Join-Path $releaseRoot 'release-manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json

$configPath = Join-Path $releaseRoot ($manifest.config.path -replace '/', '\')
$templatePath = Join-Path $releaseRoot ($manifest.templates.path -replace '/', '\')
$appPath = Join-Path $releaseRoot ($manifest.application.download_path -replace '/', '\')

[PSCustomObject]@{
    ManifestExists = Test-Path -LiteralPath $manifestPath
    ConfigExists = Test-Path -LiteralPath $configPath
    TemplateExists = Test-Path -LiteralPath $templatePath
    AppExists = Test-Path -LiteralPath $appPath
    ConfigHashOK = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash -eq $manifest.config.sha256
    TemplateHashOK = (Get-FileHash -LiteralPath $templatePath -Algorithm SHA256).Hash -eq $manifest.templates.sha256
}
```

所有结果都必须为 `True`。如果 `Exists=True` 但 `HashOK=False`，说明文件内容与 manifest 不一致，不能上线。

## 9. 第一次上线检查

在一台试点电脑上：

1. 从 `app\1.1.0` 复制 EXE 到本机。
2. 双击本机 EXE。
3. 首次启动应显示正在检查中央配置和标准模板。
4. 首次同步模板时应显示更新成功信息。
5. 页面顶部应显示：

```text
程序 1.1.0 · 配置 2026.09.001 · 模板 2026.09.001 · 配置来源 central
```

6. 支持邮箱、电话和公告应与 `operations.yaml` 一致。
7. 模板目录应为只读的本机受管目录，用户不能手工替换。
8. 侧边栏应能下载当前模板整包。
9. 使用一份脱敏样例执行 Pre-check 和合并。
10. 检查 `Merged Dataset.xlsx` 的 Summary 是否包含程序、配置和模板版本。
11. 检查 `Processing Log.txt` 是否记录三种版本和配置来源。

本机缓存可以在以下位置检查：

```text
%LOCALAPPDATA%\FORVIA\TestDataConsolidation\managed
```

不要在普通问题排查时直接删除该目录；它是公共盘不可用时的 last-known-good。

## 10. 测试公共盘不可用时的回退

先确保试点电脑至少成功启动过一次。然后在单独 PowerShell 窗口中临时指定一个不存在的测试路径：

```powershell
$env:TESTDATA_TOOL_CONFIG_ROOT = '\\10.162.2.55\shares\__TestDataTool_Offline_Test__'
& 'C:\Path\To\Testing Data Consolidation Tool.exe'
Remove-Item Env:TESTDATA_TOOL_CONFIG_ROOT
```

预期结果：

- 程序在中央清单超时或失败后继续启动；
- 页面显示使用上次有效版本的警告；
- 配置来源显示 `cache`；
- 配置版本和模板版本仍是上次成功版本；
- Pre-check 和合并仍可执行。

## 11. 只修改邮箱或公告

不要直接编辑 `configs\2026.09.001\operations.yaml`。正确步骤：

1. 创建 `configs\2026.09.002`。
2. 把上一版本 `operations.yaml` 复制进去。
3. 修改邮箱、电话、公告或默认目录。
4. 重新计算新文件 SHA256。
5. 修改 manifest 中：
   - `published_at`；
   - `published_by`；
   - `config.version`；
   - `config.path`；
   - `config.sha256`。
6. 模板和程序部分保持不变。
7. 执行路径和哈希检查。
8. 在试点电脑重新启动 EXE，确认新配置生效。

这个过程不需要重新生成或重新复制 EXE。

## 12. 只更新模板

正确步骤：

1. 创建新的模板版本目录，例如 `templates\2026.09.002`。
2. 生成新的 `TemplateBundle.zip`。
3. 检查 ZIP 内容和 XLSX 文件。
4. 计算新 ZIP 的 SHA256。
5. 修改 manifest 中：
   - `published_at`；
   - `published_by`；
   - `templates.version`；
   - `templates.path`；
   - `templates.sha256`。
6. 配置和程序部分保持不变。
7. 在试点电脑重新启动。
8. 确认程序弹出模板更新提示，并切换到新模板版本。

模板更新不需要重新生成 EXE，但新模板必须仍符合当前程序支持的解析逻辑。如果新模板要求新的文件格式、解析器或识别算法，必须同步发布新 EXE。

## 13. 发布新 EXE

1. 根据代码变化更新 SemVer，例如从 `1.1.0` 到 `1.1.1`。
2. 完成全部自动化测试和 Windows 冒烟测试。
3. 创建 `app\1.1.1`，复制新版 EXE。
4. 修改 manifest 的 `application.latest_version` 和 `download_path`。
5. 如果旧版本仍兼容，保持 `minimum_supported_version: "1.1.0"`。
6. 如果旧版本会产生错误结果，再把 `minimum_supported_version` 提高到 `1.1.1`。
7. 用户下次启动旧版时会看到升级提示；低于最低版本时将不能继续处理数据。

## 14. 回滚

因为历史版本目录没有被覆盖，回滚不需要重新打包：

1. 找到上一个验证成功的配置版本和模板版本。
2. 复制当前 manifest 为本地备份。
3. 创建新的临时 manifest，把版本、路径和 SHA256 改回上一个有效组合。
4. 使用 `ConvertFrom-Json` 验证语法。
5. 执行完整路径和哈希检查。
6. 最后用临时文件替换根目录的 `release-manifest.json`。
7. 在试点电脑重新启动并确认配置来源为 `central`。

不要通过删除新版本目录来回滚；保留问题版本用于审计和问题分析。

## 15. 权限与发布纪律

- 普通用户：根目录、配置、模板和 EXE 全部只读。
- 发布管理员：具有写权限。
- 任何人不得直接编辑已经发布的版本目录。
- 永远先上传配置、模板和 EXE，最后更新 `release-manifest.json`。
- manifest 更新前必须完成 JSON 语法、路径和 SHA256 检查。
- 公共配置不得存储密码、令牌或敏感测试数据。
- 建议在根目录另建 `release-history.md`，记录每次发布日期、发布人、三种版本、变更原因、验证结果和回滚版本。

## 16. 常见问题

### 页面显示 `built-in`

表示当前运行的是源码环境，或者 EXE 没有读取到中央地址。检查是否为正式 `1.1.0` EXE，以及 `central_management.central_root` 是否正确。

### 页面显示 `cache`

表示本次没有成功读取中央版本，程序正在使用 last-known-good。检查公共盘权限、网络、manifest 语法、路径和 SHA256。

### 修改配置后用户没有看到变化

检查是否：

- 创建了新的 `config.version`；
- 更新了 `config.path`；
- 重新计算了 SHA256；
- 最后更新了根目录 manifest；
- 用户完全关闭并重新打开了 EXE。

### 模板更新失败

检查 ZIP 中是否确实包含 `.xlsx`、文件是否能打开、SHA256 是否一致，以及 ZIP 是否包含 `..` 等不安全路径。

### 用户被要求强制更新程序

检查 `minimum_supported_version`。如果只是推荐升级，不要把最低支持版本同步提高到最新版。
