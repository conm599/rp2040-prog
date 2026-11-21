# -*- mode: python ; coding: utf-8 -*-
# debugprobe 一键烧录器打包配置
# 用法：pyinstaller Flasher.spec --noconfirm --distpath dist --workpath build_tmp
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

HERE = os.path.dirname(os.path.abspath(SPEC))  # noqa: F821  (SPEC 由 PyInstaller 注入)
ROOT = os.path.dirname(HERE)

datas = [
    (os.path.join(HERE, "ui.html"), "."),
    (os.path.join(HERE, "src"), "src"),
]
# 内置精简 ARM 工具链（make_toolchain.py 产出），拖 .c 源码即可编译
TC = os.path.join(HERE, "tc_min")
if os.path.isdir(TC):
    datas.append((TC, os.path.join("toolchain", "gcc")))

binaries = []
hiddenimports = ["usb.backend.libusb1", "pyocd.target.builtin"]
datas += collect_data_files("pyocd")
hiddenimports += collect_submodules("pyocd")
for pkg in ("libusb_package", "usb", "serial"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(HERE, "launcher.py")],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["cmsis_pack_manager", "pyocd.subcommands"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Flasher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        # 工具链里的 exe/dll 被 UPX 压过会报错或崩溃，一律排除
        "arm-none-eabi-*", "cc1*", "collect2*", "*.dll",
        "as", "ld", "objcopy", "objdump", "nm", "ar", "ranlib",
        "strip", "readelf", "ld.bfd", "libgcc_s_seh-1", "libgmp-10",
        "libmpfr-4", "libmpc-3", "libzstd", "liblto_plugin",
    ],
    # 内置工具链解压到「exe 所在目录」而不是 %TEMP%，别往 C 盘塞 100MB
    runtime_tmpdir=".",
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
