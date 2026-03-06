const API = "http://127.0.0.1:8000";

let selectedIndex = null;
let selectedExpiry = null;
let selectedType = null;
let selectedStrike = null;
let strikesData = [];
let suggestedSL = null;
let dashboardSocket = null;
let dashboardPollTimer = null;
let indexPollTimer = null;
let strikeRefreshTimer = null;
let LOT_SIZE = { NIFTY: 65, BANKNIFTY: 30, SENSEX: 20 };

document.addEventListener("DOMContentLoaded", init);

async function init() {
    await loadConfig();
    bindInputs();
    try {
        const status = await fetch(`${API}/api/broker-status`).then((r) => r.json());
        if (status.authenticated) {
            showApp();
            await loadProfile();
            await loadIndexPrices();
            if (!indexPollTimer) indexPollTimer = setInterval(loadIndexPrices, 900);
            loadDashboard();
            startDashboardFeed();
        }
    } catch {
        showModal();
    }
}

function bindInputs() {
    ["entry-price", "fixed-sl", "lots"].forEach((id) => {
        document.getElementById(id)?.addEventListener("input", () => {
            updateSLPreview();
            validate();
        });
    });
}

async function loadConfig() {
    const cfg = await fetch(`${API}/api/config`).then((r) => r.json()).catch(() => ({}));
    LOT_SIZE = cfg.lot_sizes || LOT_SIZE;
}

function showModal() { document.getElementById("broker-modal").classList.add("active"); }
function hideModal() { document.getElementById("broker-modal").classList.remove("active"); }
function showApp() { hideModal(); document.getElementById("app").classList.remove("hidden"); document.getElementById("index-cards").classList.remove("hidden"); }

async function loginFyers() { const login = await fetch(`${API}/auth/login`).then((r) => r.json()); if (login.login_url) window.location.href = login.login_url; }
async function logout() { await fetch(`${API}/auth/logout`, { method: "POST" }); location.reload(); }
async function loadProfile() { const data = await fetch(`${API}/auth/status`).then((r) => r.json()).catch(() => ({})); document.getElementById("user-name").textContent = data.user_name || data.user_id || "Trader"; }

async function loadIndexPrices() {
    const indexes = ["NIFTY", "BANKNIFTY", "SENSEX"];
    const responses = await Promise.all(indexes.map((index) =>
        fetch(`${API}/api/index-quote/${index}`).then((r) => r.json()).catch(() => ({}))
    ));

    indexes.forEach((index, i) => {
        const data = responses[i] || {};
        if (!data.price) return;

        document.getElementById(`${index.toLowerCase()}-price`).textContent = data.price.toLocaleString("en-IN", { maximumFractionDigits: 2 });
        const changeEl = document.getElementById(`${index.toLowerCase()}-change`);
        const sign = data.change >= 0 ? "+" : "";
        changeEl.textContent = `${sign}${(data.change || 0).toFixed(2)} (${sign}${(data.change_percent || 0).toFixed(2)}%)`;
        changeEl.className = `index-change ${data.change >= 0 ? "up" : "down"}`;
    });
}

async function selectIndex(index) {
    selectedIndex = index;
    selectedExpiry = null;
    selectedType = null;
    selectedStrike = null;
    suggestedSL = null;
    stopStrikeRefresh();
    document.querySelectorAll(".index-card").forEach((el) => el.classList.toggle("selected", el.dataset.index === index));
    document.getElementById("trade-form").classList.remove("hidden");
    await loadExpiries();
    updateQty();
    validate();
}

async function loadExpiries() {
    const box = document.getElementById("expiry-btns");
    box.innerHTML = "Loading...";
    const data = await fetch(`${API}/api/expiries/${selectedIndex}`).then((r) => r.json()).catch(() => ({}));
    box.innerHTML = (data.expiries || []).slice(0, 4).map((exp) => `<button class="btn-select" data-expiry="${exp}" onclick="selectExpiry('${exp}')">${new Date(exp).getDate()} ${new Date(exp).toLocaleString('en', { month: 'short' })}</button>`).join("") || "No expiries";
}

async function selectExpiry(expiry) {
    selectedExpiry = expiry;
    document.querySelectorAll("[data-expiry]").forEach((el) => el.classList.toggle("selected", el.dataset.expiry === expiry));
    await loadStrikes();
    startStrikeRefresh();
}



function startStrikeRefresh() {
    stopStrikeRefresh();
    if (!selectedIndex || !selectedExpiry) return;

    strikeRefreshTimer = setInterval(async () => {
        if (!selectedIndex || !selectedExpiry) return;
        await loadStrikes({ keepSelection: true, silent: true });
    }, 800);
}

function stopStrikeRefresh() {
    if (strikeRefreshTimer) {
        clearInterval(strikeRefreshTimer);
        strikeRefreshTimer = null;
    }
}

async function loadStrikes({ keepSelection = false, silent = false } = {}) {
    const previousStrike = selectedStrike;
    const data = await fetch(`${API}/api/strikes/${selectedIndex}?expiry=${selectedExpiry}`).then((r) => r.json()).catch(() => ({}));
    strikesData = data.strikes || [];

    const select = document.getElementById("strike-select");
    const strikeOptions = '<option value="">-- Select Strike --</option>' + strikesData.map((s) => `<option value="${s.strike}">${s.strike}${s.is_atm ? " ★" : ""}</option>`).join("");
    if (select.innerHTML !== strikeOptions) {
        select.innerHTML = strikeOptions;
    }

    const hasPrevious = keepSelection && previousStrike && strikesData.some((s) => s.strike === previousStrike);
    if (hasPrevious) {
        select.value = previousStrike;
        selectedStrike = previousStrike;
    } else {
        const atm = strikesData.find((s) => s.is_atm);
        if (atm) {
            select.value = atm.strike;
            selectedStrike = atm.strike;
        }
    }

    await updateEntryPrice();
    if (!silent) {
        await fetchSLReference();
    }
    validate();
}

async function selectType(type) {
    selectedType = type;
    document.getElementById("btn-ce").classList.toggle("selected", type === "CE");
    document.getElementById("btn-pe").classList.toggle("selected", type === "PE");
    await updateEntryPrice();
    fetchSLReference();
    validate();
}

async function onStrikeChange() {
    selectedStrike = parseInt(document.getElementById("strike-select").value) || null;
    await updateEntryPrice();
    await fetchSLReference();
    validate();
}

async function onOrderTypeChange() {
    const t = document.getElementById("order-type").value;
    const triggerWrap = document.getElementById("trigger-wrap");
    triggerWrap.classList.toggle("hidden", t !== "STOP_LIMIT");
    const entry = document.getElementById("entry-price");
    if (t === "MARKET") {
        entry.readOnly = true;
        await updateEntryPrice();
    } else {
        entry.readOnly = false;
        entry.value = "";
    }
    validate();
}

function onSLModeChange() {
    const mode = document.getElementById("sl-mode").value;
    document.getElementById("candle-wrap").classList.toggle("hidden", mode !== "candle");
    document.getElementById("fixed-wrap").classList.toggle("hidden", mode !== "fixed");
    fetchSLReference();
    updateSLPreview();
}

async function updateEntryPrice() {
    if (!selectedStrike || !selectedType || !selectedIndex || !selectedExpiry) return;
    const strikeInfo = strikesData.find((s) => s.strike === selectedStrike);
    const ltpEl = document.getElementById("strike-ltp");

    let ltp = strikeInfo ? (selectedType === "CE" ? strikeInfo.ce_ltp : strikeInfo.pe_ltp) : null;

    if (ltp == null || ltp <= 0) {
        const data = await fetch(`${API}/api/ltp?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}`)
            .then((r) => r.json())
            .catch(() => ({}));
        ltp = data.ltp;
    }

    if (ltp != null && ltp > 0) {
        ltpEl.textContent = `LTP: ₹${ltp.toFixed(2)}`;
        ltpEl.classList.remove("hidden");
        if (document.getElementById("order-type").value === "MARKET") {
            document.getElementById("entry-price").value = ltp.toFixed(2);
        }
    } else {
        ltpEl.textContent = "LTP unavailable";
        ltpEl.classList.remove("hidden");
    }
    updateSLPreview();
}

async function fetchSLReference() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;
    if (document.getElementById("sl-mode").value !== "candle") return;

    const resolution = document.getElementById("candle-resolution").value;
    const count = parseInt(document.getElementById("candle-count").value) || 5;
    const offset = parseFloat(document.getElementById("sl-offset").value) || 0;

    const data = await fetch(`${API}/api/sl-reference?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}&resolution=${resolution}&count=${count}&offset=${offset}`).then((r) => r.json()).catch(() => ({}));
    if (data.suggested_sl) {
        suggestedSL = data.suggested_sl;
        document.getElementById("last-low").textContent = `₹${(data.min_low || 0).toFixed(2)}`;
        document.getElementById("suggested-sl").textContent = `₹${data.suggested_sl.toFixed(2)}`;
        document.getElementById("candle-info").classList.remove("hidden");
    } else {
        suggestedSL = null;
        document.getElementById("candle-info").classList.add("hidden");
    }
    updateSLPreview();
}

function updateSLPreview() {
    const mode = document.getElementById("sl-mode").value;
    const fixed = parseFloat(document.getElementById("fixed-sl").value);
    const entry = parseFloat(document.getElementById("entry-price").value);
    let sl = null;
    if (mode === "fixed" && fixed > 0) sl = fixed;
    else if (mode === "candle" && suggestedSL > 0) sl = suggestedSL;
    else if (entry > 0) sl = entry - 5;
    document.getElementById("sl-price").textContent = sl ? `₹${sl.toFixed(2)}` : "--";
}

function changeLots(delta) {
    const el = document.getElementById("lots");
    el.value = Math.max(1, Math.min(50, (parseInt(el.value) || 1) + delta));
    updateQty();
}

function updateQty() {
    const lots = parseInt(document.getElementById("lots").value) || 1;
    const size = LOT_SIZE[selectedIndex] || 50;
    document.getElementById("qty-display").textContent = `= ${lots * size} qty`;
}

function validate() {
    const entry = parseFloat(document.getElementById("entry-price").value);
    const isValid = selectedIndex && selectedExpiry && selectedType && selectedStrike && entry > 0;
    document.getElementById("submit-btn").disabled = !isValid;
}

async function placeTrade() {
    const payload = {
        index: selectedIndex,
        option_type: selectedType,
        strike_price: selectedStrike,
        expiry: selectedExpiry,
        lots: parseInt(document.getElementById("lots").value),
        order_type: document.getElementById("order-type").value,
        entry_price: parseFloat(document.getElementById("entry-price").value),
        trigger_price: parseFloat(document.getElementById("trigger-price").value) || null,
        sl_mode: document.getElementById("sl-mode").value,
        fixed_sl: parseFloat(document.getElementById("fixed-sl").value) || null,
        sl_offset: parseFloat(document.getElementById("sl-offset").value) || 0,
        candle_resolution: document.getElementById("candle-resolution").value,
        candle_count: parseInt(document.getElementById("candle-count").value) || 5,
    };

    const data = await fetch(`${API}/api/trade`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    }).then((r) => r.json()).catch((e) => ({ success: false, error: e.message }));

    showStatus(data.success ? `✅ ${data.message}` : `❌ ${data.error}`, data.success ? "success" : "error");
    if (data.success) loadDashboard();
}

function openDashboardModal() { document.getElementById("dashboard-modal").classList.add("active"); }
function closeDashboardModal() { document.getElementById("dashboard-modal").classList.remove("active"); }

async function loadDashboard() {
    const data = await fetch(`${API}/api/dashboard`).then((r) => r.json()).catch(() => ({ trades: [], metrics: {} }));
    renderDashboard(data);
}

function renderDashboard(data) {
    const m = data.metrics || {};
    document.getElementById("metric-open").textContent = m.open_trades || 0;
    document.getElementById("metric-pnl").textContent = `₹${(m.total_pnl || 0).toFixed(2)}`;
    document.getElementById("metric-pos").textContent = m.total_positions || 0;
    document.getElementById("metric-retries").textContent = m.orders_with_retries || 0;
    document.getElementById("trades-body").innerHTML = (data.trades || []).map((t) => `<tr><td>${t.trade_id}</td><td>${t.symbol}</td><td>${t.order_type}</td><td>${t.quantity}</td><td>${(t.ltp || 0).toFixed(2)}</td><td>${(t.sl_price || 0).toFixed(2)}</td><td class="${(t.pnl || 0) >= 0 ? 'up' : 'down'}">${(t.pnl || 0).toFixed(2)}</td></tr>`).join("") || '<tr><td colspan="7">No open trades</td></tr>';
}

function startDashboardFeed() {
    const startFallbackPolling = () => {
        if (!dashboardPollTimer) dashboardPollTimer = setInterval(loadDashboard, 2500);
    };

    try {
        dashboardSocket = new WebSocket(API.replace("http", "ws") + "/ws/dashboard");
        dashboardSocket.onmessage = (e) => renderDashboard(JSON.parse(e.data));
        dashboardSocket.onerror = startFallbackPolling;
        dashboardSocket.onclose = startFallbackPolling;
    } catch {
        startFallbackPolling();
    }
}

function showStatus(msg, type) {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.className = `status ${type}`;
    el.classList.remove("hidden");
}
