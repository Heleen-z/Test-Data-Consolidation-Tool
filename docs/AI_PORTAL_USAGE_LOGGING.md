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
  excel_bridge_enabled: true
  seed_url: "https://faurecia.sharepoint.com/sites/ES-Asia_RandD2/Released Documents/CHD-F-DSE-1018 BOM Conversion Tool.xlsm"
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

## Excel 桥和手动补传

每轮先使用原 PowerShell 通道；明确返回 HTTP 403 时，自动启动独立隐藏 Excel，用 Office 公司账号尝试建立 SharePoint 会话，再上传本工具的记录。同轮后续日志复用该桥。单条日志每轮最多发送三次，切换通道也计入次数。

Excel 只读打开 seed_url 指向的文件，禁用该文件的宏、工作簿事件和外部链接更新；等待 7 秒，关闭且不保存，再等待 2 秒。桥使用随 EXE 打包并校验过的 excel_bridge.xlsm 执行网络请求，用户无需启用 VBA 工程访问。公司 Office 策略仍可阻止宏，工具会保留日志并显示失败原因。

首次默认使用已验证的 CHD-F-DSE-1018 文件。建立会话后，每日最多一次只读枚举 ES-Asia_RandD2 的 Released Documents（含子目录和分页），缓存编号 1001–1020 范围内的真实 xlsx/xlsm 地址。默认地址失效时尝试已缓存的候选，每轮最多 3 个；无法认证时不会依赖在线搜索完成登录。地址缓存为本工具 bridge/seed-cache.json，日志队列位置不变。

Excel 桥初始化最多 90 秒，后续单次请求最多 15 秒，候选发现最多 30 秒。辅助进程监督主进程存活和超时，只清理它创建并持有句柄的 Excel 实例；空闲 2 分钟后释放，不关闭用户打开的工作簿。Excel 未安装、Office 账号或权限不足、宏被阻止时保留积压，可在 logging 中设置 excel_bridge_enabled: false 关闭自动桥。

积压至少 6 条时，在“开始合并”下面显示“手动补传日志”。未做 Pre-check 时入口位于使用记录区域。online 模式下可点击；cache_only/off 下显示但禁用，提示开启线上模式。补传时按钮禁用，每 5 秒显示进度，完成后显示本次成功量和剩余量；剩余不足 6 条后按钮隐藏，结果仍显示。点击不会执行合并或新增日志。

自动和手动补传共用队列和租约；手动批次只包含点击时的积压记录，仍尊重重试等待时间。故障恢复后可重新点击，或通过下一次转换唤醒自动补传。不要与历史运维脚本 flush_usage_queue.py 同时操作队列；该脚本为现场原型，正式程序不调用它。

## 联调

使用公司 Windows 账号分别验证一次成功转换、一次失败转换和一次断网后恢复网络的补传。检查 ToolUseLogs 中的标题、输入格式、行数、耗时、UTC 时间、用户、项目名和 Toolname。自动测试只使用模拟传输或本机回环服务，不向生产列表写入数据。

开发机可运行 scripts/verify_excel_bridge.py 验证预构建宏的本机回环请求、中文编码和 Excel 清理；加 --sharepoint-read-only 验证种子登录和真实列表元数据读取，不写入列表项。真实手动补传应使用实际积压；不要为满足按钮阈值制造生产测试日志。
