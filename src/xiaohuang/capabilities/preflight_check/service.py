"""preflight_check/service.py — startup preflight resource checks.

Checks: memory, STT port, Python env, model cache, logs writability.
No process launch. No STT / LLM / TTS calls. No secrets access.
"""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from typing import Callable

from xiaohuang.capabilities.preflight_check.models import (
    PreflightCheckItem,
    PreflightCheckResult,
)

_DEFAULT_PYTHON_PATH = r"F:\for_xiaohuang\conda310\python.exe"
_DEFAULT_MODEL_CACHE_BASE = Path(r"F:\for_xiaohuang\models\modelscope")
_STT_HOST = "127.0.0.1"
_STT_PORT = 8766

_MEMORY_OK_GB = 6.0
_MEMORY_WARN_GB = 3.0
_VIRTUAL_OK_GB = 8.0
_VIRTUAL_WARN_GB = 4.0

_MODEL_FILES = [
    "models/iic/SenseVoiceSmall/model.pt",
    "models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch/model.pt",
]


def run_preflight_check(
    project_root: Path,
    *,
    python_path: str = _DEFAULT_PYTHON_PATH,
    model_cache_base: Path = _DEFAULT_MODEL_CACHE_BASE,
    stt_host: str = _STT_HOST,
    stt_port: int = _STT_PORT,
    memory_reader: Callable[[], dict | None] | None = None,
) -> PreflightCheckResult:
    items: list[PreflightCheckItem] = []

    items.append(_check_memory((memory_reader or _read_memory)()))
    items.append(_check_stt_port(stt_host, stt_port))
    items.append(_check_python_env(Path(python_path)))
    items.append(_check_model_cache(model_cache_base))
    items.append(_check_logs_writable(project_root))

    has_error = any(item.status == "error" for item in items)
    has_warning = any(item.status == "warning" for item in items)

    if has_error:
        status = "error"
        summary = "环境存在问题，建议修复后再启动。"
    elif has_warning:
        status = "warning"
        summary = "可以启动，但建议先处理警告项。"
    else:
        status = "ok"
        summary = "环境正常，可以启动小黄。"

    return PreflightCheckResult(status=status, summary=summary, items=items)


def _check_memory(mem: dict | None) -> PreflightCheckItem:
    if mem is None:
        return PreflightCheckItem(
            key="memory",
            label="物理内存",
            status="warning",
            message="无法读取物理内存信息。",
            suggestion="请检查系统内存状态。",
        )

    free_gb = mem.get("free_physical_gb", 0.0)
    free_virtual_gb = mem.get("free_virtual_gb", 0.0)

    if free_gb >= _MEMORY_OK_GB and free_virtual_gb >= _VIRTUAL_OK_GB:
        return PreflightCheckItem(
            key="memory",
            label="物理内存",
            status="ok",
            message=f"可用物理内存 {free_gb:.1f}GB，虚拟内存 {free_virtual_gb:.1f}GB。",
            details={"free_physical_gb": free_gb, "free_virtual_gb": free_virtual_gb},
        )

    if free_gb < _MEMORY_WARN_GB or free_virtual_gb < _VIRTUAL_WARN_GB:
        parts = []
        if free_gb < _MEMORY_WARN_GB:
            parts.append(f"可用物理内存仅 {free_gb:.1f}GB，严重偏低。")
        if free_virtual_gb < _VIRTUAL_WARN_GB:
            parts.append(f"可用虚拟内存仅 {free_virtual_gb:.1f}GB，偏低。")
        return PreflightCheckItem(
            key="memory",
            label="物理内存",
            status="error",
            message=" ".join(parts),
            suggestion="建议关闭 Chrome / VSCode / Claude Code / 其他大内存程序后重试；如果仍失败，可增加 Windows 虚拟内存。",
            details={"free_physical_gb": free_gb, "free_virtual_gb": free_virtual_gb},
        )

    return PreflightCheckItem(
        key="memory",
        label="物理内存",
        status="warning",
        message=f"可用物理内存 {free_gb:.1f}GB，偏低。可用虚拟内存 {free_virtual_gb:.1f}GB。",
        suggestion="建议关闭 Chrome / VSCode / Claude Code 后重试。",
        details={"free_physical_gb": free_gb, "free_virtual_gb": free_virtual_gb},
    )


def _check_stt_port(host: str, port: int) -> PreflightCheckItem:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        sock.connect((host, port))
        return PreflightCheckItem(
            key="stt_port",
            label="STT 端口",
            status="ok",
            message=f"端口 {host}:{port} 已有服务在监听，STT server 可能已运行。",
            details={"host": host, "port": port, "listening": True},
        )
    except (ConnectionRefusedError, OSError):
        return PreflightCheckItem(
            key="stt_port",
            label="STT 端口",
            status="ok",
            message=f"端口 {host}:{port} 空闲，可以启动 STT server。",
            details={"host": host, "port": port, "listening": False},
        )
    except Exception as exc:
        return PreflightCheckItem(
            key="stt_port",
            label="STT 端口",
            status="warning",
            message=f"检查端口 {host}:{port} 时出错：{exc}",
            suggestion="请检查网络状态。",
            details={"host": host, "port": port},
        )
    finally:
        sock.close()


def _check_python_env(python_path: Path) -> PreflightCheckItem:
    if python_path.is_file():
        return PreflightCheckItem(
            key="python_env",
            label="Python 环境",
            status="ok",
            message=f"Python 环境已找到：{python_path}",
            details={"path": str(python_path)},
        )
    return PreflightCheckItem(
        key="python_env",
        label="Python 环境",
        status="error",
        message=f"Python 环境不存在：{python_path}",
        suggestion="请检查 Python 安装路径是否正确，或重新安装 conda 环境。",
        details={"path": str(python_path)},
    )


def _check_model_cache(base: Path) -> PreflightCheckItem:
    missing: list[str] = []
    found: list[str] = []
    for rel in _MODEL_FILES:
        full = base / rel
        if full.is_file():
            found.append(rel)
        else:
            missing.append(rel)

    if not missing:
        return PreflightCheckItem(
            key="model_cache",
            label="模型缓存",
            status="ok",
            message=f"模型缓存完整（{len(found)} 个文件）。",
            details={"base": str(base), "found": found},
        )

    return PreflightCheckItem(
        key="model_cache",
        label="模型缓存",
        status="warning",
        message=f"模型缓存不完整，缺少 {len(missing)} 个文件（共 {len(_MODEL_FILES)} 个）。",
        suggestion="首次启动可能需要下载模型，耗时较长或受网络影响。",
        details={"base": str(base), "missing": missing, "found": found},
    )


def _check_logs_writable(project_root: Path) -> PreflightCheckItem:
    logs_dir = project_root / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(logs_dir), prefix=".preflight_", suffix=".tmp")
        os.close(fd)
        os.remove(tmp_path)
        return PreflightCheckItem(
            key="logs_writable",
            label="日志目录",
            status="ok",
            message=f"日志目录可写：{logs_dir}",
            details={"path": str(logs_dir)},
        )
    except Exception as exc:
        return PreflightCheckItem(
            key="logs_writable",
            label="日志目录",
            status="error",
            message=f"日志目录不可写：{logs_dir}（{exc}）",
            suggestion="请检查磁盘空间和目录权限。",
            details={"path": str(logs_dir)},
        )


def _read_memory() -> dict | None:
    try:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", wintypes.DWORD),
                ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            return None

        gb = 1024.0 ** 3
        return {
            "total_physical_gb": mem.ullTotalPhys / gb,
            "free_physical_gb": mem.ullAvailPhys / gb,
            "total_virtual_gb": mem.ullTotalPageFile / gb,
            "free_virtual_gb": mem.ullAvailPageFile / gb,
        }
    except Exception:
        return None
