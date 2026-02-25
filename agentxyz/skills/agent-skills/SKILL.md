---
name: agent-skills
description: Fetch and install agent skills from vercel-labs/agent-skills, anthropics/skills, and other GitHub repositories. Use when the agent needs to add new capabilities from the skills.sh ecosystem.
metadata:
  {
    "agentxyz":
      {
        "emoji": "📦",
        "requires": { "bins": ["git"] },
      },
  }
---

# Agent Skills

Install skills from the **skills.sh ecosystem** (Vercel, Anthropic, and others) into AgentXYZ workspace.

## Available Sources

| Repository | Skills | Description |
|------------|--------|-------------|
| **vercel-labs/agent-skills** | 18+ skills | React, Next.js, Vercel best practices |
| **anthropics/skills** | 15+ skills | Official Anthropic skills (pdf, docx, xlsx, frontend-design, etc.) |
| **obra/superpowers** | 10+ skills | brainstorming, planning, debugging |
| **supabase/agent-skills** | Supabase skills | PostgreSQL, Supabase best practices |

## Quick Start

### Install from Anthropic (Official)

```bash
# Clone with sparse checkout
git clone --depth 1 --filter=blob:none --sparse https://github.com/anthropics/skills.git /tmp/anthropics
cd /tmp/anthropics
git sparse-checkout set skills/pdf

# Move to main skills
cp -r /tmp/anthropics/skills/pdf ~/.agentxyz/skills/

# Cleanup
rm -rf /tmp/anthropics
```

### Install from Vercel Labs

```bash
# Clone repository
git clone --depth 1 --filter=blob:none --sparse https://github.com/vercel-labs/agent-skills.git /tmp/vercel-skills
cd /tmp/vercel-skills
git sparse-checkout set skills/frontend-design

# Move to main
cp -r /tmp/vercel-skills/skills/frontend-design ~/.agentxyz/skills/

# Cleanup
rm -rf /tmp/vercel-skills
```

### Install from Obra (Superpowers)

```bash
# Brainstorming skill
git clone --depth 1 --filter=blob:none --sparse https://github.com/obra/superpowers.git /tmp/obra
cd /tmp/obra
git sparse-checkout set skills/brainstorming
cp -r /tmp/obra/skills/brainstorming ~/.agentxyz/skills/
rm -rf /tmp/obra
```

## Popular Skills

| Skill | Source | Installs | Description |
|-------|--------|-----------|-------------|
| **pdf** | anthropics/skills | 15.1K | PDF processing |
| **docx** | anthropics/skills | 11.6K | DOCX processing |
| **xlsx** | anthropics/skills | 11.4K | Excel processing |
| **pptx** | anthropics/skills | 12.4K | PowerPoint |
| **frontend-design** | anthropics/skills | 71K | Frontend design |
| **brainstorming** | obra/superpowers | 20.2K | Brainstorming |
| **systematic-debugging** | obra/superpowers | 11.2K | Debugging workflow |
| **vercel-react-best-practices** | vercel-labs/agent-skills | 134.8K | React patterns |

## Commands Reference

```bash
# List skills in repository
git clone --depth 1 --filter=blob:none --sparse https://github.com/anthropics/skills.git /tmp/skills
cd /tmp/skills
git sparse-checkout set skills
ls skills/

# Extract specific skill
git sparse-checkout set skills/pdf

# Move to AgentXYZ
cp -r /tmp/skills/skills/pdf/* ~/.agentxyz/skills/pdf/
```

## Workflow

1. **Search** on https://skills.sh for the skill
2. **Find source** repository (e.g., `anthropics/skills/pdf`)
3. **Clone** using sparse checkout
4. **Extract** the specific skill
5. **Move** to `~/.agentxyz/skills/`
6. **Adapt** metadata if needed (`"openclaw"` → `"agentxyz"`)
7. **Verify** it works

## Notes

- Always use `--depth 1 --filter=blob:none --sparse` for fast clones
- Skills from skills.sh use Agent Skills Specification (compatible)
- Check metadata: may need to adapt for AgentXYZ
- Clean up `/tmp/` after installation
- See https://skills.sh for directory
