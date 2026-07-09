"""Async-compatible thread runner for vidapi.

Replaces the Tkinter-specific thread_runner.py with asyncio.Queue-based
callback dispatch for use in FastAPI background tasks.
"""

from __future__ import annotations

import asyncio
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class AsyncThreadRunner:
    """Runs synchronous callables in a thread pool with async-friendly callback marshaling.

    All callbacks are delivered via asyncio.Queue to the calling async context.
    """

    def __init__(self, executor: ThreadPoolExecutor | None = None) -> None:
        self.executor = executor
        self._cancel_event = threading.Event()
        self._own_executor = executor is None
        if self._own_executor:
            self.executor = ThreadPoolExecutor(max_workers=1)

    async def run(
        self,
        target: Callable[..., T],
        *args: Any,
        progress_callback: Callable[[float, str], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        found_callback: Callable[..., None] | None = None,
        done_callback: Callable[[bool], None] | None = None,
        **kwargs: Any,
    ) -> T:
        """Run target in thread pool with callback injection.

        Callbacks are marshaled to the async context via asyncio.Queue.
        """
        self._cancel_event.clear()

        # Queues for callback events from the thread
        progress_queue: asyncio.Queue[tuple[float, str]] = asyncio.Queue()
        log_queue: asyncio.Queue[str] = asyncio.Queue()
        status_queue: asyncio.Queue[str] = asyncio.Queue()
        found_queue: asyncio.Queue[tuple] = asyncio.Queue()
        done_queue: asyncio.Queue[bool] = asyncio.Queue()
        error_queue: asyncio.Queue[Exception] = asyncio.Queue()
        result_queue: asyncio.Queue[T] = asyncio.Queue()

        def marshal_progress(percent: float, message: str) -> None:
            if progress_callback:
                asyncio.get_running_loop().call_soon_threadsafe(
                    progress_queue.put_nowait, (percent, message)
                )

        def marshal_log(msg: str) -> None:
            if log_callback:
                asyncio.get_running_loop().call_soon_threadsafe(
                    log_queue.put_nowait, msg
                )

        def marshal_status(msg: str) -> None:
            if status_callback:
                asyncio.get_running_loop().call_soon_threadsafe(
                    status_queue.put_nowait, msg
                )

        def marshal_found(*args: Any) -> None:
            if found_callback:
                asyncio.get_running_loop().call_soon_threadsafe(
                    found_queue.put_nowait, args
                )

        def marshal_done(ok: bool) -> None:
            if done_callback:
                asyncio.get_running_loop().call_soon_threadsafe(
                    done_queue.put_nowait, ok
                )

        # Inject marshaled callbacks into kwargs for the target
        thread_kwargs = dict(kwargs)
        if progress_callback:
            thread_kwargs["progress_callback"] = marshal_progress
        if log_callback:
            thread_kwargs["log_callback"] = marshal_log
        if status_callback:
            thread_kwargs["status_callback"] = marshal_status
        if found_callback:
            thread_kwargs["found_callback"] = marshal_found
        if done_callback:
            thread_kwargs["done_callback"] = marshal_done

        loop = asyncio.get_running_loop()

        def wrapped_target() -> None:
            try:
                result = target(*args, **thread_kwargs)
                loop.call_soon_threadsafe(result_queue.put_nowait, result)
            except Exception as exc:
                tb = traceback.format_exc()
                loop.call_soon_threadsafe(error_queue.put_nowait, exc)
                loop.call_soon_threadsafe(log_queue.put_nowait, f"ThreadRunner error: {exc}\n{tb}")

        # Submit to thread pool
        future = self.executor.submit(wrapped_target)

        # Drain queues and invoke callbacks
        while not future.done():
            done, _ = await asyncio.wait(
                [
                    asyncio.create_task(progress_queue.get()),
                    asyncio.create_task(log_queue.get()),
                    asyncio.create_task(status_queue.get()),
                    asyncio.create_task(found_queue.get()),
                    asyncio.create_task(done_queue.get()),
                    asyncio.create_task(error_queue.get()),
                    asyncio.create_task(result_queue.get()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                item = task.result()
                if task is progress_queue.get:
                    await progress_callback(item[0], item[1])
                elif task is log_queue.get:
                    await log_callback(item)
                elif task is status_queue.get:
                    await status_callback(item)
                elif task is found_queue.get:
                    await found_callback(*item)
                elif task is done_queue.get:
                    await done_callback(item)
                elif task is error_queue.get:
                    raise item
                elif task is result_queue.get:
                    return item

        # One final drain in case result arrived just as future completed
        try:
            return result_queue.get_nowait()
        except asyncio.QueueEmpty:
            if not error_queue.empty():
                raise error_queue.get_nowait()
            raise RuntimeError("Thread completed without result or error")

    def cancel(self) -> None:
        """Signal cancellation to the running thread."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def shutdown(self, wait: bool = True) -> None:
        if self._own_executor and self.executor:
            self.executor.shutdown(wait=wait)


class SessionThreadRunner(AsyncThreadRunner):
    """Specialized runner for DownloadSession and CookieSession.

    Handles the specific callback signatures and provides cancellation
    that works with the session's internal _cancel_requested flag.
    """

    def __init__(self, executor: ThreadPoolExecutor | None = None, session: Any = None) -> None:
        super().__init__(executor)
        self.session = session

    async def run_download_session(
        self,
        progress_callback: Callable[[float, str], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
        done_callback: Callable[[tuple[int, int, int]], None] | None = None,
        error_callback: Callable[[Exception], None] | None = None,
    ) -> tuple[int, int, int]:
        """Run DownloadSession.run() in background thread."""
        return await self.run(
            target=self.session.run,
            progress_callback=progress_callback,
            log_callback=log_callback,
            done_callback=done_callback,
            error_callback=error_callback,
        )

    async def run_cookie_session(
        self,
        status_callback: Callable[[str], None] | None = None,
        found_callback: Callable[[str, str, str | None, str], None] | None = None,
        done_callback: Callable[[bool], None] | None = None,
        error_callback: Callable[[Exception], None] | None = None,
    ) -> bool:
        """Run CookieSession.run() in background thread."""
        await self.run(
            target=self.session.run,
            status_callback=status_callback,
            found_callback=found_callback,
            done_callback=done_callback,
            error_callback=error_callback,
        )
        return True

    def cancel(self) -> None:
        """Cancel both the thread and the session."""
        super().cancel()
        if hasattr(self.session, "cancel"):
            self.session.cancel()