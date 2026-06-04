# my-skills

## Core Principles

YAGNI · KISS · DRY · Brutal honesty over diplomacy · Challenge every assumption

## Structure

```
.claude/
  agents/     # sub-agents spawned by commands
  commands/   # slash commands (/plan, /cook, /fix, /learn, /code-review, /docs-fe)
  skills/     # behavioral guidance loaded by skill system
  rules/      # path-scoped design principles (lazy-load)
  hooks/      # shell hooks for lifecycle events
```

## Rules

Path-scoped — each file loads only when touching its directory:

| File | Activates for |
|------|---------------|
| `.claude/rules/agents.md` | `.claude/agents/**` |
| `.claude/rules/commands.md` | `.claude/commands/**` |
| `.claude/rules/skills.md` | `.claude/skills/**` |

## Config

`.ck.json` — project-level config for hooks and pipeline behavior:
- `cavemanMode` — thresholds for auto-triggering caveman terse mode
- `artifactFolding` — thresholds for folding large tool outputs
- `simplify.threshold` — LOC/file-count limits before auto-simplify triggers
- `codingLevel` — response verbosity (-1 = auto)

## Personal overrides

`CLAUDE.local.md` (gitignored) — personal preferences that shouldn't be committed.
