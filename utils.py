from dataclasses import dataclass
from enum import Flag, auto
from functools import reduce
from operator import or_

from pydantic import BaseModel


class CommandLevels(Flag):
    STREAMER = auto()
    MOD = auto()
    VIP = auto()
    SUBSCRIBER = auto()
    EVERYONE = 0

    @classmethod
    def parse(cls, text: str) -> "CommandLevels":
        aliases = {"moderator": "MOD", "broadcaster": "STREAMER"}
        parts = [p.strip().lower() for p in text.split("|") if p.strip()]
        names = [aliases.get(p, p).upper() for p in parts]
        return reduce(or_, (cls[n] for n in names), cls.EVERYONE)

    def allows(self, user_roles: "CommandLevels") -> bool:
        return not self or bool(self & user_roles)


class TwitchCommandFromWeb(BaseModel):
    name: str
    reply: str
    level: str
    active: bool


@dataclass()
class TwitchCommand:
    name: str
    reply: str
    user_level: CommandLevels
    active: bool

    def from_pydantic(self, command: TwitchCommandFromWeb):
        return TwitchCommand(
            command.name,
            command.reply,
            CommandLevels.parse(command.level.lower()),
            command.active,
        )
