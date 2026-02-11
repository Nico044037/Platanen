import discord
from discord.ext import commands
import os
import json
from datetime import datetime

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="$", intents=intents)

DATA_FILE = "calendar_data.json"


# -------------------------
# JSON Speicher
# -------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# -------------------------
# Embed erstellen
# -------------------------
def create_calendar_embed(guild_id):
    data = load_data()
    events = data.get(str(guild_id), [])

    embed = discord.Embed(
        title="📅 Server Kalender",
        description="Geplante Termine:",
        color=discord.Color.blue()
    )

    if not events:
        embed.add_field(name="Keine Termine", value="Noch nichts geplant.", inline=False)
    else:
        for event in events:
            embed.add_field(
                name=f"🗓 {event['date']} | ⏰ {event['time']}",
                value=f"{event['title']}",
                inline=False
            )

    embed.set_footer(text="Nur editaccess Rolle kann bearbeiten")
    return embed


# -------------------------
# Setup Command
# -------------------------
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

    view = CalendarView()
    embed = create_calendar_embed(guild.id)
    await channel.send(embed=embed, view=view)

    await ctx.reply("✅ Kalender eingerichtet!")


# -------------------------
# Buttons
# -------------------------
class CalendarView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Termin hinzufügen", style=discord.ButtonStyle.green)
    async def add_event(self, interaction: discord.Interaction, button: discord.ui.Button):

        role = discord.utils.get(interaction.guild.roles, name="editaccess")
        if role not in interaction.user.roles:
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return

        await interaction.response.send_modal(AddEventModal())


    @discord.ui.button(label="🗑 Termin löschen", style=discord.ButtonStyle.red)
    async def remove_event(self, interaction: discord.Interaction, button: discord.ui.Button):

        role = discord.utils.get(interaction.guild.roles, name="editaccess")
        if role not in interaction.user.roles:
            await interaction.response.send_message("❌ Keine Berechtigung!", ephemeral=True)
            return

        await interaction.response.send_modal(RemoveEventModal())


# -------------------------
# Modal – Termin hinzufügen
# -------------------------
class AddEventModal(discord.ui.Modal, title="Neuen Termin hinzufügen"):

    title_input = discord.ui.TextInput(label="Titel")
    date_input = discord.ui.TextInput(label="Datum (TT.MM.JJJJ)")
    time_input = discord.ui.TextInput(label="Uhrzeit (HH:MM)")

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_data()

        if guild_id not in data:
            data[guild_id] = []

        data[guild_id].append({
            "title": self.title_input.value,
            "date": self.date_input.value,
            "time": self.time_input.value
        })

        save_data(data)

        await update_calendar_message(interaction)
        await interaction.response.send_message("✅ Termin hinzugefügt!", ephemeral=True)


# -------------------------
# Modal – Termin löschen
# -------------------------
class RemoveEventModal(discord.ui.Modal, title="Termin löschen"):

    title_input = discord.ui.TextInput(label="Titel des Termins")

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_data()

        if guild_id in data:
            data[guild_id] = [
                event for event in data[guild_id]
                if event["title"] != self.title_input.value
            ]

        save_data(data)

        await update_calendar_message(interaction)
        await interaction.response.send_message("🗑 Termin gelöscht!", ephemeral=True)


# -------------------------
# Kalender Nachricht updaten
# -------------------------
async def update_calendar_message(interaction):
    channel = discord.utils.get(interaction.guild.channels, name="kalender")

    async for message in channel.history(limit=20):
        if message.author == bot.user:
            await message.edit(embed=create_calendar_embed(interaction.guild.id), view=CalendarView())
            break


# -------------------------
bot.run(os.getenv("TOKEN"))
