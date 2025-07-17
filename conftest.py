"""pytest配置文件 - 实现run_script fixture和--merged flag"""
import pytest
import subprocess
import sys
from pathlib import Path
import shutil

# 项目根目录
ROOT = Path(__file__).parent

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
                result = subprocess.run(
                    cmd,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=True
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
        
        # 运行脚本
        cmd = [sys.executable, str(script_path)]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=script_path.parent
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