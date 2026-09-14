import json
import sys
from pathlib import Path

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR    = get_base_dir()
CONFIG_DIR  = BASE_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_keys.json"

def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

def config_exists() -> bool:
    return CONFIG_FILE.exists()

def save_api_keys(gemini_api_key: str) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["gemini_api_key"] = gemini_api_key.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def load_api_keys() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ Failed to load api_keys.json: {e}")
        return {}

def get_gemini_key() -> str | None:
    return load_api_keys().get("gemini_api_key")

def is_configured() -> bool:
    key = get_gemini_key()
    return bool(key and len(key) > 15)

def get_assistant_name() -> str:
    return load_api_keys().get("assistant_name", "JARVIS") or "JARVIS"

def get_user_name() -> str:
    return load_api_keys().get("user_name", "")

def save_assistant_config(assistant_name: str, user_name: str) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["assistant_name"] = assistant_name.strip() or "JARVIS"
    data["user_name"] = user_name.strip()
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")

# ── Assistant voice ──────────────────────────────────────────────────────────
# Native Gemini Live is intentionally locked to one English voice. The separate
# jarvis_voice plugin may use its explicitly configured English TTS voice.
AVAILABLE_VOICES = ["Charon"]
DEFAULT_VOICE    = "Charon"

def get_voice() -> str:
    return DEFAULT_VOICE

def save_voice(voice_name: str) -> None:
    # Ignore alternate values so a stale UI/config choice can never switch the
    # native live session to another voice.
    _patch_config(voice_name=DEFAULT_VOICE)

def get_wake_word_enabled() -> bool:
    return load_api_keys().get("wake_word_enabled", False)

def save_wake_word_enabled(enabled: bool) -> None:
    _patch_config(wake_word_enabled=bool(enabled))

def get_brief_enabled() -> bool:
    return load_api_keys().get("morning_brief_enabled", True)

def save_brief_enabled(enabled: bool) -> None:
    _patch_config(morning_brief_enabled=enabled)

# ── Audio devices ────────────────────────────────────────────────────────────
def _patch_config(**fields) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields)
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")

def get_input_device() -> str:
    return (load_api_keys().get("input_device", "") or "").strip()

def save_input_device(name: str) -> None:
    _patch_config(input_device=(name or "").strip())

def get_output_device() -> str:
    return (load_api_keys().get("output_device", "") or "").strip()

def save_output_device(name: str) -> None:
    _patch_config(output_device=(name or "").strip())

def get_plugin_enabled(plugin_name: str) -> bool:
    return load_api_keys().get("plugins_enabled", {}).get(plugin_name, True)

# ── Per-plugin settings ──────────────────────────────────────────────────────
def get_plugin_config(namespace: str) -> dict:
    cfg = load_api_keys().get("plugin_config")
    val = cfg.get(namespace) if isinstance(cfg, dict) else None
    return dict(val) if isinstance(val, dict) else {}

def get_plugin_setting(namespace: str, key: str, default=None):
    return get_plugin_config(namespace).get(key, default)

def save_plugin_config(namespace: str, values: dict) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    pc = data.get("plugin_config")
    if not isinstance(pc, dict):
        pc = {}
    cur = pc.get(namespace)
    if not isinstance(cur, dict):
        cur = {}
    cur.update(values)
    pc[namespace] = cur
    data["plugin_config"] = pc
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")

def save_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    ensure_config_dir()
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    plugins_cfg = data.get("plugins_enabled")
    if not isinstance(plugins_cfg, dict):
        plugins_cfg = {}
    plugins_cfg[plugin_name] = enabled
    data["plugins_enabled"] = plugins_cfg
    CONFIG_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")