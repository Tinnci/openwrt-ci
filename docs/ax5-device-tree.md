# AX5 JDCloud 设备树分析与修改边界

基线：`LiBwrt/LibWrt` 提交
`3a3d0b08595530070ad9cd8a20c0ae4ea3e77f70`，Linux 6.12.108。
以下实机读数来自当前旧固件的只读检查，不代表新固件已经通过实机测试。

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
- 本仓库仅为该板添加 `bus-width = <4>` 和 `non-removable`：
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

## 验证范围

补丁上下文核对、补丁应用测试和构建脚本测试不等于完整 DT 验证。
合并后的 DTS/DTB 仍须由锁定内核的构建完成编译，并在启动器修补后核对：
eMMC 模式、无线初始化、网口与 MAC、温控、NSS 和存储错误。
本次不刷机、不运行写盘测试、不修改实机配置。
