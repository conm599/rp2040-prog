# RP2040 烧录器固件合集

一块六块钱的 RP2040，换成不同固件就是不同型号的烧录器：SWD 调试器、JTAG 探针、SPI Flash 编程器、CH32 单线烧录器、USB-TTL 桥。

这个仓库把能直接用的 `.uf2` 打包好，配一张速查网页，顺便把每块固件的实测结果、接线方式、适用芯片都写清楚。

## 在线访问

启用 GitHub Pages 后访问：`https://<你的用户名>.github.io/rp2040-prog/`

## 内容

| 固件 | 协议 | 用途 |
|---|---|---|
| debugprobe | CMSIS-DAP v2 / SWD | 主流首选，带 UART 直通（GP4/GP5） |
| debugprobe Pico 2 | CMSIS-DAP v2 / SWD | RP2350 专用，刷到 RP2040 会被拒收 |
| MioLink | JTAG + SWD + SWO + RTT | Black Magic Probe 移植，支持 GDB server |
| DapperMime | CMSIS-DAP v1 / HID | 免驱老固件，新版软件不认时救场 |
| yapicoprobe | CMSIS-DAP v2 | 额外提供只读 U 盘，镜像目标 flash |
| pico_rvd | WCH SWIO 单线 | CH32V003，官方工具不认的那个 |
| FiXPro | SPI / I²C / JTAG / SWD / UPDI / 1-Wire | 通用编程器，网页界面 |
| pico-uart-bridge | USB ↔ 双 UART | 纯 TTL 桥，当串口卡用 |

## 网站结构

```
index.html          主页面，固件下载 + 接线说明 + 实测记录 + AI 技能包
firmware/*.uf2      8 个固件
fixpro/             FiXPro 网页烧录界面（已汉化，含原版 index.en.html）
fixpro/translate_fixpro.py  汉化脚本
skill/mcu-probe-toolkit.zip Agent Skill 包（SKILL.md 规范），解压到客户端的 skills 目录
flasher/            桌面烧录器源码（Python，见下）
```

纯静态，无构建步骤。`fixpro/` 里的界面用浏览器 Web Serial 直连串口，必须 Chrome / Edge / Opera。

## Flasher：配套的桌面烧录器

`flasher/` 是那个 Windows 烧录器的完整源码：一个本地 HTTP 服务 + 浏览器界面，只用标准库，烧录时才调 pyOCD。

```
flasher/launcher.py        本地 HTTP 服务（标准库）+ 烧录编排 + 编译调用
flasher/ui.html            拖拽界面，400ms 轮询日志
flasher/serial_isp.py      STM32 bootloader（AN3155）最小编程器，串口通道用
flasher/src/startup.c      最小启动文件（向量表 + 复位处理），用户没带启动文件时用它
flasher/src/f103.ld        链接脚本，128KB Flash / 20KB RAM
flasher/examples/blink.c   能直接烧的样例
flasher/make_toolchain.py  从完整 xpack 裁出打包用的精简工具链
flasher/Flasher.spec       PyInstaller 打包配置
```

设计上有几处不太常规的地方，改之前值得先看一眼：

- **不用 tkinter 拖拽**：界面是浏览器，文件以原始字节 POST 给本地服务，避免各平台拖拽实现的差异，也顺带能显示富文本日志。
- **自定义 pyOCD target**：目标板是 128KB Flash / 1KB 页的兼容片，直接用内置的 F103RC（2KB 页）会在末尾校验失败，所以注册了 `STM32F103CB`。
- **擦写前必须 `reset_and_halt()`**：否则 FPEC 拒绝解锁，erase 静默无效，表现为"擦除完成但写不进去"。
- **打包后探针枚举为空**：onefile 环境下 pyOCD 扫不到插件、libusb DLL 定位失败，`launcher.py` 里有三处补丁（`ensure_probe_registered` / `patch_libusb` / 排除 `cmsis_pack_manager`）。

从源码跑（需要 Python 3.10+）：

```bash
pip install pyocd pyserial
cd flasher && python launcher.py
```

要打包成单文件 exe：

```bash
python make_toolchain.py          # 从完整 xpack 工具链裁出 tc_min/，约 100MB
pyinstaller Flasher.spec --noconfirm --distpath dist
```

预编译的 exe 在 [Releases](https://github.com/conm599/rp2040-prog/releases) 里，国内直连 GitHub 慢的话网页上有几个镜像源可选。

## Agent Skill 包

`skill/mcu-probe-toolkit.zip` 是把这一整套知识固化成 AI 可读上下文的 **Agent Skill**（Anthropic 的 `SKILL.md` 规范，Claude Code、WorkBuddy 等支持该格式的客户端通用）：环境基线、三条铁律、标准工作流、排错表，外加三个已在真机跑通的脚本（`probe.py` 读芯片、`flash.py` 按 128KB+1KB 页烧录、`blink.py` 现场汇编闪灯固件）。

解压到客户端的 skills 目录（WorkBuddy 是 `~/.workbuddy/skills/`，Claude Code 是 `~/.claude/skills/`）后重开对话即生效，新对话不用再解释「这块板子是什么」。脚本依赖 `pip install pyocd keystone-engine`。

## 刷入方法

按住板上的 BOOTSEL 键插 USB，出现 `RPI-RP2` 盘后，把 `.uf2` 拖进去。RP2040 的 bootloader 在 ROM 里，刷错不会变砖，重新按 BOOTSEL 再来一次即可。

## 实测记录

2026-11-21 在 RP2040 实板上逐个刷入验证：

| 固件 | VID:PID | 表现 |
|---|---|---|
| debugprobe | `2E8A:000C` | CMSIS-DAP v2 + COM 口，pyOCD 直接识别 |
| DapperMime | `CAFE:4005` | pyOCD 显示为 `TinyUSB RP2040 CMSIS-DAP` |
| pico_rvd | `2E8A:000A` | 串口控制台，无调试器功能（设计如此） |
| FiXPro | `2E8A:000A` | 串口设备，供网页 Web Serial 连接 |
| MioLink | `1D50:6018` | 标准 BMP 设备号，GDB server + 两个串口 |
| yapicoprobe | CMSIS-DAP v2 | 附带只读 U 盘，内容为目标芯片 flash 镜像 |
| pico-uart-bridge | — | 未实机验证，family ID `0xE48BFF56` 匹配 RP2040 |

## 版权

**本站只做汇总与镜像，固件版权归各原作者所有。** 各固件许可证不同（BSD-3 / MIT / GPL-3.0 等），使用和再分发前请核对上游仓库：

- debugprobe — https://github.com/raspberrypi/debugprobe
- MioLink — https://github.com/JTAGNexus/MioLink
- DapperMime — https://github.com/majbthrd/DapperMime
- yapicoprobe — https://github.com/rgrr/yapicoprobe
- pico-rvd — https://github.com/Apache02/pico-rvd
- FiXPro — https://github.com/MYMDO/fixpro （GPL-3.0）
- pico-uart-bridge — https://github.com/Noltari/pico-uart-bridge （MIT）

FiXPro 网页界面为 GPL-3.0 项目的衍生改动（汉化），同样遵循 GPL-3.0。
