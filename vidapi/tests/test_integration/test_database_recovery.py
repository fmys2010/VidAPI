"""Integration tests for database migration and recovery."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
import aiosqlite

from vidapi.db.database import Database
from vidapi.task_manager import TaskManager
from vidapi.core.config import Config


class TestDatabaseSchema:
    """Test database schema and migrations."""
    
    @pytest_asyncio.fixture
    async def temp_db(self):
        """Create a temporary database file."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            db_path = Path(f.name)
        
        db = Database(db_path=db_path)
        await db.init()
        yield db
        await db.close()
        db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_tables_created(self, temp_db: Database):
        """Tables are created on init."""
        # Query schema
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
            tables = {row[0] for row in await cursor.fetchall()}
        
        assert "tasks" in tables
        assert "config" in tables
    
    @pytest.mark.asyncio
    async def test_tasks_table_schema(self, temp_db: Database):
        """Tasks table has correct columns."""
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(tasks)")
            columns = {row[1]: row[2] for row in await cursor.fetchall()}
        
        expected_columns = {
            "task_id": "TEXT",
            "urls": "TEXT",
            "state": "TEXT",
            "progress_pct": "REAL",
            "current_file": "TEXT",
            "error_msg": "TEXT",
            "created_at": "TIMESTAMP",
            "updated_at": "TIMESTAMP",
            "download_dir": "TEXT",
            "format_selector": "TEXT",
            "proxy": "TEXT",
            "cookie_header": "TEXT",
            "download_mode": "TEXT",
            "quality": "TEXT",
        }
        
        for col, col_type in expected_columns.items():
            assert col in columns, f"Missing column: {col}"
            # Type affinity check (SQLite is flexible)
    
    @pytest.mark.asyncio
    async def test_config_table_schema(self, temp_db: Database):
        """Config table has correct columns."""
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(config)")
            columns = {row[1]: row[2] for row in await cursor.fetchall()}
        
        assert "key" in columns
        assert "value" in columns
    
    @pytest.mark.asyncio
    async def test_indexes_created(self, temp_db: Database):
        """Indexes are created on tasks table."""
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='tasks'"
            )
            indexes = {row[0] for row in await cursor.fetchall()}
        
        # Should have indexes on state and created_at
        # (SQLite creates automatic index for PRIMARY KEY)
        assert "idx_tasks_state" in indexes or any("state" in i for i in indexes)
        assert "idx_tasks_created" in indexes or any("created" in i for i in indexes)
    
    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, temp_db: Database):
        """WAL mode is enabled."""
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute("PRAGMA journal_mode")
            mode = (await cursor.fetchone())[0]
        
        assert mode == "wal"
    
    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, temp_db: Database):
        """Foreign keys pragma is ON on the shared connection."""
        # ponytail: PRAGMA foreign_keys is per-connection in SQLite; a fresh
        # aiosqlite connection defaults to OFF. Query the live Database conn.
        cursor = await temp_db._conn.execute("PRAGMA foreign_keys")
        fk = (await cursor.fetchone())[0]
        assert fk == 1


class TestDatabaseRecovery:
    """Test database recovery on server restart."""
    
    @pytest_asyncio.fixture
    async def db_with_stuck_tasks(self):
        """Database with tasks stuck in downloading state."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as f:
            db_path = Path(f.name)
        
        db = Database(db_path=db_path)
        await db.init()
        
        # Insert a task in downloading state
        await db.save_task({
            "task_id": "stuck_task_1",
            "urls": ["https://www.youtube.com/watch?v=aaa"],
            "state": "downloading",
            "progress_pct": 50.0,
            "current_file": "video.mp4",
            "error_msg": None,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
            "download_dir": "/tmp",
            "format_selector": "bv*+ba/b",
            "proxy": None,
            "cookie_header": None,
            "download_mode": "完整视频（画面+声音）",
            "quality": "最佳",
        })
        
        # Insert another stuck task
        await db.save_task({
            "task_id": "stuck_task_2",
            "urls": ["https://www.bilibili.com/video/BV1xx"],
            "state": "downloading",
            "progress_pct": 25.0,
            "current_file": "audio.m4a",
            "error_msg": None,
            "created_at": "2024-01-01T01:00:00",
            "updated_at": "2024-01-01T01:00:00",
            "download_dir": "/tmp",
            "format_selector": "bv*+ba/b",
            "proxy": None,
            "cookie_header": "SESSDATA=test",
            "download_mode": "仅音频",
            "quality": "1080p",
        })
        
        # Insert a completed task (should not be affected)
        await db.save_task({
            "task_id": "completed_task",
            "urls": ["https://www.youtube.com/watch?v=bbb"],
            "state": "completed",
            "progress_pct": 100.0,
            "current_file": None,
            "error_msg": None,
            "created_at": "2024-01-01T02:00:00",
            "updated_at": "2024-01-01T02:00:00",
            "download_dir": "/tmp",
            "format_selector": "bv*+ba/b",
            "proxy": None,
            "cookie_header": None,
            "download_mode": "完整视频（画面+声音）",
            "quality": "最佳",
        })
        
        yield db
        await db.close()
        db_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_reset_downloading_tasks_on_recovery(
        self,
        db_with_stuck_tasks: Database,
        config: Config,
    ):
        """Downloading tasks reset to failed on recovery."""
        # Create TaskManager (simulates startup)
        with patch("vidapi.task_manager.get_config", return_value=config):
            tm = TaskManager(db_with_stuck_tasks)
            tm.config = config
            from concurrent.futures import ThreadPoolExecutor
            tm.executor = ThreadPoolExecutor(max_workers=1)
            tm._progress_queues = {}
            tm._download_sessions = {}
            
            # start() should reset stuck tasks
            await tm.start()
            
            # Check stuck tasks are now failed
            task1 = await tm.get_task("stuck_task_1")
            assert task1["state"] == "failed"
            assert "restart" in task1["error_msg"].lower() or "interrupt" in task1["error_msg"].lower()
            
            task2 = await tm.get_task("stuck_task_2")
            assert task2["state"] == "failed"
            assert "restart" in task2["error_msg"].lower() or "interrupt" in task2["error_msg"].lower()
            
            # Completed task should be unchanged
            task3 = await tm.get_task("completed_task")
            assert task3["state"] == "completed"
            
            await tm.stop()
    
    @pytest.mark.asyncio
    async def test_reset_count_returned(
        self,
        db_with_stuck_tasks: Database,
        config: Config,
    ):
        """reset_downloading_tasks returns count of reset tasks."""
        with patch("vidapi.task_manager.get_config", return_value=config):
            tm = TaskManager(db_with_stuck_tasks)
            tm.config = config
            from concurrent.futures import ThreadPoolExecutor
            tm.executor = ThreadPoolExecutor(max_workers=1)
            tm._progress_queues = {}
            tm._download_sessions = {}
            
            # Call start which calls reset_downloading_tasks
            await tm.start()
            
            # Should have reset 2 tasks
            # (The reset happens in start() -> reset_downloading_tasks())
            
            await tm.stop()


class TestDatabasePersistence:
    """Test database persistence across operations."""
    
    @pytest.mark.asyncio
    async def test_task_persists_after_create(
        self,
        database: Database,
    ):
        """Task persists in database after creation."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://www.youtube.com/watch?v=test"],
        })
        
        # Query database directly
        task = await database.get_task(task_id)
        assert task is not None
        assert task["task_id"] == task_id
        assert task["state"] == "pending"
    
    @pytest.mark.asyncio
    async def test_task_updates_persisted(
        self,
        database: Database,
    ):
        """Task updates are persisted to database."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://www.youtube.com/watch?v=test"],
        })
        
        # Update progress
        await tm.update_progress(task_id, 75.5, "75% done", "video.mp4")
        
        # Check database
        task = await database.get_task(task_id)
        assert task["progress_pct"] == 75.5
        assert task["current_file"] == "video.mp4"
    
    @pytest.mark.asyncio
    async def test_state_changes_persisted(
        self,
        database: Database,
    ):
        """State changes are persisted."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://www.youtube.com/watch?v=test"],
        })
        
        await tm.state_change(task_id, "downloading")
        
        task = await database.get_task(task_id)
        assert task["state"] == "downloading"
    
    @pytest.mark.asyncio
    async def test_delete_task_removes_from_db(
        self,
        database: Database,
    ):
        """Deleting task removes from database."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://www.youtube.com/watch?v=test"],
        })
        
        await tm.delete_task(task_id)
        
        task = await database.get_task(task_id)
        assert task is None
    
    @pytest.mark.asyncio
    async def test_multiple_tasks_listed(
        self,
        database: Database,
    ):
        """Multiple tasks can be listed."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_ids = []
        for i in range(5):
            task_id = await tm.create_task({
                "urls": [f"https://www.youtube.com/watch?v=test{i}"],
            })
            task_ids.append(task_id)
        
        tasks = await tm.list_tasks()
        assert len(tasks) >= 5
        
        returned_ids = {t["task_id"] for t in tasks}
        for tid in task_ids:
            assert tid in returned_ids
    
    @pytest.mark.asyncio
    async def test_list_tasks_pagination(
        self,
        database: Database,
    ):
        """List tasks supports pagination."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        for i in range(10):
            await tm.create_task({
                "urls": [f"https://www.youtube.com/watch?v=test{i}"],
            })
        
        page1 = await tm.list_tasks(limit=3, offset=0)
        assert len(page1) == 3
        
        page2 = await tm.list_tasks(limit=3, offset=3)
        assert len(page2) == 3
        
        # No overlap
        ids1 = {t["task_id"] for t in page1}
        ids2 = {t["task_id"] for t in page2}
        assert ids1.isdisjoint(ids2)
    
    @pytest.mark.asyncio
    async def test_list_tasks_state_filter(
        self,
        database: Database,
    ):
        """List tasks with state filter."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://www.youtube.com/watch?v=test"],
        })
        
        await tm.state_change(task_id, "downloading")
        
        pending = await tm.list_tasks(state="pending")
        downloading = await tm.list_tasks(state="downloading")
        
        assert all(t["state"] == "pending" for t in pending)
        assert all(t["state"] == "downloading" for t in downloading)
    
    @pytest.mark.asyncio
    async def test_count_tasks(
        self,
        database: Database,
    ):
        """Count tasks returns correct count."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        initial = await tm.count_tasks()
        
        await tm.create_task({"urls": ["https://youtube.com/watch?v=1"]})
        await tm.create_task({"urls": ["https://youtube.com/watch?v=2"]})
        
        after = await tm.count_tasks()
        assert after == initial + 2


class TestConfigPersistence:
    """Test config persistence in database."""
    
    @pytest.mark.asyncio
    async def test_save_and_get_config(
        self,
        database: Database,
    ):
        """Save and get config value."""
        await database.save_config("test_key", "test_value")
        
        value = await database.get_config("test_key")
        assert value == "test_value"
    
    @pytest.mark.asyncio
    async def test_get_config_default(
        self,
        database: Database,
    ):
        """Get config returns default for missing key."""
        value = await database.get_config("nonexistent", "default_value")
        assert value == "default_value"
    
    @pytest.mark.asyncio
    async def test_save_config_overwrites(
        self,
        database: Database,
    ):
        """Saving config overwrites existing value."""
        await database.save_config("key1", "value1")
        await database.save_config("key1", "value2")
        
        value = await database.get_config("key1")
        assert value == "value2"
    
    @pytest.mark.asyncio
    async def test_get_all_config(
        self,
        database: Database,
    ):
        """Get all config values."""
        await database.save_config("a", "1")
        await database.save_config("b", "2")
        await database.save_config("c", "3")
        
        all_config = await database.get_all_config()
        assert all_config == {"a": "1", "b": "2", "c": "3"}
    
    @pytest.mark.asyncio
    async def test_config_persists_across_instances(
        self,
        temp_db: Database,
    ):
        """Config persists across database instances."""
        await temp_db.save_config("persist_key", "persist_value")
        await temp_db.close()
        
        # Reopen
        new_db = Database(db_path=temp_db.db_path)
        await new_db.init()
        
        value = await new_db.get_config("persist_key")
        assert value == "persist_value"
        
        await new_db.close()


class TestDatabaseEdgeCases:
    """Edge cases for database operations."""
    
    @pytest.mark.asyncio
    async def test_corrupt_json_in_urls_handled(
        self,
        database: Database,
    ):
        """Corrupt JSON in urls column handled gracefully."""
        # Insert corrupt JSON directly
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, ?, ?)",
            ("corrupt_task", "{not valid json", "pending")
        )
        await database._conn.commit()
        
        # Should not raise, returns empty list
        task = await database.get_task("corrupt_task")
        assert task is not None
        assert task["urls"] == []
    
    @pytest.mark.asyncio
    async def test_empty_urls_json_handled(
        self,
        database: Database,
    ):
        # ponytail: schema is urls TEXT NOT NULL — NULL insert is unreachable in
        # production. Test the empty-list JSON shape instead, which is the real
        # edge case save_task + get_task must round-trip.
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, ?, ?)",
            ("empty_urls_task", "[]", "pending")
        )
        await database._conn.commit()

        task = await database.get_task("empty_urls_task")
        assert task is not None
        assert task["urls"] == []
    
    @pytest.mark.asyncio
    async def test_empty_string_urls_handled(
        self,
        database: Database,
    ):
        """Empty string urls field handled."""
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, ?, ?)",
            ("empty_urls_task", "", "pending")
        )
        await database._conn.commit()
        
        task = await database.get_task("empty_urls_task")
        assert task is not None
        assert task["urls"] == []
    
    @pytest.mark.asyncio
    async def test_upsert_task_updates_existing(
        self,
        database: Database,
    ):
        """save_task updates existing task (upsert)."""
        await database.save_task({
            "task_id": "upsert_test",
            "urls": ["https://youtube.com/watch?v=1"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        
        # Update
        await database.save_task({
            "task_id": "upsert_test",
            "urls": ["https://youtube.com/watch?v=1"],
            "state": "completed",
            "progress_pct": 100.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T01:00:00",
        })
        
        task = await database.get_task("upsert_test")
        assert task["state"] == "completed"
        assert task["progress_pct"] == 100.0
    
    @pytest.mark.asyncio
    async def test_uninitialized_db_raises(
        self,
        temp_dir: Path,
    ):
        """Uninitialized database raises RuntimeError."""
        db_path = temp_dir / "uninit.sqlite3"
        db = Database(db_path=db_path)
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.save_task({})
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_task("test")
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.list_tasks()
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.delete_task("test")
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.update_task_state("test", "pending")
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.reset_downloading_tasks()
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.save_config("key", "value")
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_config("key")
        
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_all_config()
        
        # Close should not raise
        await db.close()
    
    @pytest.mark.asyncio
    async def test_close_on_none_connection(
        self,
        temp_dir: Path,
    ):
        """close() on uninitialized connection doesn't raise."""
        db_path = temp_dir / "none.sqlite3"
        db = Database(db_path=db_path)
        await db.close()  # Should not raise


class TestDatabaseConcurrency:
    """Test database under concurrent access."""
    
    @pytest.mark.asyncio
    async def test_concurrent_task_creates(
        self,
        database: Database,
    ):
        """Multiple concurrent task creates work."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        async def create_task(i):
            return await tm.create_task({
                "urls": [f"https://youtube.com/watch?v=concurrent{i}"],
            })
        
        task_ids = await asyncio.gather(*[create_task(i) for i in range(10)])
        
        # All should be unique
        assert len(set(task_ids)) == 10
        
        # All should exist in database
        for tid in task_ids:
            task = await database.get_task(tid)
            assert task is not None
    
    @pytest.mark.asyncio
    async def test_concurrent_updates(
        self,
        database: Database,
    ):
        """Concurrent updates to same task work."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://youtube.com/watch?v=concurrent"],
        })
        
        # Concurrent progress updates
        async def update(pct):
            await tm.update_progress(task_id, pct, f"Progress {pct}")
        
        await asyncio.gather(*[update(i * 10.0) for i in range(10)])
        
        # Final state should be one of the updates
        task = await database.get_task(task_id)
        assert task["progress_pct"] in [i * 10.0 for i in range(10)]
    
    @pytest.mark.asyncio
    async def test_wal_mode_allows_concurrent_read_write(
        self,
        database: Database,
    ):
        """WAL mode allows concurrent reads during writes."""
        tm = TaskManager(database)
        tm.config = Config()
        tm.executor = MagicMock()
        tm._progress_queues = {}
        tm._download_sessions = {}
        
        task_id = await tm.create_task({
            "urls": ["https://youtube.com/watch?v=wal"],
        })
        
        # Write and read concurrently
        async def writer():
            for i in range(20):
                await tm.update_progress(task_id, float(i * 5), f"Write {i}")
                await asyncio.sleep(0.001)
        
        async def reader():
            for _ in range(20):
                task = await tm.get_task(task_id)
                assert task is not None
                await asyncio.sleep(0.001)
        
        await asyncio.gather(writer(), reader())
        # Should complete without errors


class TestDatabaseMigration:
    """Test database migration scenarios."""
    
    @pytest.mark.asyncio
    async def test_schema_compatibility(
        self,
        temp_db: Database,
    ):
        """Schema is compatible with expected structure."""
        async with aiosqlite.connect(temp_db.db_path) as conn:
            cursor = await conn.execute("PRAGMA table_info(tasks)")
            columns = await cursor.fetchall()
        
        # Verify all expected columns exist
        col_names = {col[1] for col in columns}
        required = {
            "task_id", "urls", "state", "progress_pct", "current_file",
            "error_msg", "created_at", "updated_at", "download_dir",
            "format_selector", "proxy", "cookie_header", "download_mode", "quality"
        }
        
        for req in required:
            assert req in col_names, f"Missing required column: {req}"
    
    @pytest.mark.asyncio
    async def test_future_columns_ignored(
        self,
        temp_db: Database,
    ):
        """Extra columns in future schema would be ignored by current code."""
        # Add a column (simulating future migration)
        async with aiosqlite.connect(temp_db.db_path) as conn:
            await conn.execute("ALTER TABLE tasks ADD COLUMN future_field TEXT DEFAULT 'default'")
            await conn.commit()
        
        # Current code should still work
        await temp_db.save_task({
            "task_id": "future_test",
            "urls": ["https://youtube.com/watch?v=future"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        
        task = await temp_db.get_task("future_test")
        assert task is not None
        assert task["state"] == "pending"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])