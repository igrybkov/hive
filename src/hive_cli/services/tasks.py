"""Agent task file data layer: paths, templates, read/write/delete.

Moved from commands/task.py:17-199 (A0 step 6), dropping the leading
underscore on the pure path/dir helpers now that they're cross-module
service functions. `_show_task`/`show_all_tasks`/`show_task` print, so
they stay in commands/task.py; `write_task`/`ensure_task_template`/
`delete_task` are new names for the non-printing halves of
`set_task`/`edit_task`/`clear_task`.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def get_tasks_dir(main_repo: Path) -> Path:
    """Get the tasks directory path.

    Args:
        main_repo: Path to main repository.

    Returns:
        Path to tasks directory.
    """
    return main_repo / ".claude" / "local-agents" / "tasks"


def get_task_file(main_repo: Path, agent_id: str) -> Path:
    """Get task file path for an agent.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        Path to task file.
    """
    return get_tasks_dir(main_repo) / f"agent-{agent_id}.md"


def ensure_tasks_dir(main_repo: Path) -> Path:
    """Ensure the tasks directory exists.

    Args:
        main_repo: Path to main repository.

    Returns:
        Path to tasks directory.
    """
    tasks_dir = get_tasks_dir(main_repo)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    return tasks_dir


def write_task(main_repo: Path, agent_id: str, task_content: str) -> Path:
    """Write (create or replace) the task file for an agent.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.
        task_content: Task description.

    Returns:
        Path to the written task file.
    """
    ensure_tasks_dir(main_repo)
    task_file = get_task_file(main_repo, agent_id)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    content = f"""# Agent {agent_id} Task

{task_content}

---
*Assigned: {timestamp}*
"""
    task_file.write_text(content)
    return task_file


def ensure_task_template(main_repo: Path, agent_id: str) -> Path:
    """Return the task file for an agent, seeding a template if missing.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        Path to the (now-existing) task file.
    """
    ensure_tasks_dir(main_repo)
    task_file = get_task_file(main_repo, agent_id)

    if not task_file.exists():
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        template = f"""# Agent {agent_id} Task

[Describe the task here]

## Acceptance Criteria

- [ ] Criterion 1
- [ ] Criterion 2

## Notes

---
*Assigned: {timestamp}*
"""
        task_file.write_text(template)

    return task_file


def delete_task(main_repo: Path, agent_id: str) -> bool:
    """Delete the task file for an agent.

    Args:
        main_repo: Path to main repository.
        agent_id: Agent identifier.

    Returns:
        True if a file was deleted, False if it didn't exist.
    """
    task_file = get_task_file(main_repo, agent_id)
    if task_file.exists():
        task_file.unlink()
        return True
    return False
