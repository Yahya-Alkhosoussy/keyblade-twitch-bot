from dataclasses import dataclass
from enum import StrEnum


class UserLevel(StrEnum):
    EVERYONE = "everyone"
    SUBSCRIBER = "subscriber"
    VIP = "vip"
    MODS = "moderator"
    BROADCASTER = "streamer"


@dataclass()
class TwitchCommand:
    name: str
    reply: str
    user_level: UserLevel
    active: bool
