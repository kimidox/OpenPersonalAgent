import sys
import re
from datetime import datetime, timedelta, timezone

# 固定标准格式
OUTPUT_FORMAT = "%Y-%m-%d %H:%M:%S"

def parse_tz(offset_str="+08:00"):
    """从 +08:00 / -05:00 生成 timezone 对象（标准库）"""
    match = re.match(r"([+-])(\d{1,2}):?(\d{2})?", offset_str)
    if not match:
        return timezone(timedelta(hours=8))  # 默认东八区
    sign, hh, mm = match.groups()
    hh = int(hh)
    mm = int(mm) if mm else 0
    delta = timedelta(hours=hh, minutes=mm)
    if sign == "-":
        delta = -delta
    return timezone(delta)

def convert_time(time_input, target_format="datetime", tz_offset="+08:00"):
    tz = parse_tz(tz_offset)

    # 1. 输入是时间戳
    if re.fullmatch(r"-?\d+", time_input.strip()):
        ts = int(time_input.strip())
        # 自动识别毫秒/秒
        if len(str(ts)) >= 13:
            ts = ts // 1000
        dt = datetime.fromtimestamp(ts, tz=tz)
        if target_format == "timestamp":
            return str(int(dt.timestamp()))
        else:
            return dt.strftime(OUTPUT_FORMAT)

    # 2. 输入是时间字符串（自动尝试常见格式）
    s = time_input.strip()
    fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M",
    ]
    dt = None
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    if not dt:
        return "❌ 无法解析时间格式"

    # 绑定时区
    dt = dt.replace(tzinfo=tz)

    if target_format == "timestamp":
        return str(int(dt.timestamp()))
    else:
        return dt.strftime(OUTPUT_FORMAT)

if __name__ == "__main__":
    time_input = sys.argv[1] if len(sys.argv) > 1 else ""
    target_format = sys.argv[2] if len(sys.argv) > 2 else "datetime"
    tz_offset = sys.argv[3] if len(sys.argv) > 3 else "+08:00"
    print(convert_time(time_input, target_format, tz_offset))