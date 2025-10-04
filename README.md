## Telegram USDC-first Bybit Buyer Bot

This is an async Telegram bot (python-telegram-bot v21) that buys coins on Bybit SPOT with a USDC-first logic, auto-converting USDC→USDT if only a USDT pair exists. It fetches coin name and icon from CoinGecko for confirmations, supports DRY_RUN, and includes a self-check.

### Prerequisites
- **Python 3.11**
- OS: Linux/macOS/Windows
- Bybit account with API key (TRADE ONLY). Optional IP whitelist.

### Setup
```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your TELEGRAM_TOKEN and BYBIT_API_* keys
```

### Run
```bash
python app/main.py
```

### Self-check
Runs connectivity and a dry-run planning flow (no orders placed):
```bash
python -m app.selfcheck
```

### Configuration (.env)
- `TELEGRAM_TOKEN`: Bot token
- `BYBIT_API_KEY`, `BYBIT_API_SECRET`: TRADE ONLY, no withdrawals. Consider IP whitelist
- `BASE_CURRENCY`: Default quote selection label (default `USDC`)
- `DRY_RUN`: `true`/`false` (default `true`)
- `ADMIN_USER_ID`: Numeric Telegram user id for `/dryrun` toggling
- `BUY_AMOUNTS`: Comma-separated quote amounts for inline buttons (e.g., `10,20,50`)

### Commands
- `/start`, `/help`
- `/buy <TICKER>`: Presents confirmation with icon/name and price, buttons `[Buy 10 USDC] [Buy 20 USDC] [Cancel]`
- `/balance`: Shows USDC/USDT balances
- `/pairs <TICKER>`: Shows available Bybit spot pairs for USDC/USDT
- `/dryrun on|off`: Toggle DRY_RUN (admin only)
- `/price <TICKER>`: Optional helper to view price (not required; you can use `/buy` preview)

### USDC-first buy logic
1. Load markets via ccxt and cache in memory
2. If `<TICKER>/USDC` exists → buy with quote-order-quantity if supported, else fallback using last price
3. Else if `<TICKER>/USDT` exists:
   - Check USDT balance
   - If insufficient but you have USDC, auto-convert using market order on `USDT/USDC` (preferred, buy USDT) or `USDC/USDT` (sell USDC). Uses a 0.5% buffer to cover slippage/fees
   - Then buy `<TICKER>/USDT`
4. Amounts are entered in USDC. The bot converts to the pair's quote (USDT if needed). Buttons are configurable via `BUY_AMOUNTS`

#### ccxt specifics
Preferred approach:
```python
exchange.create_order(symbol, 'market', 'buy', None, None, {'quoteOrderQty': amount_quote})
```
If unsupported, fallback to `qty = amount_quote / last_price` and clamp using `exchange.amount_to_precision` and market `limits`.

### Error handling & reliability
- Retries on transient network failures via `tenacity`
- Graceful messages for `InsufficientFunds`, `InvalidOrder`, `NetworkError`, `DDoSProtection`
- Logging to console and `logs/app.log` via `RotatingFileHandler`; secrets are masked in self-check

### Docker
```bash
docker build -t bybit-buyer .
docker run --rm -it --env-file .env -v $(pwd)/logs:/app/logs bybit-buyer
```
Or using compose:
```bash
docker-compose up --build
```

### Safety tips
- Start with DRY_RUN enabled and small amounts
- Use TRADE ONLY API key; avoid withdrawal permissions
- Consider enabling IP whitelist

### Troubleshooting
- **Insufficient funds** when pair is USDT and you hold USDC → bot performs USDC→USDT conversion with buffer
- **Market not found** → coin may not be listed on Bybit SPOT
- **Bybit market buy requires price/quoteOrderQty** → fallback mode uses last price to compute amount
- **Network errors / rate limits** → retries and logging; try again later

### License
MIT

# NewTG
