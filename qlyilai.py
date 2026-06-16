#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
遍历青龙脚本目录下的 .js/.py，提取依赖，检测是否已安装，缺失则自动安装。
用法：
  python3 ql_dep_audit_install.py --roots /ql/data/scripts --install
  python3 ql_dep_audit_install.py --roots /ql/data/scripts /ql/data/repo --dry-run
可选：
  --max-files 2000   限制最多扫描文件数
  --include node_modules __pycache__ dist build  # 额外允许进入的目录（默认会跳过这些）
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Set, Tuple, Dict, List

# -----------------------------
# 可调：一些“应该忽略”的 import/require（内置模块 / 常见误报）
# -----------------------------
PY_STDLIB_LIKE = {
    "os", "sys", "re", "json", "time", "datetime", "math", "random", "hashlib", "hmac",
    "subprocess", "pathlib", "typing", "logging", "base64", "urllib", "http", "itertools",
    "functools", "collections", "threading", "asyncio", "traceback", "uuid", "copy",
    "csv", "sqlite3", "email", "html", "xml", "argparse", "tempfile", "shutil",
}

# Node 内置模块（不需要 npm 安装）
NODE_BUILTIN = {
    "fs", "path", "os", "crypto", "http", "https", "url", "util", "stream", "buffer",
    "child_process", "events", "zlib", "querystring", "timers", "net", "tls", "dns",
    "readline", "worker_threads", "perf_hooks", "assert", "constants", "module",
}

# 常见：import 名 -> pip 包名/ npm 包名（不全，但能减少坑）
PY_IMPORT_TO_PIP = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "Crypto": "pycryptodome",
    "yaml": "PyYAML",
    "requests": "requests",
}

JS_IMPORT_TO_NPM = {
    # 一些脚本里会 require('node-fetch') 但 import 名不会变
    # 这里更多用于“规范化”，不强制
}

# -----------------------------
# 依赖提取（JS）
# -----------------------------
RE_JS_REQUIRE = re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""")
RE_JS_IMPORT_FROM = re.compile(r"""import\s+.+?\s+from\s+['"]([^'"]+)['"]""")
RE_JS_IMPORT_ONLY = re.compile(r"""import\s+['"]([^'"]+)['"]""")
RE_JS_DYNAMIC_IMPORT = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")

# -----------------------------
# 依赖提取（PY）
# -----------------------------
RE_PY_IMPORT = re.compile(r"""^\s*import\s+([a-zA-Z0-9_\.]+)""", re.M)
RE_PY_FROM = re.compile(r"""^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+""", re.M)

# -----------------------------
# 通用：跳过目录
# -----------------------------
DEFAULT_SKIP_DIRS = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".venv", "venv",
    "dist", "build", ".idea", ".vscode",
}


def run_cmd(cmd: List[str], cwd: str | None = None) -> Tuple[int, str, str]:
    p = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = p.communicate()
    return p.returncode, out, err


def is_probably_local_path(spec: str) -> bool:
    # 过滤 ./xxx、../xxx、/abs/path、@/alias、file:、node:、http(s)等
    if spec.startswith(("./", "../", "/", "file:", "node:", "http://", "https://")):
        return True
    return False


def normalize_js_pkg(spec: str) -> str | None:
    """
    把 import/require 里拿到的字符串，归一成 npm 包名
    - 去掉子路径：lodash/get -> lodash
    - 支持 scoped：@scope/pkg/sub -> @scope/pkg
    """
    if not spec or is_probably_local_path(spec):
        return None

    # 过滤一些 alias / bundler 语法
    if spec.startswith(("~", "#")):
        return None

    # scoped 包：@scope/pkg/xxx
    if spec.startswith("@"):
        parts = spec.split("/")
        if len(parts) >= 2:
            return "/".join(parts[:2])
        return None

    # 普通包：pkg/sub/path -> pkg
    return spec.split("/")[0]


def extract_js_deps(text: str) -> Set[str]:
    found: Set[str] = set()
    for pat in (RE_JS_REQUIRE, RE_JS_IMPORT_FROM, RE_JS_IMPORT_ONLY, RE_JS_DYNAMIC_IMPORT):
        for m in pat.findall(text):
            pkg = normalize_js_pkg(m.strip())
            if pkg and pkg not in NODE_BUILTIN:
                found.add(pkg)
    return found


def normalize_py_import(mod: str) -> str | None:
    if not mod:
        return None
    top = mod.split(".")[0]
    # 过滤相对导入：from .xxx import yyy / from ..xxx import yyy
    if top in ("", "."):
        return None
    return top


def extract_py_deps(text: str) -> Set[str]:
    found: Set[str] = set()
    for m in RE_PY_IMPORT.findall(text):
        top = normalize_py_import(m)
        if top:
            found.add(top)
    for m in RE_PY_FROM.findall(text):
        top = normalize_py_import(m)
        if top:
            found.add(top)
    return found


def discover_files(roots: List[str], max_files: int, include_dirs: Set[str]) -> List[Path]:
    files: List[Path] = []
    skip_dirs = DEFAULT_SKIP_DIRS - include_dirs  # include_dirs 允许进入（从 skip 移除）
    for r in roots:
        rp = Path(r).expanduser()
        if not rp.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(rp):
            # 过滤目录
            dirnames[:] = [d for d in dirnames if d not in skip_dirs]
            for fn in filenames:
                if fn.endswith(".js") or fn.endswith(".py"):
                    files.append(Path(dirpath) / fn)
                    if len(files) >= max_files:
                        return files
    return files


def pick_npm_cwd(roots: List[str]) -> str:
    """
    npm 安装的位置很依赖 cwd。
    这里选择第一个存在的 root 作为 npm cwd。
    你也可以改成 /ql/data/scripts 或你实际 node_modules 所在目录。
    """
    for r in roots:
        rp = Path(r)
        if rp.exists():
            return str(rp)
    return os.getcwd()


def npm_is_installed(pkg: str, cwd: str) -> bool:
    # npm ls pkg --depth=0 返回码为0通常表示已安装
    code, out, err = run_cmd(["npm", "ls", pkg, "--depth=0"], cwd=cwd)
    return code == 0


def npm_install(pkgs: List[str], cwd: str) -> bool:
    if not pkgs:
        return True
    # 分批安装，避免命令过长
    ok = True
    batch = 20
    for i in range(0, len(pkgs), batch):
        part = pkgs[i:i+batch]
        cmd = ["npm", "i", "--no-audit", "--no-fund", *part]
        code, out, err = run_cmd(cmd, cwd=cwd)
        if code != 0:
            ok = False
            print(f"[npm] 安装失败：{part}\n{err.strip()}\n", file=sys.stderr)
        else:
            print(f"[npm] 已安装：{', '.join(part)}")
    return ok


def pip_is_installed(import_name: str) -> bool:
    # 用 import 方式检测最通用
    code, out, err = run_cmd([sys.executable, "-c", f"import {import_name}"])
    return code == 0


def pip_install(pkgs: List[str]) -> bool:
    if not pkgs:
        return True
    ok = True
    batch = 20
    for i in range(0, len(pkgs), batch):
        part = pkgs[i:i+batch]
        cmd = [sys.executable, "-m", "pip", "install", *part]
        code, out, err = run_cmd(cmd)
        if code != 0:
            ok = False
            print(f"[pip] 安装失败：{part}\n{err.strip()}\n", file=sys.stderr)
        else:
            print(f"[pip] 已安装：{', '.join(part)}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", default=["/ql/data/scripts"], help="要扫描的根目录（可多个）")
    ap.add_argument("--max-files", type=int, default=3000, help="最多扫描文件数")
    ap.add_argument("--include", nargs="*", default=[], help="额外允许进入的目录（默认会跳过 node_modules 等）")
    ap.add_argument("--dry-run", action="store_true", help="只输出，不安装")
    ap.add_argument("--install", action="store_true", help="发现缺失就安装")
    args = ap.parse_args()

    include_dirs = set(args.include)
    files = discover_files(args.roots, args.max_files, include_dirs)
    if not files:
        print("未找到任何 .js/.py 文件，请检查 --roots 路径")
        return

    js_deps: Set[str] = set()
    py_imports: Set[str] = set()

    # 提取依赖
    for fp in files:
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if fp.suffix == ".js":
            js_deps |= extract_js_deps(text)
        elif fp.suffix == ".py":
            py_imports |= extract_py_deps(text)

    # 过滤 python 内置/常见库
    py_imports = {m for m in py_imports if m not in PY_STDLIB_LIKE}

    # import 名 -> pip 包名（尽力映射）
    py_pip_pkgs = {PY_IMPORT_TO_PIP.get(m, m) for m in py_imports}

    npm_cwd = pick_npm_cwd(args.roots)

    print(f"扫描文件数：{len(files)}")
    print(f"JS 依赖（候选）：{len(js_deps)}  | npm cwd：{npm_cwd}")
    print(f"PY 依赖（候选）：{len(py_imports)}")

    # 检测安装情况
    missing_js = []
    for pkg in sorted(js_deps):
        if pkg in NODE_BUILTIN:
            continue
        installed = npm_is_installed(pkg, cwd=npm_cwd)
        if not installed:
            missing_js.append(pkg)

    missing_py = []
    # 注意：检测用 import 名更靠谱；安装用 pip 包名
    for imp in sorted(py_imports):
        if not pip_is_installed(imp):
            missing_py.append(PY_IMPORT_TO_PIP.get(imp, imp))

    print("\n==== 缺失依赖 ====")
    print(f"JS 缺失：{len(missing_js)}")
    if missing_js:
        print("  " + ", ".join(missing_js))
    print(f"PY 缺失：{len(missing_py)}")
    if missing_py:
        print("  " + ", ".join(missing_py))

    if args.dry_run or not args.install:
        print("\n(dry-run) 未执行安装。若要自动安装：加上 --install")
        return

    # 安装
    print("\n==== 开始安装 ====")
    ok_js = npm_install(missing_js, cwd=npm_cwd)
    ok_py = pip_install(missing_py)

    if ok_js and ok_py:
        print("\n✅ 全部安装完成")
    else:
        print("\n⚠️ 部分安装失败，请看上面的错误输出（常见原因：包名映射不对/网络/权限）")


if __name__ == "__main__":
    main()
