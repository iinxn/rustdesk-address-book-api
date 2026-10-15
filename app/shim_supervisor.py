"""Shim supervisor: runs app.shim in a background thread, restarts with
bounded backoff, exposes status for /health/ready. No shell, no subprocess."""

import asyncio
import logging
import threading
import time

log = logging.getLogger(__name__)

MAX_RESTARTS = 5
RESTART_WINDOW = 600
BACKOFFS = (1, 2, 4, 8, 16, 30, 60)


class ShimSupervisor:
    def __init__(self, listen: str, upstream: str, id_key: str,
                 max_conns: int, per_ip_per_min: int, diag_msgtypes: bool = False):
        self.listen = listen
        self.upstream = upstream
        self.id_key = id_key
        self.max_conns = max_conns
        self.per_ip_per_min = per_ip_per_min
        self.diag_msgtypes = diag_msgtypes
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._fail_times: list[float] = []
        self._restarts = 0
        self.state = "disabled"

    @property
    def alive(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self.state = "running"
        self._thread = threading.Thread(target=self._serve, name="kx-shim", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        from app.shim import shim as shim_mod
        host, port = self.listen.rsplit(":", 1)
        uh, up = self.upstream.rsplit(":", 1)
        try:
            sign_sk = shim_mod.load_sign_sk(self.id_key)
            gate = shim_mod.Gate(self.max_conns, self.per_ip_per_min)

            async def _run():
                srv = await asyncio.start_server(
                    lambda r, w: shim_mod.handle(
                        r, w, (uh, int(up)), sign_sk, gate, self.diag_msgtypes),
                    host, int(port))
                log.info("shim listening %s -> %s", self.listen, self.upstream)
                async with srv:
                    while not self._stop.is_set():
                        await asyncio.sleep(0.2)
                    srv.close()
                    await srv.wait_closed()

            asyncio.run(_run())
            self.state = "stopped"
        except Exception as e:
            log.error("shim exited: %r", e)
            now = time.monotonic()
            self._fail_times = [t for t in self._fail_times if now - t < RESTART_WINDOW]
            self._fail_times.append(now)
            self.state = "crashed"

    async def watch(self) -> None:
        """Call periodically from the app loop. Bounded restarts, no infinite loop."""
        if self._stop.is_set() or self.state in ("disabled", "stopped", "down"):
            return
        if self.state == "crashed" or not self.alive:
            if len(self._fail_times) > MAX_RESTARTS:
                log.error("shim: too many restarts, giving up")
                self.state = "down"
                return
            delay = BACKOFFS[min(self._restarts, len(BACKOFFS) - 1)]
            self._restarts += 1
            self.state = "restarting"
            log.info("shim: restart #%d in %ss", self._restarts, delay)
            await asyncio.sleep(delay)
            if not self._stop.is_set():
                self.state = "running"
                self._thread = threading.Thread(target=self._serve, name="kx-shim", daemon=True)
                self._thread.start()

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        t = self._thread
        if t is not None:
            t.join(timeout)
            if t.is_alive():
                log.error("shim thread did not stop in %ss (daemon, dies with process)", timeout)

    def status(self) -> dict:
        state = self.state
        if state == "running" and not self.alive:
            state = "restarting"
        return {"state": state, "alive": self.alive, "restarts": self._restarts}
