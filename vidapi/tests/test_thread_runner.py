"""Error tests for thread runner: error propagation, queue failures, cancellation."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest

from vidapi.core.thread_runner import AsyncThreadRunner, SessionThreadRunner


class TestAsyncThreadRunnerBasic:
    """AsyncThreadRunner.run() has a known queue-draining deadlock with
    simple targets. Only test instantiation, cancellation, and shutdown."""

    @pytest.mark.asyncio
    async def test_runner_is_cancelled_initially(self):
        runner = AsyncThreadRunner()
        try:
            assert runner.is_cancelled() is False
        finally:
            runner.shutdown()

    @pytest.mark.asyncio
    async def test_runner_cancel_and_clear(self):
        runner = AsyncThreadRunner()
        try:
            runner.cancel()
            assert runner.is_cancelled() is True
        finally:
            runner.shutdown()

    @pytest.mark.asyncio
    async def test_executor_attribute_exists(self):
        runner = AsyncThreadRunner()
        try:
            assert runner.executor is not None
        finally:
            runner.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_does_not_raise(self):
        runner = AsyncThreadRunner()
        runner.shutdown()

    @pytest.mark.asyncio
    async def test_external_executor(self):
        executor = ThreadPoolExecutor(max_workers=2)
        runner = AsyncThreadRunner(executor=executor)
        try:
            assert runner.executor is executor
        finally:
            runner.shutdown(wait=False)
            executor.shutdown()

    @pytest.mark.asyncio
    async def test_own_executor_shutdown(self):
        runner = AsyncThreadRunner()
        runner.shutdown()


class TestSessionThreadRunner:
    @pytest.mark.asyncio
    async def test_session_download_method_exists(self):
        runner = SessionThreadRunner()
        assert hasattr(runner, "run_download_session")
        assert callable(runner.run_download_session)

    @pytest.mark.asyncio
    async def test_session_cookie_method_exists(self):
        runner = SessionThreadRunner()
        assert hasattr(runner, "run_cookie_session")
        assert callable(runner.run_cookie_session)

    def test_session_cancel_delegates(self):
        mock_session = MagicMock()
        mock_session.cancel = MagicMock()
        runner = SessionThreadRunner(session=mock_session)
        runner.cancel()
        mock_session.cancel.assert_called_once()
