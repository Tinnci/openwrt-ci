# 历史工作流归档（不可直接恢复运行）

此目录保存从上游继承的 10 个原始工作流，仅供参考。GitHub 只识别
`.github/workflows/` 下的工作流，因此这些归档不会因启用 Actions、
定时事件或手动 dispatch 而运行。现有远端运行记录、标签和 Release 不受此移动影响。

除文件头的归档提示外，原始内容保持不变，**并未完成安全加固**，包括：

- 定时构建其他设备、滚动源码/feeds 和第三方 Action 分支；
- 从网络下载并以 root 执行环境初始化脚本；
- 自动发布或覆盖 Release；
- `Delete-Old-Workflows.yml` 会删除历史运行、旧 Release 和标签；
- `build-packages.yml` 构建的是 x86_64 包，并非本仓库的 AX5 配套包。

不要直接将文件复制回 `.github/workflows/`。需要恢复某设备或功能时，
应先单独审查，固定依赖和 Action SHA，设置最小权限、超时及手动触发策略，
并更新工作流策略测试。

AX5 仅使用：

- `.github/workflows/check-ax5.yml`：main 提交、PR 或手动配置检查；
- `.github/workflows/IPQ60XX-CUSTOM-WIFI.yml`：手动固件构建，默认不发布。
