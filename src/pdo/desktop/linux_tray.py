"""Linux StatusNotifier tray, adapted from the MIT-licensed MailArchive project."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from dbus_next import Variant
from dbus_next.aio import MessageBus
from dbus_next.constants import BusType, MessageType, PropertyAccess
from dbus_next.message import Message
from dbus_next.service import ServiceInterface, dbus_property, method, signal

# ruff: noqa: F722, F821, N802, UP037 - D-Bus names and signatures are protocol-defined.

ITEM_INTERFACE = "org.kde.StatusNotifierItem"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/Menu"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
NOTIFICATIONS_INTERFACE = "org.freedesktop.Notifications"
NOTIFICATIONS_PATH = "/org/freedesktop/Notifications"
MENU_OPEN_ID = 1
MENU_QUIT_ID = 2
MENU_LABELS = {MENU_OPEN_ID: "Open", MENU_QUIT_ID: "Quit"}


def icon_pixmap_from_rgba(width: int, height: int, rgba: bytes) -> list[list[Any]]:
    """Convert Qt's RGBA8888 bytes to StatusNotifier ARGB pixels.

    Args:
        width: Icon width in pixels.
        height: Icon height in pixels.
        rgba: Tightly packed RGBA bytes.

    Returns:
        One D-Bus ``a(iiay)`` pixmap entry.

    Raises:
        ValueError: If the pixel buffer size is invalid.
    """
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("Invalid tray icon pixel buffer.")
    argb = bytearray(len(rgba))
    argb[0::4] = rgba[3::4]
    argb[1::4] = rgba[0::4]
    argb[2::4] = rgba[1::4]
    argb[3::4] = rgba[2::4]
    return [[width, height, bytes(argb)]]


class StatusNotifierItem(ServiceInterface):
    """Expose one icon and its activation actions over the session bus."""

    def __init__(
        self,
        pixmap: list[list[Any]],
        post_ui: Callable[[Callable[[], None]], None],
        show: Callable[[], None],
    ) -> None:
        super().__init__(ITEM_INTERFACE)
        self._pixmap = pixmap
        self._post_ui = post_ui
        self._show = show

    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "ApplicationStatus"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return "PDO"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return "PDO · Product Description Optimizer"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "Active"

    @dbus_property(access=PropertyAccess.READ)
    def WindowId(self) -> "i":
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return MENU_PATH

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":
        return self._pixmap

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def AttentionMovieName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconAccessibleDesc(self) -> "s":
        return self.Title

    @dbus_property(access=PropertyAccess.READ)
    def AttentionAccessibleDesc(self) -> "s":
        return ""

    @method()
    def Activate(self, _x: "i", _y: "i") -> "":
        self._post_ui(self._show)

    @method()
    def ContextMenu(self, _x: "i", _y: "i") -> "":
        self._post_ui(self._show)

    @method()
    def SecondaryActivate(self, _x: "i", _y: "i") -> "":
        self._post_ui(self._show)

    @method()
    def XAyatanaSecondaryActivate(self, _timestamp: "u") -> "":
        self._post_ui(self._show)

    @method()
    def Scroll(self, _delta: "i", _orientation: "s") -> "":
        return None

    @signal()
    def NewIcon(self) -> "":
        return None

    @signal()
    def NewTitle(self) -> "":
        return None

    @signal()
    def NewStatus(self, status: "s") -> "s":
        return status


class StatusNotifierMenu(ServiceInterface):
    """Provide the tray context menu through ``com.canonical.dbusmenu``."""

    def __init__(
        self,
        post_ui: Callable[[Callable[[], None]], None],
        show: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        super().__init__("com.canonical.dbusmenu")
        self._post_ui = post_ui
        self._show = show
        self._quit_app = quit_app

    @staticmethod
    def _properties(item_id: int) -> dict[str, Variant]:
        return {
            "label": Variant("s", MENU_LABELS[item_id]),
            "enabled": Variant("b", True),
            "visible": Variant("b", True),
        }

    @classmethod
    def _layout(cls, item_id: int, depth: int) -> list[Any]:
        if item_id != 0:
            return [item_id, cls._properties(item_id), []]
        children = []
        if depth != 0:
            children = [
                Variant("(ia{sv}av)", cls._layout(action_id, 0)) for action_id in MENU_LABELS
            ]
        return [0, {}, children]

    @method()
    def GetLayout(self, parent_id: "i", recursion_depth: "i", _properties: "as") -> "u(ia{sv}av)":
        if parent_id != 0 and parent_id not in MENU_LABELS:
            return [1, [parent_id, {}, []]]
        return [1, self._layout(parent_id, recursion_depth)]

    @method()
    def GetGroupProperties(self, item_ids: "ai", _properties: "as") -> "a(ia{sv})":
        return [
            [item_id, self._properties(item_id)] for item_id in item_ids if item_id in MENU_LABELS
        ]

    @method()
    def GetProperty(self, item_id: "i", name: "s") -> "v":
        if item_id not in MENU_LABELS:
            return Variant("s", "")
        return self._properties(item_id).get(name, Variant("s", ""))

    @method()
    def Event(self, item_id: "i", event_id: "s", _data: "v", _timestamp: "u") -> "":
        if event_id == "clicked":
            if item_id == MENU_OPEN_ID:
                self._post_ui(self._show)
            elif item_id == MENU_QUIT_ID:
                self._post_ui(self._quit_app)

    @method()
    def EventGroup(self, events: "a(isvu)") -> "ai":
        for event in events:
            self.Event(*event)
        return []

    @method()
    def AboutToShow(self, _item_id: "i") -> "b":
        return False

    @method()
    def AboutToShowGroup(self, _item_ids: "ai") -> "aiai":
        return [[], []]

    @dbus_property(access=PropertyAccess.READ)
    def Version(self) -> "u":
        return 3

    @dbus_property(access=PropertyAccess.READ)
    def TextDirection(self) -> "s":
        return "ltr"

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return "normal"

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "as":
        return []


class LinuxTrayController:
    """Register PDO with a StatusNotifier host on the session D-Bus."""

    def __init__(
        self,
        pixmap: list[list[Any]],
        post_ui: Callable[[Callable[[], None]], None],
        show: Callable[[], None],
        quit_app: Callable[[], None],
    ) -> None:
        self._pixmap = pixmap
        self._post_ui = post_ui
        self._show = show
        self._quit_app = quit_app
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bus: MessageBus | None = None
        self._service_name: str | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._ready = threading.Event()
        self._available = False
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """Return whether a StatusNotifier host accepted the tray item."""
        self._thread = threading.Thread(
            target=self._run,
            name="PDO-StatusNotifier",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=2)
        return self._available

    @property
    def available(self) -> bool:
        """Return whether a tray host is currently displaying items."""
        return self._available

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._connect())
            if self._available:
                self._monitor_task = loop.create_task(self._monitor_host())
                loop.run_forever()
        except Exception:
            self._available = False
        finally:
            self._ready.set()
            if self._monitor_task is not None and not self._monitor_task.done():
                self._monitor_task.cancel()
                loop.run_until_complete(asyncio.gather(self._monitor_task, return_exceptions=True))
            if self._bus is not None:
                self._bus.disconnect()
            loop.close()

    async def _connect(self) -> None:
        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        self._bus = bus
        if not await self._host_is_registered():
            raise RuntimeError("No StatusNotifier host is available.")
        self._service_name = f"{ITEM_INTERFACE}.PDO_{os.getpid()}"
        await bus.request_name(self._service_name)
        bus.export(ITEM_PATH, StatusNotifierItem(self._pixmap, self._post_ui, self._show))
        bus.export(
            MENU_PATH,
            StatusNotifierMenu(self._post_ui, self._show, self._quit_app),
        )
        if not await self._register_item():
            raise RuntimeError("No StatusNotifier host is available.")
        self._available = True
        self._ready.set()

    async def _host_is_registered(self) -> bool:
        if self._bus is None:
            return False
        try:
            reply = await self._bus.call(
                Message(
                    destination=WATCHER_INTERFACE,
                    path=WATCHER_PATH,
                    interface="org.freedesktop.DBus.Properties",
                    member="Get",
                    signature="ss",
                    body=[WATCHER_INTERFACE, "IsStatusNotifierHostRegistered"],
                )
            )
        except Exception:
            return False
        return (
            reply.message_type != MessageType.ERROR
            and len(reply.body) == 1
            and reply.body[0].value is True
        )

    async def _register_item(self) -> bool:
        if self._bus is None or self._service_name is None:
            return False
        try:
            reply = await self._bus.call(
                Message(
                    destination=WATCHER_INTERFACE,
                    path=WATCHER_PATH,
                    interface=WATCHER_INTERFACE,
                    member="RegisterStatusNotifierItem",
                    signature="s",
                    body=[self._service_name],
                )
            )
        except Exception:
            return False
        return reply.message_type != MessageType.ERROR

    async def _monitor_host(self) -> None:
        while True:
            await asyncio.sleep(1)
            host_available = await self._host_is_registered()
            if not host_available and self._available:
                self._available = False
                self._post_ui(self._show)
            elif host_available and not self._available:
                self._available = await self._register_item()

    def notify(self, message: str) -> None:
        """Send an optional desktop notification from the D-Bus thread."""
        if self._loop is not None and self._bus is not None and self._available:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._send_notification(message))
            )

    async def _send_notification(self, message: str) -> None:
        if self._bus is None:
            return
        with suppress(Exception):
            await self._bus.call(
                Message(
                    destination=NOTIFICATIONS_INTERFACE,
                    path=NOTIFICATIONS_PATH,
                    interface=NOTIFICATIONS_INTERFACE,
                    member="Notify",
                    signature="susssasa{sv}i",
                    body=["PDO", 0, "", "PDO is running", message, [], {}, 4000],
                )
            )

    def stop(self) -> None:
        """Unregister the tray item and stop its D-Bus event loop."""
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._available = False
