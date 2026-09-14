# AI Portal 使用记录建表与接入

## 1. 创建列表

使用 eBOM 共用的 SharePoint List：**AI Portal Tool Usage Logs**，站点为 `https://faurecia.sharepoint.com/sites/AIPortal`。这是列表记录，不是文档库；工具不会上传原始数据、工作簿、图片或文件路径。每条本工具记录固定写入 `Toolname=Testing Data Consolidation Tool`，可在统一列表中按工具筛选。

创建列时先使用以下英文名称，确保内部名称一致，再按需修改中文显示名称。保留默认的 `Title` 列。不要手动指定 `ListItemEntityTypeFullName`：程序每轮读取服务器返回值。

- 单行文本（最多 255 字符）：`Title`、`Toolname`、`InputFormat`、`OutputFormat`、`UserName`、`UserEmail`、`ComputerName`、`ProjectName`、`EventId`、`TestTypes`、`AppVersion`、`ConfigVersion`、`TemplateVersion`。
- 日期和时间：`Timestamp`，包含时间；客户端传 UTC，网站根据所需时区显示。
- 数字，零位小数：`RowCount`、`FileCount`、`FailedFileCount`。
- 数字，两位小数：`Duration`，单位秒。
- 多行纯文本：`ErrorMessage`，不要启用富文本或追加更改。
- **EventId 必填，强制唯一值并建立索引。** `Title` 使用默认必填规则，其余列可选，允许邮箱为空。

给使用者或对应公司用户组授予该列表的读取和新增列表项权限。读取权限用于提交前和提交结果不明确时的去重确认。不要用文档上传权限代替列表项权限。

## 2. 字段含义和统计

每次用户点击“开始合并”并成功生成非空结果，新增一条 `Title=SUCCESS` 记录。同批多个文件、多种测试类型仅记一次；部分文件失败但生成结果仍记一次，`FailedFileCount` 为实际合并失败的文件数。整个转换失败时不记录。启动、Pre-check、刷新、图表和下载操作不产生记录。

- `Toolname`：固定为 `Testing Data Consolidation Tool`；统一列表按此字段区分 eBOM 和其它工具。
- `EventId`：每次点击产生的 UUID，重复补传保持相同编号。
- `Timestamp`：结果完成后的 UTC 时间，补传保留原值。
- `InputFormat`：本次选中文件的去重、小写扩展名，例如 `csv;txt`；`OutputFormat` 固定 `XLSX`。
- `RowCount`：实际各测试类型输出行数之和；`Duration`：点击合并到完成结果保存的秒数，不含上传耗时。
- `UserName` / `ComputerName`：当前 Windows 用户名和电脑名；`UserEmail`：`whoami /upn`，失败时为空。
- `ProjectName`：输入目录最后一级名称，最长 255 字符。
- `FileCount`：实际选中参与本次合并的文件数；`FailedFileCount`：来源索引中“合并失败”的文件数。
- `TestTypes`：实际输出的测试类型，去重排序并用分号分隔，例如 `T09;T12`。
- `AppVersion` / `ConfigVersion` / `TemplateVersion`：本次执行时的版本。
- `ErrorMessage`：部分失败时只上传数量摘要，不上传路径、原始异常或文件名。

网站成功次数为 `Title=SUCCESS` 的列表项数，不是 `FileCount` 或 `RowCount` 的总和。按 `Timestamp` 转为统计时区后汇总日/月使用量；按用户、项目名称、测试类型分组。处理量可另汇总文件数和行数。若拆分 `TestTypes` 做多类型统计，跨类型总计应按 `EventId` 去重。

示例请求见 `deployment/usage-event.example.json`，其中 `__metadata.type` 仅为示意；运行时以目标列表查询结果为准。

## 3. 启用上传

默认仅在本地记录。列表准备完成后，在 EXE 旁 `local-config.yaml` 添加以下配置（保留其它已有内容），重启程序：

```yaml
logging:
  mode: online
  sharepoint_site_url: https://faurecia.sharepoint.com/sites/AIPortal
  list_name: AI Portal Tool Usage Logs
  tool_name: Testing Data Consolidation Tool
```

三种模式：`cache_only` 保存成功记录但不联网；`online` 保存并后台上传、补传；`off` 停止新记录和补传但保留队列。中央 `operations.yaml` 也支持同一节；现有本地配置文件存在时，仍按原有逻辑优先使用本地配置，不读取中央配置。

队列位置为 `%LOCALAPPDATA%\FORVIA\TestDataConsolidation\usage\queue.sqlite3`。已确认记录保留 ID 和同步状态用于去重；未确认的记录跨重启保留。切换模式不会删除历史记录。更改站点/列表会让后续待同步记录发送到新目标，生产启用后应保持目标稳定。

上传沿用 eBOM 的 MSXML2.XMLHTTP.6.0 和 SharePoint REST 顺序：读取列表实体类型、取得 Form Digest、直接 POST JSON；仅在 POST 结果不明确时按 EventId 查询确认，避免项目级读取策略阻断正常新增。隐藏的 Windows PowerShell 进程通过 stdin/stdout 接收和返回 JSON，每次请求硬超时 15 秒。无需在配置中填密码；是否能复用公司登录上下文必须在真实公司电脑验证。

网络、超时或服务器错误每轮最多尝试三次；长 Retry-After 会持久化为下次可重试时间，不占用界面等待。初始化会话、开始合并、记录新成功事件时唤醒补传。401/403、列表/字段配置错误、登录页面响应均保留缓存，页面提示状态；上传失败不使转换失败。

## 4. 联调检查

1. 建表并开启 EventId 唯一值，验证当前使用账号有读取和新增权限。
2. 默认本地模式完成一次合并，查看“仅本地记录”计数；刷新应不增加。
3. 切到 online 并重启，确认待同步记录出现于列表，Timestamp 为原转换完成时间。
4. 完成一次受控合并，核对用户、目录项目名、文件数、行数、耗时与本地结果。
5. 断网完成合并，关闭后恢复网络再启动，确认补传且不重复。
6. 若 401/403 或返回登录页面，先确认公司登录和租户认证策略；当前实现不保证每台电脑均能无交互认证。

自动测试使用模拟传输，不向生产列表写入测试数据。网站未建立前交付 cache_only 模式，真实上传仍待上述联调。
