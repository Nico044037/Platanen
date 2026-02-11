import discord
from discord.ext import commands
import os
import asyncpg

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

bot = commands.Bot(command_prefix="$", intents=intents)
pool = None


# =========================
# DATABASE SETUP
# =========================
async def setup_database():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        # Members table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS members (
                user_id BIGINT,
                username TEXT,
                display_name TEXT,
                guild_id BIGINT,
                PRIMARY KEY (user_id, guild_id)
            )
        """)

        # Calendar table
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
# MEMBER SYNC
# =========================
async def sync_guild_members(guild):
    async with pool.acquire() as conn:
        for member in guild.members:
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
            guild.id
            )


@bot.event
async def on_member_join(member):
    await sync_guild_members(member.guild)


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
        await sync_guild_members(after.guild)


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

    embed.set_footer(text="Nur editaccess Rolle kann bearbeiten")
    return embed


async def update_calendar_message(guild):
    channel = discord.utils.get(guild.channels, name="kalender")

    if not channel:
        return

    async for message in channel.history(limit=20):
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

    async def check_role(self, interaction):
        role = discord.utils.get(interaction.guild.roles, name="editaccess")
        return role in interaction.user.roles

    @discord.ui.button(label="➕ Termin hinzufügen", style=discord.ButtonStyle.green)
    async def add_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_role(interaction):
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return
        await interaction.response.send_modal(AddEventModal())

    @discord.ui.button(label="🗑 Termin löschen", style=discord.ButtonStyle.red)
    async def remove_event(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_role(interaction):
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return
        await interaction.response.send_modal(RemoveEventModal())


# =========================
# MODALS
# =========================
class AddEventModal(discord.ui.Modal, title="Neuen Termin hinzufügen"):

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

    event_id = discord.ui.TextInput(label="Event ID (steht im Kalender)")

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

    for guild in bot.guilds:
        await sync_guild_members(guild)

    print(f"Bot online als {bot.user}")


bot.run(TOKEN)
