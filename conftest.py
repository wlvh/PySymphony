"""pytest配置文件 - 实现run_script fixture和--merged flag"""
import pytest
import subprocess
import sys
import os
from pathlib import Path
import shutil
import ast
import importlib.util

# 导入 AST 审计器
from pysymphony.auditor import ASTAuditor

# 项目根目录
ROOT = Path(__file__).parent

def static_check(src: str, path: Path):
    """对生成的合并代码进行静态检查 - 使用工业级 AST 审计器"""
    
    # 使用 ASTAuditor 进行全面的多阶段审计
    auditor = ASTAuditor()
    
    if not auditor.audit(src, str(path)):
        # 审计失败，获取详细报告
        report = auditor.get_report()
        pytest.fail(f"静态分析错误 in {path}:\n{report}")
    
    # 补充使用 pyflakes 进行额外检查（性能更好）
    try:
        import pyflakes.api
        import pyflakes.reporter as reporter
        from io import StringIO
        
        # 创建输出流和 reporter
        warnings = StringIO()
        warning_reporter = reporter.Reporter(warnings, warnings)
        
        # 检查代码
        errors_found = pyflakes.api.check(src, str(path), reporter=warning_reporter)
        
        if errors_found:
            pytest.fail(f"[pyflakes] 额外的静态错误 in {path}:\n{warnings.getvalue()}")
            
    except ImportError:
        # 如果 pyflakes 未安装，回退到 flake8
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'flake8', '--select=F', '--stdin-display-name', str(path), '-'],
                input=src.encode(),
                capture_output=True,
                check=True
            )
        except FileNotFoundError:
            pytest.fail("pyflakes 或 flake8 未安装 – 请运行 `pip install -r requirements-dev.txt`")
        except subprocess.CalledProcessError as exc:
            pytest.fail(f"[flake8] 静态错误 in {path}:\n{exc.stdout.decode()}")

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
        else:
            # 即使是原始脚本也进行静态检查（确保质量基线）
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