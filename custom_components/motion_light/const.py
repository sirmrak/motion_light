"""Constants for Motion Light integration."""

DOMAIN = "motion_light"

# Configuration keys
CONF_SWITCH_ENTITIES = "switch_entities"
CONF_MAIN_SENSORS = "main_sensors"
CONF_EXTEND_SENSORS = "extend_sensors"
CONF_LUX_SENSOR = "lux_sensor"
CONF_FORCE_STOP_SENSOR = "force_stop_sensor"
CONF_FORCE_STOP_STATE = "force_stop_state"
CONF_LOG_LEVEL = "log_level"

# Defaults
DEFAULT_NAME = "Motion Light"
DEFAULT_FORCE_STOP_STATE = "off"
DEFAULT_LOG_LEVEL = "INFO"

# Entity suffixes
ENTITY_MOTION_FILTER = "motion_filter"
ENTITY_OFF_DELAY = "off_delay"
ENTITY_LUX_THRESHOLD = "lux_threshold"
ENTITY_LUX_COOLDOWN = "lux_cooldown"
ENTITY_MANUAL_IDLE_TIMEOUT = "manual_idle_timeout"
ENTITY_MANUAL_OFF_COOLDOWN = "manual_off_cooldown"
ENTITY_RESPECT_MANUAL = "respect_manual"

# Default values
DEFAULT_MOTION_FILTER = 0
DEFAULT_OFF_DELAY = 30
DEFAULT_LUX_THRESHOLD = 300
DEFAULT_LUX_COOLDOWN = 60
DEFAULT_MANUAL_IDLE_TIMEOUT = 600
DEFAULT_MANUAL_OFF_COOLDOWN = 30
DEFAULT_RESPECT_MANUAL = True

# Lux check interval
LUX_CHECK_INTERVAL = 30

# States
STATE_IDLE = "idle"
STATE_DETECTING = "detecting"
STATE_ON = "on"
STATE_DELAYING = "delaying"
STATE_ACTIVE = "active"
STATE_OFF = "off"
STATE_MANUAL_ON = "manual_on"
STATE_MANUAL_OFF_COOLDOWN = "manual_off_cooldown"
STATE_ERROR = "error"
STATE_DISABLED = "disabled"