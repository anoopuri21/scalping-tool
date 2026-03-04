const API = "http://127.0.0.1:8000";

// State
let broker = null;
let hasQuoteAPI = false;
let selectedIndex = null;
let selectedExpiry = null;
let selectedType = null;
let selectedStrike = null;
let entryMode = 'manual';  // Default: Manual
let priceUpdateInterval = null;
let candleUpdateInterval = null;
let currentCandleTimeframe = '5min';
let candleData = {};
let tradingConfig = {};

let LOT_SIZE = { NIFTY: 75, BANKNIFTY: 30, SENSEX: 20 };
let DEFAULT_SL = 5;

// ============ INIT ============

document.addEventListener("DOMContentLoaded", init);

async function init() {
    console.log("🚀 Initializing...");
    
    await loadConfig();
    
    // Set default SL
    document.getElementById("sl-points").value = DEFAULT_SL;
    
    // Add SL change listener
    document.getElementById("sl-points").addEventListener("input", updateSL);
    document.getElementById("entry-price").addEventListener("input", () => {
        updateSL();
        validate();
    });
    
    try {
        const res = await fetch(`${API}/api/broker-status`);
        const status = await res.json();
        
        if (status.broker && status.authenticated) {
            broker = status.broker;
            hasQuoteAPI = status.has_quote_api;
            hideModal();
            showApp();
            loadProfile();
            
            if (hasQuoteAPI) {
                loadIndexPrices();
                setInterval(loadIndexPrices, 5000);
            }
        } else {
            showModal();
        }
    } catch (e) {
        console.error("Init error:", e);
        showModal();
    }
}

async function loadConfig() {
    try {
        const res = await fetch(`${API}/api/config`);
        const data = await res.json();
        
        if (data.lot_sizes) {
            LOT_SIZE = data.lot_sizes;
            tradingConfig = data;
            DEFAULT_SL = data.default_sl_points || 5;
            console.log("✅ Config:", data);
        }
    } catch (e) {
        console.error("Config error:", e);
    }
}

// ============ MODAL ============

function showModal() {
    document.getElementById("broker-modal").classList.add("active");
    document.getElementById("broker-modal").style.display = "flex";
}

function hideModal() {
    document.getElementById("broker-modal").classList.remove("active");
    document.getElementById("broker-modal").style.display = "none";
}

// ============ BROKER ============

async function selectBroker(name) {
    console.log("Selecting:", name);
    
    try {
        const res = await fetch(`${API}/api/select-broker`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ broker_name: name })
        });
        
        const data = await res.json();
        
        if (data.success) {
            broker = data.broker;
            hasQuoteAPI = data.has_quote_api;
            
            if (data.authenticated) {
                hideModal();
                showApp();
                loadProfile();
                if (hasQuoteAPI) loadIndexPrices();
            } else {
                const login = await fetch(`${API}/auth/login`).then(r => r.json());
                if (login.login_url) window.location.href = login.login_url;
            }
        } else {
            alert("Error: " + data.error);
        }
    } catch (e) {
        alert("Error: " + e.message);
    }
}

function showApp() {
    document.getElementById("app").classList.remove("hidden");
    document.getElementById("app").style.display = "block";
    document.getElementById("broker-tag").textContent = broker;
    
    if (hasQuoteAPI) {
        document.getElementById("index-cards").classList.remove("hidden");
        document.getElementById("simple-index").classList.add("hidden");
        document.getElementById("entry-mode-section").classList.remove("hidden");
        document.getElementById("candle-panel").classList.remove("hidden");
        
        // Default: Manual mode selected
        selectEntryMode('manual');
    } else {
        document.getElementById("simple-index").classList.remove("hidden");
        document.getElementById("index-cards").classList.add("hidden");
        document.getElementById("entry-mode-section").classList.add("hidden");
        document.getElementById("candle-panel").classList.add("hidden");
        entryMode = 'manual';
    }
}

async function loadProfile() {
    try {
        const res = await fetch(`${API}/auth/status`);
        const data = await res.json();
        if (data.authenticated) {
            document.getElementById("user-name").textContent = data.user_name || data.user_id || "User";
        }
    } catch (e) {}
}

async function logout() {
    if (!confirm("Logout?")) return;
    stopAllUpdates();
    await fetch(`${API}/auth/logout`, { method: "POST" });
    location.reload();
}

// ============ INDEX PRICES ============

async function loadIndexPrices() {
    if (!hasQuoteAPI) return;
    
    for (const index of ["NIFTY", "BANKNIFTY", "SENSEX"]) {
        try {
            const res = await fetch(`${API}/api/index-quote/${index}`);
            const data = await res.json();
            
            if (data.price) {
                document.getElementById(`${index.toLowerCase()}-price`).textContent = 
                    data.price.toLocaleString('en-IN', { maximumFractionDigits: 2 });
                
                const changeEl = document.getElementById(`${index.toLowerCase()}-change`);
                if (changeEl) {
                    const sign = data.change >= 0 ? "+" : "";
                    changeEl.textContent = `${sign}${data.change.toFixed(2)} (${sign}${data.change_percent.toFixed(2)}%)`;
                    changeEl.className = `index-change ${data.change >= 0 ? 'up' : 'down'}`;
                }
            }
        } catch (e) {}
    }
}

// ============ INDEX SELECT ============

async function selectIndex(index) {
    selectedIndex = index;
    selectedExpiry = null;
    selectedType = null;
    selectedStrike = null;
    
    stopAllUpdates();
    
    document.querySelectorAll('.index-card').forEach(el => {
        el.classList.toggle('selected', el.dataset.index === index);
    });
    document.querySelectorAll('.btn-select[data-index]').forEach(el => {
        el.classList.toggle('selected', el.dataset.index === index);
    });
    
    document.getElementById("trade-form").classList.remove("hidden");
    document.getElementById("form-title").textContent = `${index} Trade`;
    
    // Update candle panel title
    document.getElementById("candle-index").textContent = `(${index})`;
    
    resetForm();
    await loadExpiries(index);
    updateQty();
    
    // Load candle data if a complete option is already selected
    if (hasQuoteAPI && selectedStrike && selectedType && selectedExpiry) {
        loadCandleData();
        startCandleUpdates();
    }
}

function resetForm() {
    document.getElementById("strike-select").innerHTML = '<option value="">Select Expiry First</option>';
    document.getElementById("btn-ce").classList.remove("selected", "ce");
    document.getElementById("btn-pe").classList.remove("selected", "pe");
    document.getElementById("entry-price").value = "";
    document.getElementById("sl-info").classList.add("hidden");
    document.getElementById("price-info").textContent = "";
    document.getElementById("refresh-price-btn").classList.add("hidden");
    validate();
}

async function loadExpiries(index) {
    const container = document.getElementById("expiry-btns");
    container.innerHTML = '<span style="color:var(--muted)">Loading...</span>';
    
    try {
        const res = await fetch(`${API}/api/expiries/${index}`);
        const data = await res.json();
        
        if (data.expiries?.length) {
            container.innerHTML = data.expiries.slice(0, 4).map(exp => {
                const d = new Date(exp);
                const label = `${d.getDate()} ${d.toLocaleString('en', { month: 'short' })}`;
                return `<button class="btn-select" data-expiry="${exp}" onclick="selectExpiry('${exp}')">${label}</button>`;
            }).join('');
        } else {
            container.innerHTML = '<span style="color:var(--red)">No expiries</span>';
        }
    } catch (e) {
        container.innerHTML = '<span style="color:var(--red)">Error</span>';
    }
}

async function selectExpiry(expiry) {
    selectedExpiry = expiry;
    selectedStrike = null;
    
    stopPriceUpdates();
    
    document.querySelectorAll('[data-expiry]').forEach(el => {
        el.classList.toggle('selected', el.dataset.expiry === expiry);
    });
    
    document.getElementById("entry-price").value = "";
    document.getElementById("price-info").textContent = "";
    
    await loadStrikes();

    // expiry changed, previous strike/candle data is gone
    if (selectedStrike && selectedType && selectedExpiry) {
        loadCandleData();
        startCandleUpdates();
    } else {
        clearCandleDisplay();
        stopCandleUpdates();
    }
}

async function loadStrikes() {
    if (!selectedIndex || !selectedExpiry) return;
    
    const select = document.getElementById("strike-select");
    select.innerHTML = '<option value="">Loading...</option>';
    
    try {
        const res = await fetch(`${API}/api/strikes/${selectedIndex}?expiry=${selectedExpiry}`);
        const data = await res.json();
        
        if (data.strikes?.length) {
            let options = '<option value="">-- Select Strike --</option>';
            
            for (const strike of data.strikes) {
                const isATM = strike === data.atm;
                const label = isATM ? `${strike} ★ ATM` : strike.toString();
                options += `<option value="${strike}">${label}</option>`;
            }
            
            select.innerHTML = options;
            
            // Auto-select ATM
            if (data.atm) {
                select.value = data.atm;
                selectedStrike = data.atm;
                onStrikeChange();
            }
        } else {
            select.innerHTML = '<option value="">No strikes found</option>';
        }
    } catch (e) {
        select.innerHTML = '<option value="">Error</option>';
    }
    
    validate();
}

function selectType(type) {
    selectedType = type;
    
    stopPriceUpdates();
    
    const ceBtn = document.getElementById("btn-ce");
    const peBtn = document.getElementById("btn-pe");
    
    ceBtn.classList.remove("selected", "ce");
    peBtn.classList.remove("selected", "pe");
    
    if (type === "CE") {
        ceBtn.classList.add("selected", "ce");
    } else {
        peBtn.classList.add("selected", "pe");
    }
    
    if (selectedStrike && hasQuoteAPI && entryMode === 'market') {
        fetchLTP();
        startPriceUpdates();
    }
    // candles only make sense when a full option is chosen
    if (selectedStrike && selectedType && selectedExpiry) {
        loadCandleData();
        startCandleUpdates();
    } else {
        clearCandleDisplay();
        stopCandleUpdates();
    }
    
    validate();
}

async function onStrikeChange() {
    const select = document.getElementById("strike-select");
    selectedStrike = parseInt(select.value) || null;
    
    stopPriceUpdates();
    
    if (selectedStrike && selectedType && hasQuoteAPI && entryMode === 'market') {
        await fetchLTP();
        startPriceUpdates();
    } else {
        document.getElementById("price-info").textContent = "";
    }

    if (selectedStrike && selectedType && selectedExpiry) {
        loadCandleData();
        startCandleUpdates();
    } else {
        clearCandleDisplay();
        stopCandleUpdates();
    }
    
    validate();
}

// ============ ENTRY MODE ============

function selectEntryMode(mode) {
    entryMode = mode;
    
    const marketBtn = document.getElementById("btn-market");
    const manualBtn = document.getElementById("btn-manual");
    const entryInput = document.getElementById("entry-price");
    const refreshBtn = document.getElementById("refresh-price-btn");
    
    manualBtn.classList.toggle("selected", mode === 'manual');
    marketBtn.classList.toggle("selected", mode === 'market');
    
    if (mode === 'market') {
        entryInput.placeholder = "Auto-updated";
        entryInput.readOnly = true;
        refreshBtn.classList.remove("hidden");
        
        if (selectedStrike && selectedType) {
            fetchLTP();
            startPriceUpdates();
        }
    } else {
        entryInput.placeholder = "Enter price";
        entryInput.readOnly = false;
        refreshBtn.classList.add("hidden");
        stopPriceUpdates();
    }
}

// ============ PRICE FETCHING ============

async function fetchLTP() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;
    
    const priceInfo = document.getElementById("price-info");
    priceInfo.textContent = "Fetching...";
    priceInfo.style.color = "var(--muted)";
    
    try {
        const url = `${API}/api/ltp?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}`;
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.ltp !== null && data.ltp !== undefined) {
            const entryInput = document.getElementById("entry-price");
            
            if (entryMode === 'market') {
                entryInput.value = data.ltp.toFixed(2);
            }
            
            const now = new Date().toLocaleTimeString();
            priceInfo.textContent = `₹${data.ltp.toFixed(2)} at ${now}`;
            priceInfo.style.color = "var(--green)";
            
            updateSL();
        } else {
            priceInfo.textContent = data.message || "LTP not available";
            priceInfo.style.color = "var(--red)";
        }
    } catch (e) {
        priceInfo.textContent = "Error";
        priceInfo.style.color = "var(--red)";
    }
    
    validate();
}

async function refreshPrice() {
    await fetchLTP();
}

function startPriceUpdates() {
    if (!hasQuoteAPI || entryMode !== 'market') return;
    
    stopPriceUpdates();
    
    priceUpdateInterval = setInterval(() => {
        if (selectedStrike && selectedType) {
            fetchLTP();
        }
    }, 3000);
}

function stopPriceUpdates() {
    if (priceUpdateInterval) {
        clearInterval(priceUpdateInterval);
        priceUpdateInterval = null;
    }
}

function stopAllUpdates() {
    stopPriceUpdates();
    stopCandleUpdates();
}

// ============ CANDLE DATA ============

function selectCandleTab(timeframe) {
    currentCandleTimeframe = timeframe;
    
    document.querySelectorAll('.candle-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.tf === timeframe.replace('min', '').replace('hr', '60'));
    });
    
    loadCandleData();
}

async function loadCandleData() {
    // only pull candles when we have a fully‑specified option (strike, type,
    // expiry) – otherwise there is nothing meaningful to show.
    if (!selectedIndex || !hasQuoteAPI || !selectedStrike || !selectedType || !selectedExpiry) {
        clearCandleDisplay();
        return;
    }
    
    const tfMinutes = {
        '5min': 5,
        '15min': 15,
        '30min': 30,
        '1hr': 60
    };
    
    const minutes = tfMinutes[currentCandleTimeframe] || 5;
    
    try {
        const url = new URL(`${API}/api/candles/${selectedIndex}`);
        url.searchParams.set('timeframe', minutes);
        url.searchParams.set('strike', selectedStrike);
        url.searchParams.set('option_type', selectedType);
        url.searchParams.set('expiry', selectedExpiry);
        const res = await fetch(url.toString());
        const data = await res.json();
        
        if (data.candle) {
            candleData = data.candle;
            updateCandleDisplay();
        } else {
            clearCandleDisplay();
        }
    } catch (e) {
        console.error("Candle error:", e);
        clearCandleDisplay();
    }
}

function updateCandleDisplay() {
    document.getElementById("candle-close").textContent = candleData.close?.toFixed(2) || '--';
    document.getElementById("candle-low").textContent = candleData.low?.toFixed(2) || '--';
    document.getElementById("candle-high").textContent = candleData.high?.toFixed(2) || '--';
    document.getElementById("candle-open").textContent = candleData.open?.toFixed(2) || '--';
    
    if (candleData.timestamp) {
        const time = new Date(candleData.timestamp * 1000).toLocaleTimeString();
        document.getElementById("candle-time").textContent = `Candle time: ${time}`;
    }
}

function clearCandleDisplay() {
    document.getElementById("candle-close").textContent = '--';
    document.getElementById("candle-low").textContent = '--';
    document.getElementById("candle-high").textContent = '--';
    document.getElementById("candle-open").textContent = '--';
    document.getElementById("candle-time").textContent = 'No data';
}

function startCandleUpdates() {
    stopCandleUpdates();
    
    candleUpdateInterval = setInterval(() => {
        if (selectedIndex && selectedStrike && selectedType && selectedExpiry) {
            loadCandleData();
        }
    }, 10000); // Update every 10 seconds
}

function stopCandleUpdates() {
    if (candleUpdateInterval) {
        clearInterval(candleUpdateInterval);
        candleUpdateInterval = null;
    }
}

function useClosePrice() {
    // set stop‑loss based on last candle close rather than overwrite entry
    if (candleData.close) {
        const entry = parseFloat(document.getElementById("entry-price").value) || 0;
        const slPrice = candleData.close;
        const slPoints = entry > 0 ? entry - slPrice : DEFAULT_SL;
        document.getElementById("sl-points").value = slPoints.toFixed(2);
        updateSL();
        validate();
    }
}

function useLowPrice() {
    // set stop‑loss based on last candle low
    if (candleData.low) {
        const entry = parseFloat(document.getElementById("entry-price").value) || 0;
        const slPrice = candleData.low;
        const slPoints = entry > 0 ? entry - slPrice : DEFAULT_SL;
        document.getElementById("sl-points").value = slPoints.toFixed(2);
        updateSL();
        validate();
    }
}

// ============ LOTS ============

function changeLots(delta) {
    const input = document.getElementById("lots");
    let lots = parseInt(input.value) || 1;
    lots = Math.max(1, Math.min(50, lots + delta));
    input.value = lots;
    updateQty();
}

function updateQty() {
    const lots = parseInt(document.getElementById("lots").value) || 1;
    const size = LOT_SIZE[selectedIndex] || 50;
    document.getElementById("qty-display").textContent = `= ${lots * size} qty`;
}

// ============ SL ============

function updateSL() {
    const price = parseFloat(document.getElementById("entry-price").value);
    const slPoints = parseFloat(document.getElementById("sl-points").value) || DEFAULT_SL;
    const slInfo = document.getElementById("sl-info");
    
    if (price > 0) {
        const slPrice = price - slPoints;
        document.getElementById("sl-price").textContent = `₹${slPrice.toFixed(2)} (Entry - ${slPoints} pts)`;
        slInfo.classList.remove("hidden");
    } else {
        slInfo.classList.add("hidden");
    }
}

// ============ VALIDATE ============

function validate() {
    const price = parseFloat(document.getElementById("entry-price").value);
    const slPoints = parseFloat(document.getElementById("sl-points").value);
    const valid = selectedIndex && selectedExpiry && selectedType && selectedStrike && price > 0 && slPoints > 0;
    document.getElementById("submit-btn").disabled = !valid;
}

// ============ TRADE ============

async function placeTrade() {
    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "Placing...";
    
    stopPriceUpdates();
    
    const payload = {
        index: selectedIndex,
        option_type: selectedType,
        strike_price: selectedStrike,
        expiry: selectedExpiry,
        entry_price: parseFloat(document.getElementById("entry-price").value),
        lots: parseInt(document.getElementById("lots").value),
        sl_points: parseFloat(document.getElementById("sl-points").value),
    };
    
    console.log("Trade:", payload);
    
    try {
        const res = await fetch(`${API}/api/trade`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        
        const data = await res.json();
        
        if (data.success) {
            showStatus(`✅ ${data.message} | SL: ₹${data.sl_price}`, "success");
            resetForm();
        } else {
            showStatus(`❌ ${data.error}`, "error");
        }
    } catch (e) {
        showStatus(`❌ ${e.message}`, "error");
    }
    
    btn.disabled = false;
    btn.textContent = "🚀 Place Trade";
    validate();
}

function showStatus(msg, type) {
    const el = document.getElementById("status");
    el.textContent = msg;
    el.className = `status ${type}`;
    el.classList.remove("hidden");
    
    if (type) setTimeout(() => el.classList.add("hidden"), 5000);
}

// Cleanup
window.addEventListener('beforeunload', stopAllUpdates);