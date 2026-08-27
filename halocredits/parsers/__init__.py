from . import (halopedia, igdb, mobygames, waypoint_infinite, waypoint_mcc,
               waypoint_modern)

PARSERS = {
    "halopedia": halopedia.parse,
    "igdb": igdb.parse,
    "waypoint_modern": waypoint_modern.parse,
    "waypoint_infinite": waypoint_infinite.parse,
    "waypoint_mcc": waypoint_mcc.parse,
    "mobygames": mobygames.parse,
}
