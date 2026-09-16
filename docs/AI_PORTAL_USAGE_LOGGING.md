# ToolUseLogs 使用记录接入

本工具将转换使用记录写入 SharePoint 网站 https://faurecia.sharepoint.com/sites/AIPortal 的 **ToolUseLogs** 列表。实际 REST 地址为：

~~~
https://faurecia.sharepoint.com/sites/AIPortal/_api/web/lists/getbytitle('ToolUseLogs')/items
~~~

发布配置默认在线上传：

~~~yaml
logging:
  mode: online
  sharepoint_site_url: https://faurecia.sharepoint.com/sites/AIPortal
  list_name: ToolUseLogs
  tool_name: Testing Data Consolidation Tool
~~~

配置可放在 EXE 同目录的 local-config.yaml，该文件仍按现有规则优先于中央配置。早期的 usage_logging 格式仍可读取；早期的 EBOM Conversion Logs 和 AI Portal Tool Usage Logs 名称会自动转为 ToolUseLogs，不会作为回退目标。

## SharePoint 字段

保留默认必填的 Title，并建立以下字段：InputFormat、OutputFormat、RowCount、Duration、ErrorMessage、Timestamp、UserName、UserEmail、ComputerName、ProjectCode、ProjectName 和 Toolname。Timestamp 为含时间的日期列，RowCount 为整数，Duration 为两位小数，ErrorMessage 为多行纯文本，其余为单行文本。

每次实际开始合并只产生一条记录：

- 成功且得到非空输出时：Title=SUCCESS，RowCount 为实际输出行数，ErrorMessage 为空。
- 整体合并、导出或结果校验失败时：Title=FAILED，RowCount=0，ErrorMessage 为去除本地路径后的失败摘要。

InputFormat 是本次已选输入文件的小写扩展名，以分号连接；OutputFormat 为 XLSX。ProjectName 取输入目录名，ProjectCode 暂为空。Toolname 为当前有效配置中的工具名称。程序内部事件 ID、版本和文件统计仅存本地，绝不作为 SharePoint 列发送；Status 不单独上传，状态由 Title 表示。

启动、Pre-check、刷新、图表和下载都不产生记录。部分源文件失败而本次合并仍生成有效文件时，仍是一条成功记录；详细失败信息继续保留在本地验证输出中。

## 缓存和补传

新事件先写入：

~~~
%LOCALAPPDATA%\FORVIA\TestDataConsolidation\usage\queue.sqlite3
~~~

online 模式会在启动、开始转换和新增记录后后台补传；cache_only 只记录本地，off 不创建和补传新记录。网络、超时和可重试服务器错误每轮最多重试三次，普通重试间隔两秒。权限、字段或认证错误会保留本地缓存，且不影响转换结果。

列表没有 EventId 列，因此程序通过成功 POST 返回的列表项 Id 确认写入。若服务器已写入但客户端在收到响应前断开，下次补传有可能写出重复项；本地队列仍会防止同一事件重复入队。

## 联调

使用公司 Windows 账号分别验证一次成功转换、一次失败转换和一次断网后恢复网络的补传。检查 ToolUseLogs 中的标题、输入格式、行数、耗时、UTC 时间、用户、项目名和 Toolname。自动测试只使用模拟传输或本机回环服务，不向生产列表写入数据。
