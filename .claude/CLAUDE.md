# carframe_store — Claude Code setup

Flask + Jinja2 store app. `main.py` = routes, `templates/` = Jinja2, `static/` = assets, `data/` = JSON.

## terces tooling (repo-scoped)

These merge on top of any global `~/.claude` config; nothing here edits global.

- **ponytail** (`ponytail@ponytail`) — minimal-code discipline on every code task. Run the ladder before writing: need it? reuse existing? stdlib/native/dep? one line? then minimum.
- **ui-ux-pro-max** (`ui-ux-pro-max@ui-ux-pro-max-skill`) — any UI/UX work: templates, CSS in `static/`, layout, components.
- **caveman** (`caveman@caveman`) — terse comms. Code/commits/security stay normal.
- **graphify** (`~/.claude/skills/graphify/SKILL.md`, if installed) — repo questions → knowledge graph. `/graphify`.
- **RTK** — token-optimized CLI proxy. Bash `PreToolUse` hook rewrites commands (`git status` → `rtk git status`). Requires the `rtk` binary installed on the machine (`rtk --version`); if absent the hook no-ops.

Plugins auto-install from their marketplaces on first session (see `settings.json`). RTK binary is a per-machine install, not shipped in the repo.
