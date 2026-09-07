"""Constants for Y1 PRO Whole-house Clean ETA."""

DOMAIN = "y1_pro_eta"
CONF_VACUUM_ENTITY = "vacuum_entity"
PLATFORMS = ["sensor"]
STORE_VERSION = 1
STORE_KEY_PREFIX = f"{DOMAIN}.history"

CLEANING_STATES = {"cleaning", "paused"}
TERMINAL_SUCCESS_STATES = {"returning", "docked", "idle"}
MIN_VALID_RUN_SECONDS = 10 * 60
MAX_HISTORY = 5
