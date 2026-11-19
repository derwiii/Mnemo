import pytest
import subprocess
import sys
import os
from pathlib import Path

pytest.importorskip('PyQt6.QtNetwork')

from mnemo.ui.single_instance import SingleInstance
from PyQt6.QtTest import QSignalSpy


def test_second_instance_activates_first_and_releases_lock(qapp, tmp_path):
    first = SingleInstance(tmp_path)
    activations = QSignalSpy(first.activated)
    process = None
    try:
        assert first.start()
        script = "from pathlib import Path; import sys; from PyQt6.QtCore import QCoreApplication; from mnemo.ui.single_instance import SingleInstance; app=QCoreApplication([]); instance=SingleInstance(Path(sys.argv[1])); print(instance.start()); instance.close()"
        process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')},
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert len(activations) or activations.wait(1500)
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, stderr
        assert stdout.strip() == b'False'
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        first.close()
    restarted = SingleInstance(tmp_path)
    try:
        assert restarted.start()
    finally:
        restarted.close()
