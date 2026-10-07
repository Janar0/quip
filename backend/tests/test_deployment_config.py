"""Render the actual Compose files to verify deployment configuration."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VOICE_SETTINGS = {
    "QWEN_VOICE_ENABLED": "true",
    "QWEN_REALTIME_ENDPOINT": "https://voice.example.invalid/realtime",
    "QWEN_REALTIME_API_KEY": "configuration-test-key",
    "QWEN_REALTIME_MODEL": "configuration-test-model",
    "QWEN_REALTIME_VIDEO_ENABLED": "true",
}


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI is required")
@pytest.mark.parametrize(
    ("filename", "service"),
    [("docker-compose.yml", "app"), ("docker-compose.dev.yml", "backend")],
)
def test_compose_forwards_voice_configuration(filename, service):
    environment = {
        **os.environ,
        **VOICE_SETTINGS,
        "EXECUTOR_TOKEN": "configuration-test-executor-token",
        "QUIP_IMAGE_TAG": "1" * 40,
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / ".env.example"),
            "-f",
            str(ROOT / filename),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    forwarded = json.loads(result.stdout)["services"][service]["environment"]
    assert {key: forwarded.get(key) for key in VOICE_SETTINGS} == VOICE_SETTINGS
