import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="$", intents=intents)

calendar_message_id = None


@bot.event
async def on_ready():
    print(f"Eingeloggt als {bot.user}")


@bot.command()
async def setup(ctx):

    guild = ctx.guild

    # Rolle erstellen
    role = discord.utils.get(guild.roles, name="editaccess")
    if not role:
        role = await guild.create_role(
            name="editaccess",
            colour=discord.Colour.blue(),
            reason="Kalender Bearbeitungsrolle"
        )

    # Kanal erstellen
    channel = discord.utils.get(guild.channels, name="kalender")

    if not channel:
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(send_messages=False),
            guild.me: discord.PermissionOverwrite(send_messages=True)
        }

        channel = await guild.create_text_channel(
            "kalender",
            overwrites=overwrites
        )

    # Button erstellen
    class EditButton(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="Bearbeiten", style=discord.ButtonStyle.primary, custom_id="edit_calendar")
        async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):

            if role not in interaction.user.roles:
                await interaction.response.send_message(
                    "❌ Du hast keine Berechtigung!",
                    ephemeral=True
                )
                return

            class EditModal(discord.ui.Modal, title="Kalender bearbeiten"):
                kalender_input = discord.ui.TextInput(
                    label="Neuer Kalender Inhalt",
                    style=discord.TextStyle.paragraph,
                    required=True
                )

                async def on_submit(self, interaction: discord.Interaction):

                    messages = [msg async for msg in channel.history(limit=10)]
                    bot_message = next((m for m in messages if m.author == bot.user), None)

                    if bot_message:
                        await bot_message.edit(
                            content=f"📅 **Server Kalender**\n\n{self.kalender_input.value}",
                            view=EditButton()
                        )

                    await interaction.response.send_message(
                        "✅ Kalender aktualisiert!",
                        ephemeral=True
                    )

            await interaction.response.send_modal(EditModal())

    # Kalender Nachricht senden
    msg = await channel.send(
        "📅 **Server Kalender**\n\nNoch keine Termine eingetragen.",
        view=EditButton()
    )

    await ctx.reply("✅ Kalender wurde eingerichtet!")


# Token aus Environment Variable (für Railway!)
bot.run(os.getenv("TOKEN"))
