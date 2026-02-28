# agentxyz Skills
``
This directory contains built-in skills that extend agentxyz's capabilities.

## Skill Format

Each skill is a directory containing a `SKILL.md` file with:
- YAML frontmatter (name, description, metadata)
- Markdown instructions for the agent

## Attribution

These skills are adapted from [OpenClaw](https://github.com/openclaw/openclaw)'s skill system.
The skill format and metadata structure follow OpenClaw's conventions to maintain compatibility.
``
## Available Skills

| Skill             | Description |
|-------------------|-------------|
| `agent-skills`    | Fetch and install agent skills from vercel-labs/agent-skills, anthropics/skills, and other GitHub repositories |
| `cron`            | Schedule and manage recurring tasks |
| `github`          | Interact with GitHub using the `gh` CLI |
| `memory`          | Two-layer memory system with grep-based recall |
| `skill-creator`   | Create new skills |
| `tmux`            | Remote-control tmux sessions |
| `weather`         | Get weather info using wttr.in and Open-Meteo |
