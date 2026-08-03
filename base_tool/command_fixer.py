"""命令预校验与自动修复模块。

从 dispatch.py 拆分而来，负责：
- 检测并修复已知的问题命令模式
- findstr / wmic / 批处理语法修复
- CMD 命令转 PowerShell
- PowerShell 环境变量修正
"""
from __future__ import annotations

import os
import re

from logger import get_module_logger

logger = get_module_logger("ToolDispatch")


def _detect_and_fix_command(command: str) -> tuple:
    """检测并自动修复命令中的已知问题模式。
    
    返回 (fixed_command, error_message):
    - (fixed_command, ""): 修复成功，返回修复后的命令
    - ("", error_message): 检测到不可修复的问题模式，返回错误提示
    - (command, ""): 无需修复，返回原命令
    """
    if not command:
        return command, ""
    
    # 1. 检测并转换 findstr /C:"..." 模式
    fixed, msg = _fix_findstr_quotes(command)
    if fixed is not None:
        return fixed, msg
    
    # 2. 检测并转换 wmic 命令
    fixed, msg = _fix_wmic_command(command)
    if fixed is not None:
        return fixed, msg
    
    # 3. 检测 %% 批处理语法（不可修复，直接报错）
    if _has_batch_variable_syntax(command):
        return "", "错误: 检测到批处理变量语法 (%%)。请改用 PowerShell 语法：使用 $variable 替代 %%a，使用 ForEach-Object 替代 for /f 循环。"
    
    # 4. 检测并转换常见 CMD 命令为 PowerShell 等效命令
    fixed, msg = _fix_cmd_to_powershell(command)
    if fixed is not None:
        return fixed, msg
    
    return command, ""


def _fix_findstr_quotes(command: str) -> tuple:
    """检测 findstr /C:"..." 模式并转换为 PowerShell Select-String。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 findstr /C:"..." 或 findstr /C:'...'
    # 例如: systeminfo | findstr /C:"OS Name"
    pattern = r'(\S+)\s*\|\s*findstr\s+((?:/[^ ]+\s+)*)/C:("([^"]*?)"|\'([^\']*?)\')'
    match = re.search(pattern, command, re.IGNORECASE)
    
    if match:
        before_pipe = match.group(1).strip()
        findstr_args = match.group(2).strip()  # /B /C:... 等参数
        search_pattern = match.group(4) or match.group(5)  # 引号内的内容
        
        # 分析 findstr 参数，转换为 Select-String 等效参数
        select_string_args = []
        
        # 提取搜索模式
        if search_pattern:
            # 检查是否是 /C: 格式的属性名匹配（如 "OS Name"、"System Type"）
            # 这种模式通常用于 systeminfo/wmic 输出过滤
            # 转换为 PowerShell 的 Where-Object 或 Select-String
            select_string_args.append(f"Select-String -Pattern '{search_pattern}'")
        
        # 构建 PowerShell 命令
        fixed = f"powershell {before_pipe} | {' '.join(select_string_args)}"
        return fixed, ""
    
    return None, None


def _fix_wmic_command(command: str) -> tuple:
    """检测 wmic 命令并转换为 Get-CimInstance 等效命令。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 wmic 命令: wmic <class> get <properties>
    pattern = r'wmic\s+(\w+)\s+get\s+(.+?)(?:\s*$|\s*&&|\s*2>|\s*>)'
    match = re.search(pattern, command, re.IGNORECASE)
    
    if match:
        wmic_class = match.group(1).strip()
        properties = match.group(2).strip().rstrip(',').strip()
        
        # 映射常见 WMIC 类到 CIM 类
        cim_class_map = {
            'cpu': 'Win32_Processor',
            'os': 'Win32_OperatingSystem',
            'memorychip': 'Win32_PhysicalMemory',
            'baseboard': 'Win32_BaseBoard',
            'bios': 'Win32_BIOS',
            'diskdrive': 'Win32_DiskDrive',
            'logicaldisk': 'Win32_LogicalDisk',
            'nic': 'Win32_NetworkAdapter',
            'nicconfig': 'Win32_NetworkAdapterConfiguration',
            'useraccount': 'Win32_UserAccount',
            'group': 'Win32_Group',
            'service': 'Win32_Service',
            'process': 'Win32_Process',
            'computersystem': 'Win32_ComputerSystem',
            'share': 'Win32_Share',
        }
        
        # 属性名映射
        prop_map = {
            'name': 'Name',
            'numberofcores': 'NumberOfCores',
            'numberoflogicalprocessors': 'NumberOfLogicalProcessors',
            'maxclockspeed': 'MaxClockSpeed',
            'caption': 'Caption',
            'version': 'Version',
            'serialnumber': 'SerialNumber',
            'manufacturer': 'Manufacturer',
            'model': 'Model',
            'capacity': 'Capacity',
            'speed': 'Speed',
            'size': 'Size',
            'freespace': 'FreeSpace',
            'description': 'Description',
            'status': 'Status',
            'state': 'State',
        }
        
        cim_class = cim_class_map.get(wmic_class.lower(), f'Win32_{wmic_class.title()}')
        
        # 转换属性名
        ps_props = []
        for prop in properties.split(','):
            prop = prop.strip()
            ps_prop = prop_map.get(prop.lower(), prop)
            ps_props.append(ps_prop)
        
        fixed = f"powershell Get-CimInstance {cim_class} | Select-Object {', '.join(ps_props)}"
        return fixed, ""
    
    return None, None


def _has_batch_variable_syntax(command: str) -> bool:
    """检测命令是否包含 %% 批处理变量语法。"""
    import re
    # 匹配 %%a, %%A, %%i 等批处理变量
    return bool(re.search(r'%%[a-zA-Z]', command))


def _fix_cmd_to_powershell(command: str) -> tuple:
    """检测常见 CMD 命令并转换为 PowerShell 等效命令。
    
    返回 (fixed_command, "") 或 None 表示无需处理。
    """
    import re
    
    # 匹配 systeminfo 命令
    if re.match(r'^systeminfo\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,TotalVisibleMemorySize,FreePhysicalMemory; Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,TotalPhysicalMemory; Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors", ""
    
    # 匹配 whoami 命令
    if re.match(r'^whoami\s*$', command.strip(), re.IGNORECASE):
        return "powershell [System.Security.Principal.WindowsIdentity]::GetCurrent().Name", ""
    
    # 匹配 hostname 命令
    if re.match(r'^hostname\s*$', command.strip(), re.IGNORECASE):
        return "powershell $env:COMPUTERNAME", ""
    
    # 匹配 ipconfig 命令
    if re.match(r'^ipconfig\s*(?:/all)?\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-NetIPAddress | Select-Object InterfaceAlias,IPAddress,AddressFamily,PrefixLength", ""
    
    # 匹配 tasklist 命令
    if re.match(r'^tasklist\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-Process | Select-Object Name,Id,WorkingSet64,CPU | Sort-Object WorkingSet64 -Descending", ""
    
    # 匹配 netstat 命令
    if re.match(r'^netstat\s*(?:-an|-ano)?\s*$', command.strip(), re.IGNORECASE):
        return "powershell Get-NetTCPConnection | Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State | Sort-Object LocalPort", ""
    
    return None, None


def _should_use_powershell(command: str) -> bool:
    """判断命令是否应该使用 PowerShell 执行。
    
    返回 True 如果命令应该用 PowerShell 执行，否则 False。
    """
    # 已经是 PowerShell 命令
    if command.lower().startswith("powershell"):
        return True
    
    # Python 命令不用 PowerShell
    cmd_lower = command.lower().strip()
    if cmd_lower.startswith("python") or cmd_lower.endswith(".py"):
        return False
    
    # 检测是否包含 PowerShell 特有语法
    powershell_patterns = [
        r'\bGet-\w+',      # Get- 开头的 cmdlet
        r'\bSet-\w+',      # Set- 开头的 cmdlet
        r'\bSelect-\w+',   # Select- 开头的 cmdlet
        r'\bWhere-\w+',    # Where- 开头的 cmdlet
        r'\bForEach-Object\b',
        r'\bSort-Object\b',
        r'\|',             # 管道符（PowerShell 管道更可靠）
        r'\$env:',         # 环境变量引用
        r'\[System\.',     # .NET 类型引用
    ]
    
    for pattern in powershell_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    
    return False


def _fix_powershell_env_variables(command: str) -> str:
    """
    修正 PowerShell 命令中的环境变量引用。

    将 $env:TEMP 替换为实际路径，将 $env:USERPROFILE 替换为实际路径。
    """
    import re

    fixed_command = command

    # 替换 $env:TEMP
    if "$env:TEMP" in command or "$env:temp" in command:
        temp_path = os.environ.get("TEMP", os.environ.get("TMP", ""))
        if temp_path:
            # 使用 lambda 函数避免路径中的反斜杠被解释为正则表达式转义
            fixed_command = re.sub(
                r'\$env:TEMP',
                lambda m: temp_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:USERPROFILE
    if "$env:USERPROFILE" in command or "$env:userprofile" in command:
        userprofile_path = os.environ.get("USERPROFILE", "")
        if userprofile_path:
            fixed_command = re.sub(
                r'\$env:USERPROFILE',
                lambda m: userprofile_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:APPDATA
    if "$env:APPDATA" in command or "$env:appdata" in command:
        appdata_path = os.environ.get("APPDATA", "")
        if appdata_path:
            fixed_command = re.sub(
                r'\$env:APPDATA',
                lambda m: appdata_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    # 替换 $env:LOCALAPPDATA
    if "$env:LOCALAPPDATA" in command or "$env:localappdata" in command:
        localappdata_path = os.environ.get("LOCALAPPDATA", "")
        if localappdata_path:
            fixed_command = re.sub(
                r'\$env:LOCALAPPDATA',
                lambda m: localappdata_path,
                fixed_command,
                flags=re.IGNORECASE
            )

    return fixed_command
