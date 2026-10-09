"""
Web Dashboard — Options Trading
"""

import logging
from flask import Flask, render_template_string, jsonify
from config import DASHBOARD_PORT, DASHBOARD_HOST, TRADING_MODE, STARTING_CAPITAL

logger = logging.getLogger("dashboard")
app = Flask(__name__)

_broker = None
_risk = None
_goal = None


def init_dashboard(broker, risk, goal):
    global _broker, _risk, _goal
    _broker = broker
    _risk = risk
    _goal = goal


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Options Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #0d1117; color: #c9d1d9; padding: 16px; }
        .header { text-align: center; padding: 20px 0; border-bottom: 1px solid #21262d; margin-bottom: 20px; }
        .header h1 { color: #58a6ff; font-size: 22px; }
        .header .mode { color: #f0883e; font-size: 13px; margin-top: 4px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
        .card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px; }
        .card:hover { border-color: #58a6ff; }
        .card h2 { color: #58a6ff; font-size: 14px; margin-bottom: 10px; }
        .stat { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #21262d; font-size: 13px; }
        .stat:last-child { border: none; }
        .stat .label { color: #8b949e; }
        .stat .value { font-weight: 600; }
        .positive { color: #3fb950 !important; }
        .negative { color: #f85149 !important; }
        .progress-bar { width: 100%; height: 22px; background: #21262d; border-radius: 11px; overflow: hidden; margin: 10px 0; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #f0883e, #3fb950); border-radius: 11px;
                         display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #0d1117; min-width: 40px; }
        .milestone { background: #1c2128; color: #f0883e; padding: 6px 10px; border-radius: 6px; font-size: 12px; margin-top: 8px; text-align: center; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; }
        th { color: #8b949e; text-align: left; padding: 5px; border-bottom: 1px solid #21262d; }
        td { padding: 5px; border-bottom: 1px solid #161b22; }
        .ce { color: #3fb950; font-weight: 700; }
        .pe { color: #f85149; font-weight: 700; }
        .refresh { position: fixed; bottom: 16px; right: 16px; background: #58a6ff; color: #0d1117;
                   border: none; border-radius: 50%; width: 44px; height: 44px; font-size: 18px; cursor: pointer; }
        #upd { text-align: center; color: #484f58; font-size: 11px; margin-top: 14px; }
        .market-status { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
        .market-open { background: #0d2818; color: #3fb950; }
        .market-closed { background: #2d1010; color: #f85149; }
    </style>
</head>
<body>
<div class="header">
    <h1>📊 Options Trading Bot</h1>
    <div class="mode" id="mode"></div>
</div>
<div class="grid">
    <div class="card">
        <h2>🎯 Goal: ₹1 Crore</h2>
        <div class="progress-bar"><div class="progress-fill" id="gbar">0%</div></div>
        <div class="stat"><span class="label">Capital</span><span class="value" id="cap">—</span></div>
        <div class="stat"><span class="label">Growth</span><span class="value" id="growth">—</span></div>
        <div class="stat"><span class="label">Remaining</span><span class="value" id="rem">—</span></div>
        <div class="stat"><span class="label">Trading Days Left</span><span class="value" id="dleft">—</span></div>
        <div class="stat"><span class="label">Need/day</span><span class="value" id="need">—</span></div>
        <div class="stat"><span class="label">Actual/day</span><span class="value" id="actual">—</span></div>
        <div class="stat"><span class="label">Win/Loss Days</span><span class="value" id="wl">—</span></div>
        <div class="milestone" id="ms"></div>
    </div>
    <div class="card">
        <h2>📈 Today</h2>
        <div class="stat"><span class="label">P&L</span><span class="value" id="pnl">—</span></div>
        <div class="stat"><span class="label">Trades</span><span class="value" id="trd">—</span></div>
        <div class="stat"><span class="label">Open Positions</span><span class="value" id="opos">—</span></div>
        <div class="stat"><span class="label">Market</span><span class="value" id="mkt">—</span></div>
    </div>
    <div class="card" style="grid-column:1/-1;">
        <h2>📋 Open Positions</h2>
        <table id="ptbl"><thead><tr><th>Index</th><th>Strike</th><th>Type</th><th>Entry</th><th>Current</th><th>Qty</th><th>P&L</th></tr></thead><tbody></tbody></table>
    </div>
    <div class="card" style="grid-column:1/-1;">
        <h2>📝 Recent Trades</h2>
        <table id="ttbl"><thead><tr><th>Time</th><th>Index</th><th>Strike</th><th>Type</th><th>Entry</th><th>Exit</th><th>P&L</th></tr></thead><tbody></tbody></table>
    </div>
</div>
<div id="upd">—</div>
<button class="refresh" onclick="refresh()">↻</button>
<script>
async function refresh(){
 try{
  const r=await fetch('/api/status');const d=await r.json();
  document.getElementById('mode').innerHTML=d.mode.toUpperCase()+' <span class="market-status '+(d.market_open?'market-open':'market-closed')+'">'+(d.market_open?'MARKET OPEN':'MARKET CLOSED')+'</span>';
  document.getElementById('cap').textContent='₹'+d.capital.toLocaleString('en-IN');
  document.getElementById('growth').textContent=d.goal.growth_x+'x from ₹'+"""+str(int(STARTING_CAPITAL))+""".toLocaleString('en-IN');
  document.getElementById('rem').textContent='₹'+d.goal.remaining.toLocaleString('en-IN');
  document.getElementById('dleft').textContent=d.goal.trading_days_left;
  document.getElementById('need').textContent=d.goal.required_daily_pct+'%';
  document.getElementById('actual').textContent=d.goal.avg_daily_pct+'%';
  document.getElementById('wl').textContent=d.goal.win_days+'W / '+d.goal.loss_days+'L';
  const gb=document.getElementById('gbar');
  gb.style.width=Math.max(Math.min(d.goal.progress_pct,100),2)+'%';
  gb.textContent=d.goal.progress_pct+'%';
  // Milestone
  const ms=[{t:10000,l:'₹10K'},{t:25000,l:'₹25K'},{t:50000,l:'₹50K'},{t:100000,l:'₹1L'},{t:500000,l:'₹5L'},{t:1000000,l:'₹10L'}];
  let mst='';for(const m of ms){if(d.capital<m.t){mst='🏁 Next: '+m.l+' ('+(d.capital/m.t*100).toFixed(0)+'%)';break;}}
  document.getElementById('ms').textContent=mst;
  const pnl=document.getElementById('pnl');
  pnl.textContent='₹'+d.daily_pnl.toLocaleString('en-IN');
  pnl.className='value '+(d.daily_pnl>=0?'positive':'negative');
  document.getElementById('trd').textContent=d.trades_today;
  document.getElementById('opos').textContent=d.positions.length;
  document.getElementById('mkt').innerHTML='<span class="market-status '+(d.market_open?'market-open':'market-closed')+'">'+(d.market_open?'OPEN':'CLOSED')+'</span>';
  // Positions
  const pb=document.querySelector('#ptbl tbody');
  pb.innerHTML=d.positions.map(p=>{
   const cur=p.current_premium||p.entry_premium;
   const pl=(cur-p.entry_premium)*p.total_qty;
   return '<tr><td>'+p.symbol+'</td><td>'+p.strike+'</td><td class="'+(p.option_type==='CE'?'ce':'pe')+'">'+p.option_type+'</td><td>₹'+p.entry_premium.toFixed(1)+'</td><td>₹'+cur.toFixed(1)+'</td><td>'+p.total_qty+'</td><td class="'+(pl>=0?'positive':'negative')+'">₹'+pl.toFixed(0)+'</td></tr>';
  }).join('')||'<tr><td colspan="7" style="color:#484f58">No open positions</td></tr>';
  // Trades
  const tb=document.querySelector('#ttbl tbody');
  tb.innerHTML=d.trades.slice(-15).reverse().map(t=>{
   return '<tr><td>'+(t.exit_time||'').slice(11,19)+'</td><td>'+t.symbol+'</td><td>'+t.strike+'</td><td class="'+(t.option_type==='CE'?'ce':'pe')+'">'+t.option_type+'</td><td>₹'+(t.entry_premium||0).toFixed(1)+'</td><td>₹'+(t.exit_premium||0).toFixed(1)+'</td><td class="'+((t.pnl||0)>=0?'positive':'negative')+'">₹'+(t.pnl||0).toFixed(0)+'</td></tr>';
  }).join('')||'<tr><td colspan="7" style="color:#484f58">No trades yet</td></tr>';
  document.getElementById('upd').textContent='Updated: '+new Date().toLocaleTimeString();
 }catch(e){console.error(e);}
}
refresh();setInterval(refresh,15000);
</script>
</body></html>
"""


@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    from broker.client import BrokerClient
    from risk_manager import RiskManager
    from goal_tracker import GoalTracker

    broker = _broker or BrokerClient()
    risk = _risk or RiskManager()
    goal = _goal or GoalTracker()

    capital = broker.get_portfolio_value()
    progress = goal.get_progress(capital)
    stats = risk.get_daily_stats()

    from datetime import datetime, timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(IST)
    market_open = (now.weekday() < 5 and
                   now.replace(hour=9, minute=15) <= now <= now.replace(hour=15, minute=30))

    return jsonify({
        "mode": TRADING_MODE,
        "capital": round(capital, 2),
        "daily_pnl": stats["pnl_today"],
        "trades_today": stats["trades_today"],
        "positions": broker.get_open_positions(),
        "trades": broker.get_closed_trades(20),
        "goal": progress,
        "market_open": market_open,
    })


def run_dashboard(broker, risk, goal):
    init_dashboard(broker, risk, goal)
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT, debug=False, use_reloader=False)
