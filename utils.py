from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel


class UserLevel(StrEnum):
    EVERYONE = "everyone"
    SUBSCRIBER = "subscriber"
    VIP = "vip"
    MODS = "moderator"
    BROADCASTER = "streamer"


class TwitchCommandFromWeb(BaseModel):
    name: str
    reply: str
    level: str
    active: bool


@dataclass()
class TwitchCommand:
    name: str
    reply: str
    user_level: UserLevel
    active: bool

    def from_pydantic(self, command: TwitchCommandFromWeb):
        return TwitchCommand(
            command.name,
            command.reply,
            UserLevel(command.level.lower()),
            command.active,
        )
