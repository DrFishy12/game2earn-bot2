import discord
from discord.ext import commands
import asyncio
import io
import random
import time
from datetime import datetime, timedelta

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  
intents.guilds = True
intents.moderation = True

bot = commands.Bot(command_prefix="!", intents=intents)

# משתנים לשמירת נתוני המערכת
LOG_CHANNEL_ID = None
STAFF_ROLE_ID = None
WELCOME_CHANNEL_ID = None
GENERAL_LOG_CHANNEL_ID = None
SUGGESTION_CHANNEL_ID = 1507499908163178686
BOOST_CHANNEL_ID = 1436500583833141349

# איידיאים של חדר המערכת וחדרי אישור טפסים
FORMS_REVIEW_CHANNEL_ID = 1438985080763711659
FORMS_APPROVED_CHANNEL_ID = 1508196191693967401
FORMS_REJECTED_CHANNEL_ID = 1508196230088360016
TICKET_CHANNEL_ID = 1439044665100996648  # חדר פתיחת הטיקט
OPEN_TICKET_CATEGORY_ID = 1439045893419696271
CLOSED_TICKET_CATEGORY_ID = 1439045981399154829
FORM_USE_PRIVATE_CHANNELS = True  # False מחזיר את המערכת לשליחת הטפסים ב-DM
FORM_CATEGORY_ID = 1553512470419865630
APPROVED_FORM_TICKET_CATEGORY_ID = 1553514234325770280
APPROVED_FORM_TICKET_ROLE_IDS = [
    1436484436618252371,
    1436484624963604682,
    1436490886149181570,
]

# מילון מעקב Cooldown למשתמשים (user_id: datetime_when_can_apply_again)
forms_cooldowns = {}

# מילון לשמירת מי שפתח כל טיקט (channel_id: member_object)
ticket_owners = {}
approved_form_tickets = {}

# מילון ניהול הרשאות דינמי: {role_id: [list_of_command_names]}
role_custom_permissions = {}

# --- מערכת רמות (Levels System) ---
# מבנה הנתונים: user_xp_data[user_id] = {"xp": int, "level": int}
user_xp_data = {}
message_cooldowns = {}  # למניעת ספאם XP: {user_id: datetime}

# רשימת הקטגוריות הדינמית של הטיקטים
ticket_categories = [
    {"label": "תלונה", "description": "דיווח על שחקן / איש צוות", "emoji": "⚠️", "value": "complaint"},
    {"label": "תרמה", "description": "שאלות או עזרה לגבי תרומה", "emoji": "💵", "value": "donation"},
    {"label": "פדים", "description": "בקשות או שאלות בנוגע לפדים", "emoji": "📦", "value": "pads"},
    {"label": "מועמדות", "description": "הגשת מועמדות לעבודה / לצוות", "emoji": "🌐", "value": "staff"},
    {"label": "Test", "description": "בדיקת מערכת טיקטים", "emoji": "❓", "value": "test"}
]

# הגדרת שאלות לכל סוג טופס
FORM_QUESTIONS = {
    "discord_staff": [
        "מהו שמך האמיתי וגילך?",
        "מהי רמת הפעילות שלך בשרת ביום (שעות)?",
        "למה אתה חושב שאתה מתאים לתפקיד צוות דיסקורד?",
        "האם יש לך ניסיון קודם בניהול שרתי דיסקורד? אם כן, פרט."
    ],
    "tournament_staff": [
        "מהו שמך האמיתי וגילך?",
        "האם יש לך ניסיון בניהול ופיקוח על טורנירים וגיימינג?",
        "איך תתמודד עם שחקן שלא שומר על הכללים בטורניר?",
        "מהי הזמינות שלך בסופי שבוע?"
    ]
}

# --- מערכת הגרלות: פונקציית פענוח זמן (לדוגמה: 10m, 1h, 2d) ---
def parse_time(time_str: str) -> int:
    time_str = time_str.lower()
    total_seconds = 0
    number = ""
    for char in time_str:
        if char.isdigit():
            number += char
        else:
            if not number:
                continue
            val = int(number)
            if char == 's':
                total_seconds += val
            elif char == 'm':
                total_seconds += val * 60
            elif char == 'h':
                total_seconds += val * 3600
            elif char == 'd':
                total_seconds += val * 86400
            number = ""
    return total_seconds


# --- מחלקת כפתורי ההגרלה ---
class GiveawayView(discord.ui.View):
    def __init__(self, required_role: discord.Role = None, bonus_role: discord.Role = None, guild: discord.Guild = None, prize: str = ""):
        super().__init__(timeout=None)
        self.participants = set()
        self.raw_participants = set()
        self.required_role = required_role
        self.bonus_role = bonus_role
        self.guild = guild
        self.prize = prize

    @discord.ui.button(label="Enter Giveaway", style=discord.ButtonStyle.green, emoji="🎁", custom_id="giveaway_enter_btn")
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if self.required_role and self.required_role not in user.roles:
            await interaction.response.send_message(f"❌ עליך להיות בעל הרול {self.required_role.mention} כדי להשתתף בהגרלה זו!", ephemeral=True)
            return

        user_id = user.id
        if user_id in self.raw_participants:
            self.raw_participants.remove(user_id)
            self.participants = {uid for uid in self.participants if uid != user_id}
            msg = "❌ יצאת מההגרלה בהצלחה."
            await send_general_log(interaction.guild, "🎁 משתמש יצא מהגרלה", f"המשתמש {user.mention} יצא מההגרלה על הפרס **{self.prize}**.", discord.Color.orange())
        else:
            self.raw_participants.add(user_id)
            self.participants.add(user_id)
            bonus_text = ""
            if self.bonus_role and self.bonus_role in user.roles:
                self.participants.add(user_id)
                bonus_text = " (כולל כרטיס בונוס 🌟)"
                msg = "🎉 נכנסת בהגרלה בהצלחה! קיבלת כרטיס בונוס עקב רול מיוחד! 🌟"
            else:
                msg = "🎉 נכנסת בהגרלה בהצלחה!"
            
            await send_general_log(interaction.guild, "🎁 משתמש נכנס להגרלה", f"המשתמש {user.mention} נכנס להגרלה על הפרס **{self.prize}**{bonus_text}.", discord.Color.green())

        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Participants", style=discord.ButtonStyle.secondary, emoji="👥", custom_id="giveaway_participants_btn")
    async def participants_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        count = len(self.raw_participants)
        await interaction.response.send_message(f"👥 סך כל המשתתפים הייחודיים בהגרלה כרגע: **{count}**", ephemeral=True)


# --- מחלקת כפתורי הטורנירים ---
class TournamentView(discord.ui.View):
    def __init__(self, max_slots: int, tournament_name: str, payment_link: str = None):
        super().__init__(timeout=None)
        self.participants = set()
        self.max_slots = max_slots
        self.tournament_name = tournament_name

        if payment_link:
            self.add_item(discord.ui.Button(label="Payment Link", style=discord.ButtonStyle.green, emoji="💳", url=payment_link))

    @discord.ui.button(label="Register", style=discord.ButtonStyle.blurple, emoji="✍️", custom_id="tournament_register_btn")
    async def register_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        user_id = user.id

        if user_id in self.participants:
            self.participants.remove(user_id)
            await interaction.response.send_message("❌ ביטלת את הרשמתך לטורניר בהצלחה.", ephemeral=True)
            await send_general_log(interaction.guild, "🏆 שחקן ביטל הרשמה לטורניר", f"השחקן {user.mention} ביטל את הרשמתך לטורניר **{self.tournament_name}**.", discord.Color.orange())
        else:
            if len(self.participants) >= self.max_slots:
                await interaction.response.send_message("❌ מצטערים, הטורניר מלא לגמרי (Reached Max Slots)!", ephemeral=True)
                return
            
            self.participants.add(user_id)
            await interaction.response.send_message("✅ נרשמת בהצלחה לטורניר! בהצלחה! 🎮", ephemeral=True)
            await send_general_log(interaction.guild, "🏆 שחקן נרשם לטורניר", f"השחקן {user.mention} נרשם לטורניר **{self.tournament_name}** ({len(self.participants)}/{self.max_slots}).", discord.Color.green())

    @discord.ui.button(label="Participants", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="tournament_participants_btn")
    async def participants_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.participants:
            await interaction.response.send_message("📋 עדיין אין שחקנים רשומים לטורניר זה.", ephemeral=True)
            return
        
        mentions = ", ".join([f"<@{uid}>" for uid in self.participants])
        await interaction.response.send_message(f"📋 **שחקנים רשומים ({len(self.participants)}/{self.max_slots}):**\n{mentions}", ephemeral=True)


@bot.event
async def on_ready():
    bot.add_view(TicketPanelView())
    bot.add_view(TicketControlView())
    bot.add_view(ApprovedFormTicketView())
    bot.add_view(FormPanelView())
    bot.add_view(SuggestionVoteView())
    bot.add_view(GiveawayView())

    print(f'הבוט מחובר בהצלחה כ-{bot.user}!')
    activity = discord.Game(name="game2earn.life | /help")
    await bot.change_presence(activity=activity)
    
    try:
        synced = await bot.tree.sync()
        print(f"סונכרנו {len(synced)} פקודות Slash בהצלחה.")
    except Exception as e:
        print(e)

# --- אירוע הודעה ומערכת רמות אוטומטית ---
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    user_id = message.author.id
    now = datetime.now()

    # בדיקת Cooldown למניעת ספאם XP (פעם ב-60 שניות למשתמש)
    if user_id in message_cooldowns:
        if now < message_cooldowns[user_id]:
            await bot.process_commands(message)
            return

    message_cooldowns[user_id] = now + timedelta(seconds=60)

    # הוספת XP רנדומלי בין 15 ל-25 הודעה
    earned_xp = random.randint(15, 25)

    if user_id not in user_xp_data:
        user_xp_data[user_id] = {"xp": 0, "level": 1}

    user_xp_data[user_id]["xp"] += earned_xp
    current_xp = user_xp_data[user_id]["xp"]
    current_level = user_xp_data[user_id]["level"]

    # חישוב XP נדרש לרמה הבאה: level^2 * 100 + 500
    needed_xp = (current_level ** 2) * 100 + 500

    if current_xp >= needed_xp:
        user_xp_data[user_id]["level"] += 1
        new_level = user_xp_data[user_id]["level"]
        
        # שליחת הודעת עליית רמה לחדר שבו נשלחה ההודעה
        try:
            await message.channel.send(f"🎉 כל הכבוד {message.author.mention}! עלית לרמה **{new_level}**! 🚀")
        except:
            pass

    await bot.process_commands(message)

# --- אירוע כניסת משתמש חדש (Welcome System) ---
@bot.event
async def on_member_join(member: discord.Member):
    global WELCOME_CHANNEL_ID
    if WELCOME_CHANNEL_ID:
        channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
        if channel:
            embed = discord.Embed(
                title="New G2E Player Is In ThE House !",
                description=f"Welcome ! {member.mention} To Game2Earn !",
                color=discord.Color.from_rgb(186, 85, 211)
            )
            if member.avatar:
                embed.set_thumbnail(url=member.avatar.url)
            elif member.default_avatar:
                embed.set_thumbnail(url=member.default_avatar.url)

            await channel.send(embed=embed)
            
    await send_general_log(member.guild, "📥 משתמש הצטרף לשרת", f"המשתמש {member.mention} (`{member.name}`) הצטרף לשרת.", discord.Color.green())

@bot.event
async def on_member_remove(member: discord.Member):
    await send_general_log(member.guild, "📤 משתמש עזב את השרת", f"המשתמש {member.mention} (`{member.name}`) עזב את השרת.", discord.Color.red())

# פקודות מערכת רמות: /rank ופסגת המשתמשים /leaderboard
@bot.tree.command(name="rank", description="בדוק את הרמה וה-XP הנוכחי שלך או של משתמש אחר")
@discord.app_commands.describe(member="בחר משתמש לבדיקה (אופציונלי)")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    user_id = target.id

    data = user_xp_data.get(user_id, {"xp": 0, "level": 1})
    current_xp = data["xp"]
    current_level = data["level"]
    needed_xp = (current_level ** 2) * 100 + 500

    embed = discord.Embed(
        title=f"📊 דירוג רמות - {target.display_name}",
        color=discord.Color.blue()
    )
    if target.avatar:
        embed.set_thumbnail(url=target.avatar.url)
    
    embed.add_field(name="🏆 רמה (Level)", value=str(current_level), inline=True)
    embed.add_field(name="✨ נקודות (XP)", value=f"{current_xp} / {needed_xp}", inline=True)
    
    # חישוב מיקום בלוח המובילים
    sorted_users = sorted(user_xp_data.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
    rank_position = "לא מדורג"
    for idx, (uid, _) in enumerate(sorted_users, 1):
        if uid == target.id:
            rank_position = f"#{idx}"
            break
            
    embed.add_field(name="🏅 מיקום בשרת", value=rank_position, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="leaderboard", description="הצג את 10 המובילים בדירוג הרמות בשרת (Top 10)")
async def leaderboard(interaction: discord.Interaction):
    if not user_xp_data:
        await interaction.response.send_message("📋 לוח המובילים ריק כרגע, התחילו לשוחח בשרת כדי לצבור רמות!", ephemeral=True)
        return

    # מיון המשתמשים לפי רמה ו-XP בסדר יורד
    sorted_users = sorted(user_xp_data.items(), key=lambda x: (x[1]["level"], x[1]["xp"]), reverse=True)
    top_10 = sorted_users[:10]

    embed = discord.Embed(
        title="🏆 לוח המובילים בשרת - Top 10 Leaderboard",
        description="השחקנים הפעילים ביותר בשרת לפי מערכת הרמות:",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    description_text = ""
    for index, (uid, data) in enumerate(top_10):
        member = interaction.guild.get_member(uid)
        name = member.mention if member else f"משתמש עזב (`{uid}`)"
        medal = medals[index] if index < len(medals) else f"#{index+1}"
        description_text += f"{medal} {name} — **רמה {data['level']}** (`{data['xp']} XP`)\n"

    embed.description = description_text
    embed.set_footer(text=f"מוצג לבקשת {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

    await interaction.response.send_message(embed=embed)

# --- פקודת /site לאתר הקהילה ---
@bot.tree.command(name="site", description="קבל את הקישור לאתר הרשמי של קהילת Game2Earn")
async def site(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌐 האתר הרשמי של קהילת Game2Earn",
        description=(
            "כל מה שקורה בקהילה מחכה לכם במקום אחד!\n\n"
            "היכנסו עכשיו לאתר, הכירו את השירותים שלנו, התעדכנו בחדשות "
            "ואל תפספסו את הטורנירים והאירועים הקרובים."
        ),
        color=discord.Color.from_rgb(0, 170, 255),
        url="https://game2earn.life/"
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    embed.add_field(
        name="🎮 מה מחכה לכם באתר?",
        value="חדשות הקהילה • טורנירים • פרסים • עדכונים מיוחדים",
        inline=False
    )
    embed.add_field(
        name="🚀 מוכנים להצטרף?",
        value="לחצו על הכפתור למטה ובקרו באתר הרשמי של Game2Earn.",
        inline=False
    )
    embed.set_footer(
        text=f"Game2Earn • הוזמן על ידי {interaction.user.display_name}",
        icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url
    )
    embed.timestamp = discord.utils.utcnow()
    
    # הוספת כפתור לחיץ שמוביל לאתר
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="כניסה לאתר הרשמי", style=discord.ButtonStyle.link, emoji="🚀", url="https://game2earn.life/"))

    await interaction.response.send_message(embed=embed, view=view)

# --- פקודת /help לעזרה ופתיחת טיקט ---
@bot.tree.command(name="help", description="קבלת עזרה והפניה מהירה לפתיחת טיקט בשרת")
async def help_command(interaction: discord.Interaction):
    global TICKET_CHANNEL_ID
    embed = discord.Embed(
        title="🤖 Game2Earn Bot Help & Support",
        description="צריכים עזרה, יש לכם שאלה או שאפתם לפנות לצוות? לחצו על הכפתור למטה כדי לעבור ישירות לחדר פתיחת הטיקטים בשרת!",
        color=discord.Color.from_rgb(52, 152, 219)
    )
    embed.set_footer(text=f"Game2Earn • מוצג לבקשת {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    
    view = discord.ui.View()
    ticket_channel_obj = interaction.guild.get_channel(TICKET_CHANNEL_ID)
    url_link = f"https://discord.com/channels/{interaction.guild.id}/{TICKET_CHANNEL_ID}" if ticket_channel_obj else "https://discord.com"
    
    view.add_item(discord.ui.Button(label="מעבר לחדר הטיקטים", style=discord.ButtonStyle.link, emoji="🎫", url=url_link))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
# פונקציית עזר לשליחת לוגים
async def send_log(guild, title, description, color, file=None):
    global LOG_CHANNEL_ID
    if LOG_CHANNEL_ID:
        log_channel = guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title=title, description=description, color=color)
            if file:
                await log_channel.send(embed=embed, file=file)
            else:
                await log_channel.send(embed=embed)

async def send_general_log(guild, title, description, color):
    global GENERAL_LOG_CHANNEL_ID
    if GENERAL_LOG_CHANNEL_ID:
        channel = guild.get_channel(GENERAL_LOG_CHANNEL_ID)
        if channel:
            embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
            await channel.send(embed=embed)

# --- מאזיני לוגים כלליים מקיפים לכל שינוי בשרת ---
@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot:
        return
    desc = f"**הודעה נמחקה ב-{message.channel.mention}**\n**מאת:** {message.author.mention}\n**תוכן:**\n{message.content or '*ללא תוכן / קובץ מצורף*'}"
    await send_general_log(message.guild, "🗑️ הודעה נמחקה", desc, discord.Color.red())

@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or before.content == after.content:
        return
    desc = f"**עריכת הודעה ב-{before.channel.mention}**\n**מאת:** {before.author.mention}\n\n**לפני:**\n{before.content}\n\n**אחרי:**\n{after.content}"
    await send_general_log(before.guild, "✏️ הודעה נערכה", desc, discord.Color.orange())

@bot.event
async def on_guild_channel_create(channel):
    await send_general_log(channel.guild, "📁 ערוץ/קטגוריה נוצרו", f"הערוץ **{channel.name}** (`{channel.type}`) נוצר בהצלחה.", discord.Color.green())

@bot.event
async def on_guild_channel_delete(channel):
    await send_general_log(channel.guild, "🗑️ ערוץ/קטגוריה נמחקו", f"הערוץ **{channel.name}** נמחק.", discord.Color.red())

@bot.event
async def on_guild_channel_update(before, after):
    if before.name != after.name:
        await send_general_log(before.guild, "✏️ שם ערוץ שונה", f"הערוץ `{before.name}` שינה את שמו ל- **{after.name}**.", discord.Color.orange())

@bot.event
async def on_guild_role_create(role):
    await send_general_log(role.guild, "🛡️ רול חדש נוצר", f"הרול **{role.name}** נוצר בהצלחה.", discord.Color.green())

@bot.event
async def on_guild_role_delete(role):
    await send_general_log(role.guild, "🛡️ רול נמחק", f"הרול **{role.name}** נמחק מהשרת.", discord.Color.red())

@bot.event
async def on_guild_role_update(before, after):
    if before.name != after.name:
        await send_general_log(before.guild, "🛡️ רול עודכן", f"הרול `{before.name}` שינה את שמו ל- **{after.name}**.", discord.Color.orange())

@bot.event
async def on_member_update(before, after):
    if before.premium_since is None and after.premium_since is not None:
        boost_channel = after.guild.get_channel(BOOST_CHANNEL_ID)
        if boost_channel:
            embed = discord.Embed(
                title="🚀 תודה על ה־Boost!",
                description=(
                    f"{after.mention} תודה ענקית על התמיכה בקהילת **{after.guild.name}**!\n\n"
                    "ה־Boost שלך עוזר לנו להמשיך לגדול, להשתפר ולבנות קהילה חזקה יותר. 💙"
                ),
                color=discord.Color.from_rgb(255, 115, 190),
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="💎 Booster חדש", value=after.mention, inline=True)
            embed.add_field(name="🌟 סטטוס", value="תמכת בקהילה שלנו!", inline=True)
            embed.set_thumbnail(url=after.avatar.url if after.avatar else after.default_avatar.url)
            embed.set_footer(text=f"{after.guild.name} • תודה על התמיכה שלך")
            await boost_channel.send(embed=embed)

    if before.nick != after.nick:
        await send_general_log(before.guild, "🏷️ כינוי משתמש שונה", f"המשתמש {after.mention} שינה כינוי מ- `{before.nick or before.name}` ל- `{after.nick or after.name}`.", discord.Color.blue())
    if before.roles != after.roles:
        added = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        text = ""
        if added: text += f"**נוספו רולים:** {', '.join(added)}\n"
        if removed: text += f"**הוסרו רולים:** {', '.join(removed)}"
        if text:
            await send_general_log(before.guild, "🎭 רולים של משתמש עודכנו", f"המשתמש {after.mention}:\n{text}", discord.Color.purple())

def check_user_command_permission(member: discord.Member, command_name: str):
    if member.guild_permissions.administrator:
        return True
    for role in member.roles:
        allowed_cmds = role_custom_permissions.get(role.id, [])
        if command_name in allowed_cmds:
            return True
    return False

def has_staff_permissions(member: discord.Member):
    if member.guild_permissions.administrator:
        return True
    if STAFF_ROLE_ID:
        staff_role = member.guild.get_role(STAFF_ROLE_ID)
        if staff_role and staff_role in member.roles:
            return True
    return False


# --- טופס יצירת ה-Embed עבור /say embed ---
class PerfectEmbedModal(discord.ui.Modal, title="יצירת הודעת Embed מקצועית"):
    embed_author = discord.ui.TextInput(
        label="כותרת עליונה קטנה (Author)", 
        placeholder="לדוגמה: Community Guidelines", 
        required=False
    )
    embed_title = discord.ui.TextInput(
        label="כותרת ראשית (Title)", 
        placeholder="הכנס כותרת ראשית...", 
        required=True
    )
    embed_description = discord.ui.TextInput(
        label="טקסט (Description)", 
        placeholder="תוכן הודעת ה-Embed...", 
        style=discord.TextStyle.paragraph, 
        required=True
    )
    embed_color = discord.ui.TextInput(
        label="צבע (blue, red, green, gold, purple)", 
        placeholder="blue", 
        required=False,
        max_length=10
    )
    embed_image = discord.ui.TextInput(
        label="תמונה / באנר (Image URL)", 
        placeholder="https://... (קישור ישיר לתמונה)", 
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        color = discord.Color.blue()
        c_text = self.embed_color.value.strip().lower()
        if c_text == "red":
            color = discord.Color.red()
        elif c_text == "green":
            color = discord.Color.green()
        elif c_text == "gold" or c_text == "yellow":
            color = discord.Color.gold()
        elif c_text == "purple":
            color = discord.Color.purple()

        embed_msg = discord.Embed(
            title=self.embed_title.value,
            description=self.embed_description.value,
            color=color
        )
        if self.embed_author.value.strip():
            embed_msg.set_author(name=self.embed_author.value.strip())
        if self.embed_image.value.strip():
            embed_msg.set_image(url=self.embed_image.value.strip())

        embed_msg.set_footer(text=f"נוצר לבקשת {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

        await interaction.channel.send(embed=embed_msg)
        await interaction.response.send_message("הודעת ה-Embed נוצרה ונשלחה בהצלחה! 🚀", ephemeral=True)

@bot.tree.command(name="say", description="שליחת הודעות שונות בשם הבוט (לצוות בלבד)")
async def say(interaction: discord.Interaction, type: str, message: str = None):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "say")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    if type == "text":
        if not message:
            await interaction.response.send_message("חובה לכתוב טקסט עבור הודעה רגילה!", ephemeral=True)
            return
        await interaction.channel.send(message)
        await interaction.response.send_message("ההודעה נשלחה בהצלחה! ✅", ephemeral=True)
    elif type == "embed":
        modal = PerfectEmbedModal()
        await interaction.response.send_modal(modal)


# --- פקודת מחיקת הודעות /delete ---
@bot.tree.command(name="delete", description="מחיקת כמות הודעות מוגדרת מהחדר (לצוות בלבד)")
@discord.app_commands.describe(amount="כמות ההודעות שתרצה למחוק")
async def delete_messages(interaction: discord.Interaction, amount: int):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "delete")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    if amount <= 0:
        await interaction.response.send_message("❌ נא להזין מספר הגדול מ-0.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    
    await interaction.followup.send(f"🗑️ נמחקו בהצלחה **{len(deleted)}** הודעות מהחדר.", ephemeral=True)


# --- מערכת טורנירים מותאמת אישית (Tournaments System) ---

@bot.tree.command(name="start-tournament", description="יצירת טורניר חדש עם עיצוב אישי וכפתור תשלום אופציונלי (לצוות בלבד)")
@discord.app_commands.describe(
    title="כותרת הטורניר הראשית (לדוגמה: 🏆 New Tournament: טורניר ואלורנט)",
    description="תיאור מלא של הטורניר עם כל הפרטים והאימוג'ים",
    game="שם המשחק (לדוגמה: VALORANT)",
    prize="סכום או תיאור הפרס (לדוגמה: 400.00 ILS)",
    entry_fee="דמי כניסה (לדוגמה: Free או 50 ILS)",
    slots="מספר שחקנים/מקומות מקסימלי",
    channel="ערוץ פרסום הטורניר",
    days_from_now="עוד כמה ימים הטורניר מתחיל (ברירת מחדל 4)",
    payment_link="קישור ישיר לתשלום (אופציונלי - יוסיף כפתור תשלום אוטומטי אם יוזן)"
)
async def start_tournament(
    interaction: discord.Interaction,
    title: str,
    description: str,
    game: str,
    prize: str,
    entry_fee: str,
    slots: int,
    channel: discord.TextChannel,
    days_from_now: int = 4,
    payment_link: str = None
):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "start-tournament")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    start_date = datetime.utcnow() + timedelta(days=days_from_now)
    unix_timestamp = int(start_date.timestamp())

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.gold()
    )
    embed.add_field(name="🎮 Game", value=game, inline=True)
    embed.add_field(name="💰 Entry Fee", value=entry_fee, inline=True)
    embed.add_field(name="🎁 Guaranteed Prize", value=prize, inline=True)
    embed.add_field(name="📅 Starts", value=f"<t:{unix_timestamp}:F> ( <t:{unix_timestamp}:R> )", inline=False)
    embed.add_field(name="👥 Slots", value=str(slots), inline=False)
    
    embed.set_footer(text=f"Spark Bots - discord.gg/SparkBots • {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')}")

    view = TournamentView(max_slots=slots, tournament_name=title, payment_link=payment_link)
    await channel.send(embed=embed, view=view)
    
    await interaction.response.send_message(f"✅ הטורניר נוצר ופורסם בהצלחה ב-{channel.mention}!", ephemeral=True)

    await send_general_log(
        interaction.guild,
        "🏆 טורניר חדש נוצר",
        f"הטורניר **{title}** נוצר על ידי {interaction.user.mention} בערוץ {channel.mention}.",
        discord.Color.gold()
    )


# --- מערכת הגרלות (Giveaways System) ---

@bot.tree.command(name="start-giveaway", description="התחלת הגרלה חדשה בשרת (לצוות בלבד)")
@discord.app_commands.describe(
    prize="פרס ההגרלה",
    winners="מספר הזוכים",
    time="משך ההגרלה (לדוגמה: 10m, 1h, 1d)",
    channel="ערוץ ההגרלה",
    bonus_entry_role="רול המעניק בונוס כרטיסים (אופציונלי)",
    description="תיאור נוסף להגרלה (אופציונלי)",
    required_role="רול חובה להשתתפות (אופציונלי)",
    color="צבע ההגרלה (blue, green, red, gold, purple)",
    title="כותרת ההגרלה (אופציונלי)"
)
async def start_giveaway(
    interaction: discord.Interaction,
    prize: str,
    winners: int,
    time: str,
    channel: discord.TextChannel,
    bonus_entry_role: discord.Role = None,
    description: str = None,
    required_role: discord.Role = None,
    color: str = "blue",
    title: str = "🎉 Giveaway Started 🎉"
):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "start-giveaway")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    seconds = parse_time(time)
    if seconds <= 0:
        await interaction.response.send_message("❌ זמן לא תקין! השתמש בפורמט כמו 30s, 10m, 1h, 2d.", ephemeral=True)
        return

    end_time = datetime.utcnow() + timedelta(seconds=seconds)
    unix_timestamp = int(end_time.timestamp())

    embed_color = discord.Color.blue()
    c = color.strip().lower()
    if c == "green": embed_color = discord.Color.green()
    elif c == "red": embed_color = discord.Color.red()
    elif c == "gold" or c == "yellow": embed_color = discord.Color.gold()
    elif c.startswith("p"): embed_color = discord.Color.purple()

    embed = discord.Embed(
        title=title,
        description=description if description else "",
        color=embed_color
    )
    embed.add_field(name="Prize", value=prize, inline=False)
    embed.add_field(name="Ends", value=f"<t:{unix_timestamp}:R> ( <t:{unix_timestamp}:F> )", inline=False)
    embed.add_field(name="Hosted By", value=interaction.user.mention, inline=False)
    embed.add_field(name="Winners", value=str(winners), inline=False)
    
    if required_role:
        embed.add_field(name="Required Role", value=required_role.mention, inline=False)
    if bonus_entry_role:
        embed.add_field(name="Bonus Role", value=bonus_entry_role.mention, inline=False)

    embed.set_footer(text=f"Spark Bots - discord.gg/SparkBots • {datetime.utcnow().strftime('%B %d, %Y at %I:%M %p')}")

    view = GiveawayView(required_role=required_role, bonus_role=bonus_entry_role, guild=interaction.guild, prize=prize)
    giveaway_msg = await channel.send(embed=embed, view=view)
    
    await interaction.response.send_message(f"✅ ההגרלה התחילה בהצלחה ב-{channel.mention}!", ephemeral=True)

    await send_general_log(
        interaction.guild,
        "🎉 הגרלה חדשה נפתחה",
        f"הגרלה חדשה על הפרס **{prize}** נוצרה על ידי {interaction.user.mention} בערוץ {channel.mention}.",
        discord.Color.gold()
    )

    await asyncio.sleep(seconds)

    try:
        fetched_msg = await channel.fetch_message(giveaway_msg.id)
    except:
        return

    if not view.participants:
        ended_embed = fetched_msg.embeds[0]
        ended_embed.color = discord.Color.red()
        ended_embed.title = "🎉 Giveaway Ended 🎉"
        ended_embed.add_field(name="Winners", value="אף אחד לא השתתף בהגרלה!", inline=False)
        for child in view.children:
            child.disabled = True
        await fetched_msg.edit(embed=ended_embed, view=view)
        await channel.send("❌ ההגרלה הסתיימה, אך אף אחד לא השתתף בה!")
        
        await send_general_log(
            interaction.guild,
            "🛑 הגרלה הסתיימה ללא משתתפים",
            f"ההגרלה על הפרס **{prize}** הסתיימה ולא היו משתתפים.",
            discord.Color.red()
        )
        return

    pool = list(view.participants)
    actual_winners_count = min(winners, len(view.raw_participants))
    
    chosen_winners = []
    while len(chosen_winners) < actual_winners_count and pool:
        winner_id = random.choice(pool)
        if winner_id not in chosen_winners:
            chosen_winners.append(winner_id)
        pool = [uid for uid in pool if uid != winner_id]

    winners_mentions = ", ".join([f"<@{uid}>" for uid in chosen_winners])

    ended_embed = fetched_msg.embeds[0]
    ended_embed.color = discord.Color.green()
    ended_embed.title = "🎉 Giveaway Ended 🎉"
    ended_embed.add_field(name="Winners", value=winners_mentions, inline=False)
    
    for child in view.children:
        child.disabled = True
    await fetched_msg.edit(embed=ended_embed, view=view)
    await channel.send(f"🎊 כל הכבוד ל-{winners_mentions}! זכית בפרס: **{prize}**!")

    await send_general_log(
        interaction.guild,
        "🎁 הגרלה הסתיימה והוכרזו זוכים",
        f"ההגרלה על הפרס **{prize}** הסתיימה. הזוכים: {winners_mentions}",
        discord.Color.green()
    )


@bot.tree.command(name="end-giveaway", description="סיום הגרלה מיידית לפי מזהה הודעה (לצוות בלבד)")
@discord.app_commands.describe(message_id="מזהה ההודעה (Message ID) של ההגרלה")
async def end_giveaway(interaction: discord.Interaction, message_id: str):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "end-giveaway")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ מזהה הודעה לא תקין.", ephemeral=True)
        return

    target_channel = None
    for channel in interaction.guild.text_channels:
        try:
            msg = await channel.fetch_message(msg_id)
            if msg:
                target_channel = channel
                break
        except:
            continue

    if not target_channel:
        await interaction.response.send_message("❌ לא נמצאה הודעת הגרלה עם ה-ID הזה בשרת.", ephemeral=True)
        return

    await interaction.response.send_message(f"✅ ההגרלה בחדר {target_channel.mention} הופסקה ונסגרה ידנית.", ephemeral=True)
    
    await send_general_log(
        interaction.guild,
        "🛑 הגרלה נסגרה ידנית",
        f"ההגרלה עם מזהה ההודעה `{msg_id}` בערוץ {target_channel.mention} נסגרה ידנית על ידי {interaction.user.mention}.",
        discord.Color.red()
    )


@bot.tree.command(name="reroll-giveaway", description="בחירת זוכה חדש מחדש להגרלה (לצוות בלבד)")
@discord.app_commands.describe(message_id="מזהה ההודעה (Message ID) של ההגרלה")
async def reroll_giveaway(interaction: discord.Interaction, message_id: str):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "reroll-giveaway")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    try:
        msg_id = int(message_id)
    except ValueError:
        await interaction.response.send_message("❌ מזהה הודעה לא תקין.", ephemeral=True)
        return

    target_channel = None
    for channel in interaction.guild.text_channels:
        try:
            msg = await channel.fetch_message(msg_id)
            if msg:
                target_channel = channel
                break
        except:
            continue

    if not target_channel:
        await interaction.response.send_message("❌ לא נמצאה הודעת הגרלה עם ה-ID הזה בשרת.", ephemeral=True)
        return

    await interaction.response.send_message("🔄 בוצעה הגרלה מחדש (Reroll) בהצלחה!", ephemeral=True)

    await send_general_log(
        interaction.guild,
        "🔄 בוצעה הגרלה מחדש (Reroll)",
        f"בוצעה הגרלה מחדש להגרלה בערוץ {target_channel.mention} על ידי {interaction.user.mention}.",
        discord.Color.gold()
    )


# --- טופס פקודת /know-staff ---
class KnowStaffModal(discord.ui.Modal, title="יצירת כרטיס היכרות - Know The Staff"):
    staff_role_title = discord.ui.TextInput(
        label="כותרת תפקיד (לדוגמה: ⚡ Server Owner ⚡)", 
        placeholder="⚡ Server Owner ⚡", 
        required=True
    )
    staff_content = discord.ui.TextInput(
        label="תוכן היכרות וסיפור אישי", 
        placeholder="היי לכם! השם שלי הוא...", 
        style=discord.TextStyle.paragraph, 
        required=True
    )

    def __init__(self, target_member: discord.Member):
        super().__init__()
        self.target_member = target_member

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description=f"### {self.staff_role_title.value}\n\n{self.target_member.mention}\n-----------------------------------------\n\n{self.staff_content.value}",
            color=discord.Color.red()
        )
        
        guild_icon = interaction.guild.icon.url if interaction.guild.icon else None
        embed.set_author(name="Know The Staff", icon_url=guild_icon)

        if self.target_member.avatar:
            embed.set_thumbnail(url=self.target_member.avatar.url)
        elif self.target_member.default_avatar:
            embed.set_thumbnail(url=self.target_member.default_avatar.url)

        sent_message = await interaction.channel.send(embed=embed)
        await sent_message.add_reaction("⬆️")
        await sent_message.add_reaction("⬇️")

        await interaction.response.send_message("כרטיס ההיכרות פורסם עם תמונת הפרופיל ואפשרויות הדירוג בהצלחה! ✨", ephemeral=True)


# --- מערכת ההצעות (Suggestions System) ---

class SuggestionVoteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.yes_votes = set()
        self.no_votes = set()

    @discord.ui.button(label="בעד", style=discord.ButtonStyle.green, emoji="✅", custom_id="suggest_yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id in self.yes_votes:
            self.yes_votes.remove(user_id)
            msg = "ההצבעה שלך (בעד) בוטלה."
        else:
            if user_id in self.no_votes:
                self.no_votes.remove(user_id)
            self.yes_votes.add(user_id)
            msg = "הצבעתך (בעד) נקלטה בהצלחה! 👍"

        await interaction.response.send_message(msg, ephemeral=True)
        await self.update_suggestion_embed(interaction)

    @discord.ui.button(label="נגד", style=discord.ButtonStyle.red, emoji="❌", custom_id="suggest_no")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id
        
        if user_id in self.no_votes:
            self.no_votes.remove(user_id)
            msg = "ההצבעה שלך (נגד) בוטלה."
        else:
            if user_id in self.yes_votes:
                self.yes_votes.remove(user_id)
            self.no_votes.add(user_id)
            msg = "הצבעתך (נגד) נקלטה בהצלחה. 👎"

        await interaction.response.send_message(msg, ephemeral=True)
        await self.update_suggestion_embed(interaction)

    async def update_suggestion_embed(self, interaction: discord.Interaction):
        message = interaction.message
        embed = message.embeds[0]
        
        yes_count = len(self.yes_votes)
        no_count = len(self.no_votes)
        total_votes = yes_count + no_count

        embed.clear_fields()
        embed.add_field(name="✅ בעד", value=f"`{yes_count}` קולות", inline=True)
        embed.add_field(name="❌ נגד", value=f"`{no_count}` קולות", inline=True)
        embed.add_field(name="📊 סך הכל מצביעים", value=f"`{total_votes}`", inline=True)

        await message.edit(embed=embed, view=self)


class SuggestionModal(discord.ui.Modal, title="יצירת הצעה חדשה - Suggestion"):
    suggestion_title = discord.ui.TextInput(
        label="כותרת ההצעה", 
        placeholder="הכנס כותרת קצרה להצעה שלך...", 
        required=True
    )
    suggestion_description = discord.ui.TextInput(
        label="תוכן ההצעה המלא", 
        placeholder="תאר את ההצעה שלך בפירוט...", 
        style=discord.TextStyle.paragraph, 
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"💡 הצעה חדשה: {self.suggestion_title.value}",
            description=self.suggestion_description.value,
            color=discord.Color.gold()
        )
        
        author_name = f"הוצע על ידי: {interaction.user.display_name}"
        author_icon = interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url
        embed.set_author(name=author_name, icon_url=author_icon)
        
        embed.add_field(name="✅ בעד", value="`0` קולות", inline=True)
        embed.add_field(name="❌ נגד", value="`0` קולות", inline=True)
        embed.add_field(name="📊 סך הכל מצביעים", value="`0`", inline=True)
        
        embed.set_footer(text=f"מערכת הצעות • {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)

        view = SuggestionVoteView()
        target_channel = interaction.guild.get_channel(SUGGESTION_CHANNEL_ID)
        if target_channel:
            await target_channel.send(embed=embed, view=view)
        else:
            await interaction.channel.send(embed=embed, view=view)
            
        await interaction.response.send_message("ההצעה שלך פורסמה בהצלחה בערוץ ההצעות! 🚀", ephemeral=True)


# --- מערכת הטיקטים והפאנל המעוצב ---

class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.is_locked = False

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.green, emoji="🙋‍♂️", custom_id="claim_ticket")
    async def claim_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ רק אנשי צוות או מנהלים רשאים לקחת טיקט זה!", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Claimed by {interaction.user.name}"
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"🔒 הטיקט הזה נלקח לטיפול על ידי **{interaction.user.mention}**.")
        
        await send_log(
            interaction.guild,
            "🙋‍♂️ טיקט נלקח לטיפול (Claim)",
            f"הטיקט **{interaction.channel.name}** נלקח על ידי {interaction.user.mention}.",
            discord.Color.gold()
        )

    @discord.ui.button(label="Close", style=discord.ButtonStyle.red, emoji="🔒", custom_id="close_ticket")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ רק אנשי צוות או מנהלים רשאים לסגור טיקט זה!", ephemeral=True)
            return

        await interaction.response.send_message("⚠️ הטיקט ייסגר בעוד 5 שניות וישמר קובץ שיחה...", ephemeral=False)

        closed_category = interaction.guild.get_channel(CLOSED_TICKET_CATEGORY_ID)
        if isinstance(closed_category, discord.CategoryChannel):
            await interaction.channel.edit(category=closed_category)

        ticket_owner = ticket_owners.get(interaction.channel.id)
        if ticket_owner:
            await interaction.channel.set_permissions(ticket_owner, send_messages=False)
        
        messages = []
        async for message in interaction.channel.history(limit=None, oldest_first=True):
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            messages.append(f"[{timestamp}] {message.author}: {message.content}")
        
        transcript_content = "\n".join(messages)
        file_bytes = io.BytesIO(transcript_content.encode('utf-8'))
        transcript_file = discord.File(file_bytes, filename=f"transcript-{interaction.channel.name}.txt")

        await send_log(
            interaction.guild,
            "🔒 טיקט נסגר - קובץ שיחה (Transcript)",
            f"הטיקט **{interaction.channel.name}** נסגר על ידי {interaction.user.mention}.\nמצורף קובץ הטקסט של השיחה.",
            discord.Color.red(),
            file=transcript_file
        )

        await asyncio.sleep(5)
        try:
            ticket_owner = ticket_owners.pop(interaction.channel.id, None)
            if ticket_owner and approved_form_tickets.get(ticket_owner.id) == interaction.channel.id:
                del approved_form_tickets[ticket_owner.id]
            await interaction.channel.delete()
        except:
            pass

    @discord.ui.button(label="Lock / Unlock", style=discord.ButtonStyle.secondary, emoji="🔐", custom_id="lock_ticket")
    async def lock_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ רק אנשי צוות או מנהלים רשאים לנעול או לפתוח טיקט זה!", ephemeral=True)
            return

        guild = interaction.guild
        owner = ticket_owners.get(interaction.channel.id)

        if not owner:
            await interaction.response.send_message("❌ לא נמצא משתמש רשום שפתח את הטיקט הזה.", ephemeral=True)
            return

        current_overwrite = interaction.channel.overwrites_for(owner)
        
        if current_overwrite.send_messages is False:
            current_overwrite.send_messages = True
            status_text = "פתח מחדש"
            log_title = "🔓 טיקט נפתח מחדש"
            log_color = discord.Color.green()
        else:
            current_overwrite.send_messages = False
            status_text = "נעל"
            log_title = "🔐 טיקט ננעל"
            log_color = discord.Color.dark_orange()

        await interaction.channel.set_permissions(owner, overwrite=current_overwrite)
        await interaction.response.send_message(f"🔐 **{interaction.user.name}** {status_text} את הטיקט.", ephemeral=False)

        await send_log(
            guild,
            log_title,
            f"הטיקט **{interaction.channel.name}** {status_text} על ידי {interaction.user.mention}.",
            log_color
        )


class ApprovedFormTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="פתיחת טיקט המשך", style=discord.ButtonStyle.green, emoji="🎫", custom_id="open_approved_form_ticket")
    async def open_ticket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        existing_channel_id = approved_form_tickets.get(interaction.user.id)
        existing_channel = guild.get_channel(existing_channel_id) if existing_channel_id else None
        if not existing_channel:
            approved_form_tickets.pop(interaction.user.id, None)
            existing_channel = next(
                (
                    channel for channel in guild.text_channels
                    if channel.category_id == APPROVED_FORM_TICKET_CATEGORY_ID
                    and channel.topic
                    and f"owner_id:{interaction.user.id}" in channel.topic
                ),
                None
            )
        if existing_channel:
            await interaction.response.send_message(
                f"יש לך כבר טיקט פתוח עבור הטופס המאושר: {existing_channel.mention}",
                ephemeral=True
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True
            )
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True
            )
        for role_id in APPROVED_FORM_TICKET_ROLE_IDS:
            staff_role = guild.get_role(role_id)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True
                )

        ticket_category = guild.get_channel(APPROVED_FORM_TICKET_CATEGORY_ID)
        ticket_channel = await guild.create_text_channel(
            name=f"approved-{interaction.user.name}",
            category=ticket_category,
            overwrites=overwrites,
            topic=f"טיקט המשך לטופס מאושר של {interaction.user} | owner_id:{interaction.user.id}"
        )
        approved_form_tickets[interaction.user.id] = ticket_channel.id
        ticket_owners[ticket_channel.id] = interaction.user

        embed = discord.Embed(
            title="🎫 טיקט המשך לטופס מאושר",
            description=(
                f"ברוכים הבאים {interaction.user.mention}!\n\n"
                "הטופס שלך אושר, והטיקט הזה נפתח כדי שתוכלו להמשיך את התהליך מול הצוות."
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="Game2Earn Support")
        await ticket_channel.send(embed=embed, view=TicketControlView())
        await interaction.response.send_message(
            f"✅ הטיקט נפתח בהצלחה: {ticket_channel.mention}",
            ephemeral=True
        )


class TicketPanelModal(discord.ui.Modal, title="עיצוב פאנל טיקטים"):
    panel_title = discord.ui.TextInput(
        label="1. כותרת לפאנל (Title)", 
        placeholder="🎫 מרכז התמיכה של Game2Earn",
        default="🎫 מרכז התמיכה של Game2Earn",
        required=True
    )
    panel_description = discord.ui.TextInput(
        label="2. כותרת משנית / תיאור (Description)", 
        placeholder="זקוקים לעזרה? בחרו קטגוריה מהתפריט ונפתח עבורכם טיקט פרטי.",
        default="שלום 👋\nזקוקים לעזרה, תמיכה או מידע נוסף?\nבחרו את הקטגוריה המתאימה מהתפריט למטה ונפתח עבורכם טיקט פרטי עם צוות הקהילה.",
        style=discord.TextStyle.paragraph, 
        required=True
    )
    panel_color = discord.ui.TextInput(
        label="3. צבע (blue, red, green, gold, purple)", 
        placeholder="blue", 
        required=False,
        max_length=10
    )
    panel_image = discord.ui.TextInput(
        label="4. תמונה לפאנל (Image URL)", 
        placeholder="https://... (קישור ישיר לתמונה)", 
        required=False
    )
    panel_footer = discord.ui.TextInput(
        label="5. טקסט תחתון (Footer Text)", 
        placeholder="Game2Earn Support • הצוות כאן בשבילכם",
        default="Game2Earn Support • הצוות כאן בשבילכם",
        required=False
    )

    async def on_submit(self, interaction: discord.Interaction):
        color = discord.Color.blue()
        c_text = self.panel_color.value.strip().lower()
        if c_text == "red":
            color = discord.Color.red()
        elif c_text == "green":
            color = discord.Color.green()
        elif c_text == "gold" or c_text == "yellow":
            color = discord.Color.gold()
        elif c_text == "purple":
            color = discord.Color.purple()

        embed = discord.Embed(
            title=self.panel_title.value,
            description=self.panel_description.value,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        if interaction.guild.icon:
            embed.set_author(name="Game2Earn Support Center", icon_url=interaction.guild.icon.url)
            embed.set_thumbnail(url=interaction.guild.icon.url)

        category_list = "\n".join(
            f"{category['emoji']} **{category['label']}** — {category['description']}"
            for category in ticket_categories
        )
        embed.add_field(
            name="🧭 איך פותחים טיקט?",
            value="בחרו קטגוריה מהתפריט למטה. הטיקט יהיה פרטי ויהיה גלוי רק לכם ולצוות המתאים.",
            inline=False
        )
        embed.add_field(
            name="📂 קטגוריות זמינות",
            value=category_list or "אין קטגוריות זמינות כרגע.",
            inline=False
        )
        if self.panel_image.value.strip():
            embed.set_image(url=self.panel_image.value.strip())
        if self.panel_footer.value.strip():
            embed.set_footer(
                text=self.panel_footer.value.strip(), 
                icon_url=interaction.guild.icon.url if interaction.guild.icon else None
            )

        view = TicketPanelView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("פאנל הטיקטים המעוצב נוצר בהצלחה! ✅", ephemeral=True)


class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label=cat["label"], 
                description=cat["description"], 
                emoji=cat["emoji"], 
                value=cat["value"]
            ) for cat in ticket_categories
        ]
        super().__init__(placeholder="בחרו קטגוריה לפתיחת טיקט", min_values=1, max_values=1, options=options, custom_id="persistent_ticket_select")

    async def callback(self, interaction: discord.Interaction):
        category_value = self.values[0]
        guild = interaction.guild
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)
        }

        global STAFF_ROLE_ID
        if STAFF_ROLE_ID:
            staff_role = guild.get_role(STAFF_ROLE_ID)
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{interaction.user.name}-{category_value}",
            category=guild.get_channel(OPEN_TICKET_CATEGORY_ID),
            overwrites=overwrites
        )

        ticket_owners[ticket_channel.id] = interaction.user

        embed = discord.Embed(
            title=f"טיקט חדש - {interaction.user.name}",
            description=f"תודה שפנית לתמיכה. הקטגוריה שנבחרה היא: **{category_value}**.\nצוות השרת יגיע בהקדם האפשרי.",
            color=discord.Color.blue()
        )
        
        view = TicketControlView()
        await ticket_channel.send(f"{interaction.user.mention} ברוך הבא לטיקט שלך!", embed=embed, view=view)
        await interaction.response.send_message(f"הטיקט שלך נוצר בהצלחה: {ticket_channel.mention} 🎫", ephemeral=True)

        await send_log(
            guild,
            "📂 פתיחת טיקט חדש",
            f"המשתמש **{interaction.user.mention}** פתח טיקט בקטגוריה: **{category_value}**\nערוץ: {ticket_channel.mention}",
            discord.Color.green()
        )

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())


# --- מערכת טפסים סופית ומעודכנת ---

class FormReviewButtons(discord.ui.View):
    def __init__(self, applicant_member: discord.Member, form_type_name: str, guild: discord.Guild, application_channel=None):
        super().__init__(timeout=None)
        self.applicant_member = applicant_member
        self.form_type_name = form_type_name
        self.guild = guild
        self.application_channel = application_channel

    @discord.ui.button(label="אשר טופס (V)", style=discord.ButtonStyle.green, emoji="✅", custom_id="approve_form_btn")
    async def approve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ רק צוות השרת מורשה לאשר טפסים!", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        approved_channel = interaction.guild.get_channel(FORMS_APPROVED_CHANNEL_ID)
        if approved_channel:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.green()
            embed.add_field(name="📌 סטטוס", value=f"אושר על ידי {interaction.user.mention}", inline=False)
            await approved_channel.send(embed=embed)

        if self.application_channel:
            result_embed = discord.Embed(
                title="✅ הטופס אושר בהצלחה!",
                description=(
                    f"{self.applicant_member.mention}, הטופס שלך אושר על ידי צוות השרת.\n\n"
                    "פתח טיקט כדי להמשיך לשלב הבא בתהליך."
                ),
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            result_embed.set_footer(text="Game2Earn Staff Recruitment")
            await self.application_channel.send(embed=result_embed, view=ApprovedFormTicketView())
            await self.application_channel.set_permissions(self.applicant_member, send_messages=False)

        dm_success = True
        if not self.application_channel:
            try:
                dm_channel = await self.applicant_member.create_dm()
                
                embed_msg = discord.Embed(
                    title=f"🎉 אושר בהצלחה - הטופס שלך ל-{self.form_type_name} 🎊",
                    description="עברת לשלב הבא! אנא פתח עכשיו טיקט בשרת כדי להמשיך בתהליך.",
                    color=discord.Color.purple()
                )
                embed_msg.set_footer(text="Game2Earn System")

                ticket_channel_obj = self.guild.get_channel(TICKET_CHANNEL_ID)
                
                class OpenTicketButton(discord.ui.View):
                    def __init__(self):
                        super().__init__(timeout=None)
                        url_link = f"https://discord.com/channels/{self.guild.id}/{TICKET_CHANNEL_ID}" if ticket_channel_obj else "https://discord.com"
                        self.add_item(discord.ui.Button(label="פתח טיקט", style=discord.ButtonStyle.secondary, emoji="🎫", url=url_link))

                await dm_channel.send(embed=embed_msg, view=OpenTicketButton())
            except Exception as e:
                dm_success = False
                print(f"שגיאה בשליחת הודעה ל-DM: {e}")

        if self.application_channel:
            await interaction.response.send_message(f"הטופס של {self.applicant_member.mention} אושר בהצלחה, והמשתמש עודכן בערוץ המועמדות!", ephemeral=True)
        elif dm_success:
            await interaction.response.send_message(f"הטופס של {self.applicant_member.mention} אושר בהצלחה, הודעה נשלחה אליו בפרטי והוא הועבר לחדר המאושרים!", ephemeral=True)
        else:
            await interaction.response.send_message(f"⚠️ הטופס אושר והועבר לחדר המאושרים, **אך לא הצלחנו לשלוח לו הודעה בפרטי (DM)** כי ההודעות הפרטיות שלו סגורות!", ephemeral=True)

    @discord.ui.button(label="דחה טופס (X)", style=discord.ButtonStyle.red, emoji="❌", custom_id="reject_form_btn")
    async def reject_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not has_staff_permissions(interaction.user):
            await interaction.response.send_message("❌ רק צוות השרת מורשה לדחות טפסים!", ephemeral=True)
            return

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)

        rejected_channel = interaction.guild.get_channel(FORMS_REJECTED_CHANNEL_ID)
        if rejected_channel:
            embed = interaction.message.embeds[0]
            embed.color = discord.Color.red()
            embed.add_field(name="📌 סטטוס", value=f"נדחה על ידי {interaction.user.mention}", inline=False)
            await rejected_channel.send(embed=embed)

        if self.application_channel:
            deletion_timestamp = int(time.time()) + 24 * 60 * 60
            result_embed = discord.Embed(
                title="❌ עדכון לגבי הטופס שלך",
                description=(
                    f"{self.applicant_member.mention}, הטופס שלך לא אושר הפעם.\n\n"
                    "ניתן להגיש טופס חדש לאחר 5 ימים.\n\n"
                    f"⏳ ערוץ הטופס יימחק <t:{deletion_timestamp}:R>."
                ),
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            result_embed.set_footer(text="Game2Earn Staff Recruitment")
            await self.application_channel.send(embed=result_embed)
            await self.application_channel.set_permissions(self.applicant_member, send_messages=False)

            async def delete_rejected_application_channel():
                await asyncio.sleep(24 * 60 * 60)
                try:
                    await self.application_channel.delete(reason="טופס נדחה - מחיקה אוטומטית לאחר 24 שעות")
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    print(f"אין לבוט הרשאה למחוק את ערוץ המועמדות {self.application_channel.id}")

            asyncio.create_task(delete_rejected_application_channel())

        if not self.application_channel:
            try:
                await self.applicant_member.send(
                    f"❌ **לצערנו, הטופס שלך ל-{self.form_type_name} לא אושר הפעם.**\n"
                    f"תוכל להגיש טופס חדש לאחר **5 ימים** מעכשיו."
                )
            except:
                pass

        await interaction.response.send_message(f"הטופס של {self.applicant_member.mention} נדחה והועבר לחדר הלא מאושרים.", ephemeral=True)


class FormStartConfirmView(discord.ui.View):
    def __init__(self, guild: discord.Guild, form_type: str, form_name_display: str):
        super().__init__(timeout=180)
        self.guild = guild
        self.form_type = form_type
        self.form_name_display = form_name_display

    @discord.ui.button(label="Start application", style=discord.ButtonStyle.green, custom_id="start_form_btn")
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_id = interaction.user.id

        if user_id in forms_cooldowns:
            if datetime.now() < forms_cooldowns[user_id]:
                remaining = forms_cooldowns[user_id] - datetime.now()
                days = remaining.days
                hours = remaining.seconds // 3600
                await interaction.response.edit_message(content=f"⏳ יש לך עדיין Cooldown פעיל! תוכל להגיש טופס חדש בעוד כ-{days} ימים ו-{hours} שעות.", embed=None, view=None)
                return

        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.response.edit_message(content="✅ תהליך הגשת הטופס החל! ענה על השאלות הבאות בהודעות חדשות.", embed=None, view=None)

        try:
            dm_channel = interaction.channel
            questions = FORM_QUESTIONS[self.form_type]
            answers = []

            def check(m):
                return m.author.id == interaction.user.id and m.channel.id == dm_channel.id

            for question_index, question_text in enumerate(questions):
                question_number = question_index + 1
                question_embed = discord.Embed(
                    title=f"📝 {self.form_name_display}",
                    description="ענה על השאלה הבאה בהודעה חדשה כדי להמשיך בתהליך המועמדות.",
                    color=discord.Color.from_rgb(42, 157, 244),
                    timestamp=discord.utils.utcnow()
                )
                question_embed.add_field(
                    name=f"שאלה {question_number} מתוך {len(questions)}",
                    value=f"**{question_text}**",
                    inline=False
                )
                question_embed.add_field(
                    name="⏱️ זמן למילוי הטופס",
                    value="יש לך עד שעתיים להשלים את כל השאלות.",
                    inline=False
                )
                if self.guild.icon:
                    question_embed.set_thumbnail(url=self.guild.icon.url)
                question_embed.set_footer(text="Game2Earn Staff Recruitment • ענה בכנות ובפירוט")
                await dm_channel.send(embed=question_embed)
                
                try:
                    msg = await bot.wait_for('message', timeout=7200.0, check=check)
                    answers.append(msg.content)
                except asyncio.TimeoutError:
                    await dm_channel.send("⏱️ עבר הזמן המוקצב (שעתיים) ולא השלמת את הטופס. תהליך ההגשה פג תוקף.")
                    return

            await dm_channel.send("✅ סיימת לענות על כל השאלות! הטופס שלך נשלח בהצלחה לצוות לבדיקה.")

            if FORM_USE_PRIVATE_CHANNELS:
                await dm_channel.set_permissions(interaction.user, send_messages=False)

            forms_cooldowns[user_id] = datetime.now() + timedelta(days=5)

            review_channel = self.guild.get_channel(FORMS_REVIEW_CHANNEL_ID)
            if review_channel:
                embed = discord.Embed(
                    title=f"📄 טופס חדש - {self.form_name_display}",
                    color=discord.Color.gold(),
                    timestamp=datetime.now()
                )
                embed.set_author(name=f"מגיש הטופס: {interaction.user.name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
                
                for idx, q_text in enumerate(questions):
                    embed.add_field(name=f"שאלה {idx+1}: {q_text}", value=f"תשובה: `{answers[idx]}`", inline=False)
                
                embed.set_footer(text=f"User ID: {user_id}")

                view = FormReviewButtons(
                    applicant_member=interaction.user,
                    form_type_name=self.form_name_display,
                    guild=self.guild,
                    application_channel=dm_channel if FORM_USE_PRIVATE_CHANNELS else None
                )
                await review_channel.send(embed=embed, view=view)

        except discord.Forbidden:
            pass

    @discord.ui.button(label="Cancel application", style=discord.ButtonStyle.red, custom_id="cancel_form_btn")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ הגשת הטופס בוטלה לבקשתך.", embed=None, view=None)


class FormSelectDropdown(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="צוות דיסקורד", 
                description="הגשת מועמדות לצוות השרת • גיל 16 ומעלה", 
                emoji="📋", 
                value="discord_staff"
            ),
            discord.SelectOption(
                label="צוות טורנירים", 
                description="ניהול והפקת טורנירים • גיל 18 ומעלה", 
                emoji="🏆", 
                value="tournament_staff"
            )
        ]
        super().__init__(placeholder="בחרו את סוג הטופס שלכם", min_values=1, max_values=1, options=options, custom_id="persistent_form_select")

    async def callback(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        form_type = self.values[0]
        form_name_display = "Game2Earn Discord Staff" if form_type == "discord_staff" else "Game2Earn Tournament Staff"

        if user_id in forms_cooldowns:
            if datetime.now() < forms_cooldowns[user_id]:
                remaining = forms_cooldowns[user_id] - datetime.now()
                days = remaining.days
                hours = remaining.seconds // 3600
                await interaction.response.send_message(f"⏳ יש לך עדיין Cooldown פעיל! תוכל להגיש טופס חדש בעוד כ-{days} ימים ו-{hours} שעות.", ephemeral=True)
                return

        if FORM_USE_PRIVATE_CHANNELS:
            guild = interaction.guild
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )
            }
            if guild.me:
                overwrites[guild.me] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_channels=True
                )
            if STAFF_ROLE_ID:
                staff_role = guild.get_role(STAFF_ROLE_ID)
                if staff_role:
                    overwrites[staff_role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_channels=True
                    )

            form_category = guild.get_channel(FORM_CATEGORY_ID)
            application_channel = await guild.create_text_channel(
                name=f"application-{interaction.user.name}",
                category=form_category if isinstance(form_category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                topic=f"מועמדות של {interaction.user} • {form_name_display}"
            )
            intro_embed = discord.Embed(
                title=f"📝 {form_name_display}",
                description=(
                    f"{interaction.user.mention}, הערוץ הפרטי שלך נפתח בהצלחה.\n\n"
                    "לחץ על הכפתור כדי להתחיל לענות על השאלות. לאחר השליחה, הערוץ יינעל "
                    "ותוצאת הטופס תפורסם כאן לאחר בדיקת הצוות."
                ),
                color=discord.Color.from_rgb(42, 157, 244),
                timestamp=discord.utils.utcnow()
            )
            intro_embed.set_footer(text="Game2Earn Staff Recruitment")
            await application_channel.send(embed=intro_embed, view=FormStartConfirmView(
                guild=guild,
                form_type=form_type,
                form_name_display=form_name_display
            ))
            await interaction.response.send_message(
                f"✅ ערוץ המועמדות הפרטי שלך נפתח: {application_channel.mention}",
                ephemeral=True
            )
            return

        await interaction.response.send_message("📬 פתחתי עבורך את הודעת האישור בהודעות הפרטיות (DM) שלך!", ephemeral=True)

        try:
            dm_channel = await interaction.user.create_dm()

            embed = discord.Embed(
                title=form_name_display,
                description=(
                    "**האם אתה בטוח שאתה מוכן להתחיל?**\n\n"
                    "ברגע שתתחיל את תהליך הגשת הטופס, אשלח לך סדרת שאלות שאליהן תצטרך לענות. "
                    "יהיו לך **שעתיים** להשלמת הטופס. במידה ולא תסיים בזמן, תצטרך להתחיל מחדש. "
                    "אם תרצה לעצור את ההגשה בכל שלב, תוכל ללחוץ על כפתור הביטול.\n\n"
                    "⚠️ **שים לב:** לאחר הגשת הטופס לא תוכל להגיש טופס חדש במשך 5 ימים."
                ),
                color=discord.Color.from_rgb(52, 152, 219)
            )
            embed.set_footer(text="Sent from Game2Earn")

            view = FormStartConfirmView(guild=interaction.guild, form_type=form_type, form_name_display=form_name_display)
            await dm_channel.send(embed=embed, view=view)

        except discord.Forbidden:
            await interaction.followup.send("❌ אינני יכול לשלוח לך הודעה פרטית (DM). אנא פתח את ההודעות הפרטיות שלך משרת זה ונסה שוב!", ephemeral=True)


class FormPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FormSelectDropdown())


# --- פקודות ניהול הטיקטים והשרת ---

@bot.tree.command(name="ticket-panel", description="יצירה ועיצוב של פאנל הטיקטים (לצוות בלבד)")
async def ticket_panel(interaction: discord.Interaction):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "ticket-panel")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    modal = TicketPanelModal()
    await interaction.response.send_modal(modal)

@bot.tree.command(name="form-panel", description="שליחת פאנל בחירת טפסים מועמדות לצוות (לצוות בלבד)")
async def form_panel(interaction: discord.Interaction):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "form-panel")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 הצטרפו לצוות Game2Earn",
        description=(
            "רוצים לקחת חלק בקהילה ולהשפיע על העתיד שלה?\n\n"
            "בחרו את המסלול שמתאים לכם מהתפריט למטה כדי להתחיל את התהליך.\n"
            "ענו כמו שצריך, וצוות השרת יבחן את הטופס שלכם."
        ),
        color=discord.Color.from_rgb(42, 157, 244),
        timestamp=discord.utils.utcnow()
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    embed.add_field(
        name="📋 צוות דיסקורד",
        value="סיוע לחברי הקהילה, ניהול השרת ושמירה על חוויית משחק טובה.\n**דרישת גיל: 16+**",
        inline=False
    )
    embed.add_field(
        name="🏆 צוות טורנירים",
        value="ניהול, פיקוח והפקת טורנירים ואירועי גיימינג בקהילה.\n**דרישת גיל: 18+**",
        inline=False
    )
    embed.set_footer(text="Game2Earn Staff Recruitment • בחרו מסלול כדי להתחיל")
    
    view = FormPanelView()
    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("פאנל הטפסים נשלח בהצלחה לערוץ! ✅", ephemeral=True)

@bot.tree.command(name="add-category", description="הוספת קטגוריה חדשה לתפריט הטיקטים (לצוות בלבד)")
@discord.app_commands.describe(label="שם הקטגוריה", description="תיאור קצר", emoji="אייקון", value="מזהה באנגלית")
async def add_category(interaction: discord.Interaction, label: str, description: str, emoji: str, value: str):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "add-category")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    ticket_categories.append({
        "label": label,
        "description": description,
        "emoji": emoji,
        "value": value
    })
    await interaction.response.send_message(f"הקטגוריה **{emoji} · {label}** נוספה בהצלחה לרשימת הטיקטים! 🚀", ephemeral=True)

@bot.tree.command(name="del-category", description="מחיקת קטגוריה מפאנל הטיקטים (לצוות בלבד)")
async def del_category(interaction: discord.Interaction):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "del-category")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    if not ticket_categories:
        await interaction.response.send_message("אין כרגע קטגוריות ברשימה למחיקה.", ephemeral=True)
        return
    
    view = DeleteCategoryView()
    await interaction.response.send_message("בחר מהרשימה הבאה את הקטגוריה שברצונך למחוק:", view=view, ephemeral=True)

class DeleteCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=cat["label"], description=cat["value"], emoji=cat["emoji"], value=cat["value"]) 
            for cat in ticket_categories
        ]
        super().__init__(placeholder="בחר קטגוריה למחיקה...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        selected_value = self.values[0]
        global ticket_categories
        removed_category = None
        for cat in ticket_categories:
            if cat["value"] == selected_value:
                removed_category = cat
                break
        
        if removed_category:
            ticket_categories.remove(removed_category)
            await interaction.response.send_message(f"הקטגוריה **{removed_category['label']}** נמחקה בהצלחה!", ephemeral=True)
        else:
            await interaction.response.send_message("הקטגוריה לא נמצאה.", ephemeral=True)

class DeleteCategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(DeleteCategorySelect())

@bot.tree.command(name="ticketslogs", description="הגדרת ערוץ לוגים למערכת הטיקטים (לצוות בלבד)")
@discord.app_commands.describe(channel="בחר את ערוץ הלוגים מהרשימה")
async def ticketslogs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "ticketslogs")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    global LOG_CHANNEL_ID
    LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"ערוץ הלוגים הוגדר בהצלחה ל- **{channel.mention}**! 📋", ephemeral=True)

@bot.tree.command(name="server-logs", description="הגדרת חדר לוגים כללי לשינויים בשרת (לצוות בלבד)")
@discord.app_commands.describe(channel="בחר את חדר הלוגים הכללי")
async def server_logs(interaction: discord.Interaction, channel: discord.TextChannel):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "server-logs")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    global GENERAL_LOG_CHANNEL_ID
    GENERAL_LOG_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"חדר הלוגים הכללי של השרת הוגדר בהצלחה ל- **{channel.mention}**! 🔔", ephemeral=True)

@bot.tree.command(name="ticket-roles", description="בחר את רול הצוות שיקבל גישה לניהול טיקטים (לצוות בלבד)")
@discord.app_commands.describe(role="בחר את רול הצוות מהרשימה")
async def ticket_roles(interaction: discord.Interaction, role: discord.Role):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "ticket-roles")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    global STAFF_ROLE_ID
    STAFF_ROLE_ID = role.id
    await interaction.response.send_message(f"רול הצוות לניהול טיקטים הוגדר בהצלחה ל- **{role.name}**! 🛡️", ephemeral=True)

@bot.tree.command(name="welcome-channel", description="הגדרת ערוץ ברוכים הבאים למצטרפים חדשים (לצוות בלבד)")
@discord.app_commands.describe(channel="בחר את ערוץ הברכות מהרשימה")
async def welcome_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "welcome-channel")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    global WELCOME_CHANNEL_ID
    WELCOME_CHANNEL_ID = channel.id
    await interaction.response.send_message(f"ערוץ ברוכים הבאים הוגדר בהצלחה ל- **{channel.mention}**! ✨", ephemeral=True)

@bot.tree.command(name="know-staff", description="יצירת כרטיס היכרות מעוצב לחבר צוות (לצוות בלבד)")
@discord.app_commands.describe(member="בחר את חבר הצוות מהרשימה")
async def know_staff(interaction: discord.Interaction, member: discord.Member):
    if not (has_staff_permissions(interaction.user) or check_user_command_permission(interaction.user, "know-staff")):
        await interaction.response.send_message("❌ אין לך הרשאה להשתמש בפקודה זו!", ephemeral=True)
        return
    modal = KnowStaffModal(target_member=member)
    await interaction.response.send_modal(modal)


# --- פקודה לניהול הרשאות רולים: /permissions ---
class PermissionSelectView(discord.ui.View):
    def __init__(self, role: discord.Role):
        super().__init__(timeout=180)
        self.role = role

    @discord.ui.select(
        placeholder="בחר פקודה להוספה/הסרה לרול...",
        options=[
            discord.SelectOption(label="know-staff", description="יצירת כרטיס היכרות לצוות", emoji="🛡️"),
            discord.SelectOption(label="say", description="שליחת הודעות בשם הבוט", emoji="💬"),
            discord.SelectOption(label="ticket-panel", description="יצירת פאנל טיקטים", emoji="🎫"),
            discord.SelectOption(label="form-panel", description="יצירת פאנל טפסים", emoji="📋"),
            discord.SelectOption(label="delete", description="מחיקת הודעות", emoji="🗑️"),
            discord.SelectOption(label="start-tournament", description="יצירת טורניר חדש", emoji="🏆"),
            discord.SelectOption(label="start-giveaway", description="התחלת הגרלה", emoji="🎉"),
            discord.SelectOption(label="end-giveaway", description="סיום הגרלה", emoji="🛑"),
            discord.SelectOption(label="reroll-giveaway", description="הגרלה מחדש", emoji="🔄"),
            discord.SelectOption(label="add-category", description="הוספת קטגוריית טיקט", emoji="➕"),
            discord.SelectOption(label="del-category", description="מחיקת קטגוריית טיקט", emoji="🗑️"),
            discord.SelectOption(label="ticketslogs", description="הגדרת ערוץ לוגים", emoji="📋"),
            discord.SelectOption(label="server-logs", description="הגדרת חדר לוגים כללי", emoji="🔔"),
            discord.SelectOption(label="welcome-channel", description="הגדרת ערוץ ברוכים הבאים", emoji="✨"),
        ]
    )
    async def select_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        cmd_name = select.values[0]
        
        if self.role.id not in role_custom_permissions:
            role_custom_permissions[self.role.id] = []

        if cmd_name in role_custom_permissions[self.role.id]:
            role_custom_permissions[self.role.id].remove(cmd_name)
            status = "הוסרה מ-"
        else:
            role_custom_permissions[self.role.id].append(cmd_name)
            status = "נוספה בהצלחה ל-"

        await interaction.response.send_message(f"הפקודה `{cmd_name}` {status}רול **{self.role.name}**!", ephemeral=True)

@bot.tree.command(name="permissions", description="ניהול הרשאות פקודות לרולים שונים בשרת (מנהלים בלבד)")
@discord.app_commands.checks.has_permissions(administrator=True)
@discord.app_commands.describe(role="בחר את הרול שעבורו תרצה להגדיר הרשאות")
async def permissions(interaction: discord.Interaction, role: discord.Role):
    view = PermissionSelectView(role=role)
    await interaction.response.send_message(f"בחר מתוך הרשימה את הפקודה שברצונך להעניק או להסיר עבור הרול **{role.name}**:", view=view, ephemeral=True)


# --- פקודות פתוחות לכלל חברי השרת ---

@bot.tree.command(name="suggest", description="הגשת הצעה חדשה לקהילה")
async def suggest(interaction: discord.Interaction):
    if interaction.channel.id != SUGGESTION_CHANNEL_ID:
        await interaction.response.send_message(f"❌ ניתן להשתמש בפקודת ההצעות אך ורק בערוץ ההצעות הייעודי בלבד (<#{SUGGESTION_CHANNEL_ID}>)!", ephemeral=True)
        return

    modal = SuggestionModal()
    await interaction.response.send_modal(modal)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("❌ אין לך הרשאת ניהול (Administrator) כדי להשתמש בפקודה זו.", ephemeral=True)
    else:
        print(f"שגיאה בפקודה: {error}")

bot.run('MTU1MzE0MzIwNjcyMjQwNDM5Mg.G9Mi65.JdjKcCCO86JiAn9trt-dWnGUsP9V0oteQLXFFU')