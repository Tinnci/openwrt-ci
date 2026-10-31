# AX5 实验机默认配置与实测（2026-11-01）

本配置基于已成功启动的 Linux 6.12.108 / 源码 3a3d0b085955。
默认 LAN 为 10.77.0.1/24，主机名 ax5，本地 DNS 域 home.arpa。
不把该域转发到公网 DNS。U-Boot 恢复页面地址仍为 192.168.1.1。
保留配置升级可能保留旧 LAN；新默认适用于清空配置/首次启动。

## 设备树与启动边界

固定已验证的 4-bit HS200、192 MHz 上限、non-removable，禁用 HS400/ES。
芯片 CARD_TYPE=0x57 声明支持 HS400，但此前 8-bit HS400 实机在启动后
读取低扇区失败。prepare 现拒绝 HS400；工作流不再提供该选项。
兼容性事实见 configs/ax5-lab-compatibility.json；构建入口已强制拒绝
HS400，设备树核验同时检查总线宽度、模式及频率上限。

保留 ART、GPT、引导链、p16 6 MiB、p17 1 GiB、p18 ext4 数据区。
不修改公共 DTSI、不覆盖校准数据、不启用推测的硬件复位/电压/总线接线。

## 动态分区

构建包含 dm-thin、snapshot、linear、crypt、verity、integrity、LVM2 和 loop。
支持 Linux 运行期逻辑卷、快照及扩容的基础设施；这不等于 Android
super/Virtual A/B，也不让现有 U-Boot 从 LVM 启动。
现有 p18 含数据，不能直接 pvcreate。没有自动格式化、自动改 GPT、
首启迁移或动态重划分引导分区。动态卷运行测试须在临时 loop 文件或
另行备份迁移的数据区进行；当前已启动的保守固件未安装这些工具。

## 内存与模块策略

保留 ARM Cortex-A53/NSS 12.5/512 MiB 配置，模块与内核同一次构建打包，
构建前解析完整 Kconfig，构建后独立核验实际 kernel.config。
保留 RAM-only zram 128 MiB / LZO，不在 eMMC 上做 swap。
脏页后台回写阈值 4 MiB、前台阈值 16 MiB，避免大型文件写入占满内存。
这是候选默认值，需要共享负载下比较吞吐与延迟，尚未证明优于旧值。
默认 I/O scheduler 当前只有 none，不写入不存在的 mq-deadline 参数。
不关闭 ext4 日志、barrier 或 flush，不强制超频，不在开机时 trim/测速。

保留上游 NSS/EDMA/RPS/XPS 分配：已有 set-irq-affinity 配置四核掩码 f，
NSS queue1/queue3 已分别在 CPU1/CPU3 有中断计数。单独增加 irqbalance
会与现有策略竞争；当前无网络压测证据支持强改亲和性。
新增 sysstat/ethtool/fio 以及手动诊断工具，便于用 mpstat/iostat/PSI/
/proc/interrupts 定位 CPU、I/O 与网络瓶颈，再进行可回退的 A/B 比较。

## 实机存储基线

TTL 控制的实验机，SLD64G / manfid 0x88，4-bit HS200 / 192 MHz。
它是受控 eMMC，无法通过 Linux 获知原始 NAND die 料号、ECC/FTL 细节。
PRE_EOL=0x01 正常；LIFE_TIME A/B=0x02/0x01（估计消耗 10–20%/0–10%）。
不要把另一台主路由历史寿命读数混作本机读数。

在 p18 ext4/noatime 临时文件上，BusyBox dd，1 MiB 块，256 MiB，
O_DIRECT；写测试结束调用 fsync。读取 /dev/null，不经过页缓存。

| 测试 | 耗时 | MiB/s |
|---|---:|---:|
| 顺序写入 1 | 3.33 s | 76.88 |
| 顺序写入 2 | 3.30 s | 77.58 |
| 顺序写入 3 | 3.32 s | 77.11 |
| 顺序读取 1 | 3.01 s | 85.05 |
| 顺序读取 2 | 3.03 s | 84.49 |
| 顺序读取 3 | 3.01 s | 85.05 |

为短测试、零填充写入，仅反映该工况，不能称为持续最大速率。
4-bit/192 MHz 的单沿接口理论上限为 96 MB/s（91.55 MiB/s），
实际读取已较接近链路上限。总线协定、FTL 与文件系统会产生开销。
读写后 MMC 超时/CRC/ADMA/tuning 等计数均为 0，dmesg 未见相关 I/O 错误。

新固件提供 ax5-emmc-report 与 ax5-emmc-benchmark：后者仅允许已挂载
的 /dev/mmcblk0p18 ext4，创建唯一临时目录，512 MiB 一次性直接写、
CRC32C 回读校验、顺序读和 15 秒 4 KiB 随机读，退出清理测试文件。
不写裸盘，不作无限 time_based 写压力。

## 参考

- https://www.rfc-editor.org/rfc/rfc8375.html
- https://docs.kernel.org/admin-guide/device-mapper/thin-provisioning.html
- https://docs.kernel.org/networking/scaling.html
- https://fio.readthedocs.io/en/latest/fio_doc.html
