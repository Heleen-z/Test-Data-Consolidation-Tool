# 中央配置与模板版本管理

## 目标

程序版本、运营配置版本和模板版本独立维护。支持邮箱、联系电话、公告、默认输入/输出目录和模板提示文案变化时，不需要重新生成 EXE；测试类型、解析器和字段算法仍然随代码版本发布。

## 用户启动流程

用户从公共盘复制 EXE 到本机并从本机启动。程序每次启动读取统一 UNC 根目录下的 `release-manifest.json`，校验运营配置和模板包后缓存到：

```text
%LOCALAPPDATA%\FORVIA\TestDataConsolidation\managed
```

公共盘不可用或中央文件校验失败时，程序使用 last-known-good 缓存并在页面显示警告。首次运行既无法访问公共盘又没有有效缓存时，程序停止启动业务功能。

中央发布清单读取的默认等待上限为 5 秒，可在内置 `central_management.startup_timeout_seconds` 中调整为 1–30 秒。超时后立即尝试 last-known-good，避免不可用的 UNC 路径长期阻塞启动。

## 配置中央地址

正式 UNC 地址已经配置为：

```yaml
central_management:
  central_root: '\\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool'
```

临时验证或公共盘迁移时，可使用以下覆盖方式，优先级从高到低：

1. 命令行 `--config-root`；
2. 环境变量 `TESTDATA_TOOL_CONFIG_ROOT`；
3. EXE 同目录的 `bootstrap.yaml`；
4. EXE 内置的 `central_management.central_root`。

用户通常只复制 EXE，因此生产环境使用内置 UNC；`bootstrap.yaml` 主要用于试点和灾难恢复。源码运行不会自动连接该内置生产地址，必须显式设置环境变量或提供 `bootstrap.yaml`。

完整的管理员操作步骤见 [PUBLIC_DRIVE_RELEASE_GUIDE.md](PUBLIC_DRIVE_RELEASE_GUIDE.md)。

## 公共盘目录

```text
production\
├─ release-manifest.json
├─ configs\<config_version>\operations.yaml
├─ templates\<template_version>\TemplateBundle.zip
└─ app\<app_version>\Testing Data Consolidation Tool.exe
```

版本目录发布后不得覆盖。管理员需要修改内容时创建新版本目录，并最后替换 `release-manifest.json`。回滚只需把 manifest 指向上一个已验证版本。

## 版本规则

- EXE 使用 SemVer，例如 `1.1.0`；只有代码或业务逻辑变化才增加。
- 运营配置使用 CalVer，例如 `2026.09.001`。
- 模板整包独立使用 CalVer，例如 `2026.09.003`。
- 页面、Processing Log 和合并工作簿 Summary 同时记录三种版本。

## 发布步骤

1. 从 `deployment/example-operations.yaml` 复制新配置。
2. 只修改白名单运营字段，不在运营配置中加入解析规则或代码参数。
3. 将标准模板目录压缩为 `TemplateBundle.zip`。
4. 在公共盘创建新的、不可变的配置和模板版本目录。
5. 使用 PowerShell `Get-FileHash -Algorithm SHA256` 计算两个文件的哈希。
6. 从 `deployment/example-release-manifest.json` 生成新 manifest。
7. 先把所有版本文件复制完成，再以临时文件写入 manifest 并原子重命名。
8. 在试点电脑启动一次，确认配置来源为 `central`、模板版本正确、Pre-check 正常。
9. 普通用户授予只读权限，只有指定管理员拥有发布目录写权限。

## 配置边界

中央 `operations.yaml` 只允许：

- `contact`
- `defaults`
- `ui`
- `managed_templates`
- `support_links`
- `usage_logging`：使用记录模式、AI Portal 站点和列表名称。

任何未知顶层字段或未知子字段都会拒绝激活。配置不能包含密码、令牌、命令、Python 表达式、解析器、扩展名、类型识别规则、横轴算法或性能参数。

## 模板切换与失败保护

模板包先复制到本机 staging 目录并校验 SHA256，再检查 ZIP 路径安全性和 XLSX 文件存在性。只有全部成功后才切换 `active.json`。下载中断、ZIP 损坏或哈希不一致时继续使用上一个模板版本，不会覆盖当前有效模板。

受管模板启用后，用户不能在界面修改正式模板目录；历史 `preferences.json` 中的 `template_folder` 会被忽略，输入和输出目录偏好仍然保留。
# 本地测试配置

若测试机没有中央发布配置或本地缓存，可在 EXE 同目录创建 `local-config.yaml`。它使用与 `deployment/local-config.yaml.example` 相同的格式，并且优先级高于中央配置：存在时程序不会访问中央发布目录，也不会读取缓存。该文件可设置测试标题、提示、联系方式、默认输入/输出路径和本地模板路径。

打包脚本首次生成 EXE 时会把示例复制为 `dist/local-config.yaml`；直接编辑该文件后启动 EXE 即可测试。测试完成后删除或重命名此文件，程序会恢复正常的中央配置和缓存逻辑。
