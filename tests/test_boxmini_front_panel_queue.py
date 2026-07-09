import logging
import queue
import unittest

from droplogic.base import HardwareCommand, Priority
from droplogic.hardware.box_mini1 import BOXMini


class BoxMiniFrontPanelQueueTests(unittest.TestCase):
    def _make_boxmini_stub(self):
        box = object.__new__(BOXMini)
        box.logger = logging.getLogger("test.boxmini.front_panel_queue")
        box._hardware_queues = {priority: queue.Queue() for priority in Priority}
        box.close = lambda: None
        return box

    def _queued_paths(self, box):
        return [cmd.path for cmd in list(box._hardware_queues[Priority.LOW].queue)]

    def test_expression_and_state_commands_coalesce_to_latest(self):
        box = self._make_boxmini_stub()

        box._enqueue_hardware_command(
            HardwareCommand("front_panel.expression", "idle", Priority.LOW, 1.0)
        )
        box._enqueue_hardware_command(
            HardwareCommand("front_panel.state", "working", Priority.LOW, 2.0)
        )
        box._enqueue_hardware_command(
            HardwareCommand("front_panel.expression", "sad", Priority.LOW, 3.0)
        )

        queued = list(box._hardware_queues[Priority.LOW].queue)

        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].path, "front_panel.expression")
        self.assertEqual(queued[0].value, "sad")

    def test_front_panel_low_priority_backlog_is_bounded(self):
        box = self._make_boxmini_stub()

        for index in range(8):
            box._enqueue_hardware_command(
                HardwareCommand(f"front_panel.custom_{index}", index, Priority.LOW, float(index))
            )

        queued_paths = self._queued_paths(box)

        self.assertEqual(len(queued_paths), BOXMini.FRONT_PANEL_LOW_QUEUE_LIMIT)
        self.assertEqual(
            queued_paths,
            [f"front_panel.custom_{index}" for index in range(3, 8)],
        )


if __name__ == "__main__":
    unittest.main()
