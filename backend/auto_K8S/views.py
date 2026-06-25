import time

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .tasks import run_installation_task

from .models import Credential, Host, Installation, InstallationTarget, InstallationTemplate
from .serializers import (
    CredentialSerializer,
    HostSerializer,
    InstallationSerializer,
    InstallationTemplateSerializer,
)
from .services import build_inventory_file, get_ansible_repo_root, run_connectivity_check


def get_hosts_missing_credentials(hosts):
    return [
        {
            "id": host.id,
            "name": host.name,
            "ip_address": host.ip_address,
        }
        for host in hosts
        if not host.credential or not host.credential.username
    ]


@api_view(["GET", "POST"])
def hosts_list_create(request):
    if request.method == "GET":
        hosts = Host.objects.all()
        serializer = HostSerializer(hosts, many=True)
        return Response(serializer.data)

    serializer = HostSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
def host_detail(request, id):
    host = get_object_or_404(Host, id=id)

    if request.method == "GET":
        serializer = HostSerializer(host)
        return Response(serializer.data)

    if request.method == "PUT":
        serializer = HostSerializer(host, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    if request.method == "PATCH":
        serializer = HostSerializer(host, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=400)

    host.delete()
    return Response(status=204)

@api_view(["GET"])
def templates_list(request):
    templates = InstallationTemplate.objects.all()
    serializer = InstallationTemplateSerializer(templates, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def installations_list(request):
    installations = Installation.objects.all().order_by("-created_at")
    serializer = InstallationSerializer(installations, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def installation_detail(request, id):
    installation = get_object_or_404(Installation, id=id)
    serializer = InstallationSerializer(installation)
    return Response(serializer.data)


@api_view(["POST"])
def precheck_installation_hosts(request):
    request_started_at = time.perf_counter()
    host_ids = request.data.get("host_ids", [])

    if not host_ids:
        return Response({"message": "host_ids is required."}, status=400)

    hosts = list(Host.objects.filter(id__in=host_ids, enabled=True).select_related("credential"))

    if not hosts:
        return Response({"message": "No valid enabled hosts found."}, status=400)

    hosts_missing_credentials = get_hosts_missing_credentials(hosts)
    if hosts_missing_credentials:
        return Response(
            {
                "message": "Some selected hosts are missing credentials.",
                "hosts_missing_credentials": hosts_missing_credentials,
            },
            status=400,
        )

    inventory_path = build_inventory_file(hosts)
    inventory_content = inventory_path.read_text(encoding="utf-8")
    ansible_repo_root = get_ansible_repo_root()

    result, metadata = run_connectivity_check(
        repo_root=ansible_repo_root,
        inventory_path=inventory_path,
        expected_hosts=[host.name for host in hosts],
    )

    total_request_seconds = round(time.perf_counter() - request_started_at, 3)
    connectivity = metadata["connectivity"]
    reachable_hosts = [item for item in connectivity if item["status"] == "success"]
    unreachable_hosts = [item for item in connectivity if item["status"] != "success"]

    response_status = 200 if result.returncode == 0 else 400

    return Response(
        {
            "message": "SSH connectivity check completed." if result.returncode == 0 else "SSH connectivity check failed for one or more hosts.",
            "command": metadata["command"],
            "repo_root": str(ansible_repo_root),
            "inventory_path": str(inventory_path),
            "inventory_content": inventory_content,
            "timings": {
                "ssh_check_seconds": metadata["execution_seconds"],
                "total_request_seconds": total_request_seconds,
            },
            "summary": {
                "selected_hosts": len(hosts),
                "reachable_hosts": len(reachable_hosts),
                "failed_hosts": len(unreachable_hosts),
            },
            "connectivity": connectivity,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
        status=response_status,
    )


@api_view(["POST"])
def launch_installation(request):
    template_id = request.data.get("template_id")
    host_ids = request.data.get("host_ids", [])

    if not template_id:
        return Response({"message": "template_id is required."}, status=400)

    if not host_ids:
        return Response({"message": "host_ids is required."}, status=400)

    template = get_object_or_404(InstallationTemplate, id=template_id)
    hosts = list(Host.objects.filter(id__in=host_ids, enabled=True).select_related("credential"))

    if not hosts:
        return Response({"message": "No valid enabled hosts found."}, status=400)

    hosts_missing_credentials = get_hosts_missing_credentials(hosts)
    if hosts_missing_credentials:
        return Response(
            {
                "message": "Some selected hosts are missing credentials.",
                "hosts_missing_credentials": hosts_missing_credentials,
            },
            status=400,
        )

    installation = Installation.objects.create(
        template=template,
        status=Installation.Status.PENDING,
    )

    for host in hosts:
        InstallationTarget.objects.create(
            installation=installation,
            host=host,
            status=InstallationTarget.Status.PENDING,
        )

    celery_result = run_installation_task.delay(installation.id)

    return Response(
        {
            "installation_id": installation.id,
            "celery_task_id": celery_result.id,
            "status": installation.status,
            "message": "Installation queued successfully.",
        },
        status=202,
    )
#credentials CRUD
@api_view(["GET", "POST"])
def credentials_list(request):
    if request.method == "GET":
        credentials = Credential.objects.all()
        serializer = CredentialSerializer(credentials, many=True)
        return Response(serializer.data, status=200)

    serializer = CredentialSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=201)
    return Response(serializer.errors, status=400)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
def credential_detail(request, id):
    credential = get_object_or_404(Credential, id=id)

    if request.method == "GET":
        serializer = CredentialSerializer(credential)
        return Response(serializer.data, status=200)

    if request.method == "PUT":
        serializer = CredentialSerializer(credential, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    if request.method == "PATCH":
        serializer = CredentialSerializer(credential, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=200)
        return Response(serializer.errors, status=400)

    credential.delete()
    return Response(status=204)
