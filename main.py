import asyncio
from os import getenv
from pathlib import Path
from random import randint

import uvicorn  # noqa
from dotenv import load_dotenv
from fastapi import FastAPI  # noqa
from twitchAPI.chat import Chat, ChatCommand, ChatMessage, EventData
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticationStorageHelper
from twitchAPI.object.eventsub import (
    ChannelAdBreakBeginEvent,
    ChannelBitsUseEvent,
    ChannelCheerEvent,
    ChannelFollowEvent,
    ChannelRaidEvent,
    ChannelSubscriptionGiftEvent,
    GoalEvent,
    HypeTrainEndEvent,
    HypeTrainEvent,
)
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope, ChatEvent

from custom_commands import get_commands
from utils import TwitchCommand, TwitchCommandFromWeb, UserLevel

load_dotenv()
APP_ID = getenv("client_id")
APP_SECRET = getenv("client_secret")
USER_SCOPE = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.USER_WRITE_CHAT,
    AuthScope.CLIPS_EDIT,
    AuthScope.MODERATOR_MANAGE_ANNOUNCEMENTS,
]

MOD_SCOPE = [
    AuthScope.MODERATOR_READ_FOLLOWERS,
    AuthScope.CHANNEL_READ_ADS,
    AuthScope.CHANNEL_READ_SUBSCRIPTIONS,
    AuthScope.BITS_READ,
    AuthScope.CHANNEL_MODERATE,
    AuthScope.CHANNEL_READ_GOALS,
    AuthScope.CHANNEL_READ_HYPE_TRAIN,
    AuthScope.CHANNEL_READ_REDEMPTIONS,
]

TARGET_CHANNEL = ["emberedkeyblade"]


class Bot:
    def __init__(
        self, app_id: str, app_secret: str, user_scope: list[AuthScope], mod_scope: list[AuthScope], target_channel: list[str]
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.user_scope = user_scope
        self.mod_scope = mod_scope
        self.target_channel = target_channel

        self.eventsub: EventSubWebsocket | None = None
        self.mod_eventsub: EventSubWebsocket | None = None
        self.twitch: Twitch | None = None
        self.mod_twitch: Twitch | None = None
        self.chat: Chat | None = None
        self.keyblade_id: str | None = None
        self.bot_id: str | None = None
        self.commands: dict[str, TwitchCommand] = {}

    async def setup(self):
        if not Path("tokens").exists():
            print("tokens folder not found. Making")
            Path("tokens").mkdir()

        self.twitch = Twitch(self.app_id, self.app_secret)
        twitch_helper = UserAuthenticationStorageHelper(self.twitch, self.user_scope, Path("tokens/bot.json"))
        await twitch_helper.bind()

        self.mod_twitch = Twitch(self.app_id, self.app_secret)
        twitch_helper = UserAuthenticationStorageHelper(self.mod_twitch, self.mod_scope, Path("tokens/keyblade.json"))
        await twitch_helper.bind()

        user = await first(self.mod_twitch.get_users())
        if user is None:
            raise ValueError("Could not find keyblade! check for name change")
        self.keyblade_id = user.id

        bot = await first(self.twitch.get_users())
        if bot is None:
            raise ValueError("Could not find the bot! Check for name change")
        self.bot_id = bot.id

        self.eventsub = EventSubWebsocket(self.twitch)
        self.eventsub.start()

        self.mod_eventsub = EventSubWebsocket(self.mod_twitch)
        self.mod_eventsub.start()

        self.chat = await Chat(self.twitch)
        for command in await get_commands():
            self.commands[command.name] = command

    async def on_ready(self, ready_event: EventData):
        print("Bot is ready!")
        await ready_event.chat.join_room(self.target_channel)
        print("Bot joined target channels")

    async def update_command_list(self, command: TwitchCommand):
        self.commands[command.name] = command

    async def delete_command(self, command: TwitchCommand):
        self.commands.pop(command.name)

    def __is_command_level_met(self, command_level: UserLevel, message: ChatMessage) -> bool:
        assert message.room
        match command_level:
            case UserLevel.EVERYONE:
                return True
            case UserLevel.MODS:
                is_mod = message.user.mod or any(b in message.user.badges for b in ("moderator", "broadcaster"))
                if is_mod:
                    return True
                else:
                    return False
            case UserLevel.SUBSCRIBER:
                is_sub = message.user.subscriber or any(b in message.user.badges for b in ("subscriber", "founder"))
                is_vip = message.user.vip or "vip" in message.user.badges
                is_mod = message.user.mod or any(b in message.user.badges for b in ("moderator", "broadcaster"))

                if is_sub or is_vip or is_mod:
                    return True
                else:
                    return False
            case UserLevel.BROADCASTER:
                if message.user.name == message.room.name:
                    return True
                else:
                    return False
            case UserLevel.VIP:
                is_vip = message.user.vip or "vip" in message.user.badges
                is_mod = message.user.mod or any(b in message.user.badges for b in ("moderator", "broadcaster"))
                if is_vip or is_mod:
                    return True
                else:
                    return False
            case _:
                raise ValueError("Invalid Command Level")

    async def __deal_with_variables(self, message: str, msg: ChatMessage) -> str:
        assert msg.room and self.twitch
        if r"${user}" in message:
            message = message.replace(r"${user}", msg.user.display_name)
        if r"${game}" in message:
            stream = await first(self.twitch.get_streams(user_id=[msg.room.room_id]))

            if stream:
                game = stream.game_name
            else:
                channel_info = await self.twitch.get_channel_information(broadcaster_id=msg.room.room_id)
                game = channel_info[0].game_name

            message = message.replace(r"${game}", game)
        if r"${random}" in message:
            number = randint(0, 300)
            message = message.replace(r"${random}", str(number))
        return message

    async def on_message(self, msg: ChatMessage):
        if msg.text.split()[0] in self.commands:  # check the first word only
            command = self.commands[msg.text.split()[0]]
            if not command.active:
                return
            level_met = self.__is_command_level_met(command.user_level, msg)
            if level_met:
                command_reply = await self.__deal_with_variables(command.reply, msg)
                await msg.reply(command_reply)

    async def on_raid(self, _event: ChannelRaidEvent):
        assert self.twitch and self.chat
        event = _event.event
        raider = event.from_broadcaster_user_name
        raider_id = event.from_broadcaster_user_id
        channel_raided = event.to_broadcaster_user_name
        viewer_count = event.viewers

        stream = await first(self.twitch.get_streams(user_id=[raider_id]))

        if stream:
            game = stream.game_name
        else:
            channel_info = await self.twitch.get_channel_information(broadcaster_id=raider_id)
            game = channel_info[0].game_name

        await self.chat.send_message(
            room=channel_raided,
            text=f"{raider} is raiding the channel with {viewer_count} viewers! They were playing {game} "
            f"Check them out on https://twitch.tv/{raider}",
        )

    async def clip_command(self, cmd: ChatCommand):
        assert self.twitch and self.chat and self.keyblade_id

        if not cmd.room:
            return  # ignore it if it is a whisper

        try:
            created_clip = await self.twitch.create_clip(self.keyblade_id)
        except Exception as e:
            print(f"Got an error making the clip {str(e)}")
            await cmd.reply("Sorry, failed to make the clip")
            return

        clip = await first(self.twitch.get_clips(clip_id=[created_clip.id]))
        if clip is None:
            for _ in range(60):
                await asyncio.sleep(1)
                clip = await first(self.twitch.get_clips(clip_id=[created_clip.id]))
                if clip is not None:
                    break
        if clip is None:
            await cmd.reply("Sorry, but I could not find the clip I made")
            return
        await self.chat.send_message(room=cmd.room.name, text=clip.url)

    async def close_bot(self):
        assert self.eventsub and self.chat
        assert self.twitch
        await self.eventsub.stop()
        self.chat.stop()
        await self.twitch.close()

    async def on_follow(self, event: ChannelFollowEvent):
        assert self.chat
        await self.chat.send_message(event.event.broadcaster_user_login, f"Thank you for following {event.event.user_name}!")

    async def on_ad_break(self, _event: ChannelAdBreakBeginEvent):
        assert self.chat and self.keyblade_id and self.bot_id
        assert self.twitch
        await self.twitch.send_chat_announcement(
            self.keyblade_id,
            self.bot_id,
            f"Incoming ad break! Ads will be playing for {_event.event.duration_seconds}",
            color="purple",
        )

    async def on_channel_sub_gift(self, _event: ChannelSubscriptionGiftEvent):
        assert self.chat
        event = _event.event
        gifter = event.user_login if not event.is_anonymous else "anonymous"
        total_gifted = event.cumulative_total
        tier_of_sub = event.tier
        tier = 0
        match tier_of_sub:
            case "1000":
                tier = 1
            case "2000":
                tier = 2
            case "3000":
                tier = 3

        if total_gifted and tier != 0:
            await self.chat.send_message(
                event.broadcaster_user_login,
                f"Thank you {gifter} for gifting {total_gifted} tier {tier} sub{'s' if total_gifted > 1 else ''}!",
            )
        elif total_gifted:
            await self.chat.send_message(event.broadcaster_user_login, f"Thank you {gifter} for gifting {total_gifted} subs!")
        else:
            await self.chat.send_message(event.broadcaster_user_login, f"Thank you {gifter} for gifting subs!!")

    async def on_channel_cheer(self, _event: ChannelCheerEvent):
        assert self.chat
        cheerer = _event.event.user_name if not _event.event.is_anonymous else "anonymous"
        await self.chat.send_message(
            _event.event.broadcaster_user_name,
            f"Thank you {cheerer} for cheering with {_event.event.bits}!",
        )

    async def on_channel_goal_end(self, _event: GoalEvent):
        assert self.chat
        if not _event.event.is_achieved:
            return

        type = _event.event.type

        goal_type = ""

        match type:
            case "follow":
                goal_type = "followers"
            case "subscription":
                goal_type = "subscribers"
            case "subscription_count":
                goal_type = "subscribers"
            case "new_subscription":
                goal_type = "new subscribers"
            case "new_subscription_count":
                goal_type = "new subscribers"

        if goal_type == "":
            return

        await self.chat.send_message(
            _event.event.broadcaster_user_login,
            f"Thank you everyone! We have successfully achieved the goal of {_event.event.current_amount} {goal_type}!!",
        )

    async def on_hype_train(self, _event: HypeTrainEvent):
        assert self.twitch and self.keyblade_id and self.bot_id
        event = _event.event
        await self.twitch.send_chat_announcement(
            self.keyblade_id,
            self.bot_id,
            f"HYPE TRAIN!!! Thank you guys for starting a hype train! We need {event.goal} points to reach the next level!!",
        )

    async def on_hype_train_end(self, _event: HypeTrainEndEvent):
        assert self.twitch and self.keyblade_id and self.bot_id
        event = _event.event

        await self.twitch.send_chat_announcement(
            self.keyblade_id,
            self.bot_id,
            f"HYPE TRAIN ENDED!! Thank you all for this hype train! We ended at level {event.level} of the hype train."
            f" The total contributions to this hype train was {event.total} points!",
        )

    async def on_channel_bits_use(self, _event: ChannelBitsUseEvent):
        assert self.chat
        event = _event.event
        match event.type:
            case "cheer":
                return
            case "power_up":
                await self.chat.send_message(
                    event.broadcaster_user_login,
                    f"Thank you {event.user_name} for redeeming a power up for {event.bits}!!",
                )
            case "combo":
                await self.chat.send_message(
                    event.broadcaster_user_login, f"Thank you {event.user_name} for redeeming a combo for {event.bits}!!"
                )

    async def run(self):
        try:
            await self.setup()
            assert self.twitch, "Twitch instance is None"
            assert self.eventsub, "Eventsub instance is None"
            assert self.chat, "Chat instance is None"
            assert self.keyblade_id, "Keyblade's ID is None"
            assert self.bot_id, "Bot ID is None!!"
            assert self.mod_eventsub, "Mod eventsub is None!!"

            self.chat.register_event(ChatEvent.READY, self.on_ready)
            self.chat.register_event(ChatEvent.MESSAGE, self.on_message)

            self.chat.register_command("clip", self.clip_command)

            await self.mod_eventsub.listen_channel_raid(self.on_raid, to_broadcaster_user_id=self.keyblade_id)
            await self.mod_eventsub.listen_channel_follow_v2(self.keyblade_id, self.keyblade_id, self.on_follow)
            await self.mod_eventsub.listen_channel_ad_break_begin(self.keyblade_id, self.on_ad_break)
            await self.mod_eventsub.listen_channel_subscription_gift(self.keyblade_id, self.on_channel_sub_gift)
            await self.mod_eventsub.listen_channel_cheer(self.keyblade_id, self.on_channel_cheer)
            await self.mod_eventsub.listen_goal_end(self.keyblade_id, self.on_channel_goal_end)
            await self.mod_eventsub.listen_hype_train_begin(self.keyblade_id, self.on_hype_train)
            await self.mod_eventsub.listen_hype_train_end(self.keyblade_id, self.on_hype_train_end)
            await self.mod_eventsub.listen_channel_bits_use(self.keyblade_id, self.on_channel_bits_use)
            # await self.mod_eventsub.listen_channel_points_custom_reward_redemption_add()
            # await self.mod_eventsub.listen_channel_ban()
            # await self.mod_eventsub.listen_channel_unban()

            self.chat.start()

            await asyncio.Event().wait()
        except Exception as e:
            print(f"Error: {e}")
        finally:
            await self.close_bot()


assert APP_ID and APP_SECRET
bot = Bot(APP_ID, APP_SECRET, USER_SCOPE, MOD_SCOPE, TARGET_CHANNEL)

app = FastAPI()


@app.post("/api/v1/update_commands")
async def command_added(command: TwitchCommandFromWeb):
    print("Adding command")
    temp_command = TwitchCommand("", "", UserLevel.EVERYONE, False)
    await bot.update_command_list(temp_command.from_pydantic(command))
    print("command was added")
    return {"status": "ok"}


@app.post("/api/v1/delete_command")
async def command_deleted(command: TwitchCommandFromWeb):
    print("Deleting command")
    temp_command = TwitchCommand("", "", UserLevel.EVERYONE, False)
    await bot.delete_command(temp_command.from_pydantic(command))
    print("Command deleted")
    return {"status": "ok"}


async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=7000, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(bot.run(), server.serve(), return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
