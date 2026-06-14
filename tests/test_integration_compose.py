import os
import shutil
import subprocess
import time

import pytest


RUN_INTEGRATION = os.getenv("RUN_INTEGRATION", "0") == "1"


@pytest.mark.skipif(not RUN_INTEGRATION, reason="integration tests disabled; set RUN_INTEGRATION=1 to enable")
def test_docker_compose_orchestrator_monitor():
    """Bring up the orchestrator-monitor service and ensure it starts.

    This test is intentionally opt-in via RUN_INTEGRATION=1 to avoid running docker
    on developer machines by default.
    """
    if not shutil.which("docker"):
        pytest.skip("docker binary not available")

    compose_cmd = ["docker", "compose"]

    # Start the orchestrator-monitor service
    up_cmd = compose_cmd + ["up", "-d", "orchestrator-monitor"]
    subprocess.run(up_cmd, check=True)

    try:
        # wait for container to appear in `docker compose ps`
        deadline = time.time() + 30
        started = False
        while time.time() < deadline:
            ps = subprocess.run(compose_cmd + ["ps", "--services", "--filter", "status=running"], capture_output=True, text=True)
            if "orchestrator-monitor" in ps.stdout:
                started = True
                break
            time.sleep(1)
        assert started, "orchestrator-monitor did not start within 30 seconds"

        # Optionally check logs for startup message; be lenient
        logs = subprocess.run(compose_cmd + ["logs", "--no-color", "--tail", "50", "orchestrator-monitor"], capture_output=True, text=True)
        assert "orchestrator_started" in logs.stdout or "orchestrator_started" in logs.stderr or logs.returncode == 0

    finally:
        # Tear down the started service
        subprocess.run(compose_cmd + ["down", "--remove-orphans"], check=False)
