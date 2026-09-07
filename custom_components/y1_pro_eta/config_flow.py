"""Config flow for Y1 PRO Whole-house Clean ETA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import CONF_VACUUM_ENTITY, DOMAIN


class Y1ProEtaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure an ETA tracker for one vacuum entity."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle setup."""
        if user_input is not None:
            entity_id = user_input[CONF_VACUUM_ENTITY]
            await self.async_set_unique_id(entity_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"{entity_id} whole-house ETA", data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_VACUUM_ENTITY): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="vacuum")
                    )
                }
            ),
        )
