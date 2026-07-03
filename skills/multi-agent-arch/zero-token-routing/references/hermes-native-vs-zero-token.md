# Hermes Native Delegation vs Zero-Token Route Engine

Comparison facts established during v0.18.0 discussion (2026-07-03).

## Layer Separation

The route engine and Hermes core operate at different layers — they are not
alternatives but complementary components.

| Layer | Owns | Technology |
|-------|------|-----------|
| **Route engine** | *Which agent* to delegate to | YAML rules → Python scoring → agent name |
| **Hermes core** | *How* delegation executes | Built-in `delegate_task`, MoA, `/goal` contracts |
| **Hermes infrastructure** | Gateway, providers, transports | config.yaml, plugins, cron |

## Decision Layer: Routing ("who to delegate to")

| Dimension | Hermes v0.18.0 Native | Route Engine |
|-----------|----------------------|--------------|
| Decision maker | Main agent LLM reasoning | Pure Python + YAML rules |
| Token cost | ~1,500 tokens/decision (think → output) | ~0 tokens (<0.1s CPU) |
| Determinism | ❌ Same input → different output possible | ✅ Deterministic |
| Debuggability | LLM black box (unpredictable) | YAML rules + JSON log |
| Adding new agent | Edit SOUL.md binding table (LLM must re-learn) | `hermes-agent-add` CLI (one command) |
| Rule modification | Change system prompt / SOUL.md (trial and error) | Edit YAML rule file (WYSIWYG) |

## Execution Layer: Delegation ("how to dispatch")

| Dimension | Hermes v0.18.0 Native | Route Engine |
|-----------|----------------------|--------------|
| Single dispatch | `delegate_task` | Same — route engine calls delegate_task |
| Parallel dispatch | ✅ **v0.18.0 new**: background fan-out, merge result | ✅ Returns agent name; main agent can fan-out |
| Chain orchestration | No native chain support | ✅ `chain_executor.py` state machine |
| Verification | ✅ **v0.18.0 new**: evidence ledger + completion contracts | 6-question pre-check + evidence chain requirement |

## Key Insight

The route engine **is not a replacement** for Hermes delegation — it's a thin
layer that sits *above* `delegate_task`:

```
                      ┌─────────────────────┐
                      │  Route Engine        │  ← YAML rules, 0 token
                      │  (which agent?)      │
                      └─────────┬───────────┘
                                │
                                ▼
                      ┌─────────────────────┐
                      │  delegate_task       │  ← Hermes native API
                      │  (v0.18.0 fan-out)  │  ← route engine gains this free
                      └─────────────────────┘
                                │
                                ▼
                      ┌─────────────────────┐
                      │  Sub-agent           │
                      └─────────────────────┘
```

## What v0.18.0 Adds That Benefits the Route Engine

| v0.18.0 Feature | How it helps routing |
|----------------|---------------------|
| Background parallel fan-out | Multiple route-engine dispatches execute in parallel automatically |
| Verification contracts | Sub-agent results verified before returning — complements 6-question pre-check |
| MoA (Mixture of Agents) | Delegated sub-agent can use MoA models if configured |
| Any future delegate_task enhancement | Inherited automatically — no route-map changes needed |

## After Upgrading Hermes

```bash
# Verify routing still works (30s check)
python3 scripts/route_engine.py "修复bug"       # → programmer
python3 scripts/route_engine.py "NAS备份"       # → synology-helper
python3 scripts/route_engine.py "架构设计"       # → pm-agent
```

No route-map changes needed unless the upgrade adds/removes a sub-agent type
that the routing rules reference. Even then, only YAML rules change.
