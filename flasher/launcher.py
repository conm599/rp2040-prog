"""debugprobe 一键烧录器 —— 本地 Web GUI

运行后在浏览器打开 http://127.0.0.1:8731/，把 hex / bin / elf / uf2 或 .c 源码拖进页面即可。

设计要点：
- 纯标准库 HTTP 服务，只有烧录时才用 pyOCD
- 浏览器负责拖拽和界面，文件内容以原始字节 POST 上来，避免 tkinter 拖拽依赖
- 所有烧录任务跑在后台线程，前端轮询日志，界面不会假死
"""
import json
import os
import re
import shutil
import string
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))

# 打包成 exe 后：只读资源在临时解包目录，可写目录在 exe 旁边
FROZEN = getattr(sys, "frozen", False)
RES_DIR = getattr(sys, "_MEIPASS", ROOT) if FROZEN else ROOT
BASE_DIR = os.path.dirname(sys.executable) if FROZEN else ROOT

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
SRC_DIR = os.path.join(RES_DIR, "src")
UI_PATH = os.path.join(RES_DIR, "ui.html")
PORT = 8731

FLASH_START = 0x08000000
FLASH_SIZE = 0x20000   # 兼容片实测 128KB
PAGE_SIZE = 0x400      # 实测 1KB 页

SOURCE_EXT = {".c", ".cpp", ".cc", ".cxx", ".s", ".S"}
HEADER_EXT = {".h", ".hpp", ".hh", ".hxx", ".inc"}
LINKER_EXT = {".ld", ".lds"}
FIRMWARE_EXT = {".hex", ".bin", ".elf", ".uf2"}

# 用户工程自带的启动文件特征：定义了复位入口或向量表
STARTUP_RE = [
    re.compile(r"^\s*(?:void\s+)?Reset_Handler\s*\([^;)]*\)\s*\{", re.M),
    re.compile(r"^\s*\.?(?:globl|global|weak)?\s*Reset_Handler\s*:", re.M),
    re.compile(r"^\s*(?:const\s+)?(?:void\s*\*\s*(?:const\s*)?)?(?:g_pfnVectors|__Vectors)\s*[\[=]", re.M),
]

# ---------------------------------------------------------------- 自定义 target

def ensure_probe_registered():
    """打包后 pyOCD 靠 pkgutil 扫描插件来发现探针类，在 onefile 环境里扫不到，
    PROBE_CLASSES 会是空的，导致「一个探针都没有」。这里手动登记 CMSIS-DAP。"""
    try:
        from pyocd.probe.aggregator import PROBE_CLASSES
        from pyocd.probe.cmsis_dap_probe import CMSISDAPProbe
        PROBE_CLASSES["cmsisdap"] = CMSISDAPProbe
        return list(PROBE_CLASSES)
    except Exception as e:
        log(f"登记探针类失败: {type(e).__name__}: {e}")
        return []


def register_target():
    """把 F103 兼容片的 target 注册进 pyOCD：128KB Flash / 1KB 页。

    不能直接用 pyOCD 内置的 F103RC（2KB 页），写这类芯片会在末尾校验失败。
    """
    ensure_probe_registered()
    from pyocd.core.memory_map import MemoryMap, FlashRegion, RamRegion
    from pyocd.target.builtin.target_STM32F103RC import FLASH_ALGO
    from pyocd.coresight.coresight_target import CoreSightTarget
    import pyocd.target.builtin as builtin
    import pyocd.target as _target_mod

    class STM32F103CB(CoreSightTarget):
        VENDOR = "STMicroelectronics"
        MEMORY_MAP = MemoryMap(
            FlashRegion(start=FLASH_START, length=FLASH_SIZE, blocksize=PAGE_SIZE,
                        is_boot_memory=True, algo=FLASH_ALGO),
            RamRegion(start=0x20000000, length=0x5000),
        )

        def __init__(self, session):
            super().__init__(session, self.MEMORY_MAP)

    builtin.BUILTIN_TARGETS["stm32f103cb"] = STM32F103CB
    _target_mod.TARGET["stm32f103cb"] = STM32F103CB


# ---------------------------------------------------------------- 全局状态

LOCK = threading.Lock()
STATE = {
    "files": [],          # [{"name","path","size","kind"}]
    "log": [],            # ["[12:00:00] xxx"]
    "status": "idle",     # idle | running | ok | fail
    "busy": False,
}


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with LOCK:
        STATE["log"].append(line)
        if len(STATE["log"]) > 800:
            del STATE["log"][:200]
    print(line, flush=True)


def set_status(s):
    with LOCK:
        STATE["status"] = s


# ---------------------------------------------------------------- 环境探测

def find_gcc():
    """按顺序找 arm-none-eabi-gcc：环境变量 → exe 旁 → 内置打包 → 工作区 → PATH。

    内置工具链是扇出到 tc_min/ 的最小可用子集（约 100MB，打包进 exe 后
    首次运行会解压到临时目录），所以外部完整工具链优先，内置只作兜底。
    """
    env = os.environ.get("ARM_GCC_DIR")
    if env:
        for cand in (os.path.join(env, "arm-none-eabi-gcc.exe"),
                     os.path.join(env, "bin", "arm-none-eabi-gcc.exe")):
            if os.path.exists(cand):
                return cand
    # exe 旁边的完整工具链（放一份可以省掉每次解压）
    for base in (BASE_DIR, RES_DIR):
        p = os.path.join(base, "toolchain", "bin", "arm-none-eabi-gcc.exe")
        if os.path.exists(p):
            return p
        p = os.path.join(base, "tc_min", "bin", "arm-none-eabi-gcc.exe")
        if os.path.exists(p):
            return p
        # 打包进 exe 的兜底工具链
        p = os.path.join(base, "toolchain", "gcc", "bin", "arm-none-eabi-gcc.exe")
        if os.path.exists(p):
            return p
    # 工作区里的 xpack 工具链
    for base in (BASE_DIR, os.path.dirname(BASE_DIR), ROOT, os.path.dirname(ROOT)):
        tc = os.path.join(base, "toolchain", "xpack")
        if os.path.isdir(tc):
            for d in sorted(os.listdir(tc), reverse=True):
                p = os.path.join(tc, d, "bin", "arm-none-eabi-gcc.exe")
                if os.path.exists(p):
                    return p
    exe = shutil.which("arm-none-eabi-gcc")
    return exe


def find_tool(gcc_path, *names):
    """在 gcc 所在工具链里找配套工具。

    gcc 的 bin 目录只有驱动本身，as/ld/objcopy 实际在 <prefix>/arm-none-eabi/bin，
    所以两个位置都要看，最后才退到 PATH。
    """
    prefix = os.path.dirname(os.path.dirname(gcc_path))
    dirs = [os.path.dirname(gcc_path),
            os.path.join(prefix, "arm-none-eabi", "bin")]
    for name in names:
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
        p = shutil.which(name[:-4] if name.endswith(".exe") else name)
        if p:
            return p
    return None


def toolchain_env(gcc_path):
    """编译子进程的环境：把工具链目录顶到 PATH 前面。

    gcc 执行裸名 "as"/"ld" 时靠 PATH 和自身前缀目录查找，打包环境里
    系统 PATH 干净，不注入就会报 cannot execute 'as'。
    """
    env = os.environ.copy()
    bindir = os.path.dirname(gcc_path)
    prefix = os.path.dirname(os.path.dirname(gcc_path))
    extra = [bindir, os.path.join(prefix, "arm-none-eabi", "bin")]
    env["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] +
                                  [env.get("PATH", "")])
    return env


def find_rp2040_drive():
    """找 BOOTSEL 模式下的 RPI-RP2 盘，用于刷 RP2040 固件。"""
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if os.path.exists(os.path.join(root, "INFO_UF2.TXT")):
                return root
        except OSError:
            continue
    return None


def patch_libusb():
    """打包后 libusb_package 用 importlib.resources 定位 DLL 常常失败，
    导致 pyOCD 枚举不到探针。这里直接按文件系统找 DLL 并接管查找函数。"""
    global LIBUSB_PATH
    try:
        import glob
        import libusb_package

        cands = []
        for base in {RES_DIR, BASE_DIR, os.path.dirname(RES_DIR)}:
            cands += glob.glob(os.path.join(base, "**", "libusb-1.0.dll"), recursive=True)
        if not cands:
            return
        dll = cands[0]
        LIBUSB_PATH = dll

        def _find(*args, **kwargs):
            """模拟 libusb_package.find：用指定的 DLL 建 backend 再枚举。"""
            import usb.core
            import usb.backend.libusb1 as lb
            backend = lb.get_backend(find_library=lambda *_: dll)
            return usb.core.find(*args, backend=backend, **kwargs)

        libusb_package.find = _find
    except Exception:
        pass


LIBUSB_PATH = None
patch_libusb()


def usb_diag():
    """轻量自检：libusb 与 USB 设备枚举。不 import pyOCD，避免拖慢页面启动。"""
    info = {"libusb_path": LIBUSB_PATH}
    try:
        import usb.core
        import usb.backend.libusb1 as lb
        if LIBUSB_PATH:
            backend = lb.get_backend(find_library=lambda *_: LIBUSB_PATH)
        else:
            backend = lb.get_backend()
        devs = list(usb.core.find(find_all=True, backend=backend) or [])
        info["usb_devices"] = len(devs)
        info["usb_list"] = [f"{d.idVendor:04X}:{d.idProduct:04X}" for d in devs][:12]
    except Exception as e:
        info["usb_devices"] = -1
        info["usb_list"] = f"{type(e).__name__}: {e}"
    return info


def diag_full():
    """完整自检：再看 pyOCD 的探针类注册与聚合结果，用于排查「探针未检测到」。"""
    info = usb_diag()
    try:
        from pyocd.core.helpers import ConnectHelper  # noqa: F401
        info["probe_classes"] = ensure_probe_registered() or "空"
        from pyocd.probe.pydapaccess import DAPAccess
        try:
            info["dap_devices"] = f"{len(DAPAccess.get_connected_devices())} 个"
        except Exception:
            info["dap_devices"] = traceback.format_exc().strip().splitlines()[-1][:220]
        from pyocd.probe.aggregator import DebugProbeAggregator
        try:
            info["aggregator"] = f"{len(DebugProbeAggregator.get_all_connected_probes())} 个探针"
        except Exception:
            info["aggregator"] = traceback.format_exc().strip().splitlines()[-1][:220]
    except Exception:
        info["pyocd_diag"] = traceback.format_exc().strip().splitlines()[-1][:200]
    return info


def probe_info(verbose=False):
    """连接探针并读取芯片信息，返回给前端。"""
    step = log if verbose else (lambda *_: None)
    from pyocd.core.helpers import ConnectHelper

    out = {"probes": [], "connected": False, "error": None}
    try:
        step("列举探针…")
        probes = ConnectHelper.get_all_connected_probes(blocking=False)
        out["probes"] = [f"{p.product_name} ({p.unique_id})" for p in probes]
        step(f"  找到 {len(out['probes'])} 个")
    except Exception as e:
        step(f"  列举失败: {type(e).__name__}: {e}")

    session = None
    try:
        step("加载 target 定义…")
        register_target()
        step("打开 session…")
        session = ConnectHelper.session_with_chosen_probe(
            target_override="stm32f103cb", connect_mode="halt", blocking=False,
            options={"frequency": 1000000})
        if session is None:
            out["error"] = "没有找到可用的 CMSIS-DAP 探针（可以改用串口通道）"
            step("  未找到探针")
            return out
        step("连接目标…")
        session.open()
        t = session.target
        step("暂停内核…")
        t.halt()
        step("读寄存器…")

        def rd(a):
            try:
                return t.read32(a)
            except Exception:
                return None

        _d = t.dp.dpidr
        dpidr = int(getattr(_d, "idr", _d))
        cap = rd(0x1FFFF7E0)
        uid = [rd(0x1FFFF7E8 + 4 * i) for i in range(3)]
        dbg = rd(0xE0042000)

        out.update({
            "connected": True,
            "dpidr": f"0x{dpidr:08X}",
            "dpidr_ok": dpidr == 0x1BA01477,
            "cpuid": f"0x{rd(0xE000ED00):08X}" if rd(0xE000ED00) is not None else "-",
            "flash_kb": (cap & 0xFFFF) if cap is not None else None,
            "uid": "全 0（未实现）" if all(v == 0 for v in uid) else
                   "-".join(f"{v:08X}" for v in uid if v is not None),
            "dev_id": f"0x{(dbg >> 16) & 0xFFF:03X}" if dbg is not None else "-",
            "state": str(t.get_state()).replace("State.", ""),
        })
        t.resume()
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        try:
            if session:
                session.close()
        except Exception:
            pass
    return out


# ---------------------------------------------------------------- 编译

def safe_relpath(name):
    """把浏览器给的相对路径清洗成可落盘的相对路径。

    保留子目录（拖文件夹时前端带相对路径），丢掉盘符、`..` 和 Windows 非法字符，
    防止写穿到上传目录之外。
    """
    name = (name or "").replace("\\", "/").lstrip("/")
    parts = []
    for seg in name.split("/"):
        if not seg or seg in (".", ".."):
            continue
        if re.fullmatch(r"[A-Za-z]:", seg):
            continue
        seg = re.sub(r'[<>:"|?*\x00-\x1f]', "_", seg).strip(" .")
        if seg:
            parts.append(seg)
    return "/".join(parts)


def detect_own_startup(srcs):
    """看用户源码里是不是已经带了启动文件（自己写了 Reset_Handler 或向量表）。

    带了就别再塞内置 startup.c，否则 Default_Handler / Reset_Handler 会重复定义。
    """
    for p in srcs:
        if os.path.splitext(p)[1].lower() not in {".c", ".cpp", ".cc", ".cxx", ".s"}:
            continue
        try:
            txt = open(p, "r", encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for rx in STARTUP_RE:
            if rx.search(txt):
                return p
    return None


ASM_ARM_RE = re.compile(r"^\s*(AREA|EXPORT|IMPORT|PROC|ENDP|PRESERVE8)\b", re.M)


def drop_arm_asm(srcs):
    """剔掉 Keil/IAR 那种 ARM 汇编启动文件。

    它们用的是 AREA/EXPORT/PROC 语法，gnu as 编不了，混进来只会刷一堆语法错误。
    用户真实意图是烧自己的 main.c，启动交给内置那份就行。
    """
    keep, dropped = [], []
    for p in srcs:
        if p.lower().endswith(".s"):
            try:
                txt = open(p, "r", encoding="utf-8", errors="ignore").read()
            except OSError:
                txt = ""
            if ASM_ARM_RE.search(txt):
                dropped.append(p)
                continue
        keep.append(p)
    for p in dropped:
        log(f"跳过 ARM 汇编启动文件 {os.path.basename(p)}（gnu as 不支持，改用内置启动文件）")
    return keep


def compile_sources(srcs, ldscript=None, own_startup=None):
    """把 .c/.cpp 源码编成 hex。返回 hex 路径。

    srcs 里只该有参与编译的源文件；头文件由 gcc 自己按 include 找，
    这里额外把上传目录加进 -I，保证平铺存放的 .h 能被引号 include 命中。
    """
    gcc = find_gcc()
    if not gcc:
        raise RuntimeError("找不到 arm-none-eabi-gcc，源码编译不可用（固件文件仍可烧录）")
    bindir = os.path.dirname(gcc)
    objcopy = find_tool(gcc, "arm-none-eabi-objcopy.exe", "objcopy.exe")
    if not objcopy:
        raise RuntimeError("找不到 arm-none-eabi-objcopy")

    # 用户自带启动文件时不要塞内置的，否则 Reset_Handler 会重复定义
    if own_startup:
        log(f"检测到自带启动文件 {os.path.basename(own_startup)}，不再加内置 startup.c")
        startup = None
    else:
        startup = os.path.join(SRC_DIR, "startup.c")
    # 用户带了链接脚本就用自己的，段符号才和启动文件对得上
    if ldscript:
        log(f"使用自带的链接脚本 {os.path.basename(ldscript)}")
        ld = ldscript
    else:
        ld = os.path.join(SRC_DIR, "f103.ld")
    outdir = os.path.join(UPLOAD_DIR, "_build")
    os.makedirs(outdir, exist_ok=True)
    elf = os.path.join(outdir, "app.elf")
    hexf = os.path.join(outdir, "app.hex")

    # 防止用户把同一个 .c 拖两次，链接时才会莫名其妙报重复定义
    seen, uniq = set(), []
    for s in srcs:
        key = os.path.normcase(os.path.abspath(s))
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    srcs = uniq

    inc_dirs = [UPLOAD_DIR, outdir]
    for s in srcs:
        d = os.path.dirname(os.path.abspath(s))
        if d not in inc_dirs:
            inc_dirs.append(d)
    # 工程按目录拖进来时头文件常在子目录（Core/Inc 之类），
    # 把上传目录下所有放着头文件的子目录都加进 -I，`#include "xx.h"` 才找得到
    for root, dirs, names in os.walk(UPLOAD_DIR):
        if os.path.normcase(root) == os.path.normcase(outdir):
            dirs[:] = []
            continue
        if any(n.lower().endswith((".h", ".hpp", ".hh", ".hxx", ".inc")) for n in names):
            if root not in inc_dirs:
                inc_dirs.append(root)
    inc_flags = []
    for d in inc_dirs:
        inc_flags += ["-I", d]

    cmd = [
        gcc, "-mcpu=cortex-m3", "-mthumb", "-Os", "-g0",
        "-ffunction-sections", "-fdata-sections",
        "-Wall", "-std=gnu11",
        "-nostartfiles", "--specs=nosys.specs",
        *inc_flags,
        "-T", ld,
        *([startup] if startup else []), *srcs,
        "-Wl,--gc-sections",
        "-o", elf,
    ]
    env = toolchain_env(gcc)
    log("编译: " + " ".join(os.path.basename(x) for x in srcs))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    err = r.stderr or ""
    for line in err.splitlines():
        if line.strip():
            log("  " + line.strip())
    if r.returncode != 0:
        if "multiple definition of `main'" in err or "multiple definition of 'main'" in err:
            raise RuntimeError("队列里有多个定义了 main() 的源文件，先移除多余的再编译")
        if "Reset_Handler" in err and "multiple definition" in err:
            raise RuntimeError("有两个启动文件（你的和内置的）。把工程里多余的 startup 文件移除，或只保留一份")
        if "No such file or directory" in err and ".h" in err:
            raise RuntimeError("头文件没找到：把缺的 .h 一起拖进来（可以整个文件夹拖）")
        if "undefined reference to `SystemInit'" in err:
            raise RuntimeError("缺 SystemInit：把 system_stm32f10x.c 一起拖进来，或删掉启动文件里的调用")
        raise RuntimeError("编译失败，见上方编译器输出")

    r2 = subprocess.run([objcopy, "-O", "ihex", elf, hexf],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env)
    if r2.returncode != 0:
        raise RuntimeError("objcopy 转换失败: " + (r2.stderr or "").strip())
    log(f"编译完成 → {os.path.basename(hexf)}（{os.path.getsize(hexf)} 字节）")
    return hexf


# ---------------------------------------------------------------- 烧录

def parse_hex(path):
    """极简 Intel HEX 解析，返回 (起始地址, 数据)。用于烧后回读校验。"""
    data = {}
    base = 0
    for line in open(path, "r", encoding="ascii", errors="ignore"):
        line = line.strip()
        if not line.startswith(":"):
            continue
        raw = bytes.fromhex(line[1:])
        count, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
        payload = raw[4:4 + count]
        if rtype == 0x00:
            for i, b in enumerate(payload):
                data[base + addr + i] = b
        elif rtype == 0x04:
            base = ((payload[0] << 8) | payload[1]) << 16
        elif rtype == 0x02:
            base = ((payload[0] << 8) | payload[1]) << 4
        elif rtype == 0x01:
            break
    if not data:
        raise RuntimeError("HEX 文件里没有数据记录")
    start = min(data)
    end = max(data)
    buf = bytearray(b"\xFF" * (end - start + 1))
    for a, b in data.items():
        buf[a - start] = b
    return start, bytes(buf)


def flash_hex_or_bin(path, erase=True, verify=True, reset=True):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.flash.file_programmer import FileProgrammer
    from pyocd.flash.eraser import FlashEraser

    register_target()
    session = ConnectHelper.session_with_chosen_probe(
        target_override="stm32f103cb", connect_mode="halt", blocking=False,
        options={"frequency": 1000000})
    if session is None:
        raise RuntimeError("没有找到 CMSIS-DAP 探针。检查 Pico 是否插好、固件是否为 debugprobe；或改用串口通道")

    session.open()
    try:
        t = session.target
        region = t.memory_map.get_boot_memory()

        # 关键：擦写之前必须复位并 halt。
        # 芯片在全速跑用户程序时，FPEC 控制器会拒绝解锁，擦除会静默地什么都不做，
        # 随后编程就会报 "flash program page failure"。
        t.reset_and_halt()

        log(f"目标: {t.part_number}  Flash 0x{region.start:08X} {region.length // 1024}KB "
            f"页 {region.blocksize}B")

        if erase:
            log("全片擦除…")
            FlashEraser(session, FlashEraser.Mode.CHIP).erase()
            head = bytes(t.read_memory_block8(FLASH_START, 8))
            if head != b"\xFF" * 8:
                raise RuntimeError(f"擦除未生效，首字节仍为 {head.hex()}")
            log("擦除完成")

        log("写入…")
        FileProgrammer(session).program(path)
        log("写入完成")

        if verify:
            if path.lower().endswith(".hex"):
                start, data = parse_hex(path)
            else:
                start, data = FLASH_START, open(path, "rb").read()
            back = bytes(t.read_memory_block8(start, len(data)))
            if back != data:
                for i, (a, b) in enumerate(zip(data, back)):
                    if a != b:
                        raise RuntimeError(f"校验失败，首个差异 偏移 0x{i:X}"
                                           f"（0x{start + i:08X}）期望 {a:02X} 实际 {b:02X}")
            log(f"校验通过（{len(data)} 字节）")

        if reset:
            t.reset()
            t.resume()
            log("已复位运行")
    finally:
        session.close()


def flash_uf2(path):
    drive = find_rp2040_drive()
    if not drive:
        raise RuntimeError("没找到 RPI-RP2 盘。刷 RP2040 固件要先按住 BOOTSEL 插 USB")
    dst = os.path.join(drive, os.path.basename(path))
    log(f"复制到 {drive}")
    shutil.copyfile(path, dst)
    log("已写入，板子会自动重启")


def file_to_image(path):
    """把固件文件统一成 (起始地址, 字节串)，供串口通道使用。"""
    low = path.lower()
    if low.endswith(".hex"):
        return parse_hex(path)
    if low.endswith(".bin"):
        return FLASH_START, open(path, "rb").read()
    if low.endswith(".elf"):
        gcc = find_gcc()
        if not gcc:
            raise RuntimeError("串口通道不接受 .elf，且本机没有 arm-none-eabi-objcopy，请先转成 hex 或 bin")
        objcopy = find_tool(gcc, "arm-none-eabi-objcopy.exe", "objcopy.exe")
        if not objcopy:
            raise RuntimeError("找不到 arm-none-eabi-objcopy，请先把 elf 转成 hex 或 bin")
        out = os.path.join(UPLOAD_DIR, "_build", "serial_tmp.bin")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        subprocess.run([objcopy, "-O", "binary", path, out], check=True,
                       capture_output=True, env=toolchain_env(gcc))
        return FLASH_START, open(out, "rb").read()
    raise RuntimeError(f"串口通道不支持 {os.path.splitext(path)[1]}")


def flash_serial(path, port, baud=115200, erase=True, verify=True, reset=True):
    """走 STM32 串口 bootloader 烧录。要求 BOOT0=1 且已复位。"""
    import serial_isp

    start, data = file_to_image(path)
    log(f"串口通道: {port} @{baud}，镜像 {len(data)} 字节 @0x{start:08X}")
    log("提示：BOOT0 必须是 1，且拨完要复位过；烧完记得拨回 0")

    isp = serial_isp.Stm32Isp(port, baud)
    try:
        isp.sync()
        log("握手成功（收到 ACK）")
        try:
            info = isp.get()
            log(f"bootloader 版本 {info['version']}，支持 {len(info['commands'])} 条命令")
        except Exception as e:
            log(f"读版本失败（不影响烧录）: {e}")

        if erase:
            log("全片擦除…")
            isp.erase_all()
            log("擦除完成")

        log("写入…")

        def prog(done, total):
            pct = done * 100 // total
            if pct % 25 < 5:
                log(f"  进度 {pct}%")

        isp.write(start, data, progress=prog)
        log("写入完成")

        if verify:
            back = isp.read(start, len(data))
            if back != data:
                for i, (a, b) in enumerate(zip(data, back)):
                    if a != b:
                        raise RuntimeError(f"校验失败，偏移 0x{i:X}：期望 {a:02X} 实际 {b:02X}")
            log(f"校验通过（{len(data)} 字节）")

        if reset:
            isp.go(start)
            log("已跳转运行（BOOT0 波回 0 再复位一次更稳妥）")
    finally:
        isp.close()


def run_job(files, erase, verify, reset, channel="swd", port=None, baud=115200):
    """后台任务：按文件类型与通道分派。"""
    try:
        set_status("running")

        srcs = [f["path"] for f in files if f["kind"] == "source"]
        headers = [f for f in files if f["kind"] == "header"]
        linkers = [f["path"] for f in files if f["kind"] == "linker"]
        fws = [f for f in files if f["kind"] == "firmware"]

        if headers and not srcs:
            raise RuntimeError("队列里只有头文件，还要把 .c 一起拖进来")

        if srcs:
            log(f"工程文件: {len(srcs)} 个源文件" +
                (f" + {len(headers)} 个头文件" if headers else ""))
            srcs = drop_arm_asm(srcs)
            own = detect_own_startup(srcs)
            hexf = compile_sources(srcs, linkers[0] if linkers else None, own)
            fws = [{"name": os.path.basename(hexf), "path": hexf, "kind": "firmware"}]
            # 源码是工程输入，烧完就清掉，免得下次拖新工程时混进旧的 main()
            with LOCK:
                STATE["files"] = [f for f in STATE["files"] if f["kind"] == "firmware"]

        if not fws:
            raise RuntimeError("没有可烧录的文件")

        for f in fws:
            log(f"=== {f['name']} ===")
            if f["name"].lower().endswith(".uf2"):
                flash_uf2(f["path"])
            elif channel == "serial":
                if not port:
                    raise RuntimeError("串口通道需要先选择一个 COM 口")
                flash_serial(f["path"], port, baud=baud,
                             erase=erase, verify=verify, reset=reset)
            else:
                flash_hex_or_bin(f["path"], erase=erase, verify=verify, reset=reset)

        log("全部完成")
        set_status("ok")
    except Exception as e:
        log("失败: " + str(e))
        set_status("fail")
        print(traceback.format_exc(), file=sys.stderr, flush=True)
    finally:
        with LOCK:
            STATE["busy"] = False


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._guard(self._do_get)

    def do_POST(self):
        self._guard(self._do_post)

    def _guard(self, fn):
        """兜住所有异常，别让 handler 直接把连接掐掉。

        连接被掐掉时浏览器只会看到 "Failed to fetch"，什么原因都看不出来，
        所以哪怕出错也回一个 JSON，前端才能显示真正的错误。
        """
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._send(500, {"error": f"{type(e).__name__}: {e}"})
            except Exception:
                pass

    def _do_get(self):
        u = urllib.parse.urlparse(self.path)
        if u.path in ("/", "/index.html"):
            p = UI_PATH
            return self._send(200, open(p, "rb").read(), "text/html; charset=utf-8")

        if u.path == "/api/info":
            return self._send(200, {
                "gcc": find_gcc(),
                "rp2040_drive": find_rp2040_drive(),
                "python": sys.version.split()[0],
                "frozen": FROZEN,
                "usb": usb_diag(),
            })

        if u.path == "/api/diag":
            return self._send(200, diag_full())

        if u.path == "/api/ports":
            out = []
            try:
                import serial.tools.list_ports as lp
                for p in lp.comports():
                    out.append({"device": p.device, "desc": p.description,
                                "hwid": p.hwid})
            except Exception as e:
                return self._send(200, {"ports": [], "error": str(e)})
            return self._send(200, {"ports": out})

        if u.path == "/api/probe":
            return self._send(200, probe_info(verbose=True))

        if u.path == "/api/files":
            with LOCK:
                return self._send(200, {"files": STATE["files"], "busy": STATE["busy"],
                                        "status": STATE["status"]})

        if u.path == "/api/log":
            q = urllib.parse.parse_qs(u.query)
            start = int(q.get("from", ["0"])[0])
            with LOCK:
                lines = STATE["log"][start:]
                total = len(STATE["log"])
                status = STATE["status"]
                busy = STATE["busy"]
            return self._send(200, {"from": total, "lines": lines,
                                    "status": status, "busy": busy})

        return self._send(404, {"error": "not found"})

    def _do_post(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        n = int(self.headers.get("Content-Length") or 0)

        # 无论走哪个分支都先把 body 读完。提前 return 而没读 body 会让 keep-alive
        # 连接里残留数据，浏览器下一个请求就会莫名 "Failed to fetch"。
        if n > 64 * 1024 * 1024:
            # 拖了整个 build 目录之类的大文件，读进内存没意义，直接断开连接告知
            self.close_connection = True
            return self._send(413, {"error": f"单个文件 {n // 1048576} MB 太大，只接受 64MB 以内"})
        try:
            raw_body = self.rfile.read(n) if n > 0 else b""
        except Exception:
            raw_body = b""

        if u.path == "/api/upload":
            raw = urllib.parse.unquote(q.get("name", ["unnamed"])[0])
            safe = safe_relpath(raw)
            if not safe:
                return self._send(400, {"error": f"非法文件名 {raw}"})
            if len(safe) > 180:
                return self._send(400, {"error": f"路径太长（{len(safe)} 字符），Windows 写不进去，先把工程目录层级压浅一点"})
            data = raw_body
            ext = os.path.splitext(safe)[1]
            low = ext.lower()
            if low in FIRMWARE_EXT:
                kind = "firmware"
            elif low in SOURCE_EXT:
                kind = "source"
            elif low in HEADER_EXT:
                kind = "header"
            elif low in LINKER_EXT:
                kind = "linker"
            else:
                # 拖整个工程时常见的 README.txt / .gitignore / .uvprojx，静默跳过即可
                log(f"跳过无关文件: {safe}")
                return self._send(200, {"ok": True, "skipped": True, "name": safe})
            path = os.path.join(UPLOAD_DIR, safe)
            os.makedirs(os.path.dirname(path) or UPLOAD_DIR, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            item = {"name": safe, "path": path, "size": len(data),
                    "kind": kind, "ext": low}
            with LOCK:
                # 同名文件覆盖，不要重复入队——否则多拖一次就多一份 main()
                for i, old in enumerate(STATE["files"]):
                    if old["name"] == safe:
                        STATE["files"][i] = item
                        break
                else:
                    STATE["files"].append(item)
            log(f"已加入队列: {safe}（{len(data)} 字节，{kind}）")
            return self._send(200, {"ok": True, "file": item})

        if u.path == "/api/clear":
            with LOCK:
                STATE["files"] = []
            return self._send(200, {"ok": True})

        if u.path == "/api/remove":
            try:
                body = json.loads(raw_body or b"{}")
            except ValueError:
                body = {}
            idx = body.get("index", -1)
            with LOCK:
                if 0 <= idx < len(STATE["files"]):
                    STATE["files"].pop(idx)
            return self._send(200, {"ok": True})

        if u.path == "/api/run":
            try:
                body = json.loads(raw_body or b"{}")
            except ValueError:
                body = {}
            with LOCK:
                if STATE["busy"]:
                    return self._send(409, {"error": "已有任务在跑"})
                if not STATE["files"]:
                    return self._send(400, {"error": "队列是空的"})
                files = list(STATE["files"])
                STATE["busy"] = True
            threading.Thread(target=run_job, daemon=True, args=(
                files,
                body.get("erase", True),
                body.get("verify", True),
                body.get("reset", True),
                body.get("channel", "swd"),
                body.get("port"),
                int(body.get("baud", 115200)),
            )).start()
            return self._send(200, {"ok": True})

        return self._send(404, {"error": "not found"})


def already_running():
    """端口上已经有人应答了就说明开着一个了。"""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/info")
        with urllib.request.urlopen(req, timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def main():
    url = f"http://127.0.0.1:{PORT}/"

    # 开第二个实例时两个进程会同时 listen，请求被随机分走，
    # 表现为「明明传了文件队列里却没有」这种怪事，所以先探一下
    if already_running():
        print(f"已经有一个烧录器在跑了，直接打开页面：{url}")
        print("要重启的话，先把那个黑窗口关掉再双击。")
        webbrowser.open(url)
        time.sleep(2)
        return

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ThreadingHTTPServer.allow_reuse_address = False
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        print(f"端口 {PORT} 被占用了，可能是别的程序。换个端口或关掉占用它的程序。")
        time.sleep(3)
        return

    print(f"debugprobe 一键烧录器已启动: {url}")
    print("关闭此窗口即退出")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
