"""Linux StatusNotifier protocol and tray behavior tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
import threading
import time
from importlib.resources import files
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import pytest

if sys.platform != "linux":
    pytest.skip("StatusNotifier tray is Linux-specific", allow_module_level=True)

from pdo.desktop.linux_tray import (
    StatusNotifierItem,
    StatusNotifierMenu,
    icon_pixmap_from_rgba,
)


def test_icon_uses_status_notifier_argb_order() -> None:
    pixmap = icon_pixmap_from_rgba(2, 1, bytes((1, 2, 3, 4, 5, 6, 7, 8)))
    assert pixmap == [[2, 1, bytes((4, 1, 2, 3, 8, 5, 6, 7))]]
    with pytest.raises(ValueError, match="Invalid tray icon"):
        icon_pixmap_from_rgba(2, 1, b"short")


def test_item_and_menu_dispatch_actions_to_ui() -> None:
    post_ui = Mock()
    show = Mock()
    quit_app = Mock()
    item = StatusNotifierItem([[1, 1, bytes((255, 0, 0, 0))]], post_ui, show)
    menu = StatusNotifierMenu(post_ui, show, quit_app)

    item.Activate(0, 0)
    menu.Event(1, "clicked", None, 0)
    menu.Event(2, "clicked", None, 0)
    menu.Event(3, "clicked", None, 0)

    assert post_ui.call_args_list == [call(show), call(show), call(quit_app)]
    revision, root = menu.GetLayout.__wrapped__(menu, 0, -1, [])
    assert revision == 1
    assert [child.value[0] for child in root[2]] == [1, 2]
    assert menu.GetProperty.__wrapped__(menu, 1, "label").value == "Open"
    assert menu.GetProperty.__wrapped__(menu, 2, "label").value == "Quit"
    assert item.Id == "PDO"
    assert item.Menu == "/Menu"


@pytest.mark.parametrize("host_available", [True, False])
def test_desktop_uses_dbus_tray_only_when_host_accepts_it(host_available: bool) -> None:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import DesktopWindow

    app = QApplication.instance() or QApplication([])
    window = SimpleNamespace(
        _tray_dispatcher=SimpleNamespace(invoke=SimpleNamespace(emit=Mock())),
        _show_from_tray=Mock(),
        quit=Mock(),
    )
    icon = QIcon(str(files("pdo.desktop").joinpath("logo.png")))
    with patch("pdo.desktop.linux_tray.LinuxTrayController") as controller:
        controller.return_value.start.return_value = host_available
        tray = DesktopWindow._create_tray(window, icon)
    pixmap = controller.call_args.args[0]
    assert pixmap[0][0:2] == [64, 64]
    assert len(pixmap[0][2]) == 64 * 64 * 4
    if host_available:
        assert tray is controller.return_value
        controller.return_value.stop.assert_not_called()
    else:
        assert tray is None
        controller.return_value.stop.assert_called_once()
    assert app is not None


def test_dbus_actions_reach_qt_gui_thread() -> None:
    from PySide6.QtWidgets import QApplication

    from pdo.desktop.app import _UiDispatcher

    app = QApplication.instance() or QApplication([])
    dispatcher = _UiDispatcher(app)
    gui_thread = threading.get_ident()
    callback_threads: list[int] = []
    worker = threading.Thread(
        target=lambda: dispatcher.invoke.emit(
            lambda: callback_threads.append(threading.get_ident())
        )
    )
    worker.start()
    worker.join(timeout=2)
    deadline = time.monotonic() + 2
    while not callback_threads and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert callback_threads == [gui_thread]


@pytest.mark.skipif(shutil.which("dbus-run-session") is None, reason="No private D-Bus runner")
def test_registers_with_status_notifier_host_over_dbus() -> None:
    script = textwrap.dedent(
        """
        import asyncio

        from dbus_next import Variant
        from dbus_next.aio import MessageBus
        from dbus_next.constants import BusType, MessageType, PropertyAccess
        from dbus_next.message import Message
        from dbus_next.service import ServiceInterface, dbus_property, method

        from pdo.desktop.linux_tray import (
            ITEM_INTERFACE, ITEM_PATH, MENU_PATH, WATCHER_INTERFACE, WATCHER_PATH,
            LinuxTrayController, icon_pixmap_from_rgba,
        )


        class Watcher(ServiceInterface):
            def __init__(self):
                super().__init__(WATCHER_INTERFACE)
                self.items = []
                self.host_registered = False

            @dbus_property(access=PropertyAccess.READ)
            def IsStatusNotifierHostRegistered(self) -> "b":
                return self.host_registered

            @method()
            def RegisterStatusNotifierItem(self, item: "s") -> "":
                self.items.append(item)


        async def main():
            watcher_bus = await MessageBus(bus_type=BusType.SESSION).connect()
            await watcher_bus.request_name(WATCHER_INTERFACE)
            watcher = Watcher()
            watcher_bus.export(WATCHER_PATH, watcher)
            callbacks = []
            pixmap = icon_pixmap_from_rgba(1, 1, bytes((1, 2, 3, 4)))
            without_host = LinuxTrayController(
                pixmap, lambda callback: callback(), lambda: None,
                lambda: None,
            )
            assert not await asyncio.to_thread(without_host.start)
            await asyncio.to_thread(without_host.stop)
            watcher.host_registered = True
            controller = LinuxTrayController(
                pixmap,
                lambda callback: callback(),
                lambda: callbacks.append("show"),
                lambda: callbacks.append("quit"),
            )
            client = None
            try:
                assert await asyncio.to_thread(controller.start)
                assert len(watcher.items) == 1
                client = await MessageBus(bus_type=BusType.SESSION).connect()
                properties = await client.call(Message(
                    destination=watcher.items[0], path=ITEM_PATH,
                    interface="org.freedesktop.DBus.Properties", member="GetAll",
                    signature="s", body=[ITEM_INTERFACE],
                ))
                assert properties.message_type != MessageType.ERROR, properties.body
                assert properties.body[0]["Id"].value == "PDO"
                assert properties.body[0]["Menu"].value == MENU_PATH
                assert properties.body[0]["IconPixmap"].value == [[1, 1, bytes((4, 1, 2, 3))]]
                layout = await client.call(Message(
                    destination=watcher.items[0], path=MENU_PATH,
                    interface="com.canonical.dbusmenu", member="GetLayout",
                    signature="iias", body=[0, -1, []],
                ))
                assert layout.message_type != MessageType.ERROR, layout.body
                assert len(layout.body[1][2]) == 2
                assert [child.value[1]["label"].value for child in layout.body[1][2]] == [
                    "Open", "Quit",
                ]
                clicked = await client.call(Message(
                    destination=watcher.items[0], path=MENU_PATH,
                    interface="com.canonical.dbusmenu", member="Event",
                    signature="isvu", body=[1, "clicked", Variant("s", ""), 0],
                ))
                assert clicked.message_type != MessageType.ERROR, clicked.body
                assert callbacks == ["show"]
                clicked = await client.call(Message(
                    destination=watcher.items[0], path=MENU_PATH,
                    interface="com.canonical.dbusmenu", member="Event",
                    signature="isvu", body=[2, "clicked", Variant("s", ""), 0],
                ))
                assert clicked.message_type != MessageType.ERROR, clicked.body
                assert callbacks == ["show", "quit"]
                watcher.host_registered = False
                for _ in range(40):
                    if not controller.available:
                        break
                    await asyncio.sleep(0.05)
                assert not controller.available
                assert callbacks == ["show", "quit", "show"]
                watcher.host_registered = True
                for _ in range(40):
                    if controller.available:
                        break
                    await asyncio.sleep(0.05)
                assert controller.available
                assert len(watcher.items) == 2
            finally:
                await asyncio.to_thread(controller.stop)
                if client is not None:
                    client.disconnect()
                watcher_bus.disconnect()


        asyncio.run(main())
        """
    )
    completed = subprocess.run(
        ["dbus-run-session", "--", sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
