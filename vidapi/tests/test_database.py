"""Error tests for database layer: uninitialized, constraint violations, corrupt data, edge cases."""

from __future__ import annotations

import json
import pytest

from vidapi.db.database import Database


class TestDatabaseUninitialized:
    async def test_save_task_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.save_task({"task_id": "x"})

    async def test_get_task_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_task("x")

    async def test_list_tasks_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.list_tasks()

    async def test_delete_task_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.delete_task("x")

    async def test_update_task_state_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.update_task_state("x", "pending")

    async def test_reset_downloading_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.reset_downloading_tasks()

    async def test_save_config_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.save_config("key", "value")

    async def test_get_config_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_config("key")

    async def test_get_all_config_raises(self, db_file):
        db = Database(db_path=db_file)
        with pytest.raises(RuntimeError, match="Database not initialized"):
            await db.get_all_config()

    async def test_close_on_none_connection(self, db_file):
        db = Database(db_path=db_file)
        await db.close()  # Should not raise


class TestDatabaseOperations:
    async def test_save_and_get_task(self, database: Database):
        task = {
            "task_id": "test001",
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        await database.save_task(task)
        result = await database.get_task("test001")
        assert result is not None
        assert result["task_id"] == "test001"
        assert isinstance(result["urls"], list)

    async def test_get_nonexistent_task(self, database: Database):
        result = await database.get_task("nonexistent")
        assert result is None

    async def test_update_task_preserves_original(self, database: Database):
        task = {
            "task_id": "test002",
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        await database.save_task(task)
        # Update state
        await database.update_task_state("test002", "downloading", progress_pct=50.0)
        result = await database.get_task("test002")
        assert result["state"] == "downloading"
        assert result["progress_pct"] == 50.0

    async def test_delete_task(self, database: Database):
        task = {
            "task_id": "test003",
            "urls": ["https://www.youtube.com/watch?v=abc"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        await database.save_task(task)
        deleted = await database.delete_task("test003")
        assert deleted is True
        result = await database.get_task("test003")
        assert result is None

    async def test_delete_nonexistent_task(self, database: Database):
        deleted = await database.delete_task("nonexistent")
        assert deleted is False

    async def test_list_tasks_empty(self, database: Database):
        tasks = await database.list_tasks()
        assert tasks == []

    async def test_list_tasks_with_filter(self, database: Database):
        for i in range(3):
            await database.save_task({
                "task_id": f"list_test_{i}",
                "urls": ["https://youtube.com/watch?v=x"],
                "state": "pending",
                "progress_pct": 0.0,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            })
        tasks = await database.list_tasks(state="pending")
        assert len(tasks) == 3

    async def test_list_tasks_pagination(self, database: Database):
        for i in range(5):
            await database.save_task({
                "task_id": f"page_test_{i}",
                "urls": ["https://youtube.com/watch?v=x"],
                "state": "pending",
                "progress_pct": 0.0,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            })
        page1 = await database.list_tasks(limit=2, offset=0)
        assert len(page1) == 2
        page2 = await database.list_tasks(limit=2, offset=2)
        assert len(page2) == 2

    async def test_reset_downloading_tasks(self, database: Database):
        for i in range(2):
            await database.save_task({
                "task_id": f"reset_{i}",
                "urls": ["https://youtube.com/watch?v=x"],
                "state": "downloading",
                "progress_pct": 50.0,
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            })
        count = await database.reset_downloading_tasks()
        assert count == 2
        for i in range(2):
            task = await database.get_task(f"reset_{i}")
            assert task["state"] == "failed"

    async def test_reset_downloading_no_matching(self, database: Database):
        await database.save_task({
            "task_id": "no_reset",
            "urls": ["https://youtube.com/watch?v=x"],
            "state": "completed",
            "progress_pct": 100.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        count = await database.reset_downloading_tasks()
        assert count == 0

    async def test_upsert_task(self, database: Database):
        task = {
            "task_id": "upsert_test",
            "urls": ["https://youtube.com/watch?v=x"],
            "state": "pending",
            "progress_pct": 0.0,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }
        await database.save_task(task)
        task["state"] = "downloading"
        task["progress_pct"] = 50.0
        await database.save_task(task)
        result = await database.get_task("upsert_test")
        assert result["state"] == "downloading"
        assert result["progress_pct"] == 50.0


class TestConfigTable:
    async def test_save_and_get_config(self, database: Database):
        await database.save_config("test_key", "test_value")
        result = await database.get_config("test_key")
        assert result == "test_value"

    async def test_get_config_default(self, database: Database):
        result = await database.get_config("nonexistent", default="fallback")
        assert result == "fallback"

    async def test_save_config_overwrites(self, database: Database):
        await database.save_config("key1", "v1")
        await database.save_config("key1", "v2")
        result = await database.get_config("key1")
        assert result == "v2"

    async def test_get_all_config(self, database: Database):
        await database.save_config("a", "1")
        await database.save_config("b", "2")
        all_cfg = await database.get_all_config()
        assert all_cfg == {"a": "1", "b": "2"}


class TestRowToTaskEdgeCases:
    async def test_null_urls_field(self, database: Database):
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, '', ?)",
            ("null_urls", "pending"),
        )
        await database._conn.commit()
        result = await database.get_task("null_urls")
        assert result is not None
        assert result["urls"] == []

    async def test_empty_string_urls(self, database: Database):
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, ?, ?)",
            ("empty_urls", "[]", "pending"),
        )
        await database._conn.commit()
        result = await database.get_task("empty_urls")
        assert result is not None
        assert result["urls"] == []

    async def test_corrupt_json_urls(self, database: Database):
        """Corrupt JSON in urls column should crash _row_to_task."""
        await database._conn.execute(
            "INSERT INTO tasks (task_id, urls, state) VALUES (?, ?, ?)",
            ("corrupt", "{not json}", "pending"),
        )
        await database._conn.commit()
        # This should raise json.JSONDecodeError
        with pytest.raises(json.JSONDecodeError):
            await database.get_task("corrupt")
