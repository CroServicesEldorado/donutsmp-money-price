import discord
from discord.ext import commands, tasks
import requests
import json
import os
from bs4 import BeautifulSoup
from datetime import datetime

# --- CONFIGURATION ---
URL = "https://www.eldorado.gg/donutsmp-money/g/278"
HISTORY_FILE = "price_history.txt"
# Use environment variables
TOKEN = os.getenv("DISCORD_TOKEN")
# Keep Webhook for automated alerts if you want, or just use the bot to send to a channel ID
CHANNEL_ID = os.getenv("CHANNEL_ID") # The ID of the channel to send automated alerts to
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Setup Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- TRACKING STATE ---
last_price = None

def get_eldorado_prices():
    """Scrapes the 3 lowest prices from Eldorado.gg."""
    headers = {"User-Agent": USER_AGENT}
    try:
        response = requests.get(URL, headers=headers, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        script_tag = soup.find('script', id='__NEXT_DATA__')
        if not script_tag: return []
        data = json.loads(script_tag.string)
        
        try:
            offers = data['props']['pageProps']['offers']['results']
        except KeyError:
            try:
                offers = data['props']['pageProps']['initialState']['offers']['results']
            except KeyError:
                return []

        prices = []
        for offer in offers:
            unit_price = offer.get('pricePerUnit', {}).get('amount') or offer.get('unitPrice')
            if unit_price is None:
                total_amount = offer.get('price', {}).get('amount')
                quantity = offer.get('quantity') or offer.get('minQuantity') or 1
                unit_price = total_amount / quantity if total_amount else None
            if unit_price:
                prices.append(float(unit_price))
            if len(prices) >= 3: break
        return sorted(prices)
    except Exception as e:
        print(f"Scrape Error: {e}")
        return []

def update_history(prices):
    if not prices: return None
    avg_current = sum(prices) / len(prices)
    with open(HISTORY_FILE, "a") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')},{avg_current}\n")
    return avg_current

def get_history_stats():
    if not os.path.exists(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0: return None
    prices = []
    with open(HISTORY_FILE, "r") as f:
        for line in f:
            parts = line.strip().split(',')
            if len(parts) == 2: prices.append(float(parts[1]))
    return sum(prices) / len(prices) if prices else None

def create_embed(current_price, avg_history, percent_diff, signal_type, move_since_last=None):
    if signal_type == "BUY":
        color, title = 0x00FF00, "🟢 Buy Signal!"
    elif signal_type == "SELL":
        color, title = 0xFF0000, "🔴 Sell Signal!"
    elif signal_type == "MANUAL":
        color, title = 0x3498DB, "📊 Current Market Status"
    else:
        color, title = 0x3498DB, "📈 Market Movement"

    desc = f"Market price is **{percent_diff:+.2f}%** relative to history."
    if move_since_last is not None:
        desc += f"\nChange since last check: **{move_since_last:+.2f}%**"

    embed = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.utcnow())
    embed.add_field(name="Current Price", value=f"${current_price:.4f}", inline=True)
    if avg_history:
        embed.add_field(name="Historical Avg", value=f"${avg_history:.4f}", inline=True)
    embed.set_footer(text="DonutSMP Price Tracker • Eldorado.gg")
    return embed

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    automated_check.start()

@bot.command(name="price")
async def manual_check(ctx):
    """Manually check the current price."""
    await ctx.send("🔍 Checking Eldorado.gg prices... please wait.")
    prices = get_eldorado_prices()
    if not prices:
        await ctx.send("❌ Failed to fetch prices. The site might be down or blocking the request.")
        return

    current_lowest = prices[0]
    avg_history = get_history_stats()
    percent_diff = ((current_lowest - avg_history) / avg_history) * 100 if avg_history else 0
    
    embed = create_embed(current_lowest, avg_history, percent_diff, "MANUAL")
    await ctx.send(embed=embed)

@tasks.loop(minutes=10)
async def automated_check():
    global last_price
    prices = get_eldorado_prices()
    if not prices: return

    current_lowest = prices[0]
    avg_history = get_history_stats()
    update_history(prices)
    
    move_since_last = None
    if last_price is not None:
        move_since_last = ((current_lowest - last_price) / last_price) * 100

    if avg_history and CHANNEL_ID:
        channel = bot.get_channel(int(CHANNEL_ID))
        if not channel: return

        percent_diff = ((current_lowest - avg_history) / avg_history) * 100
        
        if percent_diff <= -10:
            await channel.send(embed=create_embed(current_lowest, avg_history, percent_diff, "BUY", move_since_last))
        elif percent_diff >= 10:
            await channel.send(embed=create_embed(current_lowest, avg_history, percent_diff, "SELL", move_since_last))
        elif move_since_last and abs(move_since_last) >= 5.0:
            await channel.send(embed=create_embed(current_lowest, avg_history, 0, "MOVE", move_since_last))

    last_price = current_lowest

bot.run(TOKEN)
