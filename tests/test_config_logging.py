from unittest import TestCase
from unittest.mock import patch

MOD = "qibo_client.config_logging"


def logging_wrap_function(logger_object):
    logger_object.info("A debug log")
    logger_object.error("An error log")


class TestLogger(TestCase):
    @patch(f"{MOD}.os.environ", {"QIBO_CLIENT_LOGGER_LEVEL": "info"})
    def test_logging_with_info_level(self, mock_os):
        from qibo_client.config_logging import logger

        with self.assertLogs() as captured:
            logging_wrap_function(logger)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(captured.records[0].getMessage(), "An error log")

    @patch(f"{MOD}.os.environ", {"QIBO_CLIENT_LOGGER_LEVEL": "notset"})
    def test_logging_with_info_level(self):
        from qibo_client.config_logging import logger

        with self.assertLogs() as captured:
            logging_wrap_function(logger)
        self.assertEqual(len(captured.records), 2)
        self.assertEqual(captured.records[0].getMessage(), "A debug log")
        self.assertEqual(captured.records[1].getMessage(), "An error log")
