import discord
from discord.ext import commands
import os
import asyncpg
import asyncio

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise Exception("TOKEN not found in environment variables!")

if not DATABASE_URL:
    raise Exception("DATABASE_URL not found in environment variables!")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)
pool = None


# =========================
# DATABASE
# =========================
async def setup_database():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id BIGINT,
                username TEXT,
                display_name TEXT,
                guild_id BIGINT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id SERIAL PRIMARY KEY,
                guild_id BIGINT,
                title TEXT,
                date TEXT,
                time TEXT
            )
        """)


# =========================
# MEMBER LOGGING (SAFE)
# =========================
@bot.event
async def on_member_join(member):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO members (user_id, username, display_name, guild_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, guild_id)
            DO UPDATE SET
                username = EXCLUDED.username,
                display_name = EXCLUDED.display_name
        """,
        member.id,
        member.name,
        member.display_name,
        member.guild.id
        )


@bot.event
async def on_member_remove(member):
    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM members
            WHERE user_id = $1 AND guild_id = $2
        """,
        member.id,
        member.guild.id
        )


@bot.event
async def on_member_update(before, after):
    if before.name != after.name or before.display_name != after.display_name:
        async with pool.acquire() as conn:
            await conn.execute("""
                UPDATE members
                SET username = $1,
                    display_name = $2
                WHERE user_id = $3 AND guild_id = $4
            """,
            after.name,
            after.display_name,
            after.id,
            after.guild.id
            )


# =========================
# CALENDAR EMBED
# =========================
async def create_calendar_embed(guild_id):
    embed = discord.Embed(
        title="📅 Server Kalender",
        color=discord.Color.blue()
    )

    async with pool.acquire() as conn:
        events = await conn.fetch("""
            SELECT id, title, date, time
            FROM calendar_events
            WHERE guild_id = $1
            ORDER BY date, time
        """, guild_id)

    if not events:
        embed.add_field(name="Keine Termine", value="Noch nichts geplant.", inline=False)
    else:
        for event in events:
            embed.add_field(
                name=f"🗓 {event['date']} | ⏰ {event['time']}",
                value=f"{event['title']} (ID: {event['id']})",
                inline=False
            )

    embed.set_footer(text="Nur editaccess Rolle darf bearbeiten")
    return embed


async def update_calendar_message(guild):
    channel = discord.utils.get(guild.channels, name="kalender")
    if not channel:
        return

    async for message in channel.history(limit=10):
        if message.author == bot.user:
            embed = await create_calendar_embed(guild.id)
            await message.edit(embed=embed, view=CalendarView())
            break


# =========================
# BUTTON VIEW
# =========================
class CalendarView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def has_permission(self, interaction):
        role = discord.utils.get(interaction.guild.roles, name="editaccess")
        return role and role in interaction.user.roles

    @discord.ui.button(label="➕ Termin hinzufügen", style=discord.ButtonStyle.green)
    async def add_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return
        await interaction.response.send_modal(AddEventModal())

    @discord.ui.button(label="🗑 Termin löschen", style=discord.ButtonStyle.red)
    async def remove_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.has_permission(interaction):
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return
        await interaction.response.send_modal(RemoveEventModal())


# =========================
# MODALS
# =========================
class AddEventModal(discord.ui.Modal, title="Termin hinzufügen"):

    title_input = discord.ui.TextInput(label="Titel")
    date_input = discord.ui.TextInput(label="Datum (TT.MM.JJJJ)")
    time_input = discord.ui.TextInput(label="Uhrzeit (HH:MM)")

    async def on_submit(self, interaction: discord.Interaction):
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO calendar_events (guild_id, title, date, time)
                VALUES ($1, $2, $3, $4)
            """,
            interaction.guild.id,
            self.title_input.value,
            self.date_input.value,
            self.time_input.value
            )

        await update_calendar_message(interaction.guild)
        await interaction.response.send_message("✅ Termin hinzugefügt!", ephemeral=True)


class RemoveEventModal(discord.ui.Modal, title="Termin löschen"):

    event_id = discord.ui.TextInput(label="Event ID")

    async def on_submit(self, interaction: discord.Interaction):
        async with pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM calendar_events
                WHERE id = $1 AND guild_id = $2
            """,
            int(self.event_id.value),
            interaction.guild.id
            )

        await update_calendar_message(interaction.guild)
        await interaction.response.send_message("🗑 Termin gelöscht!", ephemeral=True)


# =========================
# SETUP COMMAND
# =========================
@bot.command()
async def setup(ctx):
    guild = ctx.guild

    role = discord.utils.get(guild.roles, name="editaccess")
    if not role:
        role = await guild.create_role(name="editaccess")

    channel = discord.utils.get(guild.channels, name="kalender")

    if not channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(send_messages=False),
            guild.me: discord.PermissionOverwrite(send_messages=True)
        }
        channel = await guild.create_text_channel("kalender", overwrites=overwrites)

    embed = await create_calendar_embed(guild.id)
    await channel.send(embed=embed, view=CalendarView())
    await ctx.reply("✅ Kalender & Datenbank aktiv!")


# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    await setup_database()
    print(f"Bot online als {bot.user}")


# =========================
# SAFE START
# =========================
async def main():
    async with bot:
        await bot.start(TOKEN)

asyncio.run(main())
