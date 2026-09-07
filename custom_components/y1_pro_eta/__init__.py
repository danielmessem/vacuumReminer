"""Y1 PRO Whole-house Clean ETA integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_VACUUM_ENTITY, PLATFORMS
from .tracker import WholeHouseEtaTracker

type Y1ProEtaConfigEntry = ConfigEntry[WholeHouseEtaTracker]


async def async_setup_entry(hass: HomeAssistant, entry: Y1ProEtaConfigEntry) -> bool:
    """Set up an ETA tracker."""
    tracker = WholeHouseEtaTracker(
        hass, entry.entry_id, entry.data[CONF_VACUUM_ENTITY]
    )
    await tracker.async_start()
    entry.runtime_data = tracker
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Y1ProEtaConfigEntry) -> bool:
    """Unload the integration."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stop()
    return True
