import discord
from discord.ext import commands
import re
from datetime import datetime

# CONFIGURAZIONE RUOLI E CANALI
INITIAL_ROLE = "Viandante"
FINAL_ROLE = "Planeswalker"
PRESENTATION_CHANNEL = "👓presentazioni👓"

class PresentationModal(discord.ui.Modal, title="Presentazione Clepshydra"):
    personali = discord.ui.TextInput(label="Dati Personali", style=discord.TextStyle.paragraph, default="Nome: \nNickname: \nAnno di nascita: \nProfessione: \nProvenienza: ", min_length=50, required=True)
    inizio_magic = discord.ui.TextInput(label="Inizio Magic", style=discord.TextStyle.paragraph, default="Anno di inizio magic cartaceo: \nAnno di inizio MTGA: ", required=True)
    preferenze = discord.ui.TextInput(label="Preferenze (Formati, Colori, Gilde)", style=discord.TextStyle.paragraph, default="Formati preferiti: \nColori preferiti: \nGilde: ", required=True)
    risultati = discord.ui.TextInput(label="Risultati in Magic", style=discord.TextStyle.paragraph, required=False)
    passioni = discord.ui.TextInput(label="Altre Passioni", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=True)
            
            logger = interaction.client.get_cog('Logger')
            member = interaction.user
            testo_totale = f"{self.personali.value}\n{self.inizio_magic.value}\n{self.preferenze.value}"
            
            patterns = {
                "Nome": r"Nome:[ \t]*(.+)",
                "Nickname": r"Nickname:[ \t]*(.+)",
                "Anno di nascita": r"Anno di nascita:[ \t]*(.+)",
                "Professione": r"Professione:[ \t]*(.+)",
                "Provenienza": r"Provenienza:[ \t]*(.+)",
                "Cartaceo": r"Anno di inizio magic cartaceo:[ \t]*(.+)",
                "Arena": r"Anno di inizio MTGA:[ \t]*(.+)",
                "Formati": r"Formati preferiti:[ \t]*(.+)",
                "Colori": r"Colori preferiti:[ \t]*(.+)",
                "Gilde": r"Gilde(?: preferite)?:[ \t]*(.+)",
            }
            
            campi_mancanti = set()
            campi_invalidi = set()
            dati_estratti = {}

            for campo, pattern in patterns.items():
                match = re.search(pattern, testo_totale, re.IGNORECASE | re.MULTILINE)
                
                if match and match.group(1).strip():
                    contenuto = match.group(1).strip().lower()
                    dati_estratti[campo] = contenuto
                    
                    if campo == "Anno di nascita":
                        anno_corrente = datetime.now().year

                        if not re.fullmatch(r"\d{4}", contenuto):
                            campi_invalidi.add("Anno di nascita")
                        else:
                            anno = int(contenuto)
                            eta = anno_corrente - anno

                            if not (1900 < anno < anno_corrente) or eta < 16:
                                campi_invalidi.add("Anno di nascita")

                    if campo == "Cartaceo":
                        if contenuto not in ["mai", "no"]:
                            if not re.fullmatch(r"\d{4}", contenuto):
                                campi_invalidi.add("Anno inizio Cartaceo")
                            else:
                                anno_cartaceo = int(contenuto)

                                if anno_cartaceo < 1993 or anno_cartaceo > datetime.now().year:
                                    campi_invalidi.add("Anno inizio Cartaceo")

                    if campo == "Arena":
                        if contenuto not in ["mai", "no"]:

                            if not re.fullmatch(r"\d{4}", contenuto):
                                campi_invalidi.add("Anno inizio Arena")
                            else:
                                anno_arena = int(contenuto)

                                if anno_arena < 2017 or anno_arena > datetime.now().year:
                                    campi_invalidi.add("Anno inizio Arena")
                            
                    if campo == "Formati":
                        formati_validi = [
                            "standard", "pioneer", "modern", "legacy", "vintage", 
                            "draft", "sealed", "limited", "centurion", "penny dreadful", 
                            "extended", "two-headed giant", "two headed giant", "conspiracy", 
                            "planechase", "archenemy", "momir", "kitchen table",
                            "commander", "oathbreaker", "alchemy", "historic",
                            "brawl", "timeless", "pauper", "penny", "artisan",
                            "nessuno", "n/a"
                            ]
                        formati_utente = [
                            f.strip()
                            for f in re.split(r"\s*,\s*|\s+e\s+|\s*/\s*|\s*\|\s*", contenuto)
                        ]
                        def formato_valido(f):
                            return (
                                f in formati_validi
                                or "block" in f
                                or "blocco" in f
                            )
                        if not all(formato_valido(f) for f in formati_utente):
                            campi_invalidi.add("Formati preferiti")
                    
                    if campo == "Colori":
                        colori_validi = [
                                "bianco", "nero", "rosso", "blu", "verde", "incolore", 
                                "white", "black", "red", "blue", "green", "colorless",
                                "w", "b", "r", "u", "g", "5c",
                                "tutti", "nessuno", "n/a"
                            ]
                       
                        colori_utente = [
                            f.strip()
                            for f in re.split(r"\s*,\s*|\s+e\s+|\s*/\s*|\s*\|\s*", contenuto)
                        ]
                        if not all(f in colori_validi for f in colori_utente):
                            campi_invalidi.add("Colori preferiti")
                            
                    if campo == "Gilde":
                        gilde_valide = [
                                "azorius", "rakdos", "boros", "golgari",
                                "orzhov", "selesnya", "gruul", "izzet",
                                "dimir", "simic",
                                "esper", "grixis", "bant", "temur",
                                "jeskai", "mardu", "abzan", "sultai",
                                "jund", "naya", 
                                "wu", "uw", "wb", "bw", "wr", "rw",
                                "wg", "gw", "ub", "bu", "ur", "ru",
                                "ug", "gu", "br", "rb", "bg", "gb",
                                "rg", "gr",
                                "nessuno", "n/a", "tutte"
                            ]
                       
                        gilde_utente = [
                            f.strip()
                            for f in re.split(r"\s*,\s*|\s+e\s+|\s*/\s*|\s*\|\s*", contenuto)
                        ]
                        if not all(f in gilde_valide for f in gilde_utente):
                            campi_invalidi.add("Gilde preferite")
                else:
                    campi_mancanti.add(campo)

            if campi_mancanti or campi_invalidi:
                if logger:
                    await logger.send_log(
                        level="WARN", 
                        event="VERIFICA_FALLITA", 
                        user=member, 
                        info=(
                            f"\nCampi mancanti: {', '.join(sorted(campi_mancanti))} "
                            f"\nCampi invalidi: {', '.join(sorted(campi_invalidi))}"
                        )
                    )
                
                msg = "❌ **Ci sono problemi nella tua presentazione.**\n\n"

                if campi_mancanti:
                    msg += (
                        "📌 **Campi mancanti:**\n"
                        + "\n".join(f"• {c}" for c in sorted(campi_mancanti))
                        + "\n\n"
                    )

                if campi_invalidi:
                    msg += (
                        "⚠️ **Campi con valori non validi:**\n"
                        + "\n".join(f"• {c}" for c in sorted(campi_invalidi))
                        + "\n\n"
                    )

                msg += (
                    "💡 **Esempi validi:**\n"
                    "• `Anno di nascita: 1999`\n"
                    "• `Formati preferiti: Standard, Modern`\n"
                    "• `Colore preferito: Rosso`\n"
                    "• `Gilde: Azorius`"
                )

                return await interaction.followup.send(msg, ephemeral=True)

            try:
                guild = interaction.guild
                presentation_channel = discord.utils.get(guild.text_channels, name=PRESENTATION_CHANNEL)

                embed = discord.Embed(
                    title=f"🛡️ Nuova Presentazione: {member.display_name}", 
                    description=f"**Account originale:** `{member.name}`",
                    color=discord.Color.green(),
                    timestamp=datetime.now()
                )
                embed.set_thumbnail(url=member.display_avatar.url)

                embed.add_field(name="👤 Dati Personali", value=(
                    f"**Nome:** {dati_estratti['Nome']}\n**Nick Arena:** {dati_estratti['Nickname']}\n"
                    f"**Anno nascita:** {dati_estratti['Anno di nascita']}\n**Lavoro:** {dati_estratti['Professione']}\n"
                    f"**Provenienza:** {dati_estratti['Provenienza']}"
                ), inline=False)
                
                embed.add_field(name="📅 Inizio Magic", value=(
                    f"**Cartaceo:** {dati_estratti['Cartaceo']}\n**Arena:** {dati_estratti['Arena']}"
                ), inline=False)
                
                embed.add_field(name="🃏 Preferenze", value=(
                    f"**Formati:** {dati_estratti['Formati']}\n**Colori:** {dati_estratti['Colori']}\n"
                    f"**Gilde:** {dati_estratti['Gilde']}"
                ), inline=False)

                if self.risultati.value.strip():
                    embed.add_field(name="🏆 Risultati", value=self.risultati.value, inline=False)
                if self.passioni.value.strip():
                    embed.add_field(name="🌟 Altre Passioni", value=self.passioni.value, inline=False)

                presentation_msg = None
                if presentation_channel:
                    presentation_msg = await presentation_channel.send(embed=embed)

                initial_role = discord.utils.get(guild.roles, name=INITIAL_ROLE)
                final_role = discord.utils.get(guild.roles, name=FINAL_ROLE)
                
                if initial_role in member.roles:
                    await member.remove_roles(initial_role)
                if final_role:
                    await member.add_roles(final_role)

                if logger:
                    info_text = f"Utente promosso a {FINAL_ROLE}"
                    if presentation_msg:
                        info_text += f"\n**Link:** [Presentation]({presentation_msg.jump_url})"
                    await logger.send_log(
                        level="INFO", 
                        event="PRESENTAZIONE_COMPLETATA", 
                        user=member, 
                        info=info_text
                    )   
                
                await interaction.followup.send("✅ Benvenuto tra i Planeswalker!", ephemeral=True)

            except Exception as e:
                if logger:
                    await logger.send_log(
                        level="ERROR", 
                        event="SUBMIT_ERROR", 
                        user=member, 
                        info=f"Errore critico durante on_submit: {str(e)}"
                    )
                await interaction.followup.send("⚠️ Errore durante l'elaborazione. Riprova.", ephemeral=True)  
                
class Presentation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @commands.Cog.listener()
    async def on_member_join(self, member):
        logger = self.bot.get_cog('Logger')
        role = discord.utils.get(member.guild.roles, name=INITIAL_ROLE)
        try:
            if role:
                await member.add_roles(role)
        except discord.errors.HTTPException as e:
            if logger:
                level = "WARN" if e.status == 429 else "ERROR"
                await logger.send_log(
                    level=level,
                    event="JOIN_ROLE_FAIL",
                    user=member,
                    info=f"Errore API {e.status}: {e.text}"
                )
        except discord.errors.Forbidden:
            if logger:
                await logger.send_log(
                    level="ERROR",
                    event="JOIN_PERMISSIONS_FAIL",
                    user=member,
                    info="Il bot non ha permessi per gestire il ruolo Viandante."
                )
        
        channel = discord.utils.get(member.guild.text_channels, name=PRESENTATION_CHANNEL)
        if channel:
            await channel.send(
                f'''👋 Benvenuto {member.mention}! Attualmente hai una visione limitata dei canali del serve. \nUsa `/presentati` per sbloccare tutte le funzionalità del server. \nAll'interno troverai canali specifici per ogni formato di Magic Arena, canali generali e qualche nuovo amico.
                ''',
                delete_after=300.0
            )       
        
    @discord.app_commands.command(name="presentati", description="Apri il modulo di presentazione")
    async def presentati(self, interaction: discord.Interaction):
        if any(role.name == FINAL_ROLE for role in interaction.user.roles):
            return await interaction.response.send_message("Sei già verificato!", ephemeral=True)
        await interaction.response.send_modal(PresentationModal())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user: return
        
        if message.channel.name == PRESENTATION_CHANNEL:
            logger = self.bot.get_cog('Logger')
            try:
                await message.delete()
                if logger:
                    await logger.send_log(
                        level="INFO",
                        event="MESSAGE_DELETE",
                        user=message.author,
                        channel=message.channel,
                        info=f"Messaggio rimosso: {message.content}"
                    )
                await message.channel.send(
                    f"⚠️ {message.author.mention}, in questo canale puoi solo usare `/presentati`. I messaggi normali vengono eliminati.",
                    delete_after= 15
                )
            except Exception as e:
                if logger:
                    await logger.send_log(
                        level="ERROR",
                        event="CLEANUP_ERROR",
                        channel=message.channel,
                        info=f"Impossibile eliminare messaggio: {str(e)}"
                    )
                    
async def setup(bot):
    await bot.add_cog(Presentation(bot))