<img width="768" src="https://github.com/openwrt/openwrt/blob/main/include/logo.png"/>

## 本仓库 AX5 京东云定制构建

入口：Actions → **AX5 JDCloud - Build firmware** → Run workflow。仅构建 Redmi AX5 JDCloud，
不再每天重复构建固定版本；10 个历史工作流已移至 `docs/legacy-workflows/`，
不再被 GitHub Actions 识别，也不会自动清理历史 Release。

- 源码和全部 feeds 固定在 `configs/ax5-build.lock.json` 的完整提交 SHA。
  当前基线为 LiBwrt/LibWrt `25.12-nss`，内核 `6.12.108`。
- 默认只上传 Artifact；只有在 `main` 上手动运行并显式勾选 `publish` 才写入 Releases。
  保留 `IPQ60XX-CUSTOM-WIFI` 稳定下载入口，历史标签与产物统一使用构建标识。
  稳定入口的标签不代表其当前附件的源码；以附件中的 provenance 为准。
- 默认 IP 为 **192.168.3.1**。不注入密码、SSH 密钥、磁盘 UUID 或本机挂载配置。
  凭据遵循上游默认值，首次使用前自行设置。
- `scripts/customize-ax5.sh` 替代本工作流原先调用的通用 `diy-script.sh`，
  不拉取未固定版本的额外插件，不修改不存在的 Lean/x86 路径。
- 保留 aria2、HomeProxy、ZeroTier、KMS、Argon、LuCI、磁盘工具和 NSS ECM/bridge/VLAN；
  移除重复依赖列表、其他设备、无效 NSS 包名，以及额外 Docker/代理包的仅编译项。
  不再混用 NSS 与 SFE；明确选择与当前机器一致的 NSS 12.5 固件系列。
  Argon/KMS 使用锁定 feeds 的版本；未被配置选中的其他 DIY 插件不再额外拉取。
- Samba、Bonjour、Windows 发现、DLNA、NFS 服务及 NFS 内核模块选为 `=y`。
  Bonjour 使用 Samba 依赖的 D-Bus 版 Avahi，仅绑定 `br-lan`。
  DLNA/NFS 在首次启动时禁用，需显式配置后启用；不会自动导出磁盘或开放 WAN。
  这也意味着升级后不能假设现有 DLNA/NFS 服务会自动继续运行。

### Fork 的 Actions 启用策略

当前 `.github/workflows/` 仅保留配置检查和手动 AX5 构建，无定时任务：

- `prepare` 阶段应用京东云设备树补丁并锁定 feeds，不提前创建 `.config`；feeds 更新会自动刷新已有配置，
  因此必须在安装完成后由 `configure` 重新写入种子，并运行
  `make defconfig RECURSIVE_DEP_IS_ERROR=1`，再校验全部显式选择。
- 安装前应用 `patches/feeds/0001-luci-weechat-select-concrete-provider.patch`：
  将锁定 LuCI 的 WeeChat 虚拟依赖指向默认的 `weechat-minimal`，避免 variant 冲突
  引起全局 Kconfig 循环依赖。它不将 WeeChat 加入固件；补丁上下文变化时直接失败。
  补丁文件及 SHA256 会记录在 provenance 中，源码/feeds 锁定提交保持不变。
- 配置检查只对相关路径的 `main` 提交、PR 或手动运行触发；同一分支/PR 的旧检查
  会取消，不在普通功能分支的每次 push 上重复运行。
- 所有活动 Action 均固定到完整提交 SHA；更新时应审查对应上游变化。
  官方 Actions 使用原生 Node.js 24 版本：checkout v7.0.1、cache v6.1.0、
  upload-artifact v7.0.2、download-artifact v8.0.2；已逐一核对锁定版本的
  `action.yml`。磁盘准备 Action 为 composite，无 Node.js 运行时。
  沿用 Ubuntu 24.04 GitHub 托管 runner，不通过环境变量强制切换旧 Action 的运行时。
- 构建和检查显式设置 `contents: read`，checkout 不保留凭据；仅显式发布的 job
  获得 `contents: write`，发布前核对下载产物的 SHA256。
- 检查超时 10/30 分钟，完整构建上限 360 分钟，发布上限 15 分钟。
  固件 Artifact 保留 14 天，诊断和配置保留 7 天；编译缓存由 GitHub 配额策略管理。
- 编译缓存按锁文件、种子配置、源码/feeds 补丁和定制脚本隔离；每次运行/重试单独保存，
  恢复时只匹配同组输入。固件 Artifact 不再二次压缩已压缩的固件及归档，
  诊断日志仍使用默认压缩；Artifact 下载后仍是 ZIP 容器。
- 不自动发布、不自动刷机。显式发布仍会替换稳定入口的旧附件，请先确认新构建。

首次启用 fork Actions 前，请在仓库 **Settings → Actions → General** 将默认
workflow token 权限设为只读，并关闭允许 Actions 创建和批准 PR；这些是 GitHub
仓库设置，不会随 YAML 自动更改。本次文件修改不代表已启用 Actions。
然后只运行上述两个 AX5 流程，保持历史流程停用。公开仓库使用标准 Ubuntu 托管
runner；Artifact/缓存配额与未来的计费策略仍需自行留意，不代表无限免费资源。

### 内核模块策略

不把上游所有驱动和调试功能全部打开。保持 AX5 的 MMC、无线、NSS 与 512 MB
内存配置，沿用上游硬件依赖；`CONFIG_PACKAGE_kmod-*=y` 表示预装模块包，
不等于把对应 Linux 驱动静态编入内核。

- 预装：ext4、exFAT、VFAT、NTFS3、FUSE、UTF-8、USB 存储/UAS、NFS 服务端，
  以及 TUN、WireGuard、网络诊断、CAKE；启用支持不等于自动开放 VPN/NFS 服务。
- CIFS 客户端预装，用于挂载远端 SMB；不自动挂载共享，也不写入远端凭据。
  Samba 共享本机文件不依赖 CIFS 客户端。
- 预装 `kmod-zram` 和 `zram-swap`，首次启动设置 128 MiB、LZO、优先级 100，
  并启用开机服务。这是压缩交换设备的逻辑容量，不是启动即预占 128 MiB 内存；
  不创建 eMMC 交换文件/分区，不配置磁盘 writeback。
  首次启动默认脚本会覆盖保留配置中的这三个 zram 参数，之后可通过 UCI 调整；
  zram 缓解内存压力，但会消耗 CPU，不能替代实际内存。
- 仅编译匹配 APK（`=m`）：Btrfs、XFS、loop、veth。
- 默认京东云设备树补丁明确 eMMC 的 4-bit 总线和不可移除属性；
  保持上游 HS200、192 MHz，不启用 HS400、不超频、不修改保留内存。
  继承关系、实机只读核对和验证边界见 [设备树分析](docs/ax5-device-tree.md)。
- 下游内核补丁为京东云首次枚举增加 HS400 失败后的一次 HS200 路径重试；
  默认仍使用 HS200；手动构建可选择实验性 `emmc_mode=hs400`，使用 8-bit/HS400
  设备树，失败重试时清除 8-bit/HS400 能力。HS400 产物有独立名称，禁止发布到 Release。
  它不覆盖运行中故障，也不保证板上真正断电或无损恢复，
  不能替代独立恢复手段；实现与测试边界见上述设备树文档。
- 固件预装按需只读命令 `ax5-emmc-report`，报告实际模式、主机能力、寿命、
  错误计数和 MMC 日志；无自动采集或上传。旧固件可通过 SSH 临时执行仓库中的
  `scripts/collect-emmc-telemetry.sh`，无需安装。
- 不额外开启 SFE 或修改 NSS/软件流量卸载运行配置；CAKE/SQM 的实际整形效果仍需
  在机器上验证，安装模块不保证 NSS 加速流量经过软件队列。
- 不执行格式化、挂载或存储迁移；文件系统工具也不会因为安装驱动而自动安装。

### 产物与核验

构建在 `make defconfig` 后校验必需服务、设备、内核和 feeds 提交；
打包时检查真正编译的 Linux `.config`、固件 manifest，以及同次构建的 kernel
和全部显式请求的内核模块 APK。配置被依赖系统静默丢弃时使构建失败。

- `<构建标识>-squashfs-sysupgrade.bin`、设备 manifest、`*.buildinfo`
- `<构建标识>-packages.tar.gz`：同时收集 `bin/packages` 和目标目录的包，避免遗漏内核模块
- `<构建标识>-provenance.tar.gz`：OpenWrt 与 Linux 完整配置、`kernel-audit.json`、
  diffconfig、锁文件和源码/feeds/CI 提交
- `<构建标识>-sha256sums.txt`、`<构建标识>-release.md`、`<构建标识>-build.json`

统一构建标识示例：

```text
libwrt-ax5-jdcloud-k6.12.108-s3a3d0b085955-ce17601ad89f4-r40100409146-a1
```

其中 `s` 为上游源码 SHA 前 12 位，`c` 为本仓库 CI 提交 SHA 前 12 位，
`r` 为 GitHub run ID，`a` 为重试编号。同一次构建的固件文件、配套包和历史 Release
使用相同标识，Actions Artifact 则分别添加 `-firmware`、`-diagnostics`、`-config`。
本地命令不依赖 GitHub 环境，后缀为 `-local`；它不是唯一的构建批次标识，也不表示工作区干净。
`-build.json` 保留原始固件文件名及输出文件映射。仅重命名分发副本，不修改固件内容、
APK 原始文件名或包内路径。解压 Artifact 后，在所在目录执行：

```sh
sha256sum --check ./*-sha256sums.txt
```

工作流文件名和稳定 Release 标签保持兼容；Actions 界面分别显示
**AX5 JDCloud - Build firmware** 和 **AX5 JDCloud - Check configuration**，
运行标题显示批次与分支，job/步骤显示设备、阶段序号及用途。
下载、并行编译、失败后的单线程重试日志分别保存为 `logs/ci/01-download.log`、
`02-compile.log`、`03-compile-retry.log`（仅重试时生成），随诊断 Artifact 上传。
打包成功后，Actions Summary 会列出本批次文件、字节数和校验命令；不代表上传、发布或刷机验证成功。

不要把这些 APK 与滚动 snapshot 软件源混装。固定提交不等于逐字节可复现：
Ubuntu 软件包和构建工具仍由 runner 提供；需要严格复现时还应固定构建容器。
编译日志和失败时已有的配置也会单独上传，避免失败后只剩退出码。

**从当前 `6.12.55/mmc_do_upgrade` 固件跨版本升级尚未验证，不能直接当作可安全刷入的版本。**
先将配置、共享文件和 Time Machine 数据备份到路由器以外。
“保留配置”不保证 `/overlay` 数据、用户账户或挂载方式保持不变。
此流程刻意不打包 factory 镜像。没有执行分区、格式化或自动刷机操作。

### 修改和验证

修改锁文件和精简配置后运行：

```sh
python3 -m unittest discover -s tests -v
bash -n scripts/customize-ax5.sh
shellcheck scripts/customize-ax5.sh
```

完整构建在 Ubuntu 24.04 的手动工作流中验证。修改锁文件时需重新检查 feeds 兼容性、
`make defconfig` 校验及完整编译，不应把单元测试通过当作固件可用的证明。
`AX5 JDCloud - Check configuration` 还会在 Ubuntu 中拉取真实源码/feeds，运行 `make defconfig`
并核对所有显式请求的 `=y` 选项及 `=m` 模块，避免不存在的包名被静默丢弃。

下面保留的是原上游项目说明，其地址、下载链接及默认设置不适用于上述定制入口。

## 特别提示 [![](https://img.shields.io/badge/-个人免责声明-FFFFFF.svg)](#特别提示-)

- **本人不对任何人因使用本固件所遭受的任何理论或实际的损失承担责任！**

- **本固件禁止用于任何商业用途，请务必严格遵守国家互联网使用相关法律规定！**

## 项目说明 [![](https://img.shields.io/badge/-项目基本介绍-FFFFFF.svg)](#项目说明-)
- 固件默认管理地址：`192.168.1.1` 默认用户：`root` 默认密码：`password`
- 源码：[LiBwrt](https://github.com/LiBwrt-op/openwrt-6.x)
- 源码：[immortalwrt](https://github.com/immortalwrt/immortalwrt)
- 云编译来源：https://github.com/haiibo/OpenWrt

## 固件下载 [![](https://img.shields.io/badge/-编译状态及下载链接-FFFFFF.svg)](#固件下载-)
点击下表中 [![](https://img.shields.io/badge/下载-链接-blueviolet.svg?style=flat&logo=hack-the-box)](https://github.com/haiibo/OpenWrt/releases) 即可跳转到该设备固件下载页面
| 平台+设备名称 | 固件编译状态 | 配置文件 | 固件下载 |
| :-------------: | :-------------: | :-------------: | :-------------: |
| [![](https://img.shields.io/badge/IPQ60XX-ALL-32C955.svg?logo=openwrt)](https://github.com/breeze303/openwrt-ci/blob/main/.github/workflows/IPQ60XX-ALL.yml) | [![](https://github.com/breeze303/openwrt-ci/actions/workflows/IPQ60XX-ALL.yml/badge.svg)](https://github.com/breeze303/openwrt-ci/actions/workflows/IPQ60XX-ALL.yml) | [![](https://img.shields.io/badge/编译-配置-orange.svg?logo=apache-spark)](https://github.com/breeze303/openwrt-ci/blob/main/configs/ipq60xx-all.config) | [![](https://img.shields.io/badge/下载-链接-blueviolet.svg?logo=hack-the-box)](https://github.com/breeze303/openwrt-ci/releases/IPQ60XX-ALL) |
| [![](https://img.shields.io/badge/IPQ60XX-NOWIFI-32C955.svg?logo=openwrt)](https://github.com/breeze303/openwrt-ci/blob/main/.github/workflows/IPQ60XX-NOWIFI.yml) | [![](https://github.com/breeze303/openwrt-ci/actions/workflows/IPQ60XX-NOWIFI.yml/badge.svg)](https://github.com/breeze303/openwrt-ci/actions/workflows/IPQ60XX-WIFI.yml) | [![](https://img.shields.io/badge/编译-配置-orange.svg?logo=apache-spark)](https://github.com/breeze303/openwrt-ci/blob/main/configs/ipq60xx.config) | [![](https://img.shields.io/badge/下载-链接-blueviolet.svg?logo=hack-the-box)](https://github.com/breeze303/openwrt-ci/releases/IPQ60XX-NOWIFI) |
| [![](https://img.shields.io/badge/IPQ807X-WIFI-32C955.svg?logo=openwrt)](https://github.com/breeze303/OpenWrt/blob/main/.github/workflows/IPQ807X-WIFI.yml) | [![](https://github.com/breeze303/OpenWrt/actions/workflows/IPQ807X-WIFI.yml/badge.svg)](https://github.com/breeze303/OpenWrt/actions/workflows/IPQ807X-WIFI.yml) | [![](https://img.shields.io/badge/编译-配置-orange.svg?logo=apache-spark)](https://github.com/breeze303/OpenWrt/blob/main/configs/ipq807x-wifi.config) | [![](https://img.shields.io/badge/下载-链接-blueviolet.svg?logo=hack-the-box)](https://github.com/breeze303/OpenWrt/releases/IPQ807X-WIFI) |
| [![](https://img.shields.io/badge/X86-64-32C955.svg?logo=openwrt)](https://github.com/breeze303/openwrt-ci/blob/main/.github/workflows/X86-64.yml) | [![](https://github.com/breeze303/openwrt-ci/actions/workflows/X86-64.yml/badge.svg)](https://github.com/breeze303/openwrt-ci/actions/workflows/X86-64.yml) | [![](https://img.shields.io/badge/编译-配置-orange.svg?logo=apache-spark)](https://github.com/breeze303/openwrt-ci/blob/main/configs/x86-64.config) | [![](https://img.shields.io/badge/下载-链接-blueviolet.svg?logo=hack-the-box)](https://github.com/breeze303/openwrt-ci/releases/tag/X86-64) |


## 定制固件 [![](https://img.shields.io/badge/-项目基本编译教程-FFFFFF.svg)](#定制固件-)
1. 首先要登录 Gihub 账号，然后 Fork 此项目到你自己的 Github 仓库
2. 修改 `configs` 目录对应文件添加或删除插件，或者上传自己的 `xx.config` 配置文件
3. 插件对应名称及功能请参考恩山网友帖子：[Applications 添加插件应用说明](https://www.right.com.cn/forum/thread-3682029-1-1.html)
4. 如需修改默认 IP、添加或删除插件包以及一些其他设置请在 `diy-script.sh` 文件内修改
5. 添加或修改 `xx.yml` 文件，最后点击 `Actions` 运行要编译的 `workflow` 即可开始编译
6. 编译大概需要3-5小时，编译完成后在仓库主页 [Releases](https://github.com/haiibo/OpenWrt/releases) 对应 Tag 标签内下载固件

如果你觉得修改 config 文件麻烦，那么你可以点击此处尝试本地提取 https://github.com/LiBwrt/openwrt-6.x

**如果看不懂编译界面可以参考 YouTube 视频：[软路由固件 OpenWrt 编译界面设置](https://www.youtube.com/watch?v=jEE_J6-4E3Y&list=WL&index=7)**


<a href="#readme">
<img src="https://img.shields.io/badge/-返回顶部-FFFFFF.svg" title="返回顶部" align="right"/>
</a>
