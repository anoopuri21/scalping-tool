const API = "http://127.0.0.1:8000";

let selectedIndex = null;
let selectedExpiry = null;
let selectedType = null;
let selectedStrike = null;
let strikesData = [];
let tradingConfig = {};
let suggestedSL = null;
let dashboardSocket = null;

let LOT_SIZE = { NIFTY: 75, BANKNIFTY: 30, SENSEX: 20 };

document.addEventListener("DOMContentLoaded", init);

["entry-price", "fixed-sl", "sl-offset", "limit-price", "trigger-price", "candle-count"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => {
        updateSL();
        validate();
    });
});

async function init() {
    await loadConfig();
    toggleOrderInputs();
    toggleSLInputs();

    try {
        const status = await fetch(`${API}/api/broker-status`).then((r) => r.json());
        if (status.authenticated) {
            hideModal();
            showApp();
            loadProfile();
            loadIndexPrices();
            setInterval(loadIndexPrices, 5000);
            loadDashboard();
            startDashboardFeed();
        } else showModal();
    } catch { showModal(); }
}

async function loadConfig() { const data = await fetch(`${API}/api/config`).then((r) => r.json()).catch(() => ({})); LOT_SIZE = data.lot_sizes || LOT_SIZE; tradingConfig = data; }
function showModal() { document.getElementById("broker-modal").classList.add("active"); document.getElementById("app").classList.add("hidden"); }
function hideModal() { document.getElementById("broker-modal").classList.remove("active"); }
async function loginFyers() { const login = await fetch(`${API}/auth/login`).then((r) => r.json()); if (login.login_url) window.location.href = login.login_url; }
function showApp() { document.getElementById("app").classList.remove("hidden"); document.getElementById("broker-tag").textContent = "FYERS"; document.getElementById("index-cards").classList.remove("hidden"); }
async function loadProfile() { const data = await fetch(`${API}/auth/status`).then((r) => r.json()).catch(() => ({})); if (data.authenticated) document.getElementById("user-name").textContent = data.user_name || data.user_id || "Trader"; }
async function logout() { await fetch(`${API}/auth/logout`, { method: "POST" }); location.reload(); }

async function loadIndexPrices() {
    for (const index of ["NIFTY", "BANKNIFTY", "SENSEX"]) {
        const data = await fetch(`${API}/api/index-quote/${index}`).then((r) => r.json()).catch(() => ({}));
        if (!data.price) continue;
        document.getElementById(`${index.toLowerCase()}-price`).textContent = data.price.toLocaleString("en-IN", { maximumFractionDigits: 2 });
        const changeEl = document.getElementById(`${index.toLowerCase()}-change`);
        if (!changeEl) continue;
        const sign = data.change >= 0 ? "+" : "";
        changeEl.textContent = `${sign}${(data.change || 0).toFixed(2)} (${sign}${(data.change_percent || 0).toFixed(2)}%)`;
        changeEl.className = `index-change ${data.change >= 0 ? "up" : "down"}`;
    }
}

async function selectIndex(index) { selectedIndex = index; selectedExpiry = null; selectedType = null; selectedStrike = null; suggestedSL = null; document.querySelectorAll('.index-card').forEach((el) => el.classList.toggle('selected', el.dataset.index === index)); document.getElementById("trade-form").classList.remove("hidden"); resetForm(); await loadExpiries(index); updateQty(); }
function resetForm() { document.getElementById("strike-select").innerHTML = '<option value="">Select Expiry First</option>'; ["btn-ce", "btn-pe"].forEach((id) => document.getElementById(id).classList.remove("selected", "ce", "pe")); document.getElementById("entry-price").value = ""; document.getElementById("fixed-sl").value = ""; document.getElementById("sl-offset").value = "0"; document.getElementById("candle-info").classList.add("hidden"); validate(); }

async function loadExpiries(index) {
    const data = await fetch(`${API}/api/expiries/${index}`).then((r) => r.json()).catch(() => ({}));
    const container = document.getElementById("expiry-btns");
    container.innerHTML = (data.expiries || []).slice(0, 4).map((exp) => `<button class="btn-select" data-expiry="${exp}" onclick="selectExpiry('${exp}')">${new Date(exp).getDate()} ${new Date(exp).toLocaleString('en', { month: 'short' })}</button>`).join("") || '<span style="color:var(--red)">No expiries</span>';
}

async function selectExpiry(expiry) { selectedExpiry = expiry; document.querySelectorAll('[data-expiry]').forEach((el) => el.classList.toggle('selected', el.dataset.expiry === expiry)); await loadStrikes(); }
async function loadStrikes() {
    if (!selectedIndex || !selectedExpiry) return;
    const data = await fetch(`${API}/api/strikes/${selectedIndex}?expiry=${selectedExpiry}`).then((r) => r.json()).catch(() => ({}));
    strikesData = data.strikes || [];
    document.getElementById("strike-select").innerHTML = '<option value="">-- Select Strike --</option>' + strikesData.map((item) => `<option value="${item.strike}">${item.strike}${item.is_atm ? ' ★' : ''}</option>`).join("");
    const atmItem = strikesData.find((s) => s.is_atm); if (atmItem) { document.getElementById("strike-select").value = atmItem.strike; selectedStrike = atmItem.strike; }
    updateEntryPrice(); await fetchSLReference(); validate();
}
function selectType(type) { selectedType = type; document.getElementById("btn-ce").classList.toggle("selected", type === "CE"); document.getElementById("btn-ce").classList.toggle("ce", type === "CE"); document.getElementById("btn-pe").classList.toggle("selected", type === "PE"); document.getElementById("btn-pe").classList.toggle("pe", type === "PE"); updateEntryPrice(); fetchSLReference(); validate(); }
async function onStrikeChange() { selectedStrike = parseInt(document.getElementById("strike-select").value) || null; updateEntryPrice(); await fetchSLReference(); validate(); }

function updateEntryPrice() {
    if (!selectedStrike || !selectedType) return;
    const strikeInfo = strikesData.find((s) => s.strike === selectedStrike); if (!strikeInfo) return;
    const ltp = selectedType === "CE" ? strikeInfo.ce_ltp : strikeInfo.pe_ltp;
    if (ltp) { document.getElementById("entry-price").value = ltp.toFixed(2); document.getElementById("strike-ltp").textContent = `LTP: ₹${ltp.toFixed(2)}`; document.getElementById("strike-ltp").classList.remove("hidden"); }
    updateSL();
}

function toggleOrderInputs() { const isLimit = document.getElementById("order-type").value !== "MARKET"; const isStop = document.getElementById("order-type").value === "STOP_LIMIT"; document.getElementById("limit-wrap").classList.toggle("hidden", !isLimit); document.getElementById("trigger-wrap").classList.toggle("hidden", !isStop); }
function toggleSLInputs() { const mode = document.getElementById("sl-mode").value; document.getElementById("fixed-sl-wrap").classList.toggle("hidden", mode !== "fixed"); document.getElementById("candle-sl-wrap").classList.toggle("hidden", mode !== "candle"); fetchSLReference(); }

async function fetchSLReference() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;
    if (document.getElementById("sl-mode").value !== "candle") return;
    const resolution = document.getElementById("candle-resolution").value;
    const count = document.getElementById("candle-count").value || 3;
    const offset = document.getElementById("sl-offset").value || 0;
    const data = await fetch(`${API}/api/sl-reference?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}&resolution=${resolution}&count=${count}&offset=${offset}`).then((r) => r.json()).catch(() => ({}));
    if (data.suggested_sl) {
        suggestedSL = data.suggested_sl;
        document.getElementById("last-3-low").textContent = `₹${(data.min_low || 0).toFixed(2)}`;
        document.getElementById("suggested-sl").textContent = `₹${data.suggested_sl.toFixed(2)}`;
        document.getElementById("candle-info").classList.remove("hidden");
    }
    updateSL();
}

function updateSL() {
    const mode = document.getElementById("sl-mode").value;
    const entry = parseFloat(document.getElementById("entry-price").value);
    const fixed = parseFloat(document.getElementById("fixed-sl").value);
    let activeSL = null;
    if (mode === "fixed" && fixed > 0) activeSL = fixed;
    else if (mode === "candle" && suggestedSL > 0) activeSL = suggestedSL;
    else if (entry > 0) activeSL = entry - (tradingConfig.sl_points || 5);
    document.getElementById("sl-price").textContent = activeSL ? `₹${activeSL.toFixed(2)}` : "--";
}

function changeLots(delta) { const input = document.getElementById("lots"); input.value = Math.max(1, Math.min(50, (parseInt(input.value) || 1) + delta)); updateQty(); }
function updateQty() { const lots = parseInt(document.getElementById("lots").value) || 1; document.getElementById("qty-display").textContent = `= ${lots * (LOT_SIZE[selectedIndex] || 50)} qty`; }
function validate() { const price = parseFloat(document.getElementById("entry-price").value); document.getElementById("submit-btn").disabled = !(selectedIndex && selectedExpiry && selectedType && selectedStrike && price > 0); }

async function placeTrade() {
    const payload = {
        index: selectedIndex, option_type: selectedType, strike_price: selectedStrike, expiry: selectedExpiry,
        entry_price: parseFloat(document.getElementById("entry-price").value), lots: parseInt(document.getElementById("lots").value),
        sl_mode: document.getElementById("sl-mode").value, fixed_sl: parseFloat(document.getElementById("fixed-sl").value) || null,
        sl_offset: parseFloat(document.getElementById("sl-offset").value) || 0, candle_resolution: document.getElementById("candle-resolution").value,
        candle_count: parseInt(document.getElementById("candle-count").value) || 3, order_type: document.getElementById("order-type").value,
        limit_price: parseFloat(document.getElementById("limit-price").value) || null, trigger_price: parseFloat(document.getElementById("trigger-price").value) || null,
        trailing_sl_points: parseFloat(document.getElementById("trailing-sl").value) || null,
    };
    const data = await fetch(`${API}/api/trade`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }).then((r) => r.json()).catch((e) => ({ success: false, error: e.message }));
    showStatus(data.success ? `✅ ${data.message} (attempts: ${data.order_attempts})` : `❌ ${data.error}`, data.success ? "success" : "error");
    loadDashboard();
}

async function loadDashboard() { const data = await fetch(`${API}/api/dashboard`).then((r) => r.json()).catch(() => ({ trades: [], metrics: {} })); renderDashboard(data); }
function renderDashboard(data) {
    const m = data.metrics || {};
    document.getElementById("metric-open").textContent = m.open_trades || 0;
    document.getElementById("metric-pnl").textContent = `₹${(m.total_pnl || 0).toFixed(2)}`;
    document.getElementById("metric-pos").textContent = m.total_positions || 0;
    document.getElementById("metric-retries").textContent = m.orders_with_retries || 0;
    document.getElementById("trades-body").innerHTML = (data.trades || []).map((t) => `<tr><td>${t.trade_id}</td><td>${t.symbol}</td><td>${t.order_type}</td><td>${t.quantity}</td><td>${(t.ltp || 0).toFixed(2)}</td><td>${(t.sl_price || 0).toFixed(2)}</td><td class="${(t.pnl || 0) >= 0 ? 'up' : 'down'}">${(t.pnl || 0).toFixed(2)}</td></tr>`).join("") || '<tr><td colspan="7">No open trades</td></tr>';
}
function startDashboardFeed() {
    const wsUrl = API.replace("http", "ws") + "/ws/dashboard";
    dashboardSocket = new WebSocket(wsUrl);
    dashboardSocket.onmessage = (e) => renderDashboard(JSON.parse(e.data));
    dashboardSocket.onerror = () => setInterval(loadDashboard, 2500);
}
function showStatus(msg, type) { const el = document.getElementById("status"); el.textContent = msg; el.className = `status ${type}`; el.classList.remove("hidden"); }
