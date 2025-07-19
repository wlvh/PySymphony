"""pytest配置文件 - 实现run_script fixture和--merged flag"""
import pytest
import subprocess
import sys
import os
from pathlib import Path
import shutil
import warnings
import importlib.util

# 项目根目录
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tests"))

# 导入新的 AST 审计器
from ast_auditor import ASTAuditor, audit_code

def static_check(src: str, path: Path, is_main_script: bool = True):
    """对生成的合并代码进行静态检查 - 使用新的 ASTAuditor"""
    
    # 使用 ASTAuditor 进行全面的静态分析
    audit_result = audit_code(src, filename=str(path), is_main_script=is_main_script)
    
    # 如果有错误，生成详细的错误报告
    if audit_result.has_errors:
        error_report = [f"Static analysis errors in {path}:"]
        for error in audit_result.errors:
            error_report.append(f"  - {error}")
        pytest.fail('\n'.join(error_report))
    
    # 使用 pyflakes API 进行额外的检查（如果可用）
    if importlib.util.find_spec("pyflakes") is not None:
        try:
            from pyflakes import api as pyflakes_api
            from pyflakes.reporter import Reporter
            import io
            
            # 捕获 pyflakes 输出
            output = io.StringIO()
            reporter = Reporter(output, output)
            
            # 运行 pyflakes 检查
            pyflakes_api.check(src, str(path), reporter=reporter)
            
            # 检查是否有错误
            pyflakes_output = output.getvalue()
            if pyflakes_output:
                pytest.fail(f'[pyflakes] static errors in {path}:\n{pyflakes_output}')
                
        except ImportError:
            warnings.warn("pyflakes not installed - skipping additional checks")
    
    # 记录警告（但不失败）
    if audit_result.warnings:
        for warning in audit_result.warnings:
            warnings.warn(f"Static analysis warning: {warning}")

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