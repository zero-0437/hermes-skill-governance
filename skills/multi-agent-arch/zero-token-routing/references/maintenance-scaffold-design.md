# Route-Map Maintenance Scaffold Design

## Three CLI Entry Points

### hermes-agent-add

Creates a new sub-agent with all necessary files:

```
hermes-agent-add <agent-name> \
  --priority <n> \
  --condition "<trigger condition>" \
  --description "<brief description>" \
  --model "<model>" (optional) \
  --toolsets "<toolset list>" (optional) \
  --skills "<cat1:skill1,skill2;cat2:skill3>" (optional)
```

**Automated steps:**
1. Validate agent-name uniqueness (against route-map/index.yaml + profiles/ + skills/)
2. Create `route-map/routes/<agent>.yaml` from template (2-4 placeholder rules)
3. Insert into `route-map/index.yaml` agents section
4. Create `skill-map.yaml` placeholder entry (1 category + 1 skill)
5. Create `profiles/<agent>/config.yaml` (inherits main config, overrides model/toolsets)
6. Create `profiles/<agent>/.placeholder` (marks SOUL.md as TODO)
7. Update main SOUL.md binding table (auto-detect layer from skill-map)
8. Run `rebuild-cache.py` → .skill-cache.json + allowed-skills.md
9. Run `validate-route-map.py` + `validate-skill-map.py`
10. Output: success report + "Please edit profiles/<agent>/SOUL.md"

**Manual step:** SOUL.md design (Agent persona, boundaries, rules)

### hermes-skill-add

Registers a new skill under an existing agent:

```
hermes-skill-add --agent <agent-name> \
  --category "<category name>" \
  --name "<skill-name>" \
  --layer <1|2|3|4> \
  --load <auto|manual> \
  [--intentional] \
  [--add-route]           # optionally add a route rule too
  [--route-pattern "..."] \
  [--route-weight <0.0-2.0>]
```

**Automated steps:**
1. Validate skill-name uniqueness (skill-map.yaml global uniqueness)
2. Append to skill-map.yaml under target agent's categories
3. If --add-route: append to route-map/routes/<agent>.yaml
4. Update SOUL.md binding table (auto/manual deduction)
5. Run rebuild-cache.py
6. Run validate-skill-map.py
7. Output: success report + "Please create skills/<skill-name>/SKILL.md"

**Manual step:** SKILL.md content (implementation document)

### hermes-route-add

Adds a routing rule to an existing agent:

```
hermes-route-add --agent <agent-name> \
  --type <keyword|phrase|regex> \
  --pattern "<match pattern>" \
  --weight <0.0-2.0> \
  --skills "<skill1,skill2>" (optional) \
  [--neg-weight]           # flag as negative false-match protection
```

**Fully automated** (~95%) — no manual content required.

## Shared Library Modules

| Module | Purpose |
|--------|---------|
| `_yaml_ops.py` | ruamel YAML read/append/insert (preserves comments) |
| `_templates.py` | Jinja2 templates for route files, profiles, configs |
| `_validation.py` | Conflict detection (name uniqueness, schema version, reference integrity) |
| `_binding_table.py` | SOUL.md markdown table parser + updater |

## Transaction Safety

All three CLIs implement all-or-nothing:

1. Backup affected files to `/tmp/<ts>/backup/`
2. Execute change sequence
3. If any step fails → restore from backup, output failure detail
4. If all succeed → run validate-route-map.py + validate-skill-map.py
5. If validation fails → rollback + output failure detail
6. If validation passes → commit, output success report

## Governance Red Lines (must block)

- route-map/index.yaml references non-existent routes/*.yaml → BLOCK
- route-map/rules skills field references unknown skill-map entry → BLOCK
- profiles/<agent>/ directory exists but has no SOUL.md → BLOCK
- rebuild-cache.py not run (stale cache) → BLOCK
- schema_version mismatch between route-map and skill-map → BLOCK

## Estimated Implementation

| Module | Est. hours |
|--------|:----------:|
| _yaml_ops.py | 2-3 |
| _templates.py | 1-2 |
| _validation.py | 1-2 |
| _binding_table.py | 1-2 |
| hermes-agent-add CLI | 2-3 |
| hermes-skill-add CLI | 1-2 |
| hermes-route-add CLI | 0.5-1 |
| Rollback/transaction | 1-2 |
| Tests | 2-3 |
| **Total** | **11-20** |
