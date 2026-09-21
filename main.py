import asyncio
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from twitchAPI.chat import Chat, ChatCommand, ChatMessage, EventData
from twitchAPI.eventsub.websocket import EventSubWebsocket
from twitchAPI.helper import first
from twitchAPI.oauth import UserAuthenticationStorageHelper
from twitchAPI.object.eventsub import ChannelRaidEvent
from twitchAPI.twitch import Twitch
from twitchAPI.type import AuthScope, ChatEvent

load_dotenv()
APP_ID = getenv("client_id")
APP_SECRET = getenv("client_secret")
USER_SCOPE = [
    AuthScope.CHAT_READ,
    AuthScope.CHAT_EDIT,
    AuthScope.USER_WRITE_CHAT,
    AuthScope.CLIPS_EDIT,
]

TARGET_CHANNEL = ["emberedkeyblade"]


class Bot:
    def __init__(self, app_id: str, app_secret: str, user_scope: list[AuthScope], target_channel: list[str]):
        self.app_id = app_id
        self.app_secret = app_secret
        self.user_scope = user_scope
        self.target_channel = target_channel

        self.eventsub: EventSubWebsocket | None = None
        self.twitch: Twitch | None = None
        self.chat: Chat | None = None
        self.keyblade_id: str | None = None
        self.bot_id: str | None = None

    async def setup(self):
        self.twitch = Twitch(self.app_id, self.app_secret)
        twitch_helper = UserAuthenticationStorageHelper(self.twitch, self.user_scope, Path("tokens/bot.json"))
        await twitch_helper.bind()

        user = await first(self.twitch.get_users(logins=["emberedkeyblade"]))
        if user is None:
            raise ValueError("Could not find keyblade! check for name change")
        self.keyblade_id = user.id

        bot = await first(self.twitch.get_users(logins=["Bot name"]))
        if bot is None:
            raise ValueError("Could not find the bot! Check for name change")
        self.bot_id = bot.id

        self.eventsub = EventSubWebsocket(self.twitch)
        self.eventsub.start()

        self.chat = await Chat(self.twitch)

    async def on_ready(self, ready_event: EventData):
        print("Bot is ready!")
        await ready_event.chat.join_room(self.target_channel)
        print("Bot joined target channels")

    async def on_message(self, msg: ChatMessage):
        pass  # just in case I want to use it in the future

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
            text=f"{raider} is raiding the channel with {viewer_count} viewers! They were playing {game}"
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

    async def lurk_command(self, cmd: ChatCommand):
        await cmd.reply(f"Thank you for lurking {cmd.user.display_name}! Hope you enjoy the stream and sit back and relax")

    async def close_bot(self):
        assert self.eventsub and self.chat
        assert self.twitch
        await self.eventsub.stop()
        self.chat.stop()
        await self.twitch.close()

    async def run(self):
        await self.setup()
        assert self.twitch, "Twitch instance is None"
        assert self.eventsub, "Eventsub instance is None"
        assert self.chat, "Chat instance is None"
        assert self.keyblade_id, "Keyblade's ID is None"
        assert self.bot_id, "Bot ID is None!!"

        self.chat.register_event(ChatEvent.READY, self.on_ready)
        self.chat.register_event(ChatEvent.MESSAGE, self.on_message)

        self.chat.register_command("lurk", self.lurk_command)
        self.chat.register_command("clip", self.clip_command)

        await self.eventsub.listen_channel_raid(self.on_raid, to_broadcaster_user_id=self.keyblade_id)

        self.chat.start()

        try:
            input("press ENTER to stop \n")
        finally:
            await self.close_bot()


assert APP_ID and APP_SECRET
bot = Bot(APP_ID, APP_SECRET, USER_SCOPE, TARGET_CHANNEL)
asyncio.run(bot.run())
