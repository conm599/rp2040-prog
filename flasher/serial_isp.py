"""STM32 串口 ISP（AN3155 bootloader 协议）最小实现。

用途：SWD 走不通时的备用通道。要求目标板 BOOT0=1 并复位过，串口接到 USART1（PA9/PA10）。

注意：串口 ISP 只能烧写，不能调试；烧完要把 BOOT0 拨回 0 再复位，程序才会跑。
"""
import time

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

ACK = 0x79
NACK = 0x1F

CMD_GET = 0x00
CMD_GET_VERSION = 0x01
CMD_GET_ID = 0x02
CMD_READ = 0x11
CMD_GO = 0x21
CMD_WRITE = 0x31
CMD_ERASE = 0x43
CMD_EXT_ERASE = 0x44


class IspError(Exception):
    pass


class Stm32Isp:
    def __init__(self, port, baud=115200):
        if serial is None:
            raise IspError("没有安装 pyserial")
        # ST 官方推荐 8 位数据 + 偶校验 + 1 停止位
        self.ser = serial.Serial(port=port, baudrate=baud, bytesize=8,
                                 parity=serial.PARITY_EVEN, stopbits=1,
                                 timeout=2, write_timeout=2)
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    # ---------------------------------------------------------------- 基础
    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _read_exact(self, n, timeout=2.0):
        deadline = time.time() + timeout
        buf = b""
        while len(buf) < n and time.time() < deadline:
            chunk = self.ser.read(n - len(buf))
            if chunk:
                buf += chunk
                deadline = time.time() + timeout
        if len(buf) < n:
            raise IspError(f"等待 {n} 字节超时，只收到 {buf.hex() or '空'}")
        return buf

    def _wait_ack(self, timeout=2.0):
        b = self._read_exact(1, timeout)[0]
        if b == NACK:
            raise IspError("芯片返回 NACK（命令被拒绝，可能是地址越界或未解锁）")
        if b != ACK:
            raise IspError(f"期望 ACK(0x79)，收到 0x{b:02X}")
        return True

    def _send_cmd(self, cmd):
        self.ser.write(bytes([cmd]))
        self.ser.flush()
        self._wait_ack()

    @staticmethod
    def _xor(data):
        v = 0
        for b in data:
            v ^= b
        return v

    # ---------------------------------------------------------------- 协议
    def sync(self, attempts=3):
        """发 0x7F 握手。失败通常意味着 BOOT0 没拨到 1，或没复位过。"""
        last = None
        for _ in range(attempts):
            self.ser.reset_input_buffer()
            self.ser.write(b"\x7f")
            self.ser.flush()
            try:
                b = self._read_exact(1, 1.0)[0]
                if b == ACK:
                    return True
                last = f"收到 0x{b:02X}（期望 0x79）"
            except IspError as e:
                last = str(e)
            time.sleep(0.15)
        raise IspError(
            "握手失败：" + str(last) + "。检查 BOOT0 是否拨到 1 并复位过、"
            "TX/RX 是否交叉（模块 TX→PA10、模块 RX→PA9）、是否共地、波特率是否 115200")

    def get(self):
        """读取 bootloader 版本与支持的命令。"""
        self._send_cmd(CMD_GET)
        n = self._read_exact(1)[0]
        payload = self._read_exact(n + 1)
        self._wait_ack()
        version = payload[0]
        cmds = list(payload[1:])
        return {"version": f"{version >> 4}.{version & 0x0F}", "commands": cmds}

    def get_id(self):
        self._send_cmd(CMD_GET_ID)
        n = self._read_exact(1)[0]
        data = self._read_exact(n + 1)
        self._wait_ack()
        return int.from_bytes(data[1:], "big")

    def erase_all(self):
        """全片擦除（0x43 + 0xFF 0x00）。"""
        self._send_cmd(CMD_ERASE)
        self.ser.write(b"\xff\x00")
        self.ser.flush()
        self._wait_ack(timeout=15.0)

    def write(self, addr, data, chunk=256, progress=None):
        """按 256 字节一块写入。最后一块补 0xFF 对齐。"""
        total = len(data)
        written = 0
        while written < total:
            part = data[written:written + chunk]
            if len(part) < chunk:
                part = part + b"\xFF" * (chunk - len(part))

            self._send_cmd(CMD_WRITE)
            a = (addr + written).to_bytes(4, "big")
            self.ser.write(a + bytes([self._xor(a)]))
            self.ser.flush()
            self._wait_ack()

            body = bytes([len(part) - 1]) + part
            self.ser.write(body + bytes([self._xor(body)]))
            self.ser.flush()
            self._wait_ack(timeout=5.0)

            written += chunk
            if progress:
                progress(min(written, total), total)

    def read(self, addr, length, chunk=256):
        """读回数据，用于校验。"""
        out = bytearray()
        pos = 0
        while pos < length:
            n = min(chunk, length - pos)
            self._send_cmd(CMD_READ)
            a = (addr + pos).to_bytes(4, "big")
            self.ser.write(a + bytes([self._xor(a)]))
            self.ser.flush()
            self._wait_ack()

            body = bytes([n - 1, 0xFF ^ (n - 1)])
            self.ser.write(body)
            self.ser.flush()
            self._wait_ack()
            out += self._read_exact(n, timeout=5.0)
            pos += n
        return bytes(out)

    def go(self, addr):
        self._send_cmd(CMD_GO)
        a = addr.to_bytes(4, "big")
        self.ser.write(a + bytes([self._xor(a)]))
        self.ser.flush()
        self._wait_ack()
