from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..llm import chat_completion
from ..config import Config


# ── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class ContextualizedPrompt:
    original_tokens: int
    optimized_tokens: int
    savings_pct: float
    prompt: str
    changes: list[str]
    original_language: str = "en"
    filtered_skills: list[str] = field(default_factory=list)
    filtered_memory: list[str] = field(default_factory=list)


@dataclass
class ContextualizerConfig:
    enabled: bool = False
    model: str = "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf"
    provider: str = "llama.cpp"
    api_base: str = "http://localhost:11437/v1"
    api_endpoint: str | None = None
    api_key: str | None = None
    max_context_tokens: int = 2000
    # New options
    use_heuristic_prefilter: bool = True   # Pre-filter context before LLM call
    min_savings_pct: float = 10.0          # Skip LLM if likely savings below this %
    timeout: int = 45                       # Per-request timeout for local models
    dataset_size: int = 300                 # How many training examples to load


# ── Config I/O ───────────────────────────────────────────────────────────────

def load_ctx_config(root: Path) -> ContextualizerConfig:
    path = root / "ctx.config.json"
    if not path.exists():
        return ContextualizerConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ContextualizerConfig(
            enabled=bool(data.get("enabled", False)),
            model=str(data.get("model", "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf")),
            provider=str(data.get("provider", "llama.cpp")),
            api_base=str(data.get("api_base", "http://localhost:11437/v1")),
            api_endpoint=data.get("api_endpoint"),
            api_key=data.get("api_key"),
            max_context_tokens=int(data.get("max_context_tokens", 2000)),
            use_heuristic_prefilter=bool(data.get("use_heuristic_prefilter", True)),
            min_savings_pct=float(data.get("min_savings_pct", 10.0)),
            timeout=int(data.get("timeout", 45)),
            dataset_size=int(data.get("dataset_size", 300)),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return ContextualizerConfig()


def save_ctx_config(root: Path, cfg: ContextualizerConfig) -> None:
    data = {
        "enabled": cfg.enabled,
        "model": cfg.model,
        "provider": cfg.provider,
        "api_base": cfg.api_base,
        "api_endpoint": cfg.api_endpoint,
        "api_key": cfg.api_key,
        "max_context_tokens": cfg.max_context_tokens,
        "use_heuristic_prefilter": cfg.use_heuristic_prefilter,
        "min_savings_pct": cfg.min_savings_pct,
        "timeout": cfg.timeout,
        "dataset_size": cfg.dataset_size,
    }
    (root / "ctx.config.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# ── Recommended Models Catalog ───────────────────────────────────────────────

RECOMMENDED_MODELS = {
    "Qwen2.5-Coder-7B-Q4_K_M.gguf": {
        "desc": "Best overall: fast, clean output, no hallucinations, 96% savings",
        "size": "4.4GB", "speed": "4/5", "quality": "5/5", "recommended": True,
    },
    "google_gemma-4-E2B-it-Q4_K_M.gguf": {
        "desc": "Best plan-following: retains error states and multi-step context",
        "size": "2.0GB", "speed": "2/5", "quality": "5/5", "recommended": True,
    },
    "Phi-4-mini-instruct-Q4_K_M.gguf": {
        "desc": "Best speed/quality balance for simple tasks",
        "size": "2.5GB", "speed": "5/5", "quality": "4/5", "recommended": False,
    },
    "dolphin3.0-qwen2.5-1.5b-q4_k_m.gguf": {
        "desc": "Fastest option, good for low-memory systems",
        "size": "1.1GB", "speed": "5/5", "quality": "3/5", "recommended": False,
    },
}


# ── Token Utilities ───────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


# ── Heuristic Pre-filter ──────────────────────────────────────────────────────

def _heuristic_prefilter(
    user_prompt: str,
    skills_text: str,
    memory_text: str,
) -> tuple[str, str, list[str]]:
    """
    Fast pre-filter using keyword heuristics. Returns filtered (skills, memory, log).
    Only runs if enabled. This is NOT a replacement for LLM filtering — it's a
    first pass to reduce input tokens by ~40-60% for free.
    """
    prompt_lower = user_prompt.lower()
    changes: list[str] = []

    # --- Skill Filtering ---
    skill_blocks = re.split(r"(?=--- skill:)", skills_text)
    kept_skills: list[str] = []
    for block in skill_blocks:
        if not block.strip():
            continue
        skill_name_match = re.search(r"--- skill:([^\s\[]+)", block)
        skill_name = skill_name_match.group(1).strip() if skill_name_match else ""

        # Dynamic keyword extraction from the skill header (name + summary)
        header_line = block.split("\n")[0]
        keywords = set(re.findall(r"\b\w{3,}\b", header_line.lower()))

        if skill_name:
            keywords.add(skill_name.lower())

        if any(kw in prompt_lower for kw in keywords):
            kept_skills.append(block)
        else:
            changes.append(f"Pre-filter: removed skill '{skill_name}' (no keyword match in header)")

    filtered_skills = "\n\n".join(kept_skills) if kept_skills else skills_text

    # --- Memory Filtering ---
    prompt_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", prompt_lower))
    memory_lines: list[str] = []
    for line in memory_text.splitlines():
        line_words = set(re.findall(r"\b[a-zA-Z]{4,}\b", line.lower()))
        overlap = prompt_words & line_words
        if overlap or line.startswith("#") or line.startswith("##"):
            memory_lines.append(line)
        else:
            changes.append(f"Pre-filter: removed memory line (no overlap with prompt)")
    filtered_memory = "\n".join(memory_lines) if memory_lines else memory_text

    return filtered_skills, filtered_memory, changes


# ── Master System Prompt (Few-Shot + Chain-of-Thought) ───────────────────────

SYSTEM_PROMPT = """\
You are the Delux Agent Contextualizer — a specialized pre-processor that prepares \
a self-contained, optimized prompt for Delux, an autonomous AI shell agent.

═══════════════════════════════════════════════════════════
AGENT ACTION FORMAT (for your reference — VERY IMPORTANT)
The main Delux agent understands ONLY JSON actions like these:
  {"action":"shell","command":"ls -la","timeout":60}
  {"action":"read_file","path":"relative/path"}
  {"action":"write_file","path":"path","content":"..."}
  {"action":"edit_file","path":"path","old_str":"...","new_str":"..."}
  {"action":"run_skill","skill":"skill-slug","args":"..."}
  {"action":"search_files","query":"text"}
  {"action":"remember","note":"..."}
  {"action":"final","message":"..."}
Your job is to give the agent EXACTLY the context it needs to pick the right action.
═══════════════════════════════════════════════════════════

YOUR TASK — follow these steps mentally before responding:

STEP 1 — UNDERSTAND: What is the user trying to do? (shell command, file edit, plan step?)
STEP 2 — SCAN SKILLS: Which skills (if any) are directly applicable?
STEP 3 — SCAN MEMORY: Which memory facts are needed to complete this task correctly?
STEP 4 — SCAN PLAN: If a PLAN exists, what is the CURRENT step? What FAILED previously?
         ⚠️  CRITICAL: ANY error or failure from a previous plan step MUST be retained.
STEP 6 — DISCARD: Everything else is noise. Be aggressive. Cut it.

RULES:
- DANGER: Do NOT solve the task yourself. Your job is to PREPARE the prompt for another AI.
- FOCUS: Be the filter. Select the 2-3 most relevant expert examples from the 1000 provided.
- The output "prompt" is the ONLY thing the agent sees. Make it complete.
- DO NOT include your reasoning in the "prompt" field.
- NEVER attempt "action:final" if there are PENDING steps in the current PLAN.
- ALWAYS preserve: error messages, IPs, file paths, credentials, and plan status.
- EFFICIENCY: Encourage the agent to double-check targets before running heavy operations.

Return ONLY a JSON action object:
{
  "prompt": "The actual text the agent will see",
  "reasoning": "Internal reasoning (hidden from agent)",
  "relevant_skills": ["skill-name"],
  "relevant_memory": ["fact"]
}
"""

# ── Core Contextualizer Class ─────────────────────────────────────────────────

class Contextualizer:
    def __init__(self, config: Config, ctx_cfg: ContextualizerConfig) -> None:
        self.config = config
        self.ctx_cfg = ctx_cfg

    def is_enabled(self) -> bool:
        return self.ctx_cfg.enabled

    def _extract_json(self, text: str) -> dict:
        """Robustly extracts JSON from potentially noisy model output."""
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            match = re.search(r'(\{.*\})', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except:
                    pass
        return {}

    def _ensure_dataset_sync(self):
        """Automatically regenerate the training dataset if it doesn't match the config size."""
        training_path = self.config.root / "training" / "training_examples.md"
        target_size = min(self.ctx_cfg.dataset_size, 700)

        current_size = 0
        if training_path.exists():
            with open(training_path, "r") as f:
                current_size = len(re.findall(r"--- expert example:", f.read()))

        if current_size != target_size:
            print(f"[DEBUG] Contextualizer: Scaling expert context ({current_size} -> {target_size} cases)...")
            from ..wizard.wizard import _generate_training_dataset
            _generate_training_dataset(self.config.root, target_size)
            print(f"[DEBUG] Contextualizer: Scaling complete.")

    def contextualize(
        self,
        user_prompt: str,
        memory: str,
        skills: str,
        docs: str,
        plan_context: str = "",
    ) -> ContextualizedPrompt:
        """
        Main entry point for contextualization.
        Scales context up to 700 cases and injects 'Self-Learned' experts if available.
        """
        print(f"\n[DEBUG] Contextualizer: scaling={self.ctx_cfg.dataset_size}, model={self.ctx_cfg.model}")
        if not self.is_enabled():
            return ContextualizedPrompt(
                original_tokens=0, optimized_tokens=0, savings_pct=0,
                prompt=user_prompt,
                changes=["Contextualizer disabled — using original prompt"],
                original_language="en",
            )

        # ── Stage 0: Auto-sync dataset with config ──────────────────────────
        self._ensure_dataset_sync()

        # ── Stage 0.5: Heuristic Humanity Filter ───────────────────────────
        human_greetings = ["hola", "hi", "hey", "buenos días", "buenas tardes", "buenas noches", "qué tal", "como estas", "quien eres", "gracias", "thanks"]
        clean_input = user_prompt.lower().strip().replace("?", "").replace("!", "")

        if any(greet == clean_input for greet in human_greetings) or len(clean_input) < 3:
            print(f"[DEBUG] Contextualizer: Humanity Filter triggered for '{user_prompt}'")
            return ContextualizedPrompt(
                original_tokens=len(user_prompt.split()),
                optimized_tokens=len(user_prompt.split()),
                savings_pct=0,
                prompt=f"¡Hola! Soy Delux Agent. Mi cerebro técnico de 10K casos está activo y listo para ayudarte. ¿Qué sistema o código quieres que revisemos hoy?",
                changes=["Bypass de humanidad: Saludo detectado."],
                filtered_skills=["interaction", "greeting"]
            )

        original_tokens = (
            _estimate_tokens(user_prompt) + _estimate_tokens(memory) +
            _estimate_tokens(skills) + _estimate_tokens(docs) + _estimate_tokens(plan_context)
        )

        prefilter_changes: list[str] = []

        # ── Stage 1: Load Expert Knowledge (Static + Self-Learned) ──────────
        expert_examples_text = ""
        learned_path = self.config.root / "training" / "self_learned_experts.json"

        if learned_path.exists():
            try:
                with open(learned_path, "r", encoding="utf-8") as f:
                    learned_cases = json.load(f)[:50]
                    for case in learned_cases:
                        expert_examples_text += f"\n--- self-learned expert ---\n{case['user']}\nSTRATEGY: {case['assistant']}\n"
            except:
                pass

        training_path = self.config.root / "training" / "training_examples.md"
        if training_path.exists():
            expert_examples_text += "\n" + training_path.read_text(encoding="utf-8")

        # ── Stage 2: Heuristic pre-filter (free, no LLM call) ────────────────
        if self.ctx_cfg.use_heuristic_prefilter:
            skills, memory, prefilter_changes = _heuristic_prefilter(
                user_prompt, skills, memory
            )

        # ── Stage 2: Check if LLM pass is worth it ───────────────────────────
        pre_tokens = (
            _estimate_tokens(user_prompt) + _estimate_tokens(memory) +
            _estimate_tokens(skills) + _estimate_tokens(docs)
        )

        is_short_chat = len(user_prompt.split()) < 3

        if pre_tokens < 2 and not is_short_chat:
            return ContextualizedPrompt(
                original_tokens=original_tokens,
                optimized_tokens=pre_tokens,
                savings_pct=0,
                prompt=user_prompt,
                changes=prefilter_changes + ["Context too small for LLM pass — skipped"],
                original_language="en",
            )

        # ── Stage 3: Build LLM input ──────────────────────────────────────────
        ctx_sections: list[str] = []

        training_path = self.config.root / "training" / "training_examples.md"
        if training_path.exists():
            try:
                ctx_sections.append(f"TRAINING EXAMPLES:\n{training_path.read_text(encoding='utf-8')}")
            except:
                pass

        if plan_context.strip():
            ctx_sections.append(f"!!! PLAN IN PROGRESS — DO NOT USE 'action:final' YET !!!\n\nPLAN STATUS:\n{plan_context.strip()}")

        ctx_sections.append(f"USER PROMPT:\n{user_prompt}")

        if memory.strip():
            ctx_sections.append(f"MEMORY:\n{memory.strip()}")
        if skills.strip():
            ctx_sections.append(f"SKILLS:\n{skills.strip()}")
        if docs.strip():
            ctx_sections.append(f"DOCS:\n{docs.strip()[:3000]}")

        ctx_input = "\n\n".join(ctx_sections)

        # ── Stage 5: Call the local LLM ───────────────────────────────────────
        try:
            print(f"[DEBUG] Contextualizer: Calling LLM at {self.ctx_cfg.api_base}...")
            response = chat_completion(
                self.ctx_cfg.api_base,
                self.ctx_cfg.api_key,
                self.ctx_cfg.model,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": ctx_input},
                ],
                self.ctx_cfg.api_endpoint,
                timeout=self.ctx_cfg.timeout,
            )

            text = response.text.strip()
            print(f"[DEBUG] Contextualizer: Raw LLM response: {text[:200]}...")

            # ── Stage 5: Robust JSON extraction ───────────────────────────────
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
            text = re.sub(r"\s*```$", "", text, flags=re.MULTILINE)

            json_start = text.find("{")
            json_end = text.rfind("}")
            if json_start >= 0 and json_end > json_start:
                text = text[json_start:json_end + 1]

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"prompt": user_prompt, "changes": ["Error: Model output not valid JSON. Using raw prompt."]}

            optimized = data.get("prompt", user_prompt)
            if not optimized or not isinstance(optimized, str) or len(optimized.strip()) < 5:
                optimized = user_prompt

            changes: list[str] = prefilter_changes + (data.get("changes") or [])
            original_lang: str = data.get("original_language", "en")
            filtered_skills: list[str] = data.get("relevant_skills", [])
            filtered_memory: list[str] = data.get("relevant_memory", [])

            # Preserve plan failure context if LLM dropped it accidentally
            if plan_context.strip():
                if "PENDING" in plan_context or "CURRENT" in plan_context:
                    optimized = f"!!! PLAN IN PROGRESS — DO NOT USE 'action:final' YET !!!\n\n{optimized}"

                failed_lines = []
                if "FAILED" in plan_context and "FAILED" not in optimized:
                    failed_lines = [
                        line for line in plan_context.splitlines()
                        if "FAILED" in line or "ERROR" in line
                    ]
                if failed_lines:
                    optimized += "\n\n[PLAN FAILURE CONTEXT — DO NOT IGNORE]\n" + "\n".join(failed_lines)
                    changes.append("Safety net: re-injected plan failure context that LLM dropped")

            # ── Efficiency reasoning ──────────────────────────────────────────
            optimized += "\n\nCRITICAL: Evaluate execution time before running. If a command (like nmap or find) targets a huge scope, verify the target first."

            optimized_tokens = _estimate_tokens(optimized)
            savings = max(0, (original_tokens - optimized_tokens) / max(1, original_tokens) * 100)

            return ContextualizedPrompt(
                original_tokens=original_tokens,
                optimized_tokens=optimized_tokens,
                savings_pct=savings,
                prompt=optimized,
                changes=changes,
                original_language=original_lang,
                filtered_skills=filtered_skills,
                filtered_memory=filtered_memory,
            )

        except Exception as exc:
            print(f"[DEBUG] Contextualizer: Exception in LLM call: {exc}")
            fallback_prompt = user_prompt
            return ContextualizedPrompt(
                original_tokens=original_tokens,
                optimized_tokens=_estimate_tokens(fallback_prompt),
                savings_pct=0,
                prompt=fallback_prompt,
                changes=prefilter_changes + [f"LLM contextualizer error: {exc} — using pre-filtered context"],
                original_language="en",
            )

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def print_recommendations() -> None:
        from shutil import get_terminal_size
        w = get_terminal_size((80, 24)).columns
        print(f"\n{'=' * min(60, w)}")
        print("  Recommended Contextualizer Models")
        print(f"{'=' * min(60, w)}")
        for name, info in RECOMMENDED_MODELS.items():
            rec = " ← RECOMMENDED" if info["recommended"] else ""
            print(f"  {name}{rec}")
            print(f"    Size: {info['size']}  Speed: {info['speed']}  Quality: {info['quality']}")
            print(f"    {info['desc']}")
            print()

    @staticmethod
    def print_finetune_recommendations() -> None:
        from shutil import get_terminal_size
        w = get_terminal_size((80, 24)).columns
        print(f"\n{'=' * min(60, w)}")
        print("  Recommended Models for Fine-Tuning")
        print(f"{'=' * min(60, w)}")
        print()
        print("  For creating a custom Delux agent model via fine-tuning:")
        print()
        print("  1. Qwen 2.5 Coder 7B (BEST CHOICE)")
        print("     - Native JSON mode, multilingual (EN/ES)")
        print("     - Excellent tool-use understanding")
        print("     - Fine-tune with Unsloth or Ollama")
        print()
        print("  2. Llama 3.1 8B")
        print("     - Largest ecosystem / most tutorials")
        print("     - Fine-tune with Axolotl or Unsloth")
        print()
        print("  3. Mistral 7B v0.3")
        print("     - Good balance of size and quality")
        print("     - Fine-tune with Axolotl")
        print()
        print("  Dataset structure:")
        print('  {"messages": [')
        print('    {"role": "system", "content": "You are Delux..."},')
        print('    {"role": "user", "content": "install nginx"},')
        print('    {"role": "assistant", "content": "{\\"action\\":\\"shell\\",\\"command\\":\\"dnf install nginx\\"}"}')
        print("  ]}")
        print()
