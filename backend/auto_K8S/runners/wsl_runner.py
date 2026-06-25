import time
from pathlib import Path

from .base import BaseRunner


class WslRunner(BaseRunner):
    def __init__(self, distro_name):
        self.distro_name = distro_name

    @staticmethod
    def windows_to_wsl_path(path):
        path = Path(path).resolve()
        drive = path.drive[0].lower()
        tail = str(path).replace("\\", "/")[2:]
        return f"/mnt/{drive}{tail}"

    def build_ansible_shell_command(self, repo_root, inventory_path, command_suffix):
        repo_root = Path(repo_root)
        ansible_config_path, roles_path = self.validate_repo_layout(repo_root)

        repo_root_wsl = self.windows_to_wsl_path(repo_root)
        ansible_config_path_wsl = self.windows_to_wsl_path(ansible_config_path)
        roles_path_wsl = self.windows_to_wsl_path(roles_path)

        return (
            f"cd '{repo_root_wsl}' && "
            f"ANSIBLE_CONFIG='{ansible_config_path_wsl}' "
            f"ANSIBLE_ROLES_PATH='{roles_path_wsl}' "
            f"ANSIBLE_CALLBACKS_ENABLED='ansible.posix.profile_tasks,ansible.posix.timer' "
            f"ANSIBLE_NOCOLOR='1' "
            f"{command_suffix}"
        )

    def run_connectivity_check(self, repo_root, inventory_path):
        inventory_path_wsl = self.windows_to_wsl_path(inventory_path)
        shell_command = self.build_ansible_shell_command(
            repo_root=repo_root,
            inventory_path=inventory_path,
            command_suffix=f"ansible selected_hosts -i '{inventory_path_wsl}' -m ping",
        )

        started_at = time.perf_counter()
        result = self.run_subprocess(
            ["wsl", "-d", self.distro_name, "sh", "-lc", shell_command],
        )
        execution_seconds = round(time.perf_counter() - started_at, 3)

        return result, {
            "command": shell_command,
            "execution_seconds": execution_seconds,
            "runner_backend": "wsl",
            "runner_target": self.distro_name,
        }

    def run_playbook(self, repo_root, playbook_relative_path, inventory_path):
        repo_root = Path(repo_root)
        playbook_path = repo_root / playbook_relative_path
        inventory_path_wsl = self.windows_to_wsl_path(inventory_path)

        if not playbook_path.exists():
            raise FileNotFoundError(f"Playbook not found: {playbook_path}")

        shell_command = self.build_ansible_shell_command(
            repo_root=repo_root,
            inventory_path=inventory_path,
            command_suffix=f"ansible-playbook -i '{inventory_path_wsl}' '{playbook_relative_path}'",
        )

        started_at = time.perf_counter()
        result = self.run_subprocess(
            ["wsl", "-d", self.distro_name, "sh", "-lc", shell_command],
        )
        execution_seconds = round(time.perf_counter() - started_at, 3)

        return result, {
            "command": shell_command,
            "execution_seconds": execution_seconds,
            "runner_backend": "wsl",
            "runner_target": self.distro_name,
        }
