import discord
from discord.ext import commands
import os, re
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# CONFIG
INITIAL_ROLE = "Viandante"
FINAL_ROLE = "Planeswalker"
PRESENTATION_CHANNEL = "👓presentazioni👓"

# --- CONFIGURAZIONE COLORI CONSOLE ---
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_CYAN = "\033[96m"
C_BOLD = "\033[1m"
C_END = "\033[0m"

class PresentationModal(discord.ui.Modal, title="Presentazione Clepshydra"):
    personali = discord.ui.TextInput(
        label="Dati Personali",
        style=discord.TextStyle.paragraph,
        default="Nome: \nNickname: \nAnno di nascita: \nProfessione: \nProvenienza: ",
        min_length=50, 
        required=True
    )
    
    inizio_magic = discord.ui.TextInput(
        label="Inizio Magic",
        style=discord.TextStyle.paragraph,
        default="Anno di inizio magic cartaceo: \nAnno di inizio MTGA: ",
        placeholder="Es: Cartaceo 2010 o Mai, Arena 2020",
        required=True
    )
    
    preferenze = discord.ui.TextInput(
        label="Preferenze (Formati, Colori, Gilde)",
        style=discord.TextStyle.paragraph,
        default="Formati preferiti: \nColore preferito: \nGilde: ",
        placeholder="I tuoi formati e colori preferiti...",
        required=True
    )
    
    risultati = discord.ui.TextInput(
        label="Risultati in Magic",
        style=discord.TextStyle.paragraph,
        placeholder="Opzionale: i tuoi traguardi...",
        required=False
    )
    
    passioni = discord.ui.TextInput(
        label="Altre Passioni",
        style=discord.TextStyle.paragraph,
        placeholder="Opzionale: cosa fai oltre a Magic?",
        required=False
    )


    async def on_submit(self, interaction: discord.Interaction):
        
        await interaction.response.defer(ephemeral=True)
        # 1. Definiamo i pattern per cercare il testo dopo le etichette.
        # Spiegazione Regex: 
        # ^ indica inizio riga, \s* gestisce spazi, (.+) cattura il contenuto
        testo_totale = f"{self.personali.value}\n{self.inizio_magic.value}\n{self.preferenze.value}"
        patterns = {
            "Nome": r"Nome:\s*(.+)",
            "Nickname": r"Nickname:\s*(.+)",
            "Anno di nascita": r"Anno di nascita:\s*(.+)",
            "Professione": r"Professione:\s*(.+)",
            "Provenienza": r"Provenienza:\s*(.+)",
            "Cartaceo": r"Anno di inizio magic cartaceo:\s*(.+)",
            "Arena": r"Anno di inizio MTGA:\s*(.+)",
            "Formati": r"Formati preferiti:\s*(.+)",
            "Colori": r"Colore preferito:\s*(.+)",
            "Gilde": r"Gilde:\s*(.+)",
        }
        
        errori = []
        dati_estratti = {}
        member = interaction.user

        for campo, pattern in patterns.items():
            match = re.search(pattern, testo_totale, re.IGNORECASE | re.MULTILINE)
            
            if match and match.group(1).strip():
                contenuto = match.group(1).strip()
                dati_estratti[campo] = contenuto
                
                # Validazioni specifiche
                if campo == "Anno di nascita":
                    if not contenuto.isdigit() or not (1900 < int(contenuto) < datetime.now().year):
                        errori.append(f"Anno di nascita (es. 1995)")
                        print(f"{C_RED}[ERRORE VALORE]{C_END} {member.name} -> Anno nascita non valido: '{contenuto}'")

                if campo == "Cartaceo":
                    if contenuto.lower() not in ["mai", "nessuno", "no"] and not contenuto.isdigit():
                        errori.append("Anno inizio Cartaceo (anno o 'Mai')")
                        print(f"{C_RED}[ERRORE VALORE]{C_END} {member.name} -> Dato cartaceo errato: '{contenuto}'")

                if campo == "Arena":
                    if contenuto.lower() not in ["mai", "nessuno", "no"] and not contenuto.isdigit():
                        errori.append("Anno inizio Arena (anno o 'Mai')")
                        print(f"{C_RED}[ERRORE VALORE]{C_END} {member.name} -> Dato Arena errato: '{contenuto}'")
            else:
                errori.append(campo)
                print(f"{C_RED}[ERRORE CAMPO]{C_END} {member.name} -> Manca o etichetta rimossa: {campo}")

        # --- LOG RIEPILOGATIVO ---
        if errori:
            print("\n" + "!"*50)
            print(f"{C_YELLOW}{C_BOLD}⚠️  VERIFICA FALLITA{C_END}")
            print(f"UTENTE: {member.name} | ID: {member.id}")
            print(f"ERRORI: {', '.join(errori)}")
            print("!"*50 + "\n")
            
            return await interaction.followup.send(
                f"❌ **Dati non validi o mancanti:**\n- " + "\n- ".join(errori) + 
                "\n\nPer favore, scrivi la tua risposta subito dopo i due punti `:` senza cancellare le etichette.", 
                ephemeral=True
            )
        
        # Se la verifica ha successo (prima di inviare l'embed)
        print("\n" + "="*50)
        print(f"{C_GREEN}{C_BOLD}✅ VERIFICA APPROVATA{C_END}")
        print(f"UTENTE: {member.name} | ID: {member.id}")
        print("="*50 + "\n")

        # 3. Se arriviamo qui, i dati sono validi. Procediamo con il server.
        try: 
            guild = interaction.guild

            initial_role = discord.utils.get(guild.roles, name=INITIAL_ROLE)
            final_role = discord.utils.get(guild.roles, name=FINAL_ROLE)
            presentation_channel = discord.utils.get(guild.text_channels, name=PRESENTATION_CHANNEL)

            # Embed Riassuntivo
            embed = discord.Embed(
                title=f"🛡️ Nuova Presentazione: {member.display_name}", 
                description=f"**Account originale:** `{member.name}`",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.set_thumbnail(url=member.display_avatar.url)

            # Usiamo i dati estratti singolarmente per un look più professionale
            info_dati_personali = (
                f"**Nome:** {dati_estratti['Nome']}\n"
                f"**Nick Arena:** {dati_estratti['Nickname']}\n"
                f"**Anno di nascita:** {dati_estratti['Anno di nascita']}\n"
                f"**Lavoro:** {dati_estratti['Professione']}\n"
                f"**Provenienza:** {dati_estratti['Provenienza']}"
            )
            info_dati_magic = (
                f"**Cartaceo:** {dati_estratti['Cartaceo']}\n"
                f"**Arena:** {dati_estratti['Arena']}\n"
            )
            info_dati_preferenze = (
                f"**Formati:** {dati_estratti['Formati']}\n"
                f"**Colori:** {dati_estratti['Colori']}\n"
                f"**Gilde:** {dati_estratti['Gilde']}\n"
            )
            embed.add_field(name="👤 Dati Personali", value=info_dati_personali, inline=False)
            embed.add_field(name="📅 Inizio Magic", value=info_dati_magic, inline=False)
            embed.add_field(name="🃏 Preferenze", value=info_dati_preferenze, inline=False)

            if self.risultati.value.strip():
                embed.add_field(name="🏆 Risultati", value=self.risultati.value, inline=False)
            if self.passioni.value.strip():
                embed.add_field(name="🌟 Altre Passioni", value=self.passioni.value, inline=False)

            await presentation_channel.send(embed=embed)

            # Gestione Ruoli
            try:
                if initial_role in member.roles:
                    await member.remove_roles(initial_role)
                if final_role:
                    await member.add_roles(final_role)

                await interaction.followup.send("✅ Grazie! La tua presentazione è stata pubblicata e ora hai accesso a tutto il server.", ephemeral=True)
                print(f"{C_GREEN}[LOG] Verifica completata con successo per {member.name}{C_END}")
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Presentazione inviata, ma non ho i permessi per cambiare i tuoi ruoli. Contatta un admin.", ephemeral=True)
        except Exception as e:
            print(f"[ERRORE CRITICO] {e}")
            await interaction.followup.send("⚠️ Errore di connessione con Discord. Riprova tra un minuto.", ephemeral=True)

# --- SLASH COMMAND ---
@bot.tree.command(name="presentati", description="Apri il modulo di presentazione")
async def presentati(interaction: discord.Interaction):
    # Controllo se l'utente ha già il ruolo membro
    if any(role.name == FINAL_ROLE for role in interaction.user.roles):
        return await interaction.response.send_message("Sei già un membro verificato!", ephemeral=True)
    
    await interaction.response.send_modal(PresentationModal())

# --- EVENTI ---

@bot.event
async def on_message(message):
    # Evita che il bot cancelli i propri messaggi (l'Embed)
    if message.author == bot.user:
        return

    # Cancella ogni messaggio nel canale presentazioni che non sia il comando del bot
    if message.channel.name == PRESENTATION_CHANNEL:
        try:
            await message.delete()
            print(f"[LOG] messaggio cancellato:\n{message.author}: {message.content}")
            # Avviso temporaneo all'utente
            await message.channel.send(
                f"⚠️ {message.author.mention}, in questo canale puoi solo usare `/presentati`. I messaggi normali vengono eliminati.",
                delete_after= 15
            )
        except:
            print(f"[LOG] Impossibile eliminare il messaggio")
            pass # Silenzioso se mancano permessi

    await bot.process_commands(message)
    
    
@bot.event
async def on_member_join(member):
    print(f"{C_CYAN}[NUOVO UTENTE]{C_END} {C_BOLD}{member.name}{C_END} (ID: {member.id}) si è unito.")
    
    role = discord.utils.get(member.guild.roles, name=INITIAL_ROLE)
    try:
        if role:
            await member.add_roles(role)
            print(f"   └─ {C_GREEN}Ruolo {INITIAL_ROLE} assegnato.{C_END}")
    except discord.errors.HTTPException as e:
        if e.status == 429:
            print(f"{C_RED}⚠️ ERRORE 429: Discord ci sta limitando. Riprovo più tardi.")
        else:
            print(f"{C_RED}⚠️ Errore durante l'assegnazione ruolo: {e}")
    
    channel = discord.utils.get(member.guild.text_channels, name=PRESENTATION_CHANNEL)
    if channel:
        await channel.send(
            f'''👋 Benvenuto {member.mention}! Attualmente hai una visione limitata dei canali del serve. \nUsa `/presentati` per sbloccare tutte le funzionalità del server. \nAll'interno troverai canali specifici per ogni formato di Magic Arena, canali generali e qualche nuovo amico.
            ''',
            delete_after=300.0
        )

@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID) # Sincronizzazione forzata per la Guild specifica (più veloce dei comandi globali)
    bot.tree.copy_global_to(guild=guild)
    synced = await bot.tree.sync(guild=guild)
    print(f"\n{C_CYAN}{'='*40}{C_END}")
    print(f"{C_GREEN}{C_BOLD}🚀 BOT ONLINE: {bot.user}{C_END}")
    print(f"{C_GREEN}✅ Comandi sincronizzati: {len(synced)}{C_END}")
    print(f"{C_CYAN}{'='*40}{C_END}\n")

bot.run(TOKEN)