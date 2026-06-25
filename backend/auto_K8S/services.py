import re
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import Installation, InstallationTarget
from .runners import get_runner


def build_inventory_file(hosts):
    inventory_lines = [
        "all:",
        "  children:",
        "    selected_hosts:",
        "      hosts:",
    ]

    for host in hosts:
        inventory_lines.append(f"        {host.name}:")
        inventory_lines.append(f"          ansible_host: {host.ip_address}")
        inventory_lines.append(f"          ansible_port: {host.ssh_port}")

        if host.credential:
            inventory_lines.append(f"          ansible_user: \"{host.credential.username}\"")

            if host.credential.auth_type == "password" and host.credential.password:
                inventory_lines.append(f"          ansible_password: \"{host.credential.password}\"")

            if host.credential.become_password:
                inventory_lines.append(
                    f"          ansible_become_password: \"{host.credential.become_password}\""
                )

    temp_dir = tempfile.mkdtemp()
    inventory_path = Path(temp_dir) / "inventory.yml"
    inventory_path.write_text("\n".join(inventory_lines) + "\n", encoding="utf-8")

    return inventory_path


def parse_task_profile(stdout_text):
    tasks = []
    in_tasks_recap = False

    for raw_line in stdout_text.splitlines():
        line = raw_line.rstrip()

        if "TASKS RECAP" in line:
            in_tasks_recap = True
            continue

        if "PLAYBOOK RECAP" in line:
            break

        if not in_tasks_recap:
            continue

        match = re.match(r"^(?P<name>.+?)-+\s+(?P<seconds>\d+\.\d+)s$", line.strip())
        if not match:
            continue

        tasks.append(
            {
                "name": match.group("name").strip(),
                "seconds": float(match.group("seconds")),
            }
        )

    return tasks


def build_bottleneck_hints(task_profile):
    hints = []
    top_tasks = task_profile[:5]

    for task in top_tasks:
        task_name = task["name"].lower()
        seconds = task["seconds"]

        if "install kubernetes packages" in task_name or "install containerd package" in task_name:
            hints.append(
                f"Package installation took {seconds:.2f}s. This usually means repository download speed or VM internet access is slow."
            )
        elif "pull kubernetes images" in task_name:
            hints.append(
                f"Image pull took {seconds:.2f}s. This is normally slow on first runs because kubeadm downloads container images."
            )
        elif "run kubeadm init" in task_name:
            hints.append(
                f"kubeadm init took {seconds:.2f}s. API server startup, etcd bootstrap, or CPU/RAM pressure on the VM may be the bottleneck."
            )
        elif "wait for calico-node rollout" in task_name or "wait for coredns rollout" in task_name:
            hints.append(
                f"CNI rollout wait took {seconds:.2f}s. This usually points to Calico startup, networking, or image pull delays."
            )
        elif "wait for node to become ready" in task_name:
            hints.append(
                f"Node readiness wait took {seconds:.2f}s. kubelet, CNI initialization, or control-plane health is likely delaying completion."
            )
        elif "gathering facts" in task_name:
            hints.append(
                f"Fact gathering took {seconds:.2f}s. SSH connection setup, DNS resolution, or remote Python startup may be slow."
            )

    return hints


def get_ansible_repo_root():
    configured_repo_root = getattr(settings, "ANSIBLE_REPO_ROOT", "").strip()
    candidates = []

    if configured_repo_root:
        candidates.append(Path(configured_repo_root))

    candidates.extend(
        [
            Path(settings.BASE_DIR) / "backend" / "Playbooks" / "k8s-single-noded" / "k8s-single-noded",
            Path(settings.BASE_DIR) / "backend" / "Playbooks" / "k8s-single-noded",
            Path(settings.BASE_DIR) / "ansible" / "k8s-single-noded",
        ]
    )

    for candidate in candidates:
        if (candidate / "ansible.cfg").exists() and (candidate / "playbooks").exists():
            return candidate

    raise FileNotFoundError(
        "Unable to locate the Ansible repo root. Expected a folder containing "
        "'ansible.cfg' and 'playbooks'. Set ANSIBLE_REPO_ROOT in your environment "
        "to avoid controller-specific path guesses."
    )


def parse_connectivity_output(stdout_text, stderr_text, expected_hosts=None):
    statuses = {}
    patterns = [
        re.compile(r"^(?P<host>\S+)\s+\|\s+(?P<status>SUCCESS|FAILED|UNREACHABLE)!?\s+=>"),
        re.compile(r"^fatal:\s+\[(?P<host>[^\]]+)\]:\s+(?P<status>FAILED|UNREACHABLE)!?\s+=>"),
    ]

    def register_status(line):
        for pattern in patterns:
            match = pattern.match(line)
            if not match:
                continue

            statuses[match.group("host")] = {
                "host": match.group("host"),
                "status": match.group("status").lower(),
                "detail": line,
            }
            return True

        return False

    for raw_line in stdout_text.splitlines():
        line = raw_line.strip()
        register_status(line)

    for raw_line in stderr_text.splitlines():
        line = raw_line.strip()
        register_status(line)

    if expected_hosts:
        fallback_detail = (
            stderr_text.strip()
            or stdout_text.strip()
            or "No host-level status was returned by Ansible."
        )
        fallback_detail = fallback_detail.splitlines()[0]

        for host_name in expected_hosts:
            if host_name not in statuses:
                statuses[host_name] = {
                    "host": host_name,
                    "status": "failed",
                    "detail": fallback_detail,
                }

    return list(statuses.values())


def run_connectivity_check(repo_root, inventory_path, expected_hosts=None):
    runner = get_runner()
    result, metadata = runner.run_connectivity_check(
        repo_root=repo_root,
        inventory_path=inventory_path,
    )
    metadata["connectivity"] = parse_connectivity_output(
        result.stdout,
        result.stderr,
        expected_hosts=expected_hosts,
    )

    return result, metadata


def run_playbook(repo_root, playbook_relative_path, inventory_path):
    runner = get_runner()
    result, metadata = runner.run_playbook(
        repo_root=repo_root,
        playbook_relative_path=playbook_relative_path,
        inventory_path=inventory_path,
    )
    task_profile = parse_task_profile(result.stdout)
    task_profile.sort(key=lambda item: item["seconds"], reverse=True)

    metadata.update(
        {
            "task_profile": task_profile,
            "slow_tasks": task_profile[:5],
            "bottleneck_hints": build_bottleneck_hints(task_profile),
        }
    )

    return result, metadata


def execute_installation(installation_id):
    installation = Installation.objects.get(id=installation_id)
    targets = list(
        InstallationTarget.objects.filter(installation=installation).select_related(
            "host", "host__credential"
        )
    )
    hosts = [target.host for target in targets]

    installation.status = Installation.Status.RUNNING
    installation.started_at = timezone.now()
    installation.save(update_fields=["status", "started_at", "updated_at"])

    for target in targets:
        target.status = InstallationTarget.Status.RUNNING
        target.save(update_fields=["status", "updated_at"])

    try:
        inventory_started_at = time.perf_counter()
        inventory_path = build_inventory_file(hosts)
        inventory_content = inventory_path.read_text(encoding="utf-8")
        inventory_build_seconds = round(time.perf_counter() - inventory_started_at, 3)

        repo_discovery_started_at = time.perf_counter()
        ansible_repo_root = get_ansible_repo_root()
        repo_discovery_seconds = round(time.perf_counter() - repo_discovery_started_at, 3)

        result, playbook_metadata = run_playbook(
            repo_root=ansible_repo_root,
            playbook_relative_path=installation.template.playbook_path,
            inventory_path=inventory_path,
        )

        combined_output = f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}"

        if result.returncode == 0:
            installation.status = Installation.Status.SUCCESS
            target_status = InstallationTarget.Status.SUCCESS
        else:
            installation.status = Installation.Status.FAILED
            target_status = InstallationTarget.Status.FAILED

        installation.finished_at = timezone.now()
        installation.save(update_fields=["status", "finished_at", "updated_at"])

        for target in targets:
            target.status = target_status
            target.output = combined_output
            target.save(update_fields=["status", "output", "updated_at"])

        return {
            "installation_id": installation.id,
            "status": installation.status,
            "return_code": result.returncode,
            "inventory_content": inventory_content,
            "timings": {
                "inventory_build_seconds": inventory_build_seconds,
                "repo_discovery_seconds": repo_discovery_seconds,
                "playbook_execution_seconds": playbook_metadata["execution_seconds"],
            },
            "task_profile": playbook_metadata["task_profile"],
            "slow_tasks": playbook_metadata["slow_tasks"],
            "bottleneck_hints": playbook_metadata["bottleneck_hints"],
        }

    except Exception as exc:
        installation.status = Installation.Status.FAILED
        installation.finished_at = timezone.now()
        installation.save(update_fields=["status", "finished_at", "updated_at"])

        for target in targets:
            target.status = InstallationTarget.Status.FAILED
            target.output = str(exc)
            target.save(update_fields=["status", "output", "updated_at"])

        raise
