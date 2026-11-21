"""从完整 xpack ARM GCC 里挑出最小可用子集，供打包进 exe。

只保留 Cortex-M3 裸机 C 编译真正用到的东西：
- bin/             gcc / as / ld / objcopy / nm / size / ar / ranlib + 依赖 DLL
- libexec/gcc/.../ cc1.exe、collect2.exe 和它们依赖的 DLL
- lib/gcc/.../     启动对象、libgcc.a、内建头文件、thumb/v7-m/nofp
- arm-none-eabi/lib/thumb/v7-m/nofp    newlib（libc/libm/libnosys）
- arm-none-eabi/include                newlib 头文件

输出到 flasher/tc_min/，结构保持和原工具链一致，gcc 靠相对路径自解析。
用法：python make_toolchain.py [完整工具链根目录]
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DEFAULT = os.path.join(os.path.dirname(HERE), "toolchain", "xpack",
                           "xpack-arm-none-eabi-gcc-15.2.1-1.1")
DST = os.path.join(HERE, "tc_min")

# bin 里只留 gcc 驱动本身；as/ld/objcopy 等实际工作在 <prefix>/arm-none-eabi/bin 下，
# 不要重复复制两份
BIN_TOOLS = ["arm-none-eabi-gcc", "arm-none-eabi-cpp"]

# bin 下需要的 DLL（python/gdb/stdc++/ncurses 一律不要）
BIN_DLLS = ["libgmp-10.dll", "libmpfr-4.dll", "libmpc-3.dll",
            "libzstd.dll", "libgcc_s_seh-1.dll", "libwinpthread-1.dll"]

# gcc 执行裸名 "as"/"ld" 时是在 <prefix>/arm-none-eabi/bin 下找的，
# 这个目录缺了就会报 cannot execute 'as'，必须一并带上
TARGET_BIN_TOOLS = ["as.exe", "ld.exe", "ld.bfd.exe", "objcopy.exe", "objdump.exe",
                    "nm.exe", "ar.exe", "ranlib.exe", "strip.exe", "readelf.exe"]
TARGET_BIN_DLLS = ["libgcc_s_seh-1.dll", "libzstd.dll"]

LIBEXEC_FILES = ["cc1.exe", "collect2.exe", "libgmp-10.dll", "libmpfr-4.dll",
                 "libmpc-3.dll", "libzstd.dll", "libgcc_s_seh-1.dll",
                 "liblto_plugin.dll"]

GCC_LIB_TOP = ["crtbegin.o", "crtend.o", "crti.o", "crtn.o", "crtfastmath.o",
               "libgcc.a", "sync-dmb.specs", "sync-none.specs"]

NEWLIB_ARCH = os.path.join("thumb", "v7-m", "nofp")


def cp(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC_DEFAULT
    if not os.path.isdir(src):
        sys.exit(f"找不到完整工具链: {src}")
    if os.path.exists(DST):
        shutil.rmtree(DST)

    gcc_ver = None
    for d in sorted(os.listdir(os.path.join(src, "lib", "gcc", "arm-none-eabi"))):
        if os.path.isdir(os.path.join(src, "lib", "gcc", "arm-none-eabi", d)):
            gcc_ver = d
    if not gcc_ver:
        sys.exit("找不到 gcc 版本目录")

    n = 0
    # 1. bin
    for name in os.listdir(os.path.join(src, "bin")):
        stem = name[:-4] if name.endswith(".exe") else name
        if stem in BIN_TOOLS or name in BIN_DLLS:
            cp(os.path.join(src, "bin", name), os.path.join(DST, "bin", name))
            n += 1

    # 1b. arm-none-eabi/bin（gcc 找裸名 as/ld 的地方）
    tbin = os.path.join(src, "arm-none-eabi", "bin")
    for name in os.listdir(tbin) if os.path.isdir(tbin) else []:
        if name in TARGET_BIN_TOOLS or name in TARGET_BIN_DLLS:
            cp(os.path.join(tbin, name),
               os.path.join(DST, "arm-none-eabi", "bin", name))
            n += 1

    # 2. libexec
    lex = os.path.join(src, "libexec", "gcc", "arm-none-eabi", gcc_ver)
    for name in LIBEXEC_FILES:
        p = os.path.join(lex, name)
        if os.path.exists(p):
            cp(p, os.path.join(DST, "libexec", "gcc", "arm-none-eabi", gcc_ver, name))
            n += 1

    # 3. lib/gcc
    glib = os.path.join(src, "lib", "gcc", "arm-none-eabi", gcc_ver)
    gdst = os.path.join(DST, "lib", "gcc", "arm-none-eabi", gcc_ver)
    for name in GCC_LIB_TOP:
        p = os.path.join(glib, name)
        if os.path.exists(p):
            cp(p, os.path.join(gdst, name))
            n += 1
    for sub in ("include", "include-fixed"):
        s = os.path.join(glib, sub)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(gdst, sub))
            n += sum(len(f) for _, _, f in os.walk(s))
    arch = os.path.join(glib, NEWLIB_ARCH)
    if os.path.isdir(arch):
        shutil.copytree(arch, os.path.join(gdst, NEWLIB_ARCH))
        n += sum(len(f) for _, _, f in os.walk(arch))

    # 4. newlib 库
    narch = os.path.join(src, "arm-none-eabi", "lib", NEWLIB_ARCH)
    if not os.path.isdir(narch):
        sys.exit(f"找不到 newlib 目录: {narch}")
    shutil.copytree(narch, os.path.join(DST, "arm-none-eabi", "lib", NEWLIB_ARCH))
    n += sum(len(f) for _, _, f in os.walk(narch))

    # 4b. 顶层 specs（--specs=nosys.specs 在这里解析）
    nroot = os.path.join(src, "arm-none-eabi", "lib")
    for name in os.listdir(nroot):
        if name.endswith(".specs"):
            cp(os.path.join(nroot, name),
               os.path.join(DST, "arm-none-eabi", "lib", name))
            n += 1

    # 4c. C 编译用不到的 C++ / Fortran 运行库，剔除省体积
    for r, _, fs in os.walk(os.path.join(DST, "arm-none-eabi", "lib")):
        for f in fs:
            if f.startswith(("libstdc++", "libgfortran")):
                os.remove(os.path.join(r, f))

    # 5. newlib 头文件
    ninc = os.path.join(src, "arm-none-eabi", "include")
    if os.path.isdir(ninc):
        shutil.copytree(ninc, os.path.join(DST, "arm-none-eabi", "include"))
        n += sum(len(f) for _, _, f in os.walk(ninc))

    total = sum(os.path.getsize(os.path.join(r, f))
                for r, _, fs in os.walk(DST) for f in fs)
    print(f"完成：{n} 个文件 → {DST}")
    print(f"体积：{total / 1048576:.1f} MB")


if __name__ == "__main__":
    main()
