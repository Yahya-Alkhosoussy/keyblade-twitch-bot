from pathlib import Path

from aiosqlite import connect

from utils import TwitchCommand, UserLevel

db_dir = Path("database")
db_path = db_dir / "chat_commands.db"


async def init_db():
    async with connect(db_path) as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS commands
            (
                id INTEGER PRIMARY KEY,
                name TEXT,
                reply TEXT,
                user_level TEXT,
                active BOOLEAN DEFAULT 0,
                streamer TEXT,
                UNIQUE(name, reply)
            )
            """
        )
        await conn.commit()


if not db_dir.exists():
    import asyncio

    db_dir.mkdir()
    asyncio.run(init_db())
elif not db_path.exists():
    import asyncio

    asyncio.run(init_db())


async def get_commands():
    async with connect(db_path) as conn:
        async with conn.execute("SELECT name, reply, user_level, active FROM commands") as cur:
            results = await cur.fetchall()
            commands: list[TwitchCommand] = []
            for result in results:
                commands.append(
                    TwitchCommand(
                        name=result[0],
                        reply=result[1],
                        user_level=UserLevel(result[2].lower()),
                        active=bool(result[3]),
                    )
                )
    return commands
