# debugprobe 一键烧录器

把固件或源码拖进窗口，自动擦除、写入、校验、复位运行。底层用 pyOCD 走 SWD，不需要拨 BOOT0，不需要装 Keil。

许可证：MIT（见 `LICENSE`）。仓库里其它目录的固件各有各的许可证，跟这份源码无关。

## 启动

两种方式：

- **Releases 里的 `Flasher.exe`** — 双击即用，不需要装 Python，也不需要另装编译器（内置 arm-gcc）。约 63MB，首次启动要先解压内置工具链，黑窗口会停一会儿，具体多久看机器，之后就正常了。
- **`启动烧录器.bat`** — 从源码跑，需要 Python 3.10 + `pip install pyocd pyserial`

浏览器会自动打开 `http://127.0.0.1:8731/`，关掉那个黑窗口即停止服务。

要求：

- RP2040 已刷 debugprobe，插在电脑上
- SWD 四根线接到目标板：`GP2→SWCLK`、`GP3→SWDIO`、`GND→GND`，3V3 二选一

## 两个通道

界面上可以切换，SWD 走不通时用串口兜底。

| 通道 | 原理 | 目标板要做的准备 |
|---|---|---|
| **SWD（默认）** | pyOCD 通过调试口直接读写 Flash | 什么都不用管，不用动 BOOT0 |
| **串口 ISP** | 走芯片内置 bootloader，AN3155 协议 | **BOOT0=1 并复位**；串口 TX→PA10、RX→PA9；共地 |

串口通道会自动填充串口列表，选中即用，波特率 115200、8E1。它只能烧写不能调试，也不做远程复位，所以时序要自己卡；烧完把 BOOT0 拨回 0 再复位。

## 用法

把文件拖进虚线框，点「开始烧录」。

| 拖入 | 行为 |
|---|---|
| `.hex` / `.bin` / `.elf` | 直接烧到 `0x08000000` |
| `.uf2` | 找 `RPI-RP2` 盘并复制，用于刷 RP2040 自身 |
| `.c` / `.cpp` / `.s` | 先编译再烧（编译器内置，开箱可用） |
| `.h` / `.hpp` | 只参与编译，不单独烧 |
| 其它文件 | 静默跳过（拖整个工程时免得出错） |

一次拖多个文件会**一起**编译成一个固件，所以多文件工程直接全选拖进来就行。拖整个文件夹也行（也可以点「选整个文件夹」），目录结构会保留，`#include "xx.h"` 按子目录自动加 `-I` 搜索。

启动文件和链接脚本的取舍是自动的：

| 工程里带了什么 | 怎么处理 |
|---|---|
| 自己写了 `Reset_Handler` 的 `startup.c` | 用你的，不再塞内置启动文件 |
| Keil/IAR 的 `startup_xxx.s`（`AREA`/`EXPORT`/`PROC` 语法） | 跳过并提示，gnu as 编不了，启动交给内置那份 |
| 自己的 `.ld` / `.lds` | 用你的链接脚本 |
| 都没有 | 用内置 `src/startup.c` + `src/f103.ld` |

编译完、烧完之后队列里的源码会自动清空，避免下次拖新工程时混进上一个工程的 `main()`。固件文件不清理，可以重复烧。

三个开关：全片擦除、回读校验、完成后复位运行。默认全开。

## 源码模式

拖入 `.c` 时用的是内置的最小启动文件 `src/startup.c` 和链接脚本 `src/f103.ld`，不依赖 HAL 和 CMSIS，直接写寄存器。所以适合裸机小实验，不适合带外设库的工程。

`examples/blink.c` 是个能直接拖进去跑的例子：PC13 与 PB0 反相闪烁。

Flash 与 RAM 参数按兼容片配置：**128KB / 1KB 页 / 20KB RAM**。正品 C8T6 是 64KB，但多出来的容量照用无妨。

## 关键实现细节

擦写之前**必须先 `reset_and_halt`**。芯片在全速跑用户程序时，FPEC 控制器会拒绝解锁，`erase` 会静默地什么都不做（FLASH_SR 全 0、内容不变），紧接着编程就报 `flash program page failure`。这一点踩过坑，写在这里免得以后重犯。

擦除之后会读回首字节确认是 `0xFF`，不是就直接报错，不进入写入阶段。

### 打包成 exe 时的三个坑

PyInstaller onefile 下 pyOCD 会莫名「一个探针都找不到」，原因有三层，都已处理：

1. **libusb DLL 定位失败** — `libusb_package.find` 用 `importlib.resources` 找 DLL，解包目录里找不到。`patch_libusb()` 直接按文件系统搜 `libusb-1.0.dll`，然后接管 `libusb_package.find`，用指定 DLL 建 backend 再枚举。
2. **`cmsis_pack_manager` 的 DLL 加载失败**（`error 0x7e`），异常被吞掉后表现为 0 个探针。打包时 `--exclude-module cmsis_pack_manager`，它跟烧录无关。
3. **插件扫描失效** — pyOCD 用 `pkgutil` 扫 `pyocd.probe` 包来填充 `PROBE_CLASSES`，冻结环境里扫不到，聚合器就返回空。`ensure_probe_registered()` 手动登记 `CMSISDAPProbe`。

排查时点界面上的「自检」，它会输出 `probe_classes / dap_devices / aggregator` 三个值，哪一层断了看得出来。

### 源码模式：编译器已经内置

exe 里带了一份精简的 arm-none-eabi-gcc，拖 `.c` 进去直接编译再烧，不需要另装工具链。

体积换来的代价是 exe 变大了，启动时会先把工具链解压出来。想更快的话，把完整工具链放在 exe 旁边或设 `ARM_GCC_DIR` 指向它的 `bin` 目录，会优先用外部那份：

| 优先级 | 位置 |
|---|---|
| 1 | 环境变量 `ARM_GCC_DIR` |
| 2 | exe 旁 `toolchain\bin\` 或 `tc_min\bin\` |
| 3 | exe 内置（`toolchain\gcc\`） |
| 4 | 系统 PATH |

内置的只保留 Cortex-M3 裸机 C 编译要用的部分（cc1 / as / ld / objcopy / newlib / libgcc），**不支持 C++**（没带 cc1plus）。要编 C++ 就放外部完整工具链。

精简工具链由 `make_toolchain.py` 从完整 xpack 包生成，改完工具链版本重跑一次即可：

```
python make_toolchain.py
pyinstaller Flasher.spec --noconfirm --distpath dist --workpath build_tmp
```

体积从 1.5GB 砍到约 100MB。关键是不能只挑 `bin/` 和库：gcc 执行裸名 `as`/`ld` 时是在 `<prefix>/arm-none-eabi/bin` 里找的，漏了这个目录就会报 `cannot execute 'as': CreateProcess: No such file or directory`。


## 目录

```
launcher.py          本地 HTTP 服务 + 烧录逻辑
ui.html              界面，拖拽与日志轮询
Flasher.spec         PyInstaller 打包配置
make_toolchain.py    从完整 xpack 生成精简工具链 tc_min/
tc_min/              精简工具链（101MB，打包时塞进 exe）
src/startup.c        最小启动文件（向量表 + 复位处理）
src/f103.ld          链接脚本，128KB Flash / 20KB RAM
examples/blink.c     可直接烧的示例
启动烧录器.bat        双击启动
dev/                 接口自测脚本，平时不用
uploads/             拖进来的文件与编译产物
```

## 文件都落在哪

不往系统盘塞东西，全部跟着 exe 走：

| 内容 | 位置 |
|---|---|
| 拖进来的文件、编译产物 | exe 同级 `uploads/` |
| 内置工具链的运行时解压 | exe 同级 `_MEIxxxxx/`（关掉窗口自动删，进程被强杀才会残留） |
| 烧录镜像 | 直接写目标芯片，不落盘 |

`_MEIxxxxx` 是 PyInstaller onefile 的解包目录（约 100MB）。exe 放在移动盘上也没问题，只是每次启动都要重新解压一次。

另外同一时间只允许开一个实例：重复双击会检测到已有服务在跑，直接把浏览器指过去然后退出，不会出现两个进程抢 8731 端口、请求被随机分走的情况。

## 已知边界

- 只针对 STM32F103 系（含兼容片）。换别的芯片要改 `register_target()` 里的参数。
- 没有做 SWD 速度自动降级，连不上时手动把 `options={"frequency": ...}` 调到 100000。
- `.elf` 依赖 pyOCD 内置解析，复杂工程建议先转 hex。
