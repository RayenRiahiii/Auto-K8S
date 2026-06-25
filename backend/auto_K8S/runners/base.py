import subprocess
from pathlib import Path


class BaseRunner:
    def run_playbook(self, repo_root, playbook_relative_path, inventory_path):
        raise NotImplementedError

    def run_connectivity_check(self, repo_root, inventory_path):
        raise NotImplementedError

    @staticmethod
    def validate_repo_layout(repo_root):
        repo_root = Path(repo_root)
        ansible_config_path = repo_root / "ansible.cfg"
        roles_path = repo_root / "roles"

        if not ansible_config_path.exists():
            raise FileNotFoundError(f"Ansible config not found: {ansible_config_path}")
        if not roles_path.exists():
            raise FileNotFoundError(f"Roles path not found: {roles_path}")

        return ansible_config_path, roles_path

    @staticmethod
    def run_subprocess(command, cwd=None, env=None):
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            shell=False,
        )
