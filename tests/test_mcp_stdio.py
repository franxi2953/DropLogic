from __future__ import annotations

import errno
from unittest import mock

from droplogic.mcp import server


def test_native_stdout_redirect_allows_tool_when_stderr_handle_is_invalid() -> None:
    entered = False

    with (
        mock.patch.object(server.os, "dup", return_value=91),
        mock.patch.object(server.os, "dup2", side_effect=OSError(errno.EINVAL, "Invalid argument")),
        mock.patch.object(server.os, "close") as close,
        server._redirect_native_stdout_to_stderr(),
    ):
        entered = True

    assert entered is True
    close.assert_called_once_with(91)
