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
| `blogwatcher`     | Monitor RSS/Atom feeds and blogs for updates |
| `cron`            | Schedule and manage recurring tasks |
| `gifgrep`         | Search GIF providers (Tenor/Giphy) with TUI, download, and extract stills/sheets |
| `github`          | Interact with GitHub using the `gh` CLI |
| `memory`          | Two-layer memory system with grep-based recall |
| `qwen-code`       | Free AI code agent CLI (2,000 requests/day) via Qwen OAuth |
| `skill-creator`   | Create new skills |
| `summarize`       | Summarize or extract text/transcripts from URLs, podcasts, YouTube, and local files |
| `tmux`            | Remote-control tmux sessions |
| `weather`         | Get weather info using wttr.in and Open-Meteo |
