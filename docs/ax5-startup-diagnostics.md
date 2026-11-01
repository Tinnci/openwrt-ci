# AX5 启动诊断与崩溃留存

本轮基于已经通过实机的 Linux6.12.108 / 4-bit HS200 和 U-Boot9ce3157。
不改变 GPT、ART、U-Boot 或 eMMC 时序，也不引入启动失败自动重刷。

## 功能

- `ax5-boot-health` 只读输出系统、内存、温度、存储、LAN/DNS、无线/NSS及启动事件。
  没有外网或NSS加速连接数0不是失败。构建ID写入/etc/ax5-build-id。
- `ax5-bootenv-read` 使用O_RDONLY打开板级环境分区，校验板型/布局与完整256KiB CRC后
  仅打印bootcmd/bootdelay及救援网络等白名单。自定义命令被脱敏，没有写环境功能。
  --file选项可离线检查备份；不会输出密码或MAC。
- `/etc/fw_env.config` 为本板明确APPSBLENV，不依赖早期自动发现；启动脚本没有fw_setenv。
  该配置不是针对root用户的写保护边界，root仍有原有的块设备/环境写工具权限。
- 加入kmod-pstore/kmod-ramoops，使用原有1MiB预留区，不新增内存 carveout。
- procd服务`ax5-startup`在正常启动后采集0/30/60秒阶段报告。每次采集限时20秒。
  数据未挂载时只留/tmp；仅在正确p18 ext4挂载后写入`.ax5-diagnostics`，目录root专用。
  归档当前启动及至多四份旧记录，单个pstore文件截断至1MiB，不删除内核原始记录。
  时钟可能未同步，报告使用boot_id/uptime，轮转不会因NTP跳变删除本次记录。
- emmc报告缺少od或读取失败时显示unavailable，避免假0；显式安装od/timeout/stat。
- LVM preinit仅在本板显式提供`ax5.lvm_root=1`内核参数时扫描；普通系统启动和hotplug
  默认不自动激活外来VG。运行期需要时可设置`ax5_storage.settings.auto_activate=1`。
  手动lvm/dm工具仍然可用。子进程关闭继承的fd3，不关闭父进程看门狗。

## 验证边界

单元测试覆盖坏CRC/短读/符号链接/敏感值、数据盘未挂载、不安全归档路径、大小与轮转、
诊断工具缺失、LVM opt-in和子进程fd。云端必须重新核验完整Kconfig、PSTORE_CONSOLE及模块产物。
实际部署前做镜像校验、FIT/DTB与6MiB槽检查、数据与引导备份。
实机用非致命kmsg标记加一次受控重启，验证console-ramoops能否保留，不主动触发panic。
如固件或早期引导清空RAM，应报告限制而不能假称崩溃留存已验证。

## 单独研究的内容

U-Boot中NAND/NOR/PCI探测要先检查SMEM依赖，MAC需核对真实ART布局，不能猜偏移。
ath11k M3 dump需要匹配该NSS补丁版驱动属性；没有在本轮随意添加地址。
这些事项不通过擦除ART、伪造TRNG、超频或启用HS400解决。
