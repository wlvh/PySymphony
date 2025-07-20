"""
测试Issue #37: 合并脚本的静态审计失败问题

本测试专门验证advanced_merge.py生成的代码能否通过ASTAuditor的检查
"""

import ast
import tempfile
import pytest
from pathlib import Path

from scripts.advanced_merge import AdvancedCodeMerger
from pysymphony.auditor.auditor import ASTAuditor


class TestIssue37AuditFailures:
    """测试合并后代码的静态审计问题"""

    def test_duplicate_mod_imports(self, tmp_path):
        """测试重复的_mod导入问题"""
        # 创建测试文件结构
        pkg_dir = tmp_path / "test_pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        
        # module_a.py - 导入json
        module_a = pkg_dir / "module_a.py"
        module_a.write_text("""
import json

def func_a():
    return json.dumps({"a": 1})
""")
        
        # module_b.py - 也导入json
        module_b = pkg_dir / "module_b.py"
        module_b.write_text("""
import json

def func_b():
    return json.dumps({"b": 2})
""")
        
        # main.py - 使用两个模块
        main_script = tmp_path / "main.py"
        main_script.write_text("""
from test_pkg.module_a import func_a
from test_pkg.module_b import func_b

def main():
    print(func_a())
    print(func_b())

if __name__ == "__main__":
    main()
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmp_path)
        merged_content = merger.merge_script(main_script)
        
        # 解析合并后的AST
        merged_ast = ast.parse(merged_content)
        
        # 使用ASTAuditor检查
        auditor = ASTAuditor()
        audit_result = auditor.audit(merged_ast)
        
        # 应该通过审计（修复后）
        assert audit_result is True, f"ASTAuditor发现错误:\n{auditor.get_report()}"
        
        # 检查没有重复的_mod导入
        imports = [node for node in merged_ast.body if isinstance(node, ast.Import)]
        json_mod_count = sum(1 for imp in imports 
                            for alias in imp.names 
                            if alias.asname and 'json' in alias.asname and '_mod' in alias.asname)
        assert json_mod_count <= 1, f"发现{json_mod_count}个json__mod导入"

    def test_undefined_loop_variables(self, tmp_path):
        """测试循环变量未定义问题"""
        # 创建测试模块
        module = tmp_path / "loop_module.py"
        module.write_text("""
def process_items(items):
    result = []
    for i, item in enumerate(items):
        # 使用循环变量
        result.append((i, item))
    
    # 列表推导式中的变量
    squares = [x**2 for x in range(10)]
    
    return result, squares
""")
        
        # 主脚本
        main_script = tmp_path / "main_loop.py"
        main_script.write_text("""
from loop_module import process_items

items = ["a", "b", "c"]
result, squares = process_items(items)
print(result)
print(squares)
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmp_path)
        merged_content = merger.merge_script(main_script)
        merged_ast = ast.parse(merged_content)
        
        # 审计检查
        auditor = ASTAuditor()
        audit_result = auditor.audit(merged_ast)
        
        assert audit_result is True, f"循环变量应该被正确识别:\n{auditor.get_report()}"

    def test_store_target_mapping(self, tmp_path):
        """测试赋值目标的名称映射"""
        # 创建有名称冲突的模块
        module_a = tmp_path / "mod_a.py"
        module_a.write_text("""
x = 100
y = 200

def get_x():
    return x

def set_x(value):
    global x
    x = value
""")
        
        module_b = tmp_path / "mod_b.py"
        module_b.write_text("""
x = 300  # 同名变量
y = 400

def get_x_b():
    return x
""")
        
        main_script = tmp_path / "main_store.py"
        main_script.write_text("""
from mod_a import get_x, set_x
from mod_b import get_x_b

print(get_x())
print(get_x_b())
set_x(500)
print(get_x())
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmp_path)
        merged_content = merger.merge_script(main_script)
        merged_ast = ast.parse(merged_content)
        
        # 审计检查
        auditor = ASTAuditor()
        audit_result = auditor.audit(merged_ast)
        
        assert audit_result is True, f"Store目标应该被正确映射:\n{auditor.get_report()}"

    def test_external_import_preservation(self, tmp_path):
        """测试外部导入的保留"""
        # 创建使用多个外部库的模块
        module = tmp_path / "external_module.py"
        module.write_text("""
import os
import sys
import json
from typing import List, Dict
from pathlib import Path

def get_cwd():
    return os.getcwd()

def get_python_version():
    return sys.version

def save_json(data: Dict, path: Path):
    with open(path, 'w') as f:
        json.dump(data, f)
""")
        
        main_script = tmp_path / "main_external.py"
        main_script.write_text("""
from external_module import get_cwd, save_json
from pathlib import Path

cwd = get_cwd()
save_json({"cwd": cwd}, Path("output.json"))
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmp_path)
        merged_content = merger.merge_script(main_script)
        merged_ast = ast.parse(merged_content)
        
        # 审计检查
        auditor = ASTAuditor()
        audit_result = auditor.audit(merged_ast)
        
        assert audit_result is True, f"外部导入应该被正确处理:\n{auditor.get_report()}"
        
        # 验证外部导入存在
        import_names = set()
        for node in merged_ast.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    import_names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                import_names.add(node.module)
        
        assert 'os' in import_names or any('os' in name for name in import_names)
        assert 'sys' in import_names or any('sys' in name for name in import_names)
        assert 'json' in import_names or any('json' in name for name in import_names)

    def test_complex_real_world_scenario(self, tmp_path):
        """测试复杂的真实场景"""
        # 创建一个模拟真实项目的结构
        utils_dir = tmp_path / "utils"
        utils_dir.mkdir()
        (utils_dir / "__init__.py").write_text("")
        
        # config.py
        (utils_dir / "config.py").write_text("""
import json
import os

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}

config = load_config()
""")
        
        # logger.py
        (utils_dir / "logger.py").write_text("""
import logging
import sys

def setup_logger(name):
    logger = logging.getLogger(name)
    handler = logging.StreamHandler(sys.stdout)
    logger.addHandler(handler)
    return logger

logger = setup_logger("app")
""")
        
        # data.py
        (utils_dir / "data.py").write_text("""
import json
from typing import List, Dict

def process_data(items: List[Dict]) -> List[Dict]:
    result = []
    for i, item in enumerate(items):
        # 处理每个项目
        processed = {
            "index": i,
            "original": item,
            "processed": True
        }
        result.append(processed)
    
    # 使用列表推导式
    values = [x["value"] for x in items if "value" in x]
    
    return result

# 模块级变量
data_cache = {}
""")
        
        # main.py
        main_script = tmp_path / "main_complex.py"
        main_script.write_text("""
from utils.config import config
from utils.logger import logger
from utils.data import process_data, data_cache

def main():
    # 使用配置
    logger.info(f"Config: {config}")
    
    # 处理数据
    items = [{"value": i} for i in range(5)]
    result = process_data(items)
    
    # 更新缓存
    data_cache["result"] = result
    
    logger.info(f"Processed {len(result)} items")

if __name__ == "__main__":
    main()
""")
        
        # 执行合并
        merger = AdvancedCodeMerger(tmp_path)
        merged_content = merger.merge_script(main_script)
        merged_ast = ast.parse(merged_content)
        
        # 最关键的测试：ASTAuditor审计
        auditor = ASTAuditor()
        audit_result = auditor.audit(merged_ast)
        
        # 断言没有错误
        assert audit_result is True, f"复杂场景审计失败:\n{auditor.get_report()}"
        
        # 额外验证：编译检查
        try:
            compile(merged_ast, "<merged>", "exec")
        except Exception as e:
            pytest.fail(f"合并后的代码无法编译: {e}")