# AX5 JDCloud 设备树分析与修改边界

基线：`LiBwrt/LibWrt` 提交
`3a3d0b08595530070ad9cd8a20c0ae4ea3e77f70`，Linux 6.12.108。
以下早期读数来自主路由旧固件；2026-11-01 实验机验证结果单列于
[本次优化与实测](ax5-home-profile.md)，不要混用两台设备的寿命数据。

## 继承关系

```text
ipq6000-ax5-jdcloud.dts
└── ipq6000-xiaomi.dtsi
    ├── ipq6018-512m.dtsi → 内核 ipq6018.dtsi
    ├── ipq6018-ess.dtsi
    ├── ipq6018-nss.dtsi
    ├── ipq6018-cp-cpu.dtsi → CPR 和 MP5496 调压器
    └── ipq6018-cpr-regulator.dtsi
```

不能将普通 AX5 的 NAND 启动配置直接套给京东云 eMMC 版本。
京东云节点删除继承的 NAND `bootargs-append`，升级脚本走
`emmc_do_upgrade`，使用 `0:HLOS` / `rootfs` 分区名。
这些行为不证明旧 `mmc_do_upgrade` 固件的数据迁移安全。

## eMMC：明确硬件描述，不追求未经验证的提速

- 实机运行于 HS200、1.8 V 信号、192 MHz、4-bit 总线。
- 上游京东云节点启用 SDHC、HS200 和 DDR，删除 HS400 能力；
  最大频率继承 SoC 的 192 MHz。
- 本仓库为该板明确 `bus-width = <4>`、`non-removable`、192 MHz 上限，
  并删除继承的 enhanced-strobe：
  明确固定 eMMC 的接线和不可移除属性，不依赖驱动总线宽度默认值。
- 不启用 HS400、8-bit、额外复位能力，不改时钟、电压、分区或启动参数。
  该修改不是吞吐量提升承诺；仍需新内核启动和存储 I/O 验证。

### eMMC 扩展寄存器只读核对

通过内核 debugfs 的 `ext_csd` 读取 512 字节寄存器，并用 sysfs 的版本、
容量及寿命字段交叉核对字节顺序；没有安装工具或切换总线模式。

| 字段 | 读取结果 |
| --- | --- |
| 型号 / 制造商 ID | `SLD64G` / `0x88`（不据此猜测具体厂商料号） |
| EXT_CSD_REV | `0x08`，eMMC 5.1 |
| 用户区容量 | 119783424 × 512 = 61329113088 字节，约 57.12 GiB |
| DEVICE_TYPE [196] | `0x57`，芯片声明支持 1.8 V HS200、1.8 V HS400 |
| STROBE_SUPPORT [184] | `0x01`，芯片声明支持 enhanced strobe |
| PRE_EOL_INFO | `0x01`，正常状态 |
| LIFE_TIME A / B | `0x04` / `0x01`，对应寿命消耗估计 30–40% / 0–10% |
| 当前 host caps / caps2 | `0x405f122f` / `0x00020020` |

当前主机公布 4-bit、未公布 8-bit 和 HS400 能力；这与当前 HS200 工作状态一致。
**芯片支持 HS400，不等于 PCB 接齐 8 根数据线及 strobe，也不证明控制器/驱动可稳定使用。**
当前 4-bit 工作状态同样不能证明 PCB 只有 4 根数据线。
本补丁明确保留已观测的工作宽度，不是对 PCB 接线的鉴定。
要测试 8-bit/HS400，必须另建实验配置，不能在 4-bit 声明下仅增加 HS400 属性。

本次 host 错误统计中的超时、CRC、ADMA 和 tuning 等计数均为 0；
只反映当前统计窗口，不是设备全生命周期的无错误证明。
寿命字段也是厂商估计区间，不能换算成精确剩余年限。

补丁由 `prepare` 对锁定源码执行 `git apply --check` 后应用；
上下文不匹配时失败。原始源码提交、补丁和 SHA256 一起记录在 provenance。

## 无线、网口和加速

- 使用 `Redmi-AX5-JDCloud` 校准变体，不能替换成普通 AX5。
- ath11k 固件内存模式为 1，种子选择 512 MB profile 和 NSS 12.5。
- LAN 为 dp2/dp3/dp4，WAN 为 dp5，对应 PHY 1/2/3/4；
  交换机为 PSGMII，与板级网络脚本的三个 LAN、一个 WAN 一致。
- MAC 由启动器依 aliases 修补；源码中的全零占位不是应填入私人 MAC 的位置。
- 不调整 EDMA 队列、NSS 时钟或保留内存来换取未经测量的吞吐量。

## CPU、电压与温控

- 实机可用频率为 864、1056、1200、1320、1440、1512 MHz。
  设备树的 1608/1800 MHz 另有硬件 speed-bin 限制，不解除限制。
- CPR 的 `opp-microvolt = <1> ... <6>` 是调压器 corner 编号，
  不是错误的 1–6 微伏，不能按普通 OPP 电压值“修正”。
- 检查时 CPU 约 58°C，其余传感器约 57°C；单次读数不是满载热稳定性测试。
  旧固件 governor 为 performance，不据此修改新固件 OPP 或热保护阈值。

## 内存与崩溃记录

- 实机旧固件 `MemTotal` 为 383824 kB，并非整块 512 MB 都可供 Linux 使用。
- 新源码的 512m DTSI 将 Q6 区域设为 55 MiB；旧实机 DT 中该区域为 85 MiB。
  固件/驱动/profile 不同，不能据此直接推算升级后可用内存。
- 上游补丁已经保留 16 MiB NSS 区域及 1 MiB ramoops 区域
  （`0x50d00000`），本次不再切割内存或新建 ramoops 节点。
- 如需持久化崩溃日志，应另行检查 pstore/ramoops 内核配置、挂载与采集；
  有设备树节点不等于日志记录已经启用。
- 实机当前已有 zram；本仓库待构建配置将明确使用 128 MiB/LZO，
  并非在当前路由器上叠加第二个交换设备。

## 初始化失败后重试 HS200

`patches/kernel/9999-mmc-core-retry-ax5-hs400-init-with-hs200.patch`
在 `prepare` 中复制到锁定源码的 qualcommax 内核补丁目录，由 OpenWrt
在准备 Linux 6.12.108 时应用；补丁及 SHA256 进入 provenance。
内核补丁本身不启用 HS400，默认构建仍使用 4-bit/HS200。

下游 quirk 仅作用于根 compatible 为 `redmi,ax5-jdcloud` 的首次卡枚举：

1. 捕获 HS400 配置下 8-bit/时序选择的返回错误、普通 HS400 切换、
   8-bit HS400 路径的前置调谐，或 HS400ES 选择/调谐错误。
   对该板的首次 HS400ES 选择，保留原始错误，不让 `-EBADMSG` 被旧逻辑吞掉。
2. 仅当卡/主机具备 HS200 路径时尝试恢复；纯 HS200 调谐错误不重复尝试。
3. 原错误路径先释放尚未注册的卡对象，然后清除该 host 的 8-bit、HS400 和
   HS400ES 能力，通过 `mmc_power_cycle()` 重置主机 I/O 状态并尝试电源循环。
4. 重新执行完整卡枚举一次。保留 HS200 能力，由正常协商选择 HS200；
   既有核心逻辑也可能降为更低模式，不保证最终一定为 HS200。
5. 第二次失败直接返回该次错误，不循环重试。8-bit/HS400 能力在此次 host 生命周期内
   保持禁用，正常重新开机后重新从设备树获得能力。

不处理其他初始化错误、已注册卡的休眠恢复/运行中复位，也不处理运行中 I/O 错误、
静默损坏或控制器卡死。其他板保持原有选择/错误处理。
固定供电的板上，`mmc_power_cycle()` **不保证真正切断 eMMC 电源**；
不能将该补丁视作无损回退或替代串口、RAM 启动及外部数据备份。
默认 HS200 设备树不允许 HS400，正常使用不会触发这个分支。

`tests/test_mmc_fallback.py` 将补丁应用到 Linux 6.12.108 代码摘录，
使用 `cc -std=c11 -Wall -Wextra -Werror` 编译并执行 16 个故障注入场景，
覆盖正常路径、普通/ES 失败、重试失败、纯 HS200、其他板、恢复及无 HS200 等边界。
硬件操作由桩函数替代；这些测试只能验证控制流，不证明真实调谐、供电或完整内核编译。

## HS400 实验已关闭

2026-11-01 核对：8-bit HS400 固件在枚举成功后读取低扇区错误，
初始化 fallback 不能处理这种运行期故障。恢复为 4-bit HS200 后同机正常。
构建入口现拒绝 hs400，工作流仅提供 hs200；历史补丁与身份编码仍保留
用于审计旧产物。芯片声明支持 HS400，不足以证明该板卡配置可用。

## 按需只读遥测

此前只有构建配置/溯源和手动检查记录，没有实机遥测代理或自动上报。
新增 `scripts/collect-emmc-telemetry.sh`，同时随固件安装为
`/usr/sbin/ax5-emmc-report`。它不自动执行、不定时采集、不上传。

报告包含设备树请求的总线宽度/时钟/模式、当前主机 caps、实际 `ios`、
错误计数、EXT_CSD 的 selected bytes（芯片能力、版本、寿命）及相关内核日志。
它不采集 CID/序列号或原始 vendor EXT_CSD 数据，不挂载 debugfs、不切模式、
不做写盘测试。接口缺失时标记 unavailable；通常需 root 才能读 debugfs/dmesg。

旧固件无需安装即可临时只读执行：

```sh
ssh router sh -s < scripts/collect-emmc-telemetry.sh
```

包含该脚本的新固件上执行 `ax5-emmc-report` 即可。
检查 `actual_link` 中的实际 HS400/HS200 和位宽，再核对内核错误/回退日志。
日志可能轮转，无法启动时也没有用户态报告；启动失败仍依赖串口或独立恢复环境。

## 验证范围

补丁上下文核对、补丁应用测试和构建脚本测试不等于完整 DT 验证。
合并后的 DTS/DTB 仍须由锁定内核的构建完成编译，并在启动器修补后核对：
eMMC 模式、无线初始化、网口与 MAC、温控、NSS 和存储错误。
本次不刷机、不运行写盘测试、不修改实机配置。
