"""Persistent whole-house cleaning session tracker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CLEANING_STATES,
    MAX_HISTORY,
    MIN_VALID_RUN_SECONDS,
    STORE_KEY_PREFIX,
    STORE_VERSION,
    TERMINAL_SUCCESS_STATES,
)
from .estimator import filtered_average


class WholeHouseEtaTracker:
    """Track and estimate whole-house clean duration."""

    def __init__(self, hass: HomeAssistant, entry_id: str, entity_id: str) -> None:
        self.hass = hass
        self.entity_id = entity_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, f"{STORE_KEY_PREFIX}.{entry_id}"
        )
        self.history: list[float] = []
        self.started_at: datetime | None = None
        self.paused_at: datetime | None = None
        self.paused_seconds = 0.0
        self.is_whole_house = True
        self.cancelled = False
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        """Restore state and attach listeners."""
        data = await self._store.async_load() or {}
        self.history = [float(x) for x in data.get("history", [])][-MAX_HISTORY:]
        session = data.get("session")
        if session:
            self.started_at = dt_util.parse_datetime(session["started_at"])
            self.paused_at = dt_util.parse_datetime(session["paused_at"]) if session.get("paused_at") else None
            self.paused_seconds = float(session.get("paused_seconds", 0))
            self.is_whole_house = bool(session.get("is_whole_house", True))
            self.cancelled = bool(session.get("cancelled", False))
        self._unsubs.extend(
            [
                async_track_state_change_event(
                    self.hass, [self.entity_id], self._async_state_changed
                ),
                self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._async_service_called),
                async_track_time_interval(self.hass, self._async_tick, timedelta(seconds=30)),
            ]
        )

    async def async_stop(self) -> None:
        """Detach listeners and save."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        await self._async_save()

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to calculated updates."""
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener()

    def _targets_us(self, service_data: dict[str, Any]) -> bool:
        target = service_data.get("entity_id")
        if isinstance(target, str):
            return target == self.entity_id
        return isinstance(target, list) and self.entity_id in target

    @callback
    def _async_service_called(self, event: Event) -> None:
        if event.data.get("domain") != "vacuum":
            return
        service_data = event.data.get("service_data", {})
        if not self._targets_us(service_data):
            return
        service = event.data.get("service")
        if service in {"start", "turn_on"}:
            self.is_whole_house = True
            self.cancelled = False
        elif service in {"return_to_base", "stop", "turn_off"}:
            self.cancelled = True
        elif service == "send_command":
            # Area/spot commands are intentionally excluded from training data.
            command = str(service_data.get("command", "")).lower()
            if any(word in command for word in ("area", "room", "spot", "custom")):
                self.is_whole_house = False

    async def _async_state_changed(self, event: Event) -> None:
        old: State | None = event.data.get("old_state")
        new: State | None = event.data.get("new_state")
        if new is None:
            return
        old_state = old.state if old else None
        now = dt_util.utcnow()

        if new.state == "cleaning" and old_state not in CLEANING_STATES:
            self.started_at = now
            self.paused_at = None
            self.paused_seconds = 0
            # Unknown/app starts are treated as whole-house unless HA observed
            # an area command immediately before the state transition.
            self.cancelled = False
            await self._async_save()
        elif new.state == "paused" and self.started_at and self.paused_at is None:
            self.paused_at = now
            await self._async_save()
        elif new.state == "cleaning" and self.started_at and self.paused_at:
            self.paused_seconds += (now - self.paused_at).total_seconds()
            self.paused_at = None
            await self._async_save()
        elif (
            self.started_at
            and old_state in CLEANING_STATES
            and new.state not in CLEANING_STATES
        ):
            elapsed = self.elapsed_seconds(now)
            if (
                self.is_whole_house
                and not self.cancelled
                and new.state in TERMINAL_SUCCESS_STATES
                and elapsed >= MIN_VALID_RUN_SECONDS
            ):
                self.history = (self.history + [elapsed])[-MAX_HISTORY:]
            self.started_at = None
            self.paused_at = None
            self.paused_seconds = 0
            self.is_whole_house = True
            self.cancelled = False
            await self._async_save()
        self._notify()

    async def _async_tick(self, now: datetime) -> None:
        self._notify()

    def elapsed_seconds(self, now: datetime | None = None) -> float:
        """Return active elapsed time, excluding pauses."""
        if self.started_at is None:
            return 0
        now = now or dt_util.utcnow()
        end = self.paused_at or now
        return max(0, (end - self.started_at).total_seconds() - self.paused_seconds)

    @property
    def estimated_total_seconds(self) -> float | None:
        """Return robust historical estimate."""
        return filtered_average(self.history)

    def remaining_seconds(self) -> float | None:
        """Return estimated remaining seconds while running."""
        estimate = self.estimated_total_seconds
        if self.started_at is None or estimate is None:
            return None
        return max(0, estimate - self.elapsed_seconds())

    def completion_time(self) -> datetime | None:
        """Return estimated completion timestamp."""
        remaining = self.remaining_seconds()
        return dt_util.utcnow() + timedelta(seconds=remaining) if remaining is not None else None

    async def _async_save(self) -> None:
        session = None
        if self.started_at:
            session = {
                "started_at": self.started_at.isoformat(),
                "paused_at": self.paused_at.isoformat() if self.paused_at else None,
                "paused_seconds": self.paused_seconds,
                "is_whole_house": self.is_whole_house,
                "cancelled": self.cancelled,
            }
        await self._store.async_save({"history": self.history, "session": session})
