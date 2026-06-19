# Graph Report - .  (2026-05-08)

## Corpus Check
- Corpus is ~22,332 words - fits in a single context window. You may not need a graph.

## Summary
- 346 nodes · 840 edges · 22 communities (14 shown, 8 thin omitted)
- Extraction: 90% EXTRACTED · 10% INFERRED · 0% AMBIGUOUS · INFERRED: 81 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Delux IDE Core|Delux IDE Core]]
- [[_COMMUNITY_LLM Interaction & Agent Logic|LLM Interaction & Agent Logic]]
- [[_COMMUNITY_Configuration & I18n|Configuration & I18n]]
- [[_COMMUNITY_MCP Client & Tools Discovery|MCP Client & Tools Discovery]]
- [[_COMMUNITY_Workspace & Storage Management|Workspace & Storage Management]]
- [[_COMMUNITY_Training & Dataset Handling|Training & Dataset Handling]]
- [[_COMMUNITY_Shell Tools & File IO|Shell Tools & File I/O]]
- [[_COMMUNITY_Template Parsing & Actions|Template Parsing & Actions]]
- [[_COMMUNITY_Sidebar & Terminal UI|Sidebar & Terminal UI]]
- [[_COMMUNITY_Semantic Core Entities|Semantic Core Entities]]
- [[_COMMUNITY_Fine-tuning & Qwen Recommendations|Fine-tuning & Qwen Recommendations]]
- [[_COMMUNITY_Semantic Project Setup|Semantic Project Setup]]
- [[_COMMUNITY_Semantic PS Installer|Semantic PS Installer]]
- [[_COMMUNITY_Semantic Workspace Store|Semantic Workspace Store]]
- [[_COMMUNITY_Semantic Shell Tool|Semantic Shell Tool]]
- [[_COMMUNITY_Semantic I18n|Semantic I18n]]
- [[_COMMUNITY_Semantic Template Parser|Semantic Template Parser]]
- [[_COMMUNITY_Semantic MCP Client|Semantic MCP Client]]
- [[_COMMUNITY_Semantic MCP Store|Semantic MCP Store]]

## God Nodes (most connected - your core abstractions)
1. `DeluxIDE` - 84 edges
2. `MCPClient` - 24 edges
3. `_separator()` - 24 edges
4. `AgentPlan` - 23 edges
5. `Agent` - 20 edges
6. `ToolResult` - 16 edges
7. `PlanExecutor` - 16 edges
8. `Config` - 13 edges
9. `main()` - 13 edges
10. `run_setup()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Export for Fine-tuning` --semantically_similar_to--> `Qwen 2.5 7B Recommendation`  [INFERRED] [semantically similar]
  delux_agent/training.py → docs/fine-tuning.md
- `AgentPlan` --uses--> `AgentPlan`  [INFERRED]
  delux_agent/plan_executor.py → delux_agent/ide.py
- `DeluxIDE` --uses--> `ModelEntry`  [INFERRED]
  delux_agent/ide.py → delux_agent/config.py
- `AgentEvent` --uses--> `Config`  [INFERRED]
  delux_agent/agent.py → delux_agent/config.py
- `AgentStep` --uses--> `Config`  [INFERRED]
  delux_agent/agent.py → delux_agent/config.py

## Hyperedges (group relationships)
- **Agent Core Loop** — agent_agent, plan_executor_planexecutor, contextualizer_contextualizer, ide_deluxide [INFERRED 0.95]
- **MCP Integration** — mcp_client_mcpclient, mcp_store_load_mcp_servers, tools_run_shell [INFERRED 0.95]

## Communities (22 total, 8 thin omitted)

### Community 0 - "Delux IDE Core"
Cohesion: 0.08
Nodes (8): _badge(), DeluxIDE, _is_delicate(), Build a visual progress bar from '3/8' style string., Handle terminal resize — redraw sidebar when terminal width changes., Update sidebar state from current IDE state and redraw., _separator(), _term_width()

### Community 1 - "LLM Interaction & Agent Logic"
Cohesion: 0.06
Nodes (31): Agent, AgentEvent, AgentRunResult, AgentStep, detect_language(), _get_error_reflection(), _get_system_prompt(), Translate text to English using the main model. Returns (translated, original_la (+23 more)

### Community 2 - "Configuration & I18n"
Cohesion: 0.09
Nodes (19): _coerce_model_entry(), Config, default_root(), load_config(), ModelEntry, _read_config_file(), ContextualizedPrompt, Contextualizer (+11 more)

### Community 3 - "MCP Client & Tools Discovery"
Cohesion: 0.11
Nodes (18): MCPClient, MCPError, MCPResource, MCPTool, add_mcp_server(), cache_tools(), discover_tools(), get_enabled_servers() (+10 more)

### Community 4 - "Workspace & Storage Management"
Cohesion: 0.14
Nodes (25): build_parser(), main(), write_config(), _ask(), _ask_int(), _endpoint(), _ensure_v1(), _print_context() (+17 more)

### Community 5 - "Training & Dataset Handling"
Cohesion: 0.15
Nodes (19): In training mode, ask user if the run was good enough to save as a training exam, Restore terminal to canonical (cooked) mode for input() calls., build_training_example(), _categorize(), clear_dataset(), count_dataset_lines(), DatasetStats, ensure_training_dir() (+11 more)

### Community 6 - "Shell Tools & File I/O"
Cohesion: 0.24
Nodes (17): append_file(), call_mcp_tool(), create_skill(), _detect_package_manager(), edit_file(), _enhance_error(), move_file(), read_file() (+9 more)

### Community 7 - "Template Parsing & Actions"
Cohesion: 0.27
Nodes (14): get_action_format_instructions(), get_model_template(), list_templates(), _load_templates_file(), ModelTemplate, parse_action(), ParsedAction, record_successful_strategy() (+6 more)

### Community 8 - "Sidebar & Terminal UI"
Cohesion: 0.22
Nodes (13): _build_progress_bar(), _build_sidebar_rows(), clear_sidebar(), draw_sidebar(), init_split(), Sidebar panel for Delux IDE — right-side info panel style Claude Code.  Layout:, Clear the sidebar area., Initialize terminal for split layout — set scroll region. (+5 more)

### Community 9 - "Semantic Core Entities"
Cohesion: 0.22
Nodes (9): Agent Class, CLI Main, Configuration Class, Contextualizer, Delux IDE, Chat Completion, Plan Executor, Run Setup Wizard (+1 more)

### Community 11 - "Fine-tuning & Qwen Recommendations"
Cohesion: 0.67
Nodes (3): Qwen 2.5 7B Recommendation, Rationale for Qwen, Export for Fine-tuning

## Knowledge Gaps
- **44 isolated node(s):** `Translate text to English using the main model. Returns (translated, original_la`, `Status of a single plan step.`, `In-memory plan for a single prompt execution. Lives only during the run.`, `Return the next pending/failed step, or None if all done.`, `True when no more pending/failed steps remain.` (+39 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `DeluxIDE` connect `Delux IDE Core` to `LLM Interaction & Agent Logic`, `Configuration & I18n`, `MCP Client & Tools Discovery`, `Workspace & Storage Management`, `Training & Dataset Handling`?**
  _High betweenness centrality (0.329) - this node is a cross-community bridge._
- **Why does `AgentPlan` connect `Configuration & I18n` to `Delux IDE Core`, `LLM Interaction & Agent Logic`, `MCP Client & Tools Discovery`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `MCPClient` connect `MCP Client & Tools Discovery` to `Delux IDE Core`, `Configuration & I18n`, `Shell Tools & File I/O`?**
  _High betweenness centrality (0.101) - this node is a cross-community bridge._
- **Are the 11 inferred relationships involving `DeluxIDE` (e.g. with `Agent` and `AgentRunResult`) actually correct?**
  _`DeluxIDE` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `MCPClient` (e.g. with `ToolResult` and `MCPServerEntry`) actually correct?**
  _`MCPClient` has 7 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `AgentPlan` (e.g. with `PlanStepStatus` and `PlanExecution`) actually correct?**
  _`AgentPlan` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 7 inferred relationships involving `Agent` (e.g. with `Config` and `LLMError`) actually correct?**
  _`Agent` has 7 INFERRED edges - model-reasoned connections that need verification._