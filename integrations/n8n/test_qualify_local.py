"""The cancellation fixture is not an n8n runtime qualification."""

import asyncio
import json
import os
import sys
import time
from argparse import Namespace
from pathlib import Path

import pytest
from qualify_local import qualify


@pytest.mark.asyncio
async def test_cancellation_stops_cli_and_child_process(tmp_path):
    marker = tmp_path / "processes.json"
    binary = tmp_path / "waiting-cli"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json,os,pathlib,signal,subprocess,sys,time\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "def stop(*args):\n"
        "    child.wait(timeout=5)\n"
        "    raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        f"pathlib.Path({str(marker)!r}).write_text(json.dumps([os.getpid(),child.pid]))\n"
        "time.sleep(60)\n"
    )
    binary.chmod(0o700)
    output = tmp_path / "cancellation.json"
    task = asyncio.create_task(qualify(Namespace(n8n_binary=str(binary), output=str(output), timeout=60)))
    deadline = time.monotonic() + 5
    while not marker.exists() and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert marker.exists()
    process_ids = json.loads(marker.read_text())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for process_id in process_ids:
        with pytest.raises(ProcessLookupError):
            os.kill(process_id, 0)
    report = json.loads(Path(output).read_text())
    assert report["status"] == "blocked"
    assert report["failure"]["type"] == "CancelledError"
    assert report["source_export_unchanged"] is True
