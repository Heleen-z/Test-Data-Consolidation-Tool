# 公盘发布包：2026.09.002

这个文件夹是本次中央配置发布包。它不含 EXE；请将已验证的 EXE 单独复制到公共盘的新版本目录后，再运行 `Publish-Release.ps1` 激活发布。

## 包内文件

```text
PublicDriveRelease_2026.09.002\
├─ configs\2026.09.002\operations.yaml
├─ Publish-Release.ps1
├─ Validate-PublicRelease.ps1
└─ README.md
```

`operations.yaml` 已包含本次日志配置：默认 `online`、AIPortal 的 `ToolUseLogs`、工具名 `Testing Data Consolidation Tool`、403 Excel 桥接和专用种子 URL。

## 发布前

1. 打开当前公盘 `release-manifest.json`，记录当前的模板版本和最低支持版本。发布脚本会保留它们。
2. 如当前中央配置中的联系人、默认路径、公告、链接或模板提示与本包不同，先把当前配置中的这些值合并到本包的 `configs\2026.09.002\operations.yaml`。不要改动 `logging` 段。
3. 把新版 EXE 放到未使用的版本目录，例如：

   ```text
   \\10.162.2.55\shares\Engineering -1890\TC-AFO\DT&AI\Release\Test Data Consolidation Tool\app\1.1.1\Testing Data Consolidation Tool.exe
   ```

   不覆盖已有 `app\<版本>` 目录。发布脚本会检查此 EXE 是否已存在。

## 激活配置

在这个发布包目录中，以有公盘写权限的账号运行：

```powershell
.\Publish-Release.ps1 -AppVersion '1.1.1'
```

脚本会：创建 `configs\2026.09.002\operations.yaml`、计算 SHA-256、保留现有模板设置、更新根目录 `release-manifest.json` 的配置和应用指针。它拒绝覆盖已有配置版本；如中途失败，不会覆盖原中央配置。

## 校验

发布后执行：

```powershell
.\Validate-PublicRelease.ps1
```

通过后，在试点电脑从新的 `app\<版本>` 目录复制 EXE 到本机。确认 EXE 同目录没有 `local-config.yaml`，页面配置来源显示 `central`，再完成一次成功、一次失败和一次断网恢复补传验收。
