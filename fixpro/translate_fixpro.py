# -*- coding: utf-8 -*-
"""把 FiXPro 网页界面汉化：只替换完整文本节点、属性和 JS 完整字符串，
不做子串替换，避免改坏代码。"""
import re, os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "index.html")
EN = os.path.join(BASE, "index.en.html")
JS = os.path.join(BASE, "assets", "fixpro-core.js")

M = {
    # 顶部 / 导航
    "Click to connect device": "点击连接设备",
    "⚡ Connect": "⚡ 连接",
    "Navigation": "导航",
    "Dashboard": "仪表盘",
    "Chip Library": "芯片库",
    "Operations": "操作",
    "Hex Editor": "十六进制编辑器",
    "Script Engine": "脚本引擎",
    "Security": "安全",
    "Settings": "设置",
    "DASHBOARD": "仪表盘",
    "CHIP LIBRARY": "芯片库",
    "OPERATIONS": "操作",
    "HEX EDITOR": "十六进制编辑器",
    "SCRIPT ENGINE": "脚本引擎",
    "SECURITY": "安全",
    "SETTINGS": "设置",
    "FiXPro — Flash iX Pro": "FiXPro — 全能芯片编程器",

    # 仪表盘
    "No Chip Selected": "未选择芯片",
    "Select a chip from the library or use Auto-Detect": "从芯片库中选择芯片，或直接使用自动识别",
    "SELECT CHIP": "选择芯片",
    "◫ Browse Library": "◫ 浏览芯片库",
    "⚡ Auto-Detect": "⚡ 自动识别",
    "▶ Quick Read": "▶ 快速读取",
    "Read ⚡": "读取 ⚡",
    "Write ⚡": "写入 ⚡",
    "Chip": "芯片",
    "Chip / Operation": "芯片 / 操作",
    "Speed": "速度",
    "Speed:": "速度：",
    "Buffer": "缓冲区",
    "Protocol": "协议",
    "Capacity": "容量",
    "Voltage": "电压",
    "Idle": "空闲",
    "Ready": "就绪",
    "Active": "运行中",
    "Busy": "忙碌",
    "ETA:": "剩余：",
    "Processed:": "已处理：",
    "CRC32:": "CRC32：",
    "Transfer Speed": "传输速度",
    "KB/s": "KB/秒",
    "System Monitor": "系统监控",
    "Uptime": "运行时间",
    "Free RAM": "空闲内存",
    "Temp": "温度",
    "MCU Stats": "芯片状态",
    "Activity Log": "活动日志",
    "Not Checked": "未检查",
    "Not Verified": "未校验",
    "Not Computed": "未计算",
    "CRC32 check": "CRC32 校验",
    "Chip vs Buffer Match": "芯片与缓冲区一致性",
    "Buffer integrity": "缓冲区完整性",
    "USB Communication CRC": "USB 通信 CRC",
    "0 chips": "0 个芯片",
    "BLANK": "空白",
    "All 0xFF or 0x00": "全为 FF 或 00",
    "Non-FF:": "非 FF 字节：",

    # 操作按钮
    "READ": "读取",
    "WRITE": "写入",
    "ERASE": "擦除",
    "VERIFY": "校验",
    "DETECT": "检测",
    "Read": "读取",
    "Write": "写入",
    "▶ Main Operations": "▶ 主要操作",
    "▶ Operation Status": "▶ 操作状态",
    "▶ Quick Read": "▶ 快速读取",
    "▶ Run": "▶ 运行",
    "Blank Check": "空白检查",
    "Check if erased": "检查是否已擦除",
    "Chip erase": "整片擦除",
    "Sector erase": "扇区擦除",
    "Erase before write": "写入前先擦除",
    "Verify after write (CRC32)": "写入后校验（CRC32）",
    "Post-write verify": "写入后校验",
    "Fill FF": "填充 FF",
    "Fill 00": "填充 00",
    "Invert": "取反",
    "XOR": "异或",
    "↺ Reset": "↺ 重置",
    "↺ Reset MCU": "↺ 复位芯片",
    "⇌ I2C Scan": "⇌ I2C 扫描",
    "⌕ Find": "⌕ 查找",
    "↵ Go": "↵ 跳转",
    "✕ Cancel": "✕ 取消",
    "✕ Clear": "✕ 清除",
    "⬆ Load": "⬆ 载入",
    "⬆ Load File": "⬆ 载入文件",
    "⬆ Update Firmware": "⬆ 更新固件",
    "⬇ Export": "⬇ 导出",
    "⬇ Save Buffer": "⬇ 保存缓冲区",
    "💾 Save": "💾 保存",
    "📁 File": "📁 文件",
    "✓ Select": "✓ 选择",
    "❓ HELP": "❓ 帮助",
    "⚡ Scan": "⚡ 扫描",
    "⚡ OTP / Unique ID": "⚡ OTP / 唯一 ID",
    "🔑 Fuse Bits (AVR)": "🔑 熔丝位（AVR）",
    "🔒 Write Protection": "🔒 写保护",
    "🔧 MCU / Firmware": "🔧 芯片 / 固件",
    "◈ FiXPro Hardware Control": "◈ FiXPro 硬件控制",
    "⚙ Protocol Config": "⚙ 协议配置",
    "⚡ Performance": "⚡ 性能",
    "◈ Write Options": "◈ 写入选项",
    "⬡ Progress": "⬡ 进度",
    "⬡ Protocol Selection": "⬡ 协议选择",

    # 十六进制编辑器
    "Address:": "地址：",
    "Offset:": "偏移：",
    "Value:": "值：",
    "Cols:": "列数：",
    "Page": "页",
    "Size:": "大小：",
    "Selected:": "已选：",
    "OUTPUT": "输出",
    "Binary": "二进制",
    "All": "全部",

    # 设置 / 安全
    "USB VID:PID": "USB 厂商号:产品号",
    "USB Timeout": "USB 超时",
    "CRC-16/CCITT framing": "CRC-16/CCITT 帧校验",
    "Use DMA transfers": "使用 DMA 传输",
    "DMA Chunk": "DMA 块大小",
    "Dual-core parallel verify": "双核并行校验",
    "Skip blank pages": "跳过空白页",
    "Enable SRP (status reg protect)": "启用状态寄存器保护（SRP）",
    "Lock Bits": "锁定位",
    "Fuse Low": "低位熔丝",
    "Fuse High": "高位熔丝",
    "Fuse Ext": "扩展熔丝",
    "OTP Security Register": "OTP 安全寄存器",
    "One-Time Programmable area": "一次性可编程区",
    "Status Reg Protect (SRP/SRL)": "状态寄存器保护（SRP/SRL）",
    "Status Reg WEL Bit": "状态寄存器 WEL 位",
    "Write Enable Latch": "写使能锁存（WEL）",
    "Block Protection Bits": "块保护位",
    "BP0-BP3 in Status Reg": "状态寄存器中的 BP0-BP3",
    "Hardware Write Protect (WP#)": "硬件写保护（WP#）",
    "Physical WP pin state": "WP 引脚实际电平",
    "Permanent lock protection": "永久锁定保护",
    "Check write protection": "检查写保护状态",

    # 芯片库表头
    "Manufacturer / Name": "厂商 / 型号",
    "Page Size": "页大小",
    "Sector Size": "扇区大小",
    "JEDEC / ID": "JEDEC / ID",
    "JEDEC ID": "JEDEC ID",
    "Unique ID / UID": "唯一 ID / UID",
    "I/O Voltages": "I/O 电压",
    "CPU Core": "CPU 内核",
    "MCU Type": "芯片类型",

    # 协议名（保留专有名词，补中文）
    "ARM Cortex debug": "ARM Cortex 调试口",
    "ARM, FPGA, RISC-V": "ARM、FPGA、RISC-V",
    "ATmega / ATtiny": "ATmega / ATtiny",
    "AVR Read Signature": "AVR 读签名",
    "AVR ISP": "AVR ISP",
    "Bootloader / AVR": "Bootloader / AVR",
    "BIOS Firmware Hub": "BIOS 固件中心",
    "FWH support": "FWH 支持",
    "NAND support": "NAND 支持",
    "Serial Flash Discoverable Parameters": "串行 Flash 参数表（SFDP）",
    "SFDP (Flash Parameters)": "SFDP（Flash 参数）",
    "Custom SPI Transfer": "自定义 SPI 传输",
    "SPI Read JEDEC ID": "SPI 读 JEDEC ID",
    "SPI Read Status Reg": "SPI 读状态寄存器",
    "SPI Chip Erase": "SPI 整片擦除",
    "SPI Mode": "SPI 模式",
    "SPI Speed": "SPI 速度",
    "I²C Speed": "I²C 速度",
    "JTAG Speed": "JTAG 速度",
    "JTAG Read IDCODE": "JTAG 读 IDCODE",
    "SWD Read DP": "SWD 读调试端口",
    "I²C Bus Scan": "I²C 总线扫描",
    "1-Wire Search ROM": "1-Wire 搜索 ROM",
    "High Voltage Prog": "高压编程",
    "Pin Mapping (ZIF)": "引脚映射（ZIF 座）",
    "Overclock MCU (200 MHz)": "超频芯片（200 MHz）",
    "Recommended MCU • Open": "推荐芯片 · 开源",
    "RP2040 (Recommended)": "RP2040（推荐）",

    # 脚本引擎
    "SCRIPT // JavaScript API": "脚本 // JavaScript API",
    "FiXPro Script Engine ready. Select a template or write your own script.":
        "FiXPro 脚本引擎已就绪。可以选一个模板，或者直接写你自己的脚本。",
    "— Load Template —": "— 载入模板 —",

    # 页脚 / 其他
    "FiXPro v2.1.0 • Open Source • GPL-3.0": "FiXPro v2.1.0 · 开源 · GPL-3.0",
    "Recommended MCU • Open Source": "推荐芯片 · 开源",
    "Open Source": "开源",
    "Not Applicable": "不适用",
    "Disabled": "已禁用",
    "Firmware": "固件",
    "MODAL": "弹窗",
    "s": "秒",
    "M only": "仅主设备",

    # 原文里混进的乌克兰语（来自 4pda 论坛的实测数据）
    "RP2040 PIO — всі протоколи в залізі": "RP2040 PIO——所有协议都做在硬件里",
    "Джерело: 4pda.to/forum — реальні заміри": "数据来源：4pda.to 论坛实测",
    "🔬 Реальні бенчмарки — DCProgrammer 0.9.8.1": "🔬 实测数据 — DCProgrammer 0.9.8.1",
    "до 62.5 MHz PIO": "最高 62.5 MHz（PIO）",
}


def apply_pairs(text):
    """替换完整文本节点、属性值、JS 字符串字面量。"""
    n = 0
    for en, zh in M.items():
        # 1) 文本节点：>TEXT<
        pat = re.compile(r">(\s*)" + re.escape(en) + r"(\s*)<")
        text, k = pat.subn(lambda m: ">" + m.group(1) + zh + m.group(2) + "<", text)
        n += k
        # 2) 属性值 title="..." placeholder="..." aria-label="..."
        pat2 = re.compile(r'((?:title|placeholder|aria-label)=")' + re.escape(en) + r'(")')
        text, k = pat2.subn(lambda m: m.group(1) + zh + m.group(2), text)
        n += k
        # 3) JS 字符串
        for q in ('"', "'"):
            pat3 = re.compile(re.escape(q) + re.escape(en) + re.escape(q))
            text, k = pat3.subn(q + zh + q, text)
            n += k
    return text, n


def main():
    if not os.path.exists(EN):
        shutil.copyfile(SRC, EN)
        print("已备份原文 -> index.en.html")

    html = open(SRC, encoding="utf-8").read()
    html, n1 = apply_pairs(html)

    # 语言切换按钮（右上角浮动）
    toggle = ('<a href="index.en.html" id="langSwitch" '
              'style="position:fixed;right:14px;bottom:14px;z-index:9999;'
              'padding:8px 14px;border-radius:8px;background:#1d4ed8;color:#fff;'
              'font:600 12px/1 -apple-system,system-ui,sans-serif;text-decoration:none;'
              'box-shadow:0 4px 14px rgba(0,0,0,.28)">English</a>')
    if "id=\"langSwitch\"" not in html:
        html = html.replace("</body>", toggle + "\n</body>")

    open(SRC, "w", encoding="utf-8").write(html)
    print(f"index.html 替换 {n1} 处")

    js = open(JS, encoding="utf-8").read()
    js2, n2 = apply_pairs(js)
    if n2:
        shutil.copyfile(JS, JS + ".en.bak")
        open(JS, "w", encoding="utf-8").write(js2)
    print(f"fixpro-core.js 替换 {n2} 处")

    # 残留检查
    left = []
    body = re.sub(r"<script[\s\S]*?</script>", "", html)
    body = re.sub(r"<style[\s\S]*?</style>", "", body)
    for t in set(re.findall(r">([^<>]{3,60})<", body)):
        t = t.strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z ,.'/&\-()]{4,}", t):
            left.append(t)
    print("仍为纯英文的文本节点:", len(left))
    for t in sorted(left):
        print("   ", t)


if __name__ == "__main__":
    main()
