import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Container,
  Divider,
  Group,
  Progress,
  Radio,
  RingProgress,
  ScrollArea,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconBinaryTree2,
  IconCheck,
  IconClockHour4,
  IconLink,
  IconPlayerPlay,
  IconPlugConnected,
  IconTerminal2,
} from "@tabler/icons-react";

type Host = {
  id: number;
  name: string;
  ip_address: string;
  enabled: boolean;
};

type Template = {
  id: number;
  name: string;
  playbook_path: string;
  description: string;
};

type TimingBlock = {
  inventory_build_seconds?: number;
  repo_discovery_seconds?: number;
  playbook_execution_seconds?: number;
  total_request_seconds?: number;
  ssh_check_seconds?: number;
};

type ConnectivityStatus = {
  host: string;
  status: "success" | "failed" | "unreachable";
  detail: string;
};

type PrecheckResult = {
  message: string;
  command?: string;
  inventory_content?: string;
  timings?: TimingBlock;
  summary?: {
    selected_hosts: number;
    reachable_hosts: number;
    failed_hosts: number;
  };
  connectivity?: ConnectivityStatus[];
  stdout?: string;
  stderr?: string;
};

type LaunchQueuedResponse = {
  installation_id: number;
  celery_task_id?: string;
  status: string;
  message: string;
};

type InstallationTarget = {
  id: number;
  host: number;
  host_name: string;
  status: string;
  output: string;
};

type InstallationDetailResponse = {
  id: number;
  status: "pending" | "running" | "success" | "failed";
  template: number;
  template_name: string;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string;
  updated_at?: string;
  targets: InstallationTarget[];
};

type LaunchResult = {
  installation_id: number;
  status: string;
  message: string;
  stdout?: string;
  stderr?: string;
  rawOutput?: string;
};

type Stage = {
  threshold: number;
  label: string;
  detail: string;
};

const BASE_URL = import.meta.env.VITE_DJANGO_BASE_URL;

const progressStages: Stage[] = [
  {
    threshold: 12,
    label: "Queued for execution",
    detail: "The installation request was accepted and is waiting for the Celery worker to start it.",
  },
  {
    threshold: 32,
    label: "Opening Ansible runner",
    detail: "Celery is starting the execution context and preparing the Ansible run on the controller.",
  },
  {
    threshold: 62,
    label: "Bootstrapping Kubernetes",
    detail: "Ansible is running node preparation, container runtime, and kubeadm tasks on the target.",
  },
  {
    threshold: 92,
    label: "Collecting final result",
    detail: "The installation is finishing and the backend is waiting for the final Ansible output to be stored.",
  },
];

function formatDuration(seconds?: number) {
  if (seconds === undefined) {
    return "-";
  }

  const rounded = Math.round(seconds);
  const minutes = Math.floor(rounded / 60);
  const remainingSeconds = rounded % 60;

  if (minutes === 0) {
    return `${remainingSeconds}s`;
  }

  return `${minutes}m ${remainingSeconds}s`;
}

function formatDurationDetailed(seconds?: number) {
  if (seconds === undefined) {
    return "-";
  }

  return `${formatDuration(seconds)} (${seconds.toFixed(3)}s)`;
}

function extractStdoutStderr(output: string) {
  if (!output) {
    return { stdout: "", stderr: "", rawOutput: "" };
  }

  const stdoutMarker = "STDOUT:\n";
  const stderrMarker = "\n\nSTDERR:\n";

  if (!output.includes(stdoutMarker)) {
    return { stdout: output, stderr: "", rawOutput: output };
  }

  const stdoutStart = output.indexOf(stdoutMarker) + stdoutMarker.length;
  const stderrStart = output.indexOf(stderrMarker);

  if (stderrStart === -1) {
    return {
      stdout: output.slice(stdoutStart).trim(),
      stderr: "",
      rawOutput: output,
    };
  }

  return {
    stdout: output.slice(stdoutStart, stderrStart).trim(),
    stderr: output.slice(stderrStart + stderrMarker.length).trim(),
    rawOutput: output,
  };
}

function buildResultFromInstallation(installation: InstallationDetailResponse): LaunchResult {
  const combinedOutputs = installation.targets
    .map((target) => {
      if (target.output) {
        return `[${target.host_name}] ${target.output}`;
      }

      return `[${target.host_name}] No output captured.`;
    })
    .join("\n\n");

  const parsed = extractStdoutStderr(combinedOutputs);

  return {
    installation_id: installation.id,
    status: installation.status,
    message:
      installation.status === "success"
        ? "Playbook executed successfully."
        : installation.status === "failed"
          ? "Playbook execution failed."
          : "Installation is still in progress.",
    stdout: parsed.stdout,
    stderr: parsed.stderr,
    rawOutput: parsed.rawOutput,
  };
}

export default function RunDeployment() {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selectedHostIds, setSelectedHostIds] = useState<number[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [checkingConnectivity, setCheckingConnectivity] = useState(false);
  const [progress, setProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<LaunchResult | null>(null);
  const [precheckResult, setPrecheckResult] = useState<PrecheckResult | null>(null);
  const [activeInstallationId, setActiveInstallationId] = useState<number | null>(null);
  const [liveStatus, setLiveStatus] = useState<InstallationDetailResponse["status"] | null>(null);
  const loadingStartedAtRef = useRef<number | null>(null);

  const selectionSignature = useMemo(
    () => [...selectedHostIds].sort((a, b) => a - b).join(","),
    [selectedHostIds]
  );

  const activeStage = useMemo(() => {
    for (let index = progressStages.length - 1; index >= 0; index -= 1) {
      if (progress >= progressStages[index].threshold) {
        return progressStages[index];
      }
    }

    return progressStages[0];
  }, [progress]);

  useEffect(() => {
    fetch(`${BASE_URL}/api/hosts/`)
      .then((response) => response.json())
      .then((data) => setHosts(data))
      .catch(() => setError("Failed to load hosts."));
  }, []);

  useEffect(() => {
    fetch(`${BASE_URL}/api/templates/`)
      .then((response) => response.json())
      .then((data) => {
        setTemplates(data);
        if (data.length > 0) {
          setSelectedTemplateId(String(data[0].id));
        }
      })
      .catch(() => setError("Failed to load templates."));
  }, []);

  useEffect(() => {
    setPrecheckResult(null);
  }, [selectionSignature]);

  useEffect(() => {
    if (!loading) {
      setProgress(0);
      setElapsedSeconds(0);
      loadingStartedAtRef.current = null;
      return;
    }

    if (loadingStartedAtRef.current === null) {
      loadingStartedAtRef.current = Date.now();
    }

    const timer = window.setInterval(() => {
      const startedAt = loadingStartedAtRef.current ?? Date.now();
      const elapsed = Math.floor((Date.now() - startedAt) / 1000);
      setElapsedSeconds(elapsed);

      setProgress((current) => {
        if (liveStatus === "pending") {
          return Math.min(Math.max(current, 12), 24);
        }

        if (liveStatus === "running") {
          if (current < 32) return current + 3;
          if (current < 62) return current + 2;
          if (current < 92) return current + 1;
          return Math.min(current + 1, 96);
        }

        return current;
      });
    }, 1000);

    return () => window.clearInterval(timer);
  }, [loading, liveStatus]);

  useEffect(() => {
    if (!loading || activeInstallationId === null) {
      return;
    }

    let cancelled = false;

    async function pollInstallation() {
      try {
        const response = await fetch(`${BASE_URL}/api/installations/${activeInstallationId}/`);
        if (!response.ok) {
          throw new Error("Failed to fetch installation status.");
        }

        const data = (await response.json()) as InstallationDetailResponse;
        if (cancelled) {
          return;
        }

        setLiveStatus(data.status);

        if (data.status === "pending") {
          setProgress((current) => Math.max(current, 12));
        }

        if (data.status === "running") {
          setProgress((current) => Math.max(current, 36));
        }

        if (data.status === "success" || data.status === "failed") {
          setProgress(100);
          setResult(buildResultFromInstallation(data));
          setLoading(false);
          setActiveInstallationId(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Polling failed.");
          setLoading(false);
          setActiveInstallationId(null);
        }
      }
    }

    void pollInstallation();
    const intervalId = window.setInterval(() => {
      void pollInstallation();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, [loading, activeInstallationId]);

  function toggleHost(hostId: number, checked: boolean) {
    if (checked) {
      setSelectedHostIds((prev) => [...prev, hostId]);
      return;
    }

    setSelectedHostIds((prev) => prev.filter((id) => id !== hostId));
  }

  async function runPrecheck(showSuccessState: boolean) {
    if (selectedHostIds.length === 0) {
      setError("Select at least one host before running the SSH verification.");
      return false;
    }

    setCheckingConnectivity(true);
    setError("");

    try {
      const response = await fetch(`${BASE_URL}/api/installations/precheck/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          host_ids: selectedHostIds,
        }),
      });

      const data = (await response.json()) as PrecheckResult;
      setPrecheckResult(data);

      if (!response.ok) {
        throw new Error(data.message || "SSH verification failed.");
      }

      if (showSuccessState) {
        setResult(null);
      }

      return true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "SSH verification failed.");
      return false;
    } finally {
      setCheckingConnectivity(false);
    }
  }

  async function handleLaunch() {
    setLoading(true);
    setProgress(8);
    setError("");
    setResult(null);
    setLiveStatus("pending");

    try {
      const response = await fetch(`${BASE_URL}/api/installations/launch/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          template_id: Number(selectedTemplateId),
          host_ids: selectedHostIds,
        }),
      });

      const data = (await response.json()) as LaunchQueuedResponse;

      if (!response.ok) {
        throw new Error(data.message || "Launch failed.");
      }

      setActiveInstallationId(data.installation_id);
      setProgress(12);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Launch failed.");
      setLoading(false);
      setActiveInstallationId(null);
      setLiveStatus(null);
    }
  }

  return (
    <Container size="xl" px={0}>
      <Stack gap="lg">
        <Card className="console-panel" padding="lg">
          <Group justify="space-between" align="center">
            <div>
              <Group gap="sm" mb={6}>
                <ThemeIcon color="red" variant="light" size="lg" radius="md">
                  <IconTerminal2 size={18} />
                </ThemeIcon>
                <Title order={2}>Run Playbook</Title>
              </Group>
              <Text c="dimmed" mt={4}>
                Optionally verify SSH access first, then launch Kubernetes installation and monitor the queued background job.
              </Text>
            </div>
            <Badge size="lg" color="red" variant="dot">
              WSL + Ansible Execution
            </Badge>
          </Group>
        </Card>

        {error && (
          <Alert color="red" title="Error" variant="light">
            {error}
          </Alert>
        )}

        <Card className="console-panel" padding="lg">
          <Stack>
            <Group gap="sm">
              <ThemeIcon color="red" variant="light">
                <IconBinaryTree2 size={16} />
              </ThemeIcon>
              <Title order={3}>Select Template</Title>
            </Group>

            <Radio.Group value={selectedTemplateId} onChange={setSelectedTemplateId}>
              <Stack gap="xs">
                {templates.map((template) => (
                  <Radio
                    key={template.id}
                    value={String(template.id)}
                    label={`${template.name} - ${template.playbook_path}`}
                  />
                ))}
              </Stack>
            </Radio.Group>
          </Stack>
        </Card>

        <Card className="console-panel" padding="lg">
          <Stack>
            <Group gap="sm">
              <ThemeIcon color="red" variant="light">
                <IconPlugConnected size={16} />
              </ThemeIcon>
              <Title order={3}>Select Hosts</Title>
            </Group>

            {hosts.filter((host) => host.enabled).map((host) => (
              <Checkbox
                key={host.id}
                label={`${host.name} - ${host.ip_address}`}
                checked={selectedHostIds.includes(host.id)}
                onChange={(event) => toggleHost(host.id, event.currentTarget.checked)}
              />
            ))}
          </Stack>
        </Card>

        <Group>
          <Button
            variant="default"
            onClick={() => void runPrecheck(true)}
            loading={checkingConnectivity}
            disabled={selectedHostIds.length === 0 || loading}
            leftSection={<IconLink size={16} />}
          >
            Verify SSH
          </Button>

          <Button
            onClick={handleLaunch}
            loading={loading}
            disabled={!selectedTemplateId || selectedHostIds.length === 0 || checkingConnectivity}
            leftSection={<IconPlayerPlay size={16} />}
          >
            Run Playbook
          </Button>
        </Group>

        {checkingConnectivity && (
          <Alert color="red" variant="light" title="Connectivity Check Running">
            Validating SSH connectivity on the selected hosts before playbook execution.
          </Alert>
        )}

        {precheckResult && (
          <Card className="console-panel" padding="lg">
            <Stack gap="md">
              <Group justify="space-between">
                <Title order={3}>SSH Verification</Title>
                <Badge
                  color={
                    precheckResult.summary?.failed_hosts && precheckResult.summary.failed_hosts > 0
                      ? "red"
                      : "teal"
                  }
                  variant="filled"
                >
                  {precheckResult.summary?.failed_hosts && precheckResult.summary.failed_hosts > 0
                    ? "issues detected"
                    : "ready"}
                </Badge>
              </Group>

              <Group gap="md">
                <Text>Selected: {precheckResult.summary?.selected_hosts ?? 0}</Text>
                <Text>Reachable: {precheckResult.summary?.reachable_hosts ?? 0}</Text>
                <Text>Failed: {precheckResult.summary?.failed_hosts ?? 0}</Text>
                <Text>
                  Duration: {formatDurationDetailed(precheckResult.timings?.ssh_check_seconds)}
                </Text>
              </Group>

              {precheckResult.connectivity && precheckResult.connectivity.length > 0 && (
                <Table withTableBorder striped>
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Host</Table.Th>
                      <Table.Th>Status</Table.Th>
                      <Table.Th>Detail</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {precheckResult.connectivity.map((item) => (
                      <Table.Tr key={item.host}>
                        <Table.Td>{item.host}</Table.Td>
                        <Table.Td>
                          <Badge color={item.status === "success" ? "teal" : "red"} variant="light">
                            {item.status}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{item.detail}</Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              )}
            </Stack>
          </Card>
        )}

        {loading && (
          <Card className="console-panel" padding="lg">
            <Stack gap="lg">
              <Group justify="space-between" align="center">
                <Group gap="md">
                  <RingProgress
                    size={92}
                    thickness={8}
                    roundCaps
                    sections={[{ value: progress, color: "red" }]}
                    label={
                      <Stack gap={0} align="center" justify="center">
                        <Text size="lg" fw={700}>
                          {progress}%
                        </Text>
                        <Text size="10px" c="dimmed">
                          {formatDuration(elapsedSeconds)}
                        </Text>
                      </Stack>
                    }
                  />
                  <div>
                    <Title order={3}>Installation in Progress</Title>
                    <Text c="dimmed" size="sm" mt={4}>
                      {activeStage.label}
                    </Text>
                    <Text c="dimmed" size="sm">
                      {activeStage.detail}
                    </Text>
                    {activeInstallationId !== null && (
                      <Text size="sm" mt={6}>
                        Installation ID: {activeInstallationId}
                      </Text>
                    )}
                    {liveStatus && (
                      <Badge mt={8} color={liveStatus === "running" ? "red" : "gray"} variant="light">
                        backend status: {liveStatus}
                      </Badge>
                    )}
                  </div>
                </Group>
                <Badge color="red" variant="filled">
                  elapsed: {formatDuration(elapsedSeconds)}
                </Badge>
              </Group>

              <Progress value={progress} color="red" size="lg" radius="xl" animated />

              <Table>
                <Table.Tbody>
                  {progressStages.map((stage) => {
                    const completed = progress >= stage.threshold;
                    const current = activeStage.label === stage.label && progress < 100;

                    return (
                      <Table.Tr key={stage.label}>
                        <Table.Td w={50}>
                          <ThemeIcon
                            size="sm"
                            radius="xl"
                            color={completed ? "teal" : current ? "red" : "dark"}
                            variant={completed || current ? "filled" : "light"}
                          >
                            {completed ? (
                              <IconCheck size={12} />
                            ) : current ? (
                              <IconClockHour4 size={12} />
                            ) : (
                              <div />
                            )}
                          </ThemeIcon>
                        </Table.Td>
                        <Table.Td>
                          <Text fw={current ? 700 : 500}>{stage.label}</Text>
                          <Text size="sm" c="dimmed">
                            {stage.detail}
                          </Text>
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Stack>
          </Card>
        )}

        {result && (
          <Card className="console-panel" padding="lg">
            <Stack gap="sm">
              <Group justify="space-between" align="center">
                <Title order={3}>Execution Result</Title>
                <Badge
                  color={result.status === "success" ? "teal" : "red"}
                  variant="filled"
                  size="lg"
                >
                  {result.status}
                </Badge>
              </Group>

              <Group gap="xl">
                <Text>Installation ID: {result.installation_id}</Text>
                <Text>Message: {result.message}</Text>
              </Group>

              {result.rawOutput && (
                <>
                  <Divider />
                  <Title order={5}>Raw Output</Title>
                  <ScrollArea.Autosize mah={220}>
                    <Code block>{result.rawOutput}</Code>
                  </ScrollArea.Autosize>
                </>
              )}

              {result.stdout && (
                <>
                  <Divider />
                  <Title order={5}>Stdout</Title>
                  <ScrollArea.Autosize mah={320}>
                    <Code block>{result.stdout}</Code>
                  </ScrollArea.Autosize>
                </>
              )}

              {result.stderr && (
                <>
                  <Divider />
                  <Title order={5}>Stderr</Title>
                  <ScrollArea.Autosize mah={220}>
                    <Code block>{result.stderr}</Code>
                  </ScrollArea.Autosize>
                </>
              )}

              {result.status === "failed" && !result.rawOutput && (
                <Alert color="red" variant="light">
                  The installation failed, but no output was returned by the API for this run.
                </Alert>
              )}

              {result.status === "success" && !result.rawOutput && (
                <Alert color="teal" variant="light">
                  The installation completed successfully.
                </Alert>
              )}

              {result.status === "failed" && (
                <Alert color="red" variant="light">
                  <Group gap="xs" wrap="nowrap">
                    <IconAlertCircle size={16} />
                    <Text size="sm">
                      The queued task completed, but Ansible returned a failure on the target side.
                    </Text>
                  </Group>
                </Alert>
              )}
            </Stack>
          </Card>
        )}
      </Stack>
    </Container>
  );
}
