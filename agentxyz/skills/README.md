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
| `blogwatcher`     | Monitor blogs and RSS/Atom feeds for updates using the blogwatcher CLI |
| `clawhub`         | Search and install skills from ClawHub registry |
| `coding-agent`    | Run Codex CLI, Claude Code, OpenCode, or Pi Coding Agent via background process for programmatic control |
| `cron`            | Schedule and manage recurring tasks |
| `gifgrep`         | Search GIF providers with CLI/TUI, download results, and extract stills/sheets |
| `github`          | Interact with GitHub using the `gh` CLI |
| `memory`          | Two-layer memory system with grep-based recall |
| `notion`          | Notion API for creating and managing pages, databases, and blocks |
| `obsidian`        | Work with Obsidian vaults (plain Markdown notes) and automate via obsidian-cli |
| `qwen-code`       | Free AI code agent CLI (2,000 requests/day) via Qwen OAuth. Use for code understanding, refactoring, test generation, or programming assistance without API costs |
| `skill-creator`   | Create new skills |
| `summarize`       | Summarize URLs, files, and YouTube videos |
| `tavily-research` | Comprehensive research using Tavily with AI-synthesized results and citations |
| `tmux`            | Remote-control tmux sessions |
| `video-frames`    | Extract frames or short clips from videos using ffmpeg |
| `weather`         | Get weather info using wttr.in and Open-Meteo |
