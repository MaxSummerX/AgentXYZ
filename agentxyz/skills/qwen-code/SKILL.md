---
name: qwen-code
description: Free AI code agent CLI (2,000 requests/day) via Qwen OAuth. Use when agent needs code understanding, refactoring, test generation, or programming assistance without API costs.
homepage: https://github.com/QwenLM/qwen-code
metadata:
  {
    "agentxyz":
      {
        "emoji": "🤖",
        "requires": { "bins": ["qwen"] },
        "install":
          [
            {
              "id": "npm",
              "kind": "npm",
              "package": "@qwen-code/qwen-code",
              "bins": ["qwen"],
              "label": "Install Qwen Code (npm)",
              "global": true,
            },
            {
              "id": "brew",
              "kind": "brew",
              "package": "qwen-code",
              "bins": ["qwen"],
              "label": "Install Qwen Code (brew)",
            },
          ],
      },
  }
---

# Qwen Code

Open-source AI agent for terminal, optimized for Qwen3-Coder. Use for code understanding, refactoring, and generation.

## Authentication

### Option 1: Qwen OAuth (2,000 free requests/day) - Interactive

```bash
qwen
# Then run: /auth
# Choose Qwen OAuth → browser flow
```

### Option 2: Qwen OAuth - Workspace credentials (recommended for Docker)

**For Docker environments or to skip interactive auth:**

1. **Locally**: Authenticate once with browser flow
   ```bash
   qwen
   /auth  # → complete browser OAuth
   ```

2. **Copy credentials**: Find and copy the OAuth credentials file
   ```bash
   # Usually at ~/.qwen/oauth_creds.json or similar
   cat ~/.qwen/oauth_creds.json
   # or find location: qwen /auth
   ```

3. **Place in workspace**: Put `oauth_creds.json` in your workspace root
   ```bash
   # workspace/oauth_creds.json
   cp ~/.qwen/oauth_creds.json /path/to/workspace/oauth_creds.json
   ```

4. **Agent auto-setup**: On first qwen-code use, the agent will:
   - Detect `workspace/oauth_creds.json`
   - Copy it to `~/.qwen/oauth_creds.json` inside the container
   - Ready to use without interactive auth

**Example:**
```
User: "Install qwen-code credentials from workspace"
Agent: [reads oauth_creds.json]
       [copies to ~/.qwen/oauth_creds.json]
       Qwen OAuth credentials installed from workspace
```

### Option 3: OpenAI-compatible API

```bash
export OPENAI_API_KEY="your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o"
```

## Quick Start

### Interactive mode
```bash
qwen
# Use @file.ts to reference files
```

### Headless mode (for agent)
```bash
qwen -p "explain this code"
qwen -p "refactor function X"
qwen -p "generate tests for module Y"
```

## Session Commands

- `/help` - Display commands
- `/auth` - Switch authentication
- `/clear` - Clear conversation
- `/stats` - Session information
- `/exit` - Exit

## Common Use Cases

### Credentials setup (Docker/Remote)
```bash
# User places oauth_creds.json in workspace
# Agent installs it automatically
```
Ask the agent: "Install qwen-code credentials from workspace/oauth_creds.json"

### Code understanding
```bash
qwen -p "What does this project do?"
qwen -p "Explain the architecture"
qwen -p "How does function X work?"
```

### Code generation
```bash
qwen -p "Generate unit tests for @src/utils.ts"
qwen -p "Create a REST API endpoint"
qwen -p "Add error handling to this function"
```

### Refactoring
```bash
qwen -p "Refactor this to be more readable"
qwen -p "Optimize for performance"
qwen -p "Convert to TypeScript"
```

## Notes

- **First time**: run `qwen` then `/auth` for OAuth setup
- **Docker/Remote**: Place `oauth_creds.json` in workspace, agent will install it
- Credentials cached locally after first auth (usually `~/.qwen/oauth_creds.json`)
- Use `-p` for one-shot mode (avoid interactive)
- Reference files with `@path/to/file`
- Free tier: 2,000 requests/day via Qwen OAuth

## Troubleshooting

If auth fails, run:
```bash
qwen
/auth
```

Choose Qwen OAuth and complete browser flow.
