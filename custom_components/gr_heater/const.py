"""Constants for the Gree Air-to-Water Heater integration."""

from datetime import timedelta

DOMAIN = "gr_heater"
NAME = "Gree Air-to-Water Heater"
POLL_INTERVAL = timedelta(seconds=30)
MIN_TEMP = 40
MAX_TEMP = 80
MODE_PROFILE = "901d"
TEMPERATURE_RANGE_901D = (35, 55)
MODES = {"standard": 0, "eco": 1, "quick": 2}
