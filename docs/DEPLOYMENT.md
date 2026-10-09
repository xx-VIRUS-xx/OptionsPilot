# Deployment & Requirements Document

> **Warning.** Do not deploy with `TRADING_MODE=live` or `DASHBOARD_HOST=0.0.0.0` as listed in section 4 below. The live broker path is incomplete (no position tracking, exits or square-off), and the dashboard has no authentication. Treat this document as a requirements sketch for paper mode. See the README "Status" section.

## 1. Project Overview
- **Name:** Auto Income Options Bot
- **Purpose:** Automated options trading bot for Nifty/BankNifty (Angel One SmartAPI) with web dashboard, Telegram alerts, and a session replay simulator for learning.
- **Deployment Target:** Subdomain (e.g., `bot.yourdomain.com`)

---

## 2. System Requirements

### Server
- **OS:** Ubuntu 22.04 LTS (recommended) or any modern Linux
- **CPU:** 2+ vCPU (for live trading + dashboard)
- **RAM:** 2GB+ (4GB recommended)
- **Disk:** 10GB+ free
- **Network:** Stable internet, low latency to broker

### Software
- **Python:** 3.10+
- **pip:** Latest
- **Node.js:** (optional, for advanced dashboard features)
- **nginx:** For reverse proxy (recommended)
- **Certbot:** For SSL (Let's Encrypt)

---

## 3. Python Dependencies
Install with:
```bash
pip3 install -r requirements.txt
```
- smartapi-python>=1.3.0
- pyotp>=2.9.0
- pandas>=2.0.0
- numpy>=1.24.0
- python-dotenv>=1.0.0
- flask>=3.0.0
- apscheduler>=3.10.0
- requests>=2.31.0
- ta>=0.11.0
- websocket-client>=1.6.0
- yfinance>=0.2.30

---

## 4. Environment Variables (.env)
Copy `.env.example` to `.env` and fill in:
- ANGEL_API_KEY
- ANGEL_CLIENT_ID
- ANGEL_PASSWORD
- ANGEL_TOTP_SECRET
- TELEGRAM_BOT_TOKEN
- TELEGRAM_CHAT_ID
- TRADING_MODE=live (for production)
- DASHBOARD_HOST=0.0.0.0
- DASHBOARD_PORT=8080

---

## 5. Web Dashboard
- **Framework:** Flask
- **Port:** 8080 (configurable)
- **Access:** Expose via nginx reverse proxy to subdomain (e.g., `bot.yourdomain.com`)
- **SSL:** Use Let's Encrypt for HTTPS
- **Security:**
  - Restrict access by IP or add basic auth (recommended)
  - Never expose .env or logs to public

---

## 6. Running the Bot
- **Start in background:**
```bash
nohup python3 main.py &
```
- **Dashboard:** http://bot.yourdomain.com
- **Simulator:**
```bash
python3 simulator.py --date YYYY-MM-DD
```

---

## 7. Deployment Steps
1. **Provision server** (cloud VM or VPS)
2. **Clone repo:**
   ```bash
   git clone <repo-url> auto_income
   cd auto_income
   ```
3. **Install Python & pip**
4. **Install requirements:**
   ```bash
   pip3 install -r requirements.txt
   ```
5. **Configure .env**
6. **Test in paper mode:**
   ```bash
   python3 main.py
   # Check dashboard and Telegram alerts
   ```
7. **Switch to live mode:**
   - Set `TRADING_MODE=live` in `.env`
8. **Set up nginx reverse proxy:**
   - Point subdomain to server IP
   - Configure nginx to proxy `localhost:8080` to `bot.yourdomain.com`
   - Enable SSL with certbot
9. **Set up process manager:**
   - Use `systemd`, `supervisor`, or `pm2` to keep bot running
10. **Monitor logs:**
    - `logs/` directory for runtime logs
    - Set up log rotation

---

## 8. Security & Compliance
- **API keys:** Never commit `.env` to git
- **Access:** Restrict dashboard to trusted IPs or add authentication
- **SSL:** Always use HTTPS
- **Broker compliance:** Ensure Angel One API usage complies with their terms
- **Data privacy:** Do not log sensitive info

---

## 9. Maintenance
- **Update dependencies regularly**
- **Monitor for API changes (Angel One, NSE, Yahoo Finance)**
- **Backup data/ directory** (contains paper trading state, sim reports)
- **Test simulator on new sessions for strategy validation**

---

## 10. Support
- For issues, contact: <your-email>
- Telegram alerts will notify of errors and trade activity

---

## 11. Optional Enhancements
- Add user authentication to dashboard
- Add Dockerfile for containerized deployment
- Add CI/CD for auto-deploy
- Add advanced analytics to dashboard

---

**Ready for production deployment on a secure subdomain.**
