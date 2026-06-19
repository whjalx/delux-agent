# Fine-Tuning Delux Agent Models

This guide covers recommended models and approaches for fine-tuning a custom Delux agent model.

## Recommended Base Models

### 1. Qwen 2.5 7B (BEST CHOICE)

| Property | Value |
|----------|-------|
| Size | 4.7GB (GGUF Q4_K_M) |
| Multilingual | Yes (EN, ES, ZH, etc.) |
| JSON Mode | Native support |
| Context Window | 32K-128K |
| Fine-tune Framework | Unsloth, Axolotl, Ollama |

**Why Qwen 2.5 7B:**
- Best JSON structured output understanding
- Excellent tool-use reasoning
- Native multilingual support (no extra tokens for Spanish)
- Strong instruction following
- Active community and documentation

### 2. Llama 3.1 8B

| Property | Value |
|----------|-------|
| Size | 4.9GB (GGUF Q4_K_M) |
| Multilingual | Limited (EN-first) |
| JSON Mode | Good with prompting |
| Context Window | 128K |
| Fine-tune Framework | Unsloth, Axolotl, Ollama |

**Why Llama 3.1 8B:**
- Largest ecosystem of tutorials and datasets
- Excellent general reasoning
- Best for OpenAI-compatible API deployment

### 3. Mistral 7B v0.3

| Property | Value |
|----------|-------|
| Size | 4.1GB (GGUF Q4_K_M) |
| Multilingual | Limited |
| JSON Mode | Good |
| Context Window | 32K |
| Fine-tune Framework | Axolotl, Unsloth |

**Why Mistral 7B:**
- Smallest of the three (saves disk/RAM)
- Good balance of quality and speed

## Dataset Structure

### Format (ChatML / OpenAI)

```json
{"messages": [
  {"role": "system", "content": "You are Delux, an AI assistant for system administration..."},
  {"role": "user", "content": "install nginx on Fedora"},
  {"role": "assistant", "content": "{\"action\":\"shell\",\"command\":\"dnf install -y nginx\",\"timeout\":60}"}
]}
```

### Required Categories

1. **Tool Selection** (40% of dataset)
   - When to use shell vs read_file vs write_file
   - When to use skills vs raw commands
   - When to search vs create

2. **Command Generation** (25%)
   - Fish/bash command syntax
   - Package manager usage (dnf, apt, pacman)
   - File manipulation commands

3. **Error Recovery** (20%)
   - Handling "command not found"
   - Handling file not found
   - Handling permission errors
   - Trying alternative approaches

4. **Plan Execution** (15%)
   - Following multi-step plans
   - Skipping unnecessary steps
   - Moving files from testing to final location

### Example Dataset Entry

```json
{
  "messages": [
    {"role": "system", "content": "You are Delux, an AI assistant for system administration. Return ONLY a JSON action object.\n\nAfter each action you receive a result:\n- SUCCESS: the action succeeded. Do NOT repeat it.\n- ERROR: analyze and try a DIFFERENT approach.\n\nShell commands run in the current working directory using POSIX sh. Use ~/.delux/testing/ only when testing scripts or tools before deploying them."},
    {"role": "user", "content": "PLAN STEP (step 1 of 4): Install nginx package\n\nInstall nginx on this Fedora system. Use the appropriate package manager."},
    {"role": "assistant", "content": "{\"action\":\"shell\",\"command\":\"dnf install -y nginx\",\"timeout\":60}"},
    {"role": "user", "content": "SUCCESS: Installed nginx. Package nginx-1.24.0-1.fc40.x86_64 already installed."},
    {"role": "assistant", "content": "{\"action\":\"shell\",\"command\":\"systemctl enable --now nginx\",\"timeout\":30}"}
  ]
}
```

## Fine-Tuning Pipeline

### Option 1: Unsloth (Recommended - 2x faster, free)

```bash
# Install Unsloth
pip install unsloth

# Fine-tune with Qwen 2.5 7B
python train.py \
  --model_name "unsloth/Qwen2.5-7B" \
  --dataset_path "./delux-dataset.jsonl" \
  --max_seq_length 4096 \
  --num_train_epochs 3 \
  --learning_rate 2e-4 \
  --lora_rank 32 \
  --output_dir "./delux-qwen2.5-7b-finetuned"
```

### Option 2: Ollama Modelfile

```bash
# Export from Unsloth to GGUF
ollama create delux-agent -f Modelfile

# Modelfile:
FROM ./delux-qwen2.5-7b-finetuned-Q4_K_M.gguf
SYSTEM """You are Delux, an AI assistant for system administration. Shell commands run in POSIX sh."""
```

### Option 3: Axolotl

```yaml
# axolotl config
base_model: Qwen/Qwen2.5-7B
model_type: AutoModelForCausalLM
tokenizer_type: AutoTokenizer

datasets:
  - path: ./delux-dataset.jsonl
    type: chatml

output_dir: ./delux-finetuned
```

## Training Recommendations

- **Minimum dataset size**: 1000 examples
- **Ideal dataset size**: 5000-10000 examples
- **Training epochs**: 2-4 (avoid overfitting)
- **Learning rate**: 1e-4 to 5e-4
- **LoRA rank**: 16-32 (lower = smaller file, higher = better quality)
- **Max sequence length**: 4096-8192
- **Batch size**: 4-8 (depending on GPU memory)

## GPU Requirements

| Model | VRAM (full fine-tune) | VRAM (LoRA) |
|-------|----------------------|-------------|
| Qwen 2.5 7B | 24GB | 8GB |
| Llama 3.1 8B | 24GB | 10GB |
| Mistral 7B | 16GB | 8GB |

For LoRA fine-tuning, a GPU with 8GB VRAM (RTX 3060/4060) is sufficient.

## Testing Your Fine-Tuned Model

After fine-tuning, test with:

1. **Novel commands** the model hasn't seen in training
2. **Error scenarios** - simulate failures and check recovery
3. **Plan execution** - give multi-step tasks
4. **Multilingual** - test in Spanish if applicable
5. **JSON format** - verify output is always valid JSON

## Model Integration with Delux

After fine-tuning:

```bash
# Add to Delux config
delux /model add delux-finetuned ollama http://localhost:11434/v1

# Set as default
delux /model 0  # or whatever index it gets
```

Or in `delux.config.json`:

```json
{
  "models": [
    {
      "name": "delux-finetuned",
      "provider": "ollama",
      "api_base": "http://localhost:11434/v1",
      "model": "delux-agent"
    }
  ]
}
```
