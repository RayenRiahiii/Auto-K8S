import time
from pathlib import Path

from .base import BaseRunner


class LinuxRunner(BaseRunner):
    def build_command_env_prefix(self, repo_root):
        repo_root = Path(repo_root)
        ansible_config_path, roles_path = self.validate_repo_layout(repo_root)

        return {
            "ANSIBLE_CONFIG": str(ansible_config_path),
            "ANSIBLE_ROLES_PATH": str(roles_path),
            "ANSIBLE_CALLBACKS_ENABLED": "ansible.posix.profile_tasks,ansible.posix.timer",
            "ANSIBLE_NOCOLOR": "1",
        }

    def run_connectivity_check(self, repo_root, inventory_path):
        repo_root = Path(repo_root)
        env_overrides = self.build_command_env_prefix(repo_root)
        command = ["ansible", "selected_hosts", "-i", str(Path(inventory_path).resolve()), "-m", "ping"]

        started_at = time.perf_counter()
        result = self.run_subprocess_with_env(command, cwd=repo_root, env_overrides=env_overrides)
        execution_seconds = round(time.perf_counter() - started_at, 3)

        return result, {
            "command": " ".join(command),
            "execution_seconds": execution_seconds,
            "runner_backend": "linux",
            "runner_target": str(repo_root),
        }

    def run_playbook(self, repo_root, playbook_relative_path, inventory_path):
        repo_root = Path(repo_root)
        playbook_path = repo_root / playbook_relative_path
        env_overrides = self.build_command_env_prefix(repo_root)

        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        command = [
            "ansible-playbook",
            "-i",
            str(Path(inventory_path).resolve()),
            playbook_relative_path,
        ]

        started_at = time.perf_counter()
        result = self.run_subprocess_with_env(command, cwd=repo_root, env_overrides=env_overrides)
        execution_seconds = round(time.perf_counter() - started_at, 3)

        return result, {
            "command": " ".join(command),
            "execution_seconds": execution_seconds,
            "runner_backend": "linux",
            "runner_target": str(repo_root),
        }

    @staticmethod
    def run_subprocess_with_env(command, cwd=None, env_overrides=None):
        import os

        env = os.environ.copy()
        env.update(env_overrides or {})

        return BaseRunner.run_subprocess(command, cwd=str(cwd) if isinstance(cwd, Path) else cwd, env=env)
