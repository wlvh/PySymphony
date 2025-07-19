"""pytest配置文件 - 实现run_script fixture和--merged flag"""
import pytest
import subprocess
import sys
import os
from pathlib import Path
import shutil
import ast
import textwrap
import warnings
import importlib.util

# 项目根目录
ROOT = Path(__file__).parent

def static_check(src: str, path: Path):
    """对生成的合并代码进行静态检查"""
    # 1. 语法检查
    try:
        ast.parse(src)
    except SyntaxError as e:
        pytest.fail(f'Syntax error in {path}: {e}')
    
    # 2. 检查重复的顶级定义和导入
    tree = ast.parse(src)
    top = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            top.setdefault(node.name, []).append(node.lineno)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # 为导入语句生成唯一键
            # Python 3.8 兼容性处理
            try:
                key = ast.unparse(node).replace(' ', '')
            except AttributeError:
                # Python 3.8 fallback - 简单的字符串表示
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                    key = f"import{','.join(names)}"
                else:
                    module = node.module or ''
                    names = [alias.name for alias in node.names]
                    key = f"from{module}import{','.join(names)}"
            top.setdefault(key, []).append(node.lineno)
    
    dupes = {k: v for k, v in top.items() if len(v) > 1}
    if dupes:
        msg = textwrap.indent('\n'.join(f'{k}: lines {v}' for k, v in dupes.items()), '    ')
        pytest.fail(f'Duplicate top-level symbols in {path}:\n{msg}')
    
    # 3. 使用 flake8 进行静态分析
    if importlib.util.find_spec("flake8") is None:
        warnings.warn("flake8 not installed - skipping F-series checks")
    else:
        result = subprocess.run(
            [sys.executable, '-m', 'flake8', '--select=F', '--stdin-display-name', str(path), '-'],
            input=src.encode(),
            capture_output=True
        )
        if result.returncode != 0:
            pytest.fail(f'[flake8] static errors in {path}:\n{result.stdout.decode()}')

def pytest_addoption(parser):
    """添加--merged命令行选项"""
    parser.addoption(
        "--merged",
        action="store_true",
        default=False,
        help="Run tests with merged scripts instead of original scripts"
    )

@pytest.fixture
def run_script(tmp_path, request):
    """运行脚本的fixture，支持--merged选项"""
    merged = request.config.getoption("--merged")
    
    def _run(script_path):
        script_path = Path(script_path)
        if not script_path.is_absolute():
            script_path = ROOT / script_path
        
        if merged:
            # 生成合并后的脚本
            merged_path = tmp_path / f"{script_path.stem}_merged.py"
            
            # 计算相对路径的project_root
            # 对于tests/xxx/yyy.py，project_root应该是tests/xxx
            project_root = script_path.parent
            
            # 调用advanced_merge.py
            merge_script = ROOT / "scripts" / "advanced_merge.py"
            cmd = [sys.executable, str(merge_script), str(script_path), str(project_root)]
            
            try:
                # 设置环境变量，确保能找到 tests 目录
                env = dict(os.environ)
                env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
                
                result = subprocess.run(
                    cmd,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True,
                    env=env
                )
                
                # 查找生成的合并文件
                expected_merged = script_path.parent / f"{script_path.stem}_advanced_merged.py"
                if expected_merged.exists():
                    # 复制到临时目录
                    shutil.copy(expected_merged, merged_path)
                    script_path = merged_path
                else:
                    raise RuntimeError(f"Merged file not found at {expected_merged}")
                    
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Merge failed: {e.stderr}")
            
            # 在执行前进行静态检查（在所有合并路径后）
            code = script_path.read_text('utf-8')
            static_check(code, script_path)
        
        # 运行脚本
        cmd = [sys.executable, str(script_path)]
        # 设置环境变量，确保能找到 tests 目录
        env = dict(os.environ)
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=script_path.parent,
            env=env
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Script execution failed: {result.stderr}")
            
        return result.stdout
    
    return _run

@pytest.fixture(autouse=True)
def cleanup_merged_files():
    """测试后清理生成的合并文件"""
    yield
    
    # 清理所有生成的_advanced_merged.py文件
    for merged_file in ROOT.glob("tests/**/*_advanced_merged.py"):
        merged_file.unlink()