"""Config flow: a single global entry, like the WHA-State-Scanner panel."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries

from .const import DOMAIN


class FumihaHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the one-and-only shell entry.

    No options flow override: the base class default ("no options") is what
    we want — shell behaviour is code, page options live in the pages.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Create the entry on first use; further attempts abort."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="文羽面板", data={})
        return self.async_show_form(step_id="user")
