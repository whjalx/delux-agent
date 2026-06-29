from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from pathlib import Path


CONFIG_FILE = "delux.config.json"
DEFAULT_HOME = ".delux"


@dataclass(frozen=True)
class ModelEntry:
    name: str
    provider: str = ""
    api_base: str = ""
    api_endpoint: str = ""
    api_key: str = ""


def _coerce_model_entry(data: dict | str) -> ModelEntry:
    if isinstance(data, str):
        return ModelEntry(name=data)
    return ModelEntry(
        name=str(data.get("name", "unknown")),
        provider=str(data.get("provider", "")),
        api_base=str(data.get("api_base", "")),
        api_endpoint=data.get("api_endpoint") or "",
        api_key=data.get("api_key") or "",
    )


@dataclass(frozen=True)
class Config:
    root: Path
    memory_file: Path
    skills_dir: Path
    docs_dir: Path
    sessions_dir: Path
    testing_dir: Path
    shell: str
    provider: str
    api_base: str
    api_endpoint: str | None
    api_key: str | None
    model: str
    request_timeout: int
    models: list[ModelEntry] = field(default_factory=list)
    validator_provider: str | None = None
    validator_api_base: str | None = None
    validator_api_endpoint: str | None = None
    validator_api_key: str | None = None
    validator_model: str | None = None
    embedding_model: str | None = None
    embedding_api_base: str | None = None
    embedding_api_key: str | None = None
    lang: str = "en"
    response_template: str = "auto"
    small_model: bool = False
    cache_chunk_size: int = 0
    plan_model: str = ""
    plan_provider: str = ""
    plan_api_base: str = ""
    plan_api_key: str = ""
    plan_api_endpoint: str = ""
    ctx_model: str = ""
    ctx_provider: str = ""
    ctx_api_base: str = ""
    ctx_api_key: str = ""
    ctx_api_endpoint: str = ""
    browser_screenshot_dir: str = ""
    browser_headless: bool = True
    vision_model: str = ""
    vision_api_base: str = ""
    vision_api_key: str = ""
    cron_enabled: bool = False
    kanban_enabled: bool = False
    plan_free: bool = False

    @property
    def builtin_skills_dir(self) -> Path:
        import delux_agent
        return Path(delux_agent.__file__).parent / "skills"

    @property
    def effective_plan_model(self) -> str:
        return self.plan_model or self.model

    @property
    def effective_plan_provider(self) -> str:
        return self.plan_provider or self.provider

    @property
    def effective_plan_api_base(self) -> str:
        return self.plan_api_base or self.api_base

    @property
    def effective_plan_api_key(self) -> str:
        return self.plan_api_key or (self.api_key or "")

    @property
    def effective_plan_api_endpoint(self) -> str | None:
        return self.plan_api_endpoint or self.api_endpoint

    @property
    def effective_ctx_model(self) -> str:
        return self.ctx_model or self.model

    @property
    def effective_ctx_provider(self) -> str:
        return self.ctx_provider or self.provider

    @property
    def effective_ctx_api_base(self) -> str:
        return self.ctx_api_base or self.api_base

    @property
    def effective_ctx_api_key(self) -> str:
        return self.ctx_api_key or (self.api_key or "")

    @property
    def effective_ctx_api_endpoint(self) -> str | None:
        return self.ctx_api_endpoint or self.api_endpoint



def default_root() -> Path:
    return Path(os.environ.get("DELUX_HOME", Path.home() / DEFAULT_HOME)).expanduser().resolve()


def _read_config_file(root: Path) -> dict:
    path = root / CONFIG_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def load_config(cwd: Path | None = None) -> Config:
    root = Path(cwd or os.environ.get("DELUX_HOME", default_root())).expanduser().resolve()
    file_config = _read_config_file(root)
    shell = os.environ.get("DELUX_SHELL", "sh")

    models_raw = file_config.get("models", [])
    models: list[ModelEntry] = []
    for m in models_raw:
        models.append(_coerce_model_entry(m))

    if not models:
        fallback = ModelEntry(
            name=str(file_config.get("model", "gpt-4.1-mini")),
            provider=str(file_config.get("provider", "openai")),
            api_base=str(file_config.get("api_base", "https://api.openai.com/v1")),
            api_endpoint=str(file_config.get("api_endpoint") or ""),
            api_key=str(file_config.get("api_key") or ""),
        )
        models.append(fallback)

    return Config(
        root=root,
        memory_file=root / "memory" / "memory.md",
        skills_dir=root / "skills",
        docs_dir=root / "docs",
        sessions_dir=root / "sessions",
        testing_dir=root / "testing",
        shell=shell,
        provider=os.environ.get("DELUX_PROVIDER", str(file_config.get("provider", "openai"))),
        api_base=os.environ.get("DELUX_API_BASE", str(file_config.get("api_base", "https://api.openai.com/v1"))),
        api_endpoint=os.environ.get("DELUX_API_ENDPOINT") or file_config.get("api_endpoint"),
        api_key=os.environ.get("DELUX_API_KEY") or os.environ.get("OPENAI_API_KEY") or file_config.get("api_key"),
        model=os.environ.get("DELUX_MODEL", str(file_config.get("model", "gpt-4.1-mini"))),
        request_timeout=int(os.environ.get("DELUX_TIMEOUT", str(file_config.get("request_timeout", 180)))),
        models=models,
        validator_provider=file_config.get("validator_provider"),
        validator_api_base=file_config.get("validator_api_base"),
        validator_api_endpoint=file_config.get("validator_api_endpoint"),
        validator_api_key=file_config.get("validator_api_key"),
        validator_model=file_config.get("validator_model"),
        embedding_model=os.environ.get("DELUX_EMBEDDING_MODEL") or file_config.get("embedding_model"),
        embedding_api_base=os.environ.get("DELUX_EMBEDDING_API_BASE") or file_config.get("embedding_api_base"),
        embedding_api_key=os.environ.get("DELUX_EMBEDDING_API_KEY") or file_config.get("embedding_api_key"),
        lang=os.environ.get("DELUX_LANG", str(file_config.get("lang", "en"))),
        response_template=str(file_config.get("response_template", "auto")),
        small_model=bool(file_config.get("small_model", False)),
        cache_chunk_size=int(os.environ.get("DELUX_CACHE_CHUNK_SIZE", str(file_config.get("cache_chunk_size", 0)))),
        plan_model=os.environ.get("DELUX_PLAN_MODEL") or file_config.get("plan_model", ""),
        plan_provider=os.environ.get("DELUX_PLAN_PROVIDER") or file_config.get("plan_provider", ""),
        plan_api_base=os.environ.get("DELUX_PLAN_API_BASE") or file_config.get("plan_api_base", ""),
        plan_api_key=os.environ.get("DELUX_PLAN_API_KEY") or file_config.get("plan_api_key", ""),
        plan_api_endpoint=os.environ.get("DELUX_PLAN_API_ENDPOINT") or file_config.get("plan_api_endpoint", ""),
        ctx_model=os.environ.get("DELUX_CTX_MODEL") or file_config.get("ctx_model", ""),
        ctx_provider=os.environ.get("DELUX_CTX_PROVIDER") or file_config.get("ctx_provider", ""),
        ctx_api_base=os.environ.get("DELUX_CTX_API_BASE") or file_config.get("ctx_api_base", ""),
        ctx_api_key=os.environ.get("DELUX_CTX_API_KEY") or file_config.get("ctx_api_key", ""),
        ctx_api_endpoint=os.environ.get("DELUX_CTX_API_ENDPOINT") or file_config.get("ctx_api_endpoint", ""),
        browser_screenshot_dir=file_config.get("browser_screenshot_dir", ""),
        browser_headless=bool(file_config.get("browser_headless", True)),
        vision_model=file_config.get("vision_model", ""),
        vision_api_base=file_config.get("vision_api_base", ""),
        vision_api_key=file_config.get("vision_api_key", ""),
        cron_enabled=bool(file_config.get("cron_enabled", False)),
        kanban_enabled=bool(file_config.get("kanban_enabled", False)),
        plan_free=bool(file_config.get("plan_free", False)),
    )


_SMALL_MODEL_PATTERNS = [
    r'\b3b\b', r'\b1b\b', r'\b2b\b', r'\b4b\b',
    r'\bsmall\b', r'\btiny\b',
    r'\bphi-[0-3]\b', r'\bphi3\b',
    r'\bqwen2-0\.5', r'\bqwen2-1\.[35]', r'\bqwen2-2\b', r'\bqwen2-3b\b', r'\bqwen2-4b\b',
    r'\bgemma-2b\b', r'\bgemma-3b\b', r'\bgemma-4b\b',
    r'\bllama-3\.2-1b\b', r'\bllama-3\.2-3b\b',
]

def is_small_model(model_name: str) -> bool:
    import re
    name = model_name.lower()
    for pat in _SMALL_MODEL_PATTERNS:
        if re.search(pat, name):
            return True
    return False


def write_config(root: Path, values: dict) -> Path:
    path = root / CONFIG_FILE
    path.write_text(json.dumps(values, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
