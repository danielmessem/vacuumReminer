"""Sensors for Y1 PRO Whole-house Clean ETA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Y1ProEtaConfigEntry
from .tracker import WholeHouseEtaTracker


@dataclass(frozen=True, kw_only=True)
class EtaSensorDescription(SensorEntityDescription):
    """Describe an ETA sensor."""

    value_fn: Callable[[WholeHouseEtaTracker], Any]


DESCRIPTIONS = (
    EtaSensorDescription(
        key="percent_complete", name="Whole-house clean complete",
        native_unit_of_measurement=PERCENTAGE, icon="mdi:progress-clock",
        value_fn=lambda tracker: min(
            100, tracker.elapsed_seconds() / tracker.estimated_total_seconds * 100
        ) if tracker.started_at and tracker.estimated_total_seconds else None,
    ),
    EtaSensorDescription(
        key="remaining", name="Whole-house clean time left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-sand", value_fn=lambda tracker: tracker.remaining_seconds(),
    ),
    EtaSensorDescription(
        key="elapsed", name="Whole-house clean elapsed",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-outline",
        value_fn=lambda tracker: tracker.elapsed_seconds() if tracker.started_at else None,
    ),
    EtaSensorDescription(
        key="estimated_total", name="Whole-house clean estimated total",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        icon="mdi:timer-check-outline",
        value_fn=lambda tracker: tracker.estimated_total_seconds,
    ),
    EtaSensorDescription(
        key="completion", name="Whole-house clean expected finish",
        device_class=SensorDeviceClass.TIMESTAMP, icon="mdi:clock-check-outline",
        value_fn=lambda tracker: tracker.completion_time(),
    ),
    EtaSensorDescription(
        key="samples", name="Whole-house clean ETA samples", icon="mdi:history",
        value_fn=lambda tracker: len(tracker.history),
    ),
)


async def async_setup_entry(
    hass, entry: Y1ProEtaConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    """Set up ETA sensors."""
    device_info = None
    source = er.async_get(hass).async_get(entry.runtime_data.entity_id)
    if source and source.device_id:
        source_device = dr.async_get(hass).async_get(source.device_id)
        if source_device:
            # Reuse the Ecovacs identifiers so HA groups these calculated
            # entities on the existing vacuum device page.
            device_info = DeviceInfo(
                identifiers=source_device.identifiers,
                connections=source_device.connections,
                name=source_device.name,
                manufacturer=source_device.manufacturer,
                model=source_device.model,
            )
    async_add_entities(
        EtaSensor(entry, description, device_info) for description in DESCRIPTIONS
    )


class EtaSensor(SensorEntity):
    """A calculated whole-house ETA sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: Y1ProEtaConfigEntry,
        description: EtaSensorDescription,
        device_info: DeviceInfo | None,
    ) -> None:
        self.entity_description = description
        self._tracker = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info or {
            "identifiers": {("y1_pro_eta", entry.entry_id)},
            "name": "Beepbop whole-house ETA",
            "manufacturer": "Community",
            "model": "Y1 PRO ETA",
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to tracker changes."""
        self.async_on_remove(self._tracker.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | int | datetime | None:
        """Return current calculated value."""
        value = self.entity_description.value_fn(self._tracker)
        return round(value) if isinstance(value, float) else value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose calculation inputs on the main countdown sensor."""
        if self.entity_description.key != "remaining":
            return None
        return {
            "source_vacuum": self._tracker.entity_id,
            "historical_durations_minutes": [round(x / 60, 1) for x in self._tracker.history],
            "filtered_average_minutes": round(self._tracker.estimated_total_seconds / 60, 1)
            if self._tracker.estimated_total_seconds is not None else None,
            "learning": len(self._tracker.history) < 5,
        }
