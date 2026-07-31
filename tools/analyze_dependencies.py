"""
依赖分析工具
分析项目中实际使用的Python模块，与requirements.txt对比，识别冗余依赖
"""
import ast
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List, Tuple


def analyze_imports(project_dir: str) -> Dict[str, int]:
    """
    分析项目中所有Python文件的导入语句
    
    Args:
        project_dir: 项目根目录路径
        
    Returns:
        Dict[str, int]: 模块名到导入次数的映射
    """
    imports = defaultdict(int)
    project_path = Path(project_dir)
    
    # 需要排除的目录
    exclude_dirs = {
        '.venv', 'venv', '.env', '__pycache__', 'build', 'dist',
        'PersonalData', '.git', '.idea', '.trae', '.codegraph'
    }
    
    # 遍历所有.py文件
    for py_file in project_path.rglob('*.py'):
        # 跳过排除目录
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue
        
        try:
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                
            # 解析Python文件
            tree = ast.parse(content, filename=str(py_file))
            
            # 遍历AST节点
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    # import xxx
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]  # 只取顶层模块
                        imports[module_name] += 1
                        
                elif isinstance(node, ast.ImportFrom):
                    # from xxx import yyy
                    if node.module:
                        module_name = node.module.split('.')[0]  # 只取顶层模块
                        imports[module_name] += 1
                        
        except SyntaxError as e:
            print(f"语法错误: {py_file}: {e}")
        except Exception as e:
            print(f"处理文件失败: {py_file}: {e}")
    
    return dict(imports)


def parse_requirements(requirements_file: str) -> Dict[str, str]:
    """
    解析requirements.txt文件
    
    Args:
        requirements_file: requirements.txt文件路径
        
    Returns:
        Dict[str, str]: 包名到版本要求的映射
    """
    requirements = {}
    
    with open(requirements_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue
            
            # 解析包名和版本
            # 支持格式: package, package==1.0, package>=1.0, package~=1.0
            for sep in ['==', '>=', '<=', '~=', '>', '<']:
                if sep in line:
                    package, version = line.split(sep, 1)
                    requirements[package.strip().lower()] = f"{sep}{version.strip()}"
                    break
            else:
                # 没有版本要求
                requirements[line.lower()] = ''
    
    return requirements


def normalize_package_name(package: str) -> str:
    """
    标准化包名（处理包名与导入名不一致的情况）
    
    Args:
        package: 包名
        
    Returns:
        str: 标准化后的导入名
    """
    # 常见的包名到导入名映射
    package_to_import = {
        'pillow': 'PIL',
        'python-docx': 'docx',
        'python-pptx': 'pptx',
        'pyyaml': 'yaml',
        'opencv-python': 'cv2',
        'opencv-python-headless': 'cv2',
        'scikit-learn': 'sklearn',
        'pyautogui': 'pyautogui',
        'pywin32': 'win32api',
        'protobuf': 'google.protobuf',
        'msgpack': 'msgpack',
    }
    
    return package_to_import.get(package.lower(), package)


def analyze_dependencies(project_dir: str, requirements_file: str) -> dict:
    """
    完整的依赖分析
    
    Args:
        project_dir: 项目根目录
        requirements_file: requirements.txt文件路径
        
    Returns:
        dict: 分析结果
    """
    # 分析实际导入
    imports = analyze_imports(project_dir)
    
    # 解析requirements
    requirements = parse_requirements(requirements_file)
    
    # 标准化包名
    normalized_requirements = {
        normalize_package_name(pkg): (pkg, version)
        for pkg, version in requirements.items()
    }
    
    # 识别未使用的依赖
    unused_dependencies = []
    for import_name, (package, version) in normalized_requirements.items():
        if import_name not in imports:
            unused_dependencies.append(package)
    
    # 识别缺失的依赖（代码中导入但未在requirements中）
    missing_dependencies = []
    normalized_imports = set()
    for module in imports.keys():
        normalized_imports.add(module)
    
    for module in normalized_imports:
        if module not in normalized_requirements and module not in ['os', 'sys', 'json', 'time', 'datetime', 'pathlib', 'typing', 'collections', 'itertools', 'functools', 'logging', 'argparse', 'threading', 'multiprocessing', 'subprocess', 'tempfile', 'shutil', 'copy', 're', 'math', 'random', 'hashlib', 'io', 'abc', 'contextlib', 'dataclasses', 'enum', 'traceback', 'warnings']:
            # 排除标准库模块
            missing_dependencies.append(module)
    
    return {
        'imports': imports,
        'requirements': requirements,
        'unused_dependencies': sorted(unused_dependencies),
        'missing_dependencies': sorted(missing_dependencies),
        'import_count': len(imports),
        'requirement_count': len(requirements),
    }


def print_analysis_report(analysis: dict):
    """
    打印分析报告
    
    Args:
        analysis: 分析结果
    """
    print("=" * 80)
    print("依赖分析报告")
    print("=" * 80)
    print()
    
    # 统计信息
    print(f"【统计信息】")
    print(f"  实际导入模块数: {analysis['import_count']}")
    print(f"  requirements.txt包数: {analysis['requirement_count']}")
    print()
    
    # 未使用的依赖
    if analysis['unused_dependencies']:
        print(f"【未使用的依赖】({len(analysis['unused_dependencies'])}个)")
        for package in analysis['unused_dependencies']:
            print(f"  - {package}")
        print()
    
    # 缺失的依赖
    if analysis['missing_dependencies']:
        print(f"【缺失的依赖】({len(analysis['missing_dependencies'])}个)")
        for module in analysis['missing_dependencies'][:20]:  # 只显示前20个
            print(f"  - {module}")
        if len(analysis['missing_dependencies']) > 20:
            print(f"  ... 还有 {len(analysis['missing_dependencies']) - 20} 个")
        print()
    
    # 最常用的模块
    print(f"【最常用的模块 TOP 20】")
    sorted_imports = sorted(analysis['imports'].items(), key=lambda x: x[1], reverse=True)
    for module, count in sorted_imports[:20]:
        print(f"  {module:30s} {count:5d} 次")
    print()
    
    print("=" * 80)


def analyze_specific_modules(project_dir: str, modules: List[str]) -> Dict[str, List[str]]:
    """
    分析特定模块的使用情况
    
    Args:
        project_dir: 项目根目录
        modules: 要分析的模块列表
        
    Returns:
        Dict[str, List[str]]: 模块到使用文件列表的映射
    """
    result = {}
    project_path = Path(project_dir)
    
    # 需要排除的目录
    exclude_dirs = {
        '.venv', 'venv', '.env', '__pycache__', 'build', 'dist',
        'PersonalData', '.git', '.idea', '.trae', '.codegraph'
    }
    
    for module in modules:
        files = []
        
        for py_file in project_path.rglob('*.py'):
            if any(excluded in py_file.parts for excluded in exclude_dirs):
                continue
            
            try:
                with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # 检查是否导入该模块
                if f'import {module}' in content or f'from {module}' in content:
                    # 获取相对路径
                    rel_path = py_file.relative_to(project_path)
                    files.append(str(rel_path))
                    
            except Exception:
                pass
        
        result[module] = files
    
    return result


if __name__ == '__main__':
    import sys
    
    # 项目根目录
    project_dir = Path(__file__).parent.parent.absolute()
    requirements_file = project_dir / 'requirements.txt'
    
    print(f"项目目录: {project_dir}")
    print(f"requirements文件: {requirements_file}")
    print()
    
    # 执行完整分析
    analysis = analyze_dependencies(str(project_dir), str(requirements_file))
    print_analysis_report(analysis)
    
    # 分析特定模块的使用情况
    print("\n分析特定模块的使用情况:")
    specific_modules = ['scipy', 'pandas', 'cv2', 'PySide6', 'matplotlib', 'PIL']
    
    module_usage = analyze_specific_modules(str(project_dir), specific_modules)
    
    for module, files in module_usage.items():
        print(f"\n{module} 使用情况:")
        if files:
            for file in files[:10]:  # 只显示前10个文件
                print(f"  - {file}")
            if len(files) > 10:
                print(f"  ... 还有 {len(files) - 10} 个文件")
        else:
            print("  未找到使用")