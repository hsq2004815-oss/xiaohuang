from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from xiaohuang.settings_config_file_service import (
    _VALID_PROVIDERS,
    _KNOWN_SECTIONS,
    _dataclass_to_sections,
    load_config_with_unknown,
    normalize_ui_inputs,
    save_config,
    validate_config,
)
from xiaohuang.app_config_service import get_default_config_path, load_config as load_user_config


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="XiaoHuang Settings UI Prototype")
    p.add_argument("--config", default=None, help="Path to config.json")
    p.add_argument("--check", action="store_true", help="Load, validate, and print summary; no GUI")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Widget registry: section_name -> {field_name: widget}
# ---------------------------------------------------------------------------
_widgets: dict[str, dict[str, object]] = {}


def _reg(section: str, field: str, widget: object) -> None:
    _widgets.setdefault(section, {})[field] = widget


def _get_widget_val(section: str, field: str) -> str:
    w = _widgets.get(section, {}).get(field)
    if w is None:
        return ""
    import tkinter as tk
    if isinstance(w, tk.Text):
        return w.get("1.0", "end-1c")
    if hasattr(w, "_var"):
        return w._var.get()
    return ""


def _set_widget_val(section: str, field: str, value) -> None:
    w = _widgets.get(section, {}).get(field)
    if w is None:
        return
    import tkinter as tk
    if isinstance(w, tk.Text):
        w.delete("1.0", "end")
        w.insert("1.0", str(value) if value is not None else "")
    elif hasattr(w, "_var"):
        w._var.set(value)


# ---------------------------------------------------------------------------
# Tab builders
# ---------------------------------------------------------------------------

def _make_entry(parent, row: int, label: str, default: str, section: str, field: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=2)
    var = tk.StringVar(value=str(default))
    e = ttk.Entry(parent, textvariable=var, width=40)
    e.grid(row=row, column=1, sticky="ew", padx=10, pady=2)
    e._var = var
    _reg(section, field, e)


def _make_checkbox(parent, row: int, label: str, default: bool, section: str, field: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=2)
    var = tk.BooleanVar(value=default)
    cb = ttk.Checkbutton(parent, variable=var)
    cb.grid(row=row, column=1, sticky="w", padx=10, pady=2)
    cb._var = var
    _reg(section, field, cb)


def _make_combo(parent, row: int, label: str, default: str, values: list[str], section: str, field: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=10, pady=2)
    var = tk.StringVar(value=default)
    cb = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=37)
    cb.grid(row=row, column=1, sticky="ew", padx=10, pady=2)
    cb._var = var
    _reg(section, field, cb)


def _make_text(parent, row: int, label: str, default: str, section: str, field: str) -> None:
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="nw", padx=10, pady=2)
    t = tk.Text(parent, width=40, height=5, wrap="word")
    t.insert("1.0", str(default) if default else "")
    t.grid(row=row, column=1, sticky="ew", padx=10, pady=2)
    _reg(section, field, t)


def _make_label(parent, row: int, text: str, column_span: int = 2) -> None:
    from tkinter import ttk
    ttk.Label(parent, text=text, foreground="gray").grid(
        row=row, column=0, columnspan=column_span, sticky="w", padx=10, pady=(6, 0))


def _build_wake_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="Wake")
    s = sections.get("wake", {})
    _make_entry(f, 0, "唤醒词 (逗号分隔)", s.get("phrases", ""), "wake", "phrases")
    _make_entry(f, 1, "唤醒别名", s.get("aliases", ""), "wake", "aliases")
    _make_entry(f, 2, "唤醒窗口 (秒)", s.get("wake_window_seconds", 3.0), "wake", "wake_window_seconds")


def _build_assistant_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="Assistant")
    s = sections.get("assistant", {})
    _make_entry(f, 0, "助手名 (name)", s.get("name", ""), "assistant", "name")
    _make_entry(f, 1, "显示名 (display_name)", s.get("display_name", ""), "assistant", "display_name")
    _make_text(f, 2, "系统提示词 (persona)", s.get("persona", ""), "assistant", "persona")


def _build_llm_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="LLM")
    s = sections.get("llm", {})
    _make_checkbox(f, 0, "启用 LLM", s.get("enabled", True), "llm", "enabled")
    _make_combo(f, 1, "Provider", str(s.get("provider", "deepseek")), sorted(_VALID_PROVIDERS), "llm", "provider")
    _make_entry(f, 2, "Model", s.get("model", ""), "llm", "model")
    _make_entry(f, 3, "Base URL", s.get("base_url", ""), "llm", "base_url")
    _make_entry(f, 4, "API Key 环境变量名", s.get("api_key_env", ""), "llm", "api_key_env")
    _make_entry(f, 5, "超时 (秒)", s.get("timeout_seconds", 20.0), "llm", "timeout_seconds")
    _make_entry(f, 6, "Max Tokens", s.get("max_tokens", 256), "llm", "max_tokens")
    _make_entry(f, 7, "Temperature", s.get("temperature", 0.4), "llm", "temperature")
    _make_label(f, 8, "提示：API Key 环境变量名只填变量名（如 DEEPSEEK_API_KEY），真实 key 放在 secrets.ps1")


def _build_tts_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="TTS")
    s = sections.get("tts", {})
    _make_checkbox(f, 0, "启用 TTS", s.get("enabled", True), "tts", "enabled")
    _make_entry(f, 1, "Voice", s.get("voice", ""), "tts", "voice")


def _build_conversation_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="Conversation")
    s = sections.get("conversation", {})
    _make_checkbox(f, 0, "启用多轮会话", s.get("enabled", True), "conversation", "enabled")
    _make_entry(f, 1, "追问窗口 (秒)", s.get("followup_timeout", 12.0), "conversation", "followup_timeout")
    _make_entry(f, 2, "最大轮数", s.get("max_turns", 12), "conversation", "max_turns")
    _make_entry(f, 3, "最大会话时长 (秒)", s.get("max_session_seconds", 300.0), "conversation", "max_session_seconds")
    _make_entry(f, 4, "无语音重试次数", s.get("max_no_speech_retries", 2), "conversation", "max_no_speech_retries")
    _make_entry(f, 5, "会话超时 (秒)", s.get("session_timeout", 30.0), "conversation", "session_timeout")


def _build_advanced_tab(nb, sections: dict) -> None:
    from tkinter import ttk
    f = ttk.Frame(nb)
    nb.add(f, text="Advanced")
    ov = sections.get("overlay", {})
    rt = sections.get("runtime", {})
    _make_checkbox(f, 0, "启动时隐藏悬浮窗", ov.get("resident_hidden", True), "overlay", "resident_hidden")
    _make_entry(f, 1, "回复后冷却 (秒, 空=自动)", ov.get("post_response_cooldown", ""), "overlay", "post_response_cooldown")
    _make_checkbox(f, 2, "Debug 模式", rt.get("debug", False), "runtime", "debug")


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def _collect_all_data() -> dict[str, Any]:
    """Collect all widget data into a sections dict."""
    result: dict[str, Any] = {}
    for section_name, fields in _widgets.items():
        if section_name not in _KNOWN_SECTIONS:
            # "advanced" tab covers overlay + runtime
            pass
        section_data: dict[str, Any] = {}
        for field_name in fields:
            section_data[field_name] = _get_widget_val(section_name, field_name)
        if section_name == "advanced":
            # Split advanced into overlay + runtime
            ov_fields = _KNOWN_SECTIONS.get("overlay", [])
            rt_fields = _KNOWN_SECTIONS.get("runtime", [])
            result["overlay"] = {f: section_data.get(f) for f in ov_fields}
            result["runtime"] = {f: section_data.get(f) for f in rt_fields}
        else:
            result[section_name] = section_data
    return result


def _reload_sections(sections: dict) -> None:
    """Reload all widgets from sections dict."""
    for section_name, fields in _widgets.items():
        if section_name == "advanced":
            ov = sections.get("overlay", {})
            rt = sections.get("runtime", {})
            for f in fields:
                val = ov.get(f) if f in _KNOWN_SECTIONS.get("overlay", []) else rt.get(f)
                _set_widget_val(section_name, f, val if val is not None else "")
        else:
            sec = sections.get(section_name, {})
            for f in fields:
                _set_widget_val(section_name, f, sec.get(f, ""))


# ---------------------------------------------------------------------------
# Check mode
# ---------------------------------------------------------------------------

def _check_mode(config_path: str) -> int:
    path = Path(config_path)
    print(f"Config path: {path}")
    print(f"Exists: {path.exists()}")

    raw_data, load_err = load_config_with_unknown(path)
    if load_err:
        print(f"Load error: {load_err}")
        return 1

    try:
        cfg = load_user_config(path)
    except Exception as exc:
        print(f"Config parse error: {exc}")
        return 1

    print(f"wake.phrases: {cfg.wake.phrases}")
    print(f"assistant.name: {cfg.assistant.name}")
    print(f"llm.provider: {cfg.llm.provider}")
    print(f"llm.model: {cfg.llm.model}")
    print(f"llm.api_key_env: {cfg.llm.api_key_env}")
    print(f"tts.enabled: {cfg.tts.enabled}")
    print(f"tts.voice: {cfg.tts.voice}")
    print(f"conversation.enabled: {cfg.conversation.enabled}")
    print(f"overlay.resident_hidden: {cfg.overlay.resident_hidden}")
    print(f"runtime.debug: {cfg.runtime.debug}")

    known = set(_KNOWN_SECTIONS.keys())
    raw_keys = set(raw_data.keys())
    unknown = raw_keys - known
    if unknown:
        print(f"Unknown sections (will be preserved): {sorted(unknown)}")

    validation = validate_config(raw_data)
    if not validation.valid:
        print("Validation errors:")
        for e in validation.errors:
            print(f"  - {e}")
        return 1

    print("\nConfig validation: PASS")
    return 0


# ---------------------------------------------------------------------------
# UI main
# ---------------------------------------------------------------------------

def _build_ui(config_path: str) -> None:
    import tkinter as tk
    from tkinter import ttk, messagebox

    resolved = Path(config_path)
    raw_data, load_err = load_config_with_unknown(resolved)

    if resolved.exists() and not load_err:
        cfg = load_user_config(resolved)
    else:
        cfg = load_user_config(None)
    sections = _dataclass_to_sections(cfg)

    root = tk.Tk()
    root.title("小黄设置 V1.1.3C")
    root.geometry("580x540")
    root.resizable(True, True)

    # Path display
    pf = ttk.Frame(root)
    pf.pack(fill="x", padx=10, pady=(10, 0))
    ttk.Label(pf, text="配置文件：").pack(side="left")
    path_var = tk.StringVar(value=str(resolved))
    ttk.Label(pf, textvariable=path_var, foreground="gray").pack(side="left", padx=(4, 0))

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=10, pady=10)
    _build_wake_tab(nb, sections)
    _build_assistant_tab(nb, sections)
    _build_llm_tab(nb, sections)
    _build_tts_tab(nb, sections)
    _build_conversation_tab(nb, sections)
    _build_advanced_tab(nb, sections)

    btn_frame = ttk.Frame(root)
    btn_frame.pack(fill="x", padx=10, pady=(0, 10))

    def _do_save() -> None:
        data = _collect_all_data()
        normalized, norm_errs = normalize_ui_inputs(data)
        if norm_errs:
            messagebox.showerror("校验错误", "\n".join(norm_errs))
            return
        validation = validate_config(normalized)
        if not validation.valid:
            messagebox.showerror("校验错误", "\n".join(validation.errors))
            return
        err = save_config(resolved, normalized, original_data=raw_data if resolved.exists() else None)
        if err:
            messagebox.showerror("保存失败", err)
            return
        messagebox.showinfo("保存成功", f"配置已保存到：\n{resolved}\n\n请重启小黄以应用新配置。")

    def _do_reload() -> None:
        nonlocal raw_data, sections
        raw_data, load_err = load_config_with_unknown(resolved)
        if load_err:
            messagebox.showerror("加载失败", load_err)
            return
        if resolved.exists():
            new_cfg = load_user_config(resolved)
        else:
            new_cfg = load_user_config(None)
        sections = _dataclass_to_sections(new_cfg)
        _reload_sections(sections)
        path_var.set(str(resolved))

    ttk.Button(btn_frame, text="保存", command=_do_save).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="重新加载", command=_do_reload).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="关闭", command=root.destroy).pack(side="right", padx=4)

    root.mainloop()


def main() -> int:
    args = parse_args()
    config_path = args.config or str(get_default_config_path())

    if args.check:
        return _check_mode(config_path)

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        print("Tkinter is not available in this Python environment.")
        return 2

    _build_ui(config_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
