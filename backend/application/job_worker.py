from __future__ import annotations

import threading
import time

from backend.application.analysis_service import AnalysisService


class JobWorker:
    def __init__(self, *, analysis_service: AnalysisService, poll_sec: float = 2.0):
        self.analysis_service = analysis_service
        self.poll_sec = max(0.5, float(poll_sec))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.analysis_service.recover_stale_running_jobs()
        self._thread = threading.Thread(target=self._loop, name="analysis-job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            handled = self.analysis_service.process_next_queued_job()
            if handled:
                continue
            self._stop.wait(self.poll_sec)

