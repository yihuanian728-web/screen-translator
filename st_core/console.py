"""控制台编码处理。

中文版 Windows 的控制台默认用 GBK，直接 print 一些符号（比如 emoji）会抛
UnicodeEncodeError 把程序打挂。这里统一把输出流的 errors 改成 replace，
遇到打不出来的字符就显示成 ?，不至于崩。
"""

from __future__ import annotations

import sys


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # 保留原编码，只是不再抛异常
        except Exception:
            pass
