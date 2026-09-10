# Testing Data Consolidation Tool：从零到上线的部署教学

适用对象：负责发布本工具、维护公共盘和 AI Portal 的管理员。按步骤 1–12 依次操作，每一步检查通过后再继续。本文依据当前仓库实现编写，参考构建为 2026-09-05 的 1.1.0；版本示例不能用来覆盖已经发布的同名版本。

本文是操作说明，不表示已经替你创建网站列表或写入公共盘。当前已完成程序端实现和本机模拟请求测试，真实公司账号上传仍需按本文联调。

## 先认识整个部署链路

```text
管理员电脑：源码 → 测试和打包 → EXE、运营配置、标准模板包
                                  ↓
公共盘：版本目录 + release-manifest.json
                                  ↓ 用户复制 EXE 到本机
用户电脑：启动 → 读取公共盘配置和模板 → Pre-check → 点击开始合并
                                                        ↓ 生成可用结果
                                                本机保存一条成功记录
                                                        ↓ online 模式
AI Portal 的 SharePoint List：Test Data Consolidation Logs
                                                        ↓
                                         AI Portal 页面展示／使用量统计
```

三个地方各有用途：公共盘负责分发 EXE、配置和模板；用户电脑处理真实数据并保存使用记录队列；AI Portal 保存成功使用记录。程序界面在用户本机浏览器运行，AI Portal 无需托管这个 Streamlit 程序。

**成功口径：**一次点击“开始合并”并生成可用结果计一次。多个文件、多个测试类型仍计一次；部分文件失败但生成结果仍计一次，并附带失败数。整个合并失败、Pre-check、启动、刷新、下载和截图不计数。项目名自动取输入目录最后一级名称。

## 步骤 1：准备账号、目录和安装包

**在哪里操作：管理员电脑、文件资源管理器、AI Portal 浏览器。**

1. 确认你能打开项目目录：`C:\Users\HBZuo\Desktop\forvia\Test-Data-Consolidation-Tool`。
2. 确认能够打开正式公共盘，并有发布目录写入权限：

   `\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool`

3. 确认你是 AI Portal 的站点所有者，或有人可以代建列表和配置权限：

   [打开 AI Portal](https://faurecia.sharepoint.com/sites/AIPortal)

4. 准备一份已知能合并的脱敏样例。保留其预期文件数、测试类型和输出行数，后面用它验收。
5. 普通用户电脑需要公司批准的 Windows 环境和浏览器，不需要自行安装 Python。管理员只有重新打包时才需要 Python 3.11–3.13。

**检查通过：**公共盘可访问，网站有建列表入口，手中有可用 EXE 和样例。没有权限时由相应管理员配置，不修改整个 AI Portal 的全站权限。

## 步骤 2：确认使用哪个 EXE

**在哪里操作：项目目录的 `dist` 文件夹。**

现有产物：

- [dist/Testing Data Consolidation Tool.exe](../dist/Testing%20Data%20Consolidation%20Tool.exe)：分发给用户的程序。
- [dist/release-info.txt](../dist/release-info.txt)：本次构建时间和 SHA256。
- [dist/local-config.yaml](../dist/local-config.yaml)：本地测试用配置。

可以使用已交付的 EXE。若源码有更新，由管理员在项目根目录 PowerShell 执行以下命令重新打包；先关闭正在运行的旧 EXE：

```powershell
Set-Location -LiteralPath 'C:\Users\HBZuo\Desktop\forvia\Test-Data-Consolidation-Tool'
.\build_release.ps1
```

查看输出，确认 pytest 成功、PyInstaller 成功，且 `release-info.txt` 时间对应本次构建。当前脚本主要依靠命令输出判断测试结果，不能只凭最后出现 EXE 文件就认为所有测试通过。若公司阻止脚本执行，使用公司允许的执行方式或联系 IT。

**检查通过：**EXE 能启动，构建时间和哈希已登记。代码更新后的正式版本需要同时更新 `pyproject.toml` 与 `src/testdata_tool/__init__.py` 的版本并重新打包。已有 `app\1.1.0` 时不得用不同内容覆盖它，应使用新的程序版本。

## 步骤 3：先让工具在本机跑通

**在哪里操作：试点电脑的独立文件夹，例如 `C:\TestDataToolPilot`。**

1. 新建文件夹并放入 EXE。
2. 从 [本地配置示例](../deployment/local-config.yaml.example) 复制一份，命名为 `local-config.yaml`，与 EXE 放在同一级。
3. 文件资源管理器开启“查看 → 显示 → 文件扩展名”，确认文件不是 `local-config.yaml.txt`。
4. 配置中应包含下列内容；有同名节时修改原节，不能重复追加第二个 `usage_logging`：

```yaml
schema_version: 1
usage_logging:
  mode: cache_only
  site_url: https://faurecia.sharepoint.com/sites/AIPortal
  list_name: Test Data Consolidation Logs
```

以上可以作为最小本地配置，也可以保留示例中的联系信息等其它节。用空格缩进，不使用 Tab。不要向文件写入公司密码或登录令牌。

5. 双击本机 EXE。页面配置来源应为 `local sidecar`，使用记录应显示“仅本地记录”。
6. 选择样例输入目录、独立输出目录和模板目录。EXE 内有内置模板；也可以在本地测试中选择外部标准模板目录。
7. 点击“开始 Pre-check”，勾选需要合并的有效文件，然后点击“开始合并”。
8. 检查工作簿、验证报告和日志能打开，输出内容符合样例预期；使用记录待同步数应比合并前增加 1。
9. 刷新页面不应增加记录。项目目录名会成为本次 `ProjectName`。

**检查通过：**业务流程完成且保存了本地记录。若此时已有历史缓存，用“增加 1 条”判断，不要求总数恰好为 1。

## 步骤 4：在 AI Portal 建立列表

**在哪里操作：AI Portal 站点，不是“我的列表”个人空间。**

1. 打开 AI Portal，齿轮 → **Site contents / 网站内容**。
2. 选择 **New / 新建 → List / 列表 → Blank list / 空白列表**。
3. 名称准确填写 `Test Data Consolidation Logs`，描述可填“测试数据合并工具成功使用记录”。
4. 确认保存位置是 AI Portal 站点，创建列表。

如果要尽量模仿 ebom，也可以选择 **From existing list / 从现有列表**，以 `EBOM Conversion Logs` 为基础。微软说明此方式复制列、视图和格式而不复制已有数据；复制后仍要核对字段内部名、类型、必填约束、权限和自动规则，补齐下面字段。第一次部署推荐空白列表，便于逐项核对。[微软：创建列表](https://support.microsoft.com/en-us/sharepoint/lists/data-and-lists/create-a-list)、[从现有列表创建](https://support.microsoft.com/en-us/office/create-a-new-list-based-on-the-columns-in-another-list-49666e8c-8c48-414f-8e5e-dc0e232acd27)

**检查通过：**网站内容中能看到准确名称的列表；它位于 `/sites/AIPortal` 站点下。

## 步骤 5：逐个创建字段并设置唯一编号

**在哪里操作：刚创建的 SharePoint List。**

点击“添加列 / Add column”，先用下面英文名创建，再按需改成中文显示名称。程序依赖英文内部名，不能先用中文建列、再仅把显示名称改成英文。已有列不要重复创建；默认 `Title` 直接保留。

### 5.1 单行文本列（最大 255 字符）

- `Title`：状态；默认列，程序写入 `SUCCESS`。
- `EventId`：任务唯一编号；必须必填且唯一。
- `InputFormat`：输入格式；例如 `csv;txt`。
- `OutputFormat`：输出格式；固定 `XLSX`。
- `UserName`：Windows 用户名。
- `UserEmail`：用户 UPN；可能为空。
- `ComputerName`：电脑名。
- `ProjectName`：输入目录最后一级名称。
- `TestTypes`：实际输出测试类型，例如 `T09;T12`。
- `AppVersion`：程序版本。
- `ConfigVersion`：配置版本。
- `TemplateVersion`：模板版本。

这些字段均使用“单行文本”，包括用户邮箱和项目名称；不要把它们设为“人员或组”或“查阅”类型。

### 5.2 日期、数字和多行文本

- `Timestamp`：日期和时间，包含时间。程序写入 UTC 完成时间，网站显示时区按站点设置。
- `RowCount`：数字，0 位小数，实际输出行数之和。
- `FileCount`：数字，0 位小数，实际选中文件数。
- `FailedFileCount`：数字，0 位小数，本批合并失败文件数。
- `Duration`：数字，2 位小数，处理耗时（秒）。
- `ErrorMessage`：多行纯文本，不启用富文本和追加更改；仅用于部分失败的数量摘要。

除默认 `Title` 和 `EventId` 外，其余字段设为非必填。设置方法见[微软：创建列](https://support.microsoft.com/en-us/sharepoint/lists/data-and-lists/create-a-column-in-a-list-or-library)。

### 5.3 设置 EventId

1. 齿轮 → List settings / 列表设置 → Columns / 列 → `EventId`。
2. 将“要求此列包含信息”设为“是”。
3. 将“强制唯一值 / Enforce unique values”设为“是”。
4. 返回列表设置 → Indexed columns / 索引列，确认 `EventId` 有索引；没有则创建。
5. 建议再为 `Timestamp` 建索引，便于后续按时间查询。

唯一值约束配合本机 UUID 防止离线补传重复计数。[微软：列表设置和列属性](https://support.microsoft.com/en-us/sharepoint/lists/data-and-lists/edit-list-settings)

**检查通过：**包含默认 `Title` 在内共 19 个业务字段，类型正确，`EventId` 必填且唯一。默认系统列 ID、Created、Modified 等不计入这 19 个字段。

## 步骤 6：设置列表权限，检查读取接口

**在哪里操作：SharePoint 列表设置，由站点所有者操作。**

1. List settings → Permissions for this list / 此列表的权限。
2. 查看现有继承权限。如果已满足需求，可以保持；如需单独管理本列表，再停止继承。
3. 保留站点所有者和发布管理员权限。
4. 为工具使用者所在公司组提供“查看列表项”和“添加列表项”权限。可请 SharePoint 管理员建立相应自定义权限级别；`Contribute / 参与` 通常还包含编辑和删除，不等同于仅新增。
5. 若采用“用户只读取自己创建的项目”，管理员仍需能查看全量记录；补传应使用创建记录的同一公司账号。不要采用完全禁止用户读取的配置，程序需要按 EventId 查询去重。

权限、索引等入口说明见[微软列表设置文档](https://support.microsoft.com/en-us/sharepoint/lists/data-and-lists/edit-list-settings)。

在已登录 AI Portal 的浏览器中打开下面的只读地址：

```text
https://faurecia.sharepoint.com/sites/AIPortal/_api/web/lists/getbytitle('Test%20Data%20Consolidation%20Logs')?$select=Title,ListItemEntityTypeFullName
```

应返回包含列表标题和 `ListItemEntityTypeFullName` 的 JSON 或 XML，而不是登录页面或“找不到列表”。若要核对内部列名，打开：

```text
https://faurecia.sharepoint.com/sites/AIPortal/_api/web/lists/getbytitle('Test%20Data%20Consolidation%20Logs')/fields?$select=Title,InternalName,TypeAsString,Required,EnforceUniqueValues,Indexed
```

**检查通过：**列表存在且当前浏览器账号可读。浏览器访问成功只证明该浏览器会话可用，不能证明 EXE 的 MSXML 请求已获得同样的登录状态；下一步才验证实际上传。

## 步骤 7：在试点电脑验证一次实际上传

**在哪里操作：步骤 3 的本机试点目录及 AI Portal 列表。**

1. 查看程序“仅本地记录”的待同步数。启用 online 会补传本账号目录中全部待传记录，不只是最近一次；此前测试任务也会保留。建议用专用 Windows 试点账号控制首次联调数据范围。
2. 关闭程序，等待 EXE 退出。在 `local-config.yaml` 中把 `usage_logging.mode` 从 `cache_only` 改为 `online`，其它两项保持不变。
3. 重开 EXE，等待状态从“待同步”变为“已同步”。
4. 在 AI Portal 列表刷新，按 `Timestamp` 降序查看；新增数量应与原待同步数一致。
5. 核对一条记录：`Title=SUCCESS`、`ProjectName` 为输入目录名、文件数和行数正确、`Timestamp` 为原转换完成时间。
6. 再主动完成一次合并，确认新增 1 条、EventId 不同。刷新和下载不新增。

**若未成功：**HTTP 401/403、登录页面说明要检查公司登录上下文、租户策略及权限；404 检查站点和列表名；400 检查内部列名、类型和必填字段。不要把 `whoami /upn` 能输出邮箱当作 SharePoint 登录成功，也不要手工添加密码到配置。

当前工具沿用 ebom 的 MSXML2.XMLHTTP.6.0；公司环境若不能复用该登录通路，需要 IT 确认允许的认证方式，再评估程序认证调整。建好列表本身不能解决所有认证问题。未联通时可以继续 cache_only 试点，但应把“在线上传”标记为未验收。

**检查通过：**至少一条由 EXE 实际上传的 SUCCESS 出现在列表中。可记录该 EventId 作为联调证据。

## 步骤 8：在本机准备完整中央发布目录

**在哪里操作：管理员电脑 PowerShell。保持以下几个命令块在同一个 PowerShell 窗口执行。**

本步骤先建立本机 staging（待发布目录），不直接修改公共盘。示例使用 EXE `1.1.0`、配置及模板 `2026.09.001`。如果这些版本已发布，请换成未使用版本；EXE 版本还必须和程序真实版本一致。

```powershell
$projectRoot = 'C:\Users\HBZuo\Desktop\forvia\Test-Data-Consolidation-Tool'
$stageRoot = 'C:\TestDataToolReleaseStaging'
$appVersion = '1.1.0'
$configVersion = '2026.09.001'
$templateVersion = '2026.09.001'
$releaseRoot = '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool'

if (Test-Path -LiteralPath $stageRoot) { throw '请选择一个新的 staging 目录，避免覆盖已有文件。' }
New-Item -ItemType Directory -Path $stageRoot | Out-Null
$appDir = Join-Path $stageRoot "app\$appVersion"
$configDir = Join-Path $stageRoot "configs\$configVersion"
$templateDir = Join-Path $stageRoot "templates\$templateVersion"
New-Item -ItemType Directory -Path $appDir,$configDir,$templateDir | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'dist\Testing Data Consolidation Tool.exe') -Destination $appDir
Copy-Item -LiteralPath (Join-Path $projectRoot 'deployment\example-operations.yaml') -Destination $configDir
Rename-Item -LiteralPath (Join-Path $configDir 'example-operations.yaml') -NewName 'operations.yaml'
$configPath = Join-Path $configDir 'operations.yaml'
notepad.exe $configPath
```

记事本打开后，把内容替换为下面的完整配置。联系信息按实际负责人填写；AI Portal 联调成功后用 `online`，尚未联通则暂用 `cache_only`：

```yaml
schema_version: 1
contact:
  owner: Data Tool Support
  email: jing.pei@Forvia.com
  phone: '+86-1522-173-4487'
  note: 请附上 Processing Log.txt 和错误截图联系支持人员。
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
usage_logging:
  mode: online
  site_url: https://faurecia.sharepoint.com/sites/AIPortal
  list_name: Test Data Consolidation Logs
```

保存 `operations.yaml` 并关闭记事本。中央配置不能指定 `defaults.template_folder`；模板由发布清单中的整包管理。YAML 使用 UTF-8 和空格缩进。

继续在同一 PowerShell 窗口执行：

```powershell
$templateSource = Join-Path $projectRoot 'Raw data standard Title'
$templateFiles = @(Get-ChildItem -LiteralPath $templateSource -File -Filter '*.xlsx' |
    Where-Object { -not $_.Name.StartsWith('~$') })
if ($templateFiles.Count -eq 0) { throw '标准模板目录中没有可发布的 XLSX。' }
$templateZip = Join-Path $templateDir 'TemplateBundle.zip'
Compress-Archive -LiteralPath $templateFiles.FullName -DestinationPath $templateZip
```

打开 ZIP 确认模板直接位于根目录且 Excel 能打开。ZIP 也支持一层子目录，但本教程命令生成根目录结构，不要手动再嵌套多层文件夹。

**检查通过：**staging 下已有 `app\1.1.0\EXE`、`configs\2026.09.001\operations.yaml` 和 `templates\2026.09.001\TemplateBundle.zip`。

## 步骤 9：生成清单并在本机验证中央模式

**在哪里操作：步骤 8 的同一 PowerShell 窗口。**

下面命令自动计算哈希并生成清单。先修改 `$publisher`，其它变量沿用上一步：

```powershell
$publisher = '填写你的姓名'
$manifest = [ordered]@{
    schema_version = 1
    channel = 'production'
    published_at = (Get-Date).ToString('o')
    published_by = $publisher
    config = @{
        version = $configVersion
        path = "configs/$configVersion/operations.yaml"
        sha256 = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash
    }
    templates = @{
        version = $templateVersion
        path = "templates/$templateVersion/TemplateBundle.zip"
        sha256 = (Get-FileHash -LiteralPath $templateZip -Algorithm SHA256).Hash
        display_name = 'FORVIA Test Data Standard Templates'
    }
    application = @{
        latest_version = $appVersion
        minimum_supported_version = $appVersion
        download_path = "app/$appVersion/Testing Data Consolidation Tool.exe"
        release_note = 'Central configuration, managed templates and success usage logging'
    }
}
$manifestPath = Join-Path $stageRoot 'release-manifest.json'
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 8), $utf8NoBom)
& (Join-Path $projectRoot 'scripts\validate_managed_release.ps1') -ReleaseRoot $stageRoot
```

**必须看到** `Managed release validation passed.`。该脚本检查路径、哈希和 ZIP 中的模板数量；不等于已验证全部运营字段及实际模板解析。

清单 JSON 必须是 **UTF-8 无 BOM**。当前程序用 UTF-8 读取 JSON；Windows PowerShell 5.1 的 `Set-Content -Encoding UTF8` 会带 BOM，故上面使用 `WriteAllText` 明确编码。哈希计算以后修改 YAML 或 ZIP，要重新生成清单。

接着验证完整启动：

1. 另建 `C:\TestDataToolManagedPilot`，只复制 EXE，不复制 `local-config.yaml`。
2. 在该文件夹用记事本创建 `bootstrap.yaml`，内容如下：

```yaml
central_root: 'C:\TestDataToolReleaseStaging'
```

3. 双击 EXE。确认配置来源为 `central`，配置、模板版本均正确，模板目录已受管。
4. 完成一次样例 Pre-check 和合并；检查 Summary、日志中的三个版本，以及使用记录同步情况。

**检查通过：**程序确实使用 staging 中的配置和模板。若显示 `local sidecar`，先检查 EXE 旁是否误放了 `local-config.yaml`；若显示 `cache`，不能视为本次新发布验证成功。

## 步骤 10：发布到公共盘

**在哪里操作：管理员文件资源管理器和 PowerShell。首次发布按以下步骤；后续更新另见步骤 12。**

正式结构应是：

```text
Test Data Consolidation Tool\
├─ release-manifest.json
├─ configs\2026.09.001\operations.yaml
├─ templates\2026.09.001\TemplateBundle.zip
└─ app\1.1.0\Testing Data Consolidation Tool.exe
```

1. 在正式公共盘建立根目录，普通用户只读、发布管理员可写。
2. 从 staging 复制新建的三个版本目录到公共盘对应位置。遇到已存在版本目录时停止，不选择覆盖；先确认是复用完全相同的版本，还是必须另建版本。
3. 配置、模板和 EXE 复制完成后，先用 `Get-FileHash` 对照 staging 核对三个文件。
4. 把 staging 清单复制到公共盘根目录，临时命名为 `release-manifest.pending.json`。
5. 首次发布时，在资源管理器把它重命名为 `release-manifest.json`；若已有该文件，按步骤 12 的更新规则处理。
6. 运行正式目录检查：

```powershell
& (Join-Path $projectRoot 'scripts\validate_managed_release.ps1') -ReleaseRoot $releaseRoot
```

7. 新建一个最终试点文件夹，只从公共盘复制 EXE，不带步骤 9 的 `bootstrap.yaml` 和步骤 3 的 `local-config.yaml`。
8. 双击启动，确认 `central`、三种版本正确，再完成一次合并与 AI Portal 上传验证。

**检查通过：**最终试点通过默认 UNC 地址读取公共盘，不依赖管理员 staging 路径。记录发布日期、发布人、三个版本、EXE SHA256 和一个成功上传 EventId。

## 步骤 11：给普通用户发程序，在 AI Portal 展示记录

### 11.1 发放给用户

给用户发送公共盘中经过验证的 EXE 路径，要求复制到本机后运行。用户文件夹中通常只需要 EXE。

**不要把整个 `dist` 文件夹直接作为正式用户包发送。** 构建脚本会保留或生成 `dist\local-config.yaml`，这个文件存在时会绕过公共盘；正式用户无需携带它。需要保留测试设置时可另存到测试文件夹，不必删除。

用户第一次启动必须能读取中央发布配置；成功启动后才有可回退的本机缓存。公司未允许离线首次运行时，不能用删除缓存的方式排查网络问题。

给用户的简短操作说明：复制 EXE 到本机 → 双击 → 选输入和输出目录 → Pre-check → 勾选文件 → 开始合并 → 查看和下载结果。

### 11.2 AI Portal 页面

先在列表创建“最近成功记录”视图：过滤 `Title=SUCCESS`，按 `Timestamp` 降序，显示时间、用户、项目、测试类型、文件数、行数、耗时和失败数。可再建“部分文件失败”视图，过滤 `FailedFileCount>0`。

如果 AI Portal 页面是 SharePoint 现代页面：打开页面 → Edit / 编辑 → 添加 **List / 列表 Web 部件** → 选择 `Test Data Consolidation Logs` 和上述视图 → 发布页面。页面展示不会扩大列表读取权限。[微软：List Web 部件](https://support.microsoft.com/en-us/SharePoint/lists/web-parts-and-apps-in-sharepoint/use-the-list-web-part)

如果 AI Portal 前端使用 Power Apps 或自定义页面，仍使用这个 SharePoint List 作为数据源；页面入口由网站维护者接入，无需改变 EXE 的列表字段。

统计成功次数按 `Title=SUCCESS` 的记录数计算。显示月份前先统一 `Timestamp` 时区，不要用 SharePoint 系统 `Created` 代替业务时间，因为离线补传的创建时间可能晚很多。`FileCount` 和 `RowCount` 可以分别求和表示处理量；拆分多个 TestTypes 后的跨类型总计要按 EventId 去重。若以后做 Power Apps / Power BI 统计，要处理服务端分页或委派，避免只统计客户端已加载的前一部分列表项。

## 步骤 12：后续更新、离线验收与回滚

### 12.1 只修改公告、联系信息或上传模式

创建新的配置版本，例如 `configs\2026.09.002`，复制上一份 operations 后修改。计算新哈希，更新清单中的 `config` 和发布信息。模板与 EXE 版本可继续引用旧目录。用户重新启动后生效，无需重打包。

特别是正式用户启用上传，应发布新的中央配置 `usage_logging.mode: online`；不要给每个用户补发本地配置文件。

### 12.2 更新模板或程序

模板更新：新建模板版本目录、打包、校验，更新清单的 `templates`。如果模板变化要求新解析逻辑，还需更新 EXE。

程序更新：改源码版本 → 测试打包 → 新建 `app\新版本` → 更新 `latest_version` 与下载路径。普通升级保留旧的 `minimum_supported_version`；确需禁止旧版处理时才提高它。当前程序提示用户复制新版，不会自动覆盖本机 EXE。

### 12.3 最后切换发布清单

所有新版本文件先上传完成并校验，再切换根清单。已有清单时先备份；Windows 管理员可在同目录准备 pending 清单后采用原子替换（先在目标共享盘试点确认支持）：

```powershell
$activeManifest = Join-Path $releaseRoot 'release-manifest.json'
$pendingManifest = Join-Path $releaseRoot 'release-manifest.pending.json'
$backupManifest = Join-Path $releaseRoot ('release-manifest.backup-' + [guid]::NewGuid().ToString('N') + '.json')
if (-not (Test-Path -LiteralPath $activeManifest)) { throw '此命令用于更新已有发布；首次发布请按步骤 10。' }
if (-not (Test-Path -LiteralPath $pendingManifest)) { throw '先准备并验证 pending 清单。' }
[System.IO.File]::Replace($pendingManifest, $activeManifest, $backupManifest)
```

若共享盘不支持替换，停止本次切换，请发布管理员选择该存储支持的方式。不要先删除活动清单制造不可用窗口。

### 12.4 离线验收

中央配置回退：在独立试点窗口里，用 `--config-root` 指向不存在的测试目录。试点机先前须成功缓存正式配置，且 EXE 旁没有 local-config。预期显示 `cache` 警告、仍可使用上一次有效模板。

使用记录补传：断网或无法访问 Portal 时完成一次合并，记录待同步数和完成时间；关闭程序，恢复网络后重新打开，确认补传数量正确且时间不变。恢复网络本身不保证立即触发新补传轮次，重启或新任务会唤醒工作器。

### 12.5 回滚

保留历史版本目录。配置或模板有问题时，让新清单重新指向上一个已验证版本及对应哈希，再按 12.3 切换。不要只改版本文字却仍指向问题文件。EXE 已分发时，回滚中央清单不会自动降级本机 EXE；需另行提供经过验证的旧 EXE。不要删本机使用记录数据库来处理上传问题。

## 常见卡点：按现象检查

- **中央配置不可用且没有缓存：**首次运行未连通公共盘。检查 UNC、权限和清单；本地试点可按步骤 3 使用显式 local-config。
- **修改公共盘后仍显示 local sidecar：**EXE 旁有 local-config。把它另存为备份后重启。bootstrap 只改中央地址，不会压过 local-config。
- **显示 cache，版本没有更新：**本次中央读取或校验失败。检查清单、SHA256、配置字段和模板可读性，不要当作新发布已经生效。
- **JSON 在记事本正常、程序读取失败：**核对 UTF-8 无 BOM、逗号和双引号；按步骤 9 重新生成。
- **同一版本内容不同：**已经使用过的配置/模板版本目录被改写。发布新版本，不覆盖本机缓存绕过检查。
- **列表返回 400：**核对 19 个字段内部名及类型，检查是否误设了额外必填字段，确认 EventId 唯一设置。
- **列表返回 401/403 或登录页面：**区分权限不足与 MSXML 登录通路不可用；让 IT 核对，浏览器登录成功不代表辅助进程登录成功。
- **提示已同步但没有新记录：**先确认 mode、目标站点和列表，再确认确实完成一次合并；“已同步”也可能表示当前没有待传记录。
- **项目名不符合预期：**当前取输入目录末级名称，不是从原始文件或网站分配；按项目组织输入目录即可。
- **正式用户不应上传测试记录：**使用独立试点 Windows 账号；同一账号队列中的历史待传记录在 online 下也会补传。样例请求文件仅供对照，不要手工向生产列表插入示例 SUCCESS。

## 最终上线验收单

- [ ] 公共盘三类版本目录及根清单完整，路径和 SHA256 检查通过。
- [ ] AI Portal 列表位于正确站点，共 19 个业务字段，EventId 必填且唯一。
- [ ] 正式用户包只含所需 EXE，没有误带 local-config 或 staging 的 bootstrap。
- [ ] 最终试点显示 central，Summary 与日志中的三种版本正确。
- [ ] 样例合并输出内容、文件数、行数正确。
- [ ] EXE 实际上传成功，网站新增数量与成功任务数一致。
- [ ] 刷新、查看和下载不新增；第二次主动成功合并新增一条。
- [ ] 离线任务恢复后补传，EventId 和 Timestamp 保持不变。
- [ ] 普通用户能按权限写入记录，管理员能查看统计。
- [ ] 发布记录中保留 EXE 哈希、验证任务编号及回滚版本。

后续参考：[公共盘详细教程](PUBLIC_DRIVE_RELEASE_GUIDE.md)、[AI Portal 字段与接口说明](AI_PORTAL_USAGE_LOGGING.md)、[请求 JSON 示例](../deployment/usage-event.example.json)、[开发打包说明](BUILD.md)。
