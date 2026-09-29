"""Unit tests for centralized file logging in wayback_addin.logger."""

import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import tempfile
import unittest

from wayback_addin.logger import (
    DEFAULT_LOG_PATH,
    PROJECT_ROOT,
    get_default_log_path,
    get_logger,
    setup_file_logger,
)


class TestLogger(unittest.TestCase):
    """Tests for setup_file_logger and logger utilities."""

    def setUp(self) -> None:
        """Create a temporary directory for test log outputs."""
        self.test_dir = tempfile.mkdtemp()
        self.test_log_file = os.path.join(self.test_dir, "test_wayback.log")
        self.test_logger_name = f"test_wayback_{id(self)}"

    def tearDown(self) -> None:
        """Clean up test handlers and temporary directory."""
        test_logger = logging.getLogger(self.test_logger_name)
        for handler in list(test_logger.handlers):
            handler.close()
            test_logger.removeHandler(handler)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_log_path_points_to_project_root(self) -> None:
        """Verify get_default_log_path returns the expected file in project root."""
        default_path = get_default_log_path()
        self.assertEqual(default_path, DEFAULT_LOG_PATH)
        self.assertTrue(default_path.endswith("wayback_addin.log"))
        self.assertEqual(os.path.dirname(default_path), PROJECT_ROOT)

    def test_setup_file_logger_creates_file_and_logs(self) -> None:
        """Verify setup_file_logger creates the log file and formats output properly."""
        logger = setup_file_logger(
            log_file_path=self.test_log_file,
            level=logging.INFO,
            logger_name=self.test_logger_name,
        )
        self.assertEqual(logger.level, logging.INFO)

        test_message = "Test log message for verification"
        logger.info(test_message)

        # Flush handlers
        for handler in logger.handlers:
            handler.flush()

        self.assertTrue(os.path.exists(self.test_log_file))
        with open(self.test_log_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[INFO]", content)
        self.assertIn(self.test_logger_name, content)
        self.assertIn(test_message, content)

    def test_setup_file_logger_prevents_duplicate_handlers(self) -> None:
        """Verify calling setup_file_logger multiple times does not add duplicate handlers."""
        logger1 = setup_file_logger(
            log_file_path=self.test_log_file,
            level=logging.INFO,
            logger_name=self.test_logger_name,
        )
        handler_count_1 = len([h for h in logger1.handlers if isinstance(h, RotatingFileHandler)])

        logger2 = setup_file_logger(
            log_file_path=self.test_log_file,
            level=logging.DEBUG,
            logger_name=self.test_logger_name,
        )
        handler_count_2 = len([h for h in logger2.handlers if isinstance(h, RotatingFileHandler)])

        self.assertEqual(handler_count_1, 1)
        self.assertEqual(handler_count_2, 1)
        self.assertEqual(logger2.level, logging.DEBUG)

    def test_logger_rotation(self) -> None:
        """Verify file rotates when log size exceeds max_bytes."""
        logger = setup_file_logger(
            log_file_path=self.test_log_file,
            level=logging.INFO,
            max_bytes=100,
            backup_count=2,
            logger_name=self.test_logger_name,
        )

        # Write enough data to trigger rotation
        for i in range(20):
            logger.info(f"Rotation line test entry number {i:04d} with extra padding text")

        for handler in logger.handlers:
            handler.flush()

        rotated_file = f"{self.test_log_file}.1"
        self.assertTrue(os.path.exists(self.test_log_file))
        self.assertTrue(os.path.exists(rotated_file))

    def test_get_logger_sublogger_propagation(self) -> None:
        """Verify child logger messages propagate to package logger."""
        pkg_logger = setup_file_logger(
            log_file_path=self.test_log_file,
            level=logging.DEBUG,
            logger_name=self.test_logger_name,
        )

        child_logger = logging.getLogger(f"{self.test_logger_name}.submodule")
        child_message = "Submodule operational log message"
        child_logger.debug(child_message)

        for handler in pkg_logger.handlers:
            handler.flush()

        with open(self.test_log_file, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[DEBUG]", content)
        self.assertIn(f"{self.test_logger_name}.submodule", content)
        self.assertIn(child_message, content)


if __name__ == "__main__":
    unittest.main()
