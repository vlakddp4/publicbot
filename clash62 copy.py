import os
import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
from dotenv import load_dotenv
import traceback
import asyncio
from datetime import datetime
import re

# 그룹 CONFIG
CONFIG = {
    "COMMAND_PREFIX": "!",
    "ENV_PATH": "C:/Users/LJH/Desktop/discordbot/.env",
    "PARTICIPANTS_PER_PAGE": 3,
}

# 버튼 설정 함수
def setup_bot():
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True
    intents.messages = True
    bot = commands.Bot(command_prefix=CONFIG["COMMAND_PREFIX"], intents=intents)
    bot.synced = False
    bot.db_connection = None
    return bot

bot = setup_bot()
tree = bot.tree

# 환경 변수 로드 및 검증
if not os.path.exists(CONFIG["ENV_PATH"]):
    print(".env 파일 경로가 잘못되었습니다.")
    exit(1)
load_dotenv(dotenv_path=CONFIG["ENV_PATH"])
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
ALLOWED_GUILD_ID = int(os.getenv("ALLOWED_GUILD_ID"))
DB_PATH = os.getenv("DATABASE_PATH")

# 오류 로거 및 사용자 알림 함수
def log_and_notify_error(error_type, interaction, message="오류가 발생했습니다. 나중에 다시 시도해주세요."):
    error_message = f"[{error_type} 오류] {message}"
    print(error_message)
    if interaction:
        asyncio.create_task(send_interaction_response(interaction, message))

async def send_interaction_response(interaction, message, delete_after=None):
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(message, ephemeral=False, delete_after=delete_after)
        else:
            await interaction.followup.send(message, ephemeral=False, delete_after=delete_after)
    except discord.InteractionResponded:
        await interaction.followup.send(message, ephemeral=False, delete_after=delete_after)

# 데이터베이스 연결 초기화
async def initialize_database():
    try:
        db_connection = await aiosqlite.connect(os.path.expanduser(DB_PATH))
        await db_connection.execute('''CREATE TABLE IF NOT EXISTS participants (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            discord_nickname TEXT,
            ingame_nickname TEXT,
            tier TEXT,
            rank_points INTEGER,
            most_champions TEXT,
            dakgg_link TEXT,
            profile_image TEXT,
            self_introduction TEXT,
            updated_at TEXT
        )''')
        await db_connection.commit()
        return db_connection
    except aiosqlite.Error as e:
        print(f"데이터베이스 초기화 중 오류 발생: {e}")
        exit(1)

# 데이터베이스 연결 확인 및 재연결 함수
async def ensure_db_connection():
    if bot.db_connection is None or not bot.db_connection._running:
        bot.db_connection = await initialize_database()

# 버튼 준비 이벤트
@bot.event
async def on_ready():
    print(f'{bot.user.name}으로 로그인되었습니다.')
    try:
        await ensure_db_connection()
        if not bot.synced:
            print('전역 동기화 중...')
            await tree.sync()
            print('전역 동기화 완료.')
            bot.synced = True
    except Exception as e:
        log_and_notify_error("시작", None, str(e))
        traceback.print_exc()

# 새싱 데이터베이스 연결 유지
@bot.event
async def setup_hook():
    bot.db_connection = await initialize_database()

# 서버에 버튼이 추가되었는 경우 메인 명령어 동기화
@bot.event
async def on_guild_join(guild):
    if guild.id == ALLOWED_GUILD_ID:
        try:
            synced = await tree.sync(guild=discord.Object(id=guild.id))
            print(f'명령어가 서버 {guild.id}에 성공적으로 동기화되었습니다.')
        except Exception as e:
            log_and_notify_error("동기화", None, str(e))
            traceback.print_exc()
    else:
        print(f'서버 {guild.id}는 허용된 서버가 아니습니다. (허용된 서버 ID: {ALLOWED_GUILD_ID})')

# 버튼 연결 종료 시 데이터베이스 연결 닫기
@bot.event
async def on_disconnect():
    if bot.db_connection:
        try:
            await bot.db_connection.close()
        except aiosqlite.Error as e:
            print(f"데이터베이스 연결 종료 중 오류 발생: {e}")

# 관리자 전용 명령어 권한 검증 함수
from discord.ext.commands import has_permissions

# 참가자 정보 유지성 검증
def validate_participation_info(discord_nickname, ingame_nickname, rank_points, dakgg_link):
    if rank_points < 0:
        return "랑크 점수는 음수가 될 수 없습니다."
    if not re.match(r'^https?://', dakgg_link):
        return "올바로로는 dak.gg 링크를 입력해주세요."
    if len(discord_nickname) > 32 or len(ingame_nickname) > 32:
        return "닉네임은 32자를 넘어서는 안 됩니다."
    return None

# 참가자 정보 삽입 또는 업데이트
def get_timestamp():
    return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

async def upsert_participant(user_id, username, discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link):
    updated_at = get_timestamp()
    await ensure_db_connection()
    try:
        async with bot.db_connection.execute('''
            INSERT INTO participants (user_id, username, discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                discord_nickname=excluded.discord_nickname,
                ingame_nickname=excluded.ingame_nickname,
                tier=excluded.tier,
                rank_points=excluded.rank_points,
                most_champions=excluded.most_champions,
                dakgg_link=excluded.dakgg_link,
                updated_at=updated_at
        ''', (user_id, username, discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, updated_at)):
            await bot.db_connection.commit()
    except aiosqlite.Error as e:
        print(f"참가자 정보 업데이트 중 오류 발생: {e}")
        raise

# 참가 명령어
@tree.command(name="내전참가", description="내전에 참가합니다.")
async def participate(interaction: discord.Interaction, discord_nickname: str, ingame_nickname: str, tier: str, rank_points: int, most_champions: str, dakgg_link: str):
    if interaction.guild is None or interaction.guild.id != ALLOWED_GUILD_ID:
        await interaction.followup.send("이 명령어는 이리에 진심인 서버에서만 사용할 수 있습니다.")
        return

    validation_error = validate_participation_info(discord_nickname, ingame_nickname, rank_points, dakgg_link)
    if validation_error:
        await send_interaction_response(interaction, validation_error)
        return

    user_id = interaction.user.id
    username = interaction.user.name

    try:
        await upsert_participant(user_id, username, discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link)
        await send_interaction_response(interaction, f'{interaction.user.mention}님이 내전에 참가하셨습니다!', delete_after=60)
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 취소 명령어
@tree.command(name="내전취소", description="내전 참가를 취소합니다.")
async def cancel_participation(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id != ALLOWED_GUILD_ID:
        await send_interaction_response(interaction, "이 명령어는 이리에 진심인 서버에서만 사용할 수 있습니다.")
        return

    user_id = interaction.user.id

    try:
        await ensure_db_connection()
        await bot.db_connection.execute('DELETE FROM participants WHERE user_id = ?', (user_id,))
        await bot.db_connection.commit()
        await send_interaction_response(interaction, f'{interaction.user.mention}님의 내전 참가가 취소되었습니다.', delete_after=60)
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 내정보 명령어
@tree.command(name="내정보", description="모다의 정보를 조회합니다. (내전참가 명령어 입력해야 조회가능)")
async def myinfo(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id != ALLOWED_GUILD_ID:
        await send_interaction_response(interaction, "이 명령어는 이리에 진심인 서버에서만 사용할 수 있습니다.")
        return

    user_id = interaction.user.id

    try:
        await ensure_db_connection()
        async with bot.db_connection.execute('SELECT discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, profile_image, self_introduction, updated_at FROM participants WHERE user_id = ?', (user_id,)) as cursor:
            result = await cursor.fetchone()

        if result:
            discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, profile_image, self_introduction, updated_at = result
            embed = discord.Embed(title=f'{interaction.user.name}님의 참가 정보', color=discord.Color.green())
            embed.add_field(name="디스코드 닉네임", value=discord_nickname, inline=False)
            embed.add_field(name="인게임 닉네임", value=ingame_nickname, inline=False)
            embed.add_field(name="티어", value=tier, inline=False)
            embed.add_field(name="랭크 점수", value=rank_points, inline=False)
            embed.add_field(name="모스트 실험체", value=most_champions, inline=False)
            embed.add_field(name="Dak.gg 링크", value=f"[전적]({dakgg_link})", inline=False)
            if profile_image:
                embed.set_image(url=profile_image)
            embed.add_field(name="자기소개", value=self_introduction if self_introduction else '없음', inline=False)
            embed.set_footer(text=f"마지막 업데이트: {updated_at}")
            await interaction.response.send_message(embed=embed, delete_after=60)
        else:
            await interaction.response.send_message("등록된 내전 참가 정보가 없습니다.", ephemeral=True)
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 내정보수정 명령어
@tree.command(name="내정보수정", description="본인의 프로필 이미지와 자기소개를 수정합니다.")
@app_commands.describe(self_introduction="수정할 자기소개")
async def update_myinfo(interaction: discord.Interaction, self_introduction: str = None, profile_image: discord.Attachment = None):
    if interaction.guild is None or interaction.guild.id != ALLOWED_GUILD_ID:
        await send_interaction_response(interaction, "이 명령어는 이리에 진심인 서버에서만 사용할 수 있습니다.", ephemeral=True)
        return

    user_id = interaction.user.id

    attachment_url = None
    if profile_image:
        if profile_image.content_type and profile_image.content_type.startswith("image"):
            attachment_url = profile_image.url
        else:
            await send_interaction_response(interaction, "올바른 이미지 파일을 체크해 주세요.")
            return

    try:
        await ensure_db_connection()
        async with bot.db_connection.execute('SELECT 1 FROM participants WHERE user_id = ?', (user_id,)) as cursor:
            existing_entry = await cursor.fetchone()

        if existing_entry:
            updated_at = get_timestamp()
            await bot.db_connection.execute('''UPDATE participants SET 
                                                profile_image = ?, self_introduction = ?, updated_at = ?
                                                WHERE user_id = ?''',
                                            (attachment_url, self_introduction, updated_at, user_id))
            await bot.db_connection.commit()
            await send_interaction_response(interaction, f'{interaction.user.mention}님의 정보가 업데이트되었습니다!')
        else:
            await send_interaction_response(interaction, "등록된 내전 참가 정보가 없습니다. 내전에 참가 후 확인해주세요.")
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 내전참가 확인 명령어
@tree.command(name="내전참가확인", description="내전에 참가했는지 확인합니다 (본인만 확인 가능)")
async def check_participation(interaction: discord.Interaction):
    if interaction.guild is None or interaction.guild.id != ALLOWED_GUILD_ID:
        await send_interaction_response(interaction, "이 명령어는 이리에 진심인 서버에서만 사용할 수 있습니다.", ephemeral=True)
        return

    user_id = interaction.user.id

    try:
        await ensure_db_connection()
        async with bot.db_connection.execute('SELECT 1 FROM participants WHERE user_id = ?', (user_id,)) as cursor:
            result = await cursor.fetchone()

        if result:
            await interaction.response.send_message(f'{interaction.user.mention}님은 내전에 참가하고 있습니다.', ephemeral=True)
        else:
            await interaction.response.send_message(f'{interaction.user.mention}님은 내전에 참가하고 있지 않습니다.', ephemeral=True)
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 전체 참가자 정보 확인 명령어 (페이지 방식)
@has_permissions(administrator=True) 
@tree.command(name="참가자정보", description="전체 참가자 정보를 페이지 형식으로 확인합니다")

async def allparticipants(interaction: discord.Interaction, page: int = 1):
    try:
        await ensure_db_connection()
        if not interaction.response.is_done():
            await interaction.response.defer()

        offset = (page - 1) * CONFIG["PARTICIPANTS_PER_PAGE"]
        async with bot.db_connection.execute('SELECT COUNT(*) FROM participants') as cursor:
            total_count = (await cursor.fetchone())[0]

        total_pages = (total_count + CONFIG["PARTICIPANTS_PER_PAGE"] - 1) // CONFIG["PARTICIPANTS_PER_PAGE"]
        if page > total_pages or page < 1:
            await interaction.followup.send(f"페이지 {page}는 유형하지 않습니다. 총 페이지 수: {total_pages}", ephemeral=True)
            return

        async with bot.db_connection.execute('SELECT discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, updated_at FROM participants LIMIT ? OFFSET ?',
                                             (CONFIG["PARTICIPANTS_PER_PAGE"], offset)) as cursor:
            results = await cursor.fetchall()

        if results:
            embed = discord.Embed(title=f"페이지 {page}/{total_pages}의 참가자 목록", color=discord.Color.blue())
            for result in results:
                discord_nickname, ingame_nickname, tier, rank_points, most_champions, dakgg_link, updated_at = result
                embed.add_field(name=f"디스코드 닉네임: {discord_nickname}", value=(
                    f"인게임 닉네임: {ingame_nickname}\n"
                    f"티어: {tier}\n"
                    f"랭크 점수: {rank_points}\n"
                    f"모스트 실험체: {most_champions}\n"
                    f"[dakgg 링크]({dakgg_link})\n"
                    f"마지막 업데이트: {updated_at}"), inline=False)
            embed.set_footer(text=f"페이지 {page} / {total_pages}")

            view = discord.ui.View()
            if page > 1:
                view.add_item(discord.ui.Button(label="이전 페이지", style=discord.ButtonStyle.primary, custom_id=f"allparticipants_prev_{page - 1}"))
            if page < total_pages:
                view.add_item(discord.ui.Button(label="다음 페이지", style=discord.ButtonStyle.primary, custom_id=f"allparticipants_next_{page + 1}"))

            message = await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            if interaction.message:
                await interaction.message.delete()
        else:
            await interaction.followup.send("등록된 참가자가 없습니다.", ephemeral=True)
    except aiosqlite.Error as e:
        await log_and_notify_error("데이터베이스", interaction, str(e))
        traceback.print_exc()

# 페이지 버튼 처리기
@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id")
        if custom_id and custom_id.startswith("allparticipants_"):
            await interaction.response.defer()
            _, direction, page_str = custom_id.split("_")
            page = int(page_str)
            command = tree.get_command('참가자정보')
            if command:
                try:
                    await command.callback(interaction, page=page)
                except discord.errors.NotFound:
                    await send_interaction_response(interaction, "메시지를 찾을 수 없습니다. 이미 삭제되었을 수 있습니다.", ephemeral=True)
                except discord.errors.Forbidden:
                    await send_interaction_response(interaction, "이 작업을 수행할 권한이 없습니다.", ephemeral=True)

# 버튼 실행
bot.run(TOKEN)


