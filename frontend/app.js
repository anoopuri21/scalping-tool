const API = "http://127.0.0.1:8000";

// State
let broker = null;
let hasQuoteAPI = false;
let selectedIndex = null;
let selectedExpiry = null;
let selectedType = null;
let selectedStrike = null;
let strikesData = [];
let tradingConfig = {};

// Will be loaded from API
let LOT_SIZE = { NIFTY: 75, BANKNIFTY: 30, SENSEX: 20 };

// ============ INIT ============

document.addEventListener("DOMContentLoaded", init);

async function init() {
    console.log("🚀 Initializing...");
    
    // Load config from backend
    await loadConfig();
    
    try {
        const res = await fetch(`${API}/api/broker-status`);
        const status = await res.json();
        
        console.log("Status:", status);
        
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
            console.log("Config loaded:", data);
        }
    } catch (e) {
        console.error("Config load failed:", e);
    }
}

// ============ MODAL ============

function showModal() {
    document.getElementById("broker-modal").classList.add("active");
    document.getElementById("broker-modal").style.display = "flex";
    document.getElementById("app").classList.add("hidden");
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
    } else {
        document.getElementById("simple-index").classList.remove("hidden");
        document.getElementById("index-cards").classList.add("hidden");
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
    strikesData = [];
    
    document.querySelectorAll('.index-card').forEach(el => {
        el.classList.toggle('selected', el.dataset.index === index);
    });
    document.querySelectorAll('.btn-select[data-index]').forEach(el => {
        el.classList.toggle('selected', el.dataset.index === index);
    });
    
    document.getElementById("trade-form").classList.remove("hidden");
    document.getElementById("form-title").textContent = `${index} Trade`;
    
    resetForm();
    await loadExpiries(index);
    updateQty();
}

function resetForm() {
    document.getElementById("strike-select").innerHTML = '<option value="">Select Expiry First</option>';
    document.getElementById("btn-ce").classList.remove("selected", "ce");
    document.getElementById("btn-pe").classList.remove("selected", "pe");
    document.getElementById("entry-price").value = "";
    document.getElementById("sl-info").classList.add("hidden");
    document.getElementById("strike-ltp").classList.add("hidden");
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
    
    document.querySelectorAll('[data-expiry]').forEach(el => {
        el.classList.toggle('selected', el.dataset.expiry === expiry);
    });
    
    document.getElementById("strike-ltp").classList.add("hidden");
    document.getElementById("entry-price").value = "";
    
    await loadStrikes();
}

async function loadStrikes() {
    if (!selectedIndex || !selectedExpiry) return;
    
    const select = document.getElementById("strike-select");
    select.innerHTML = '<option value="">Loading...</option>';
    
    try {
        // Include option_type in request if selected
        let url = `${API}/api/strikes/${selectedIndex}?expiry=${selectedExpiry}`;
        
        const res = await fetch(url);
        const data = await res.json();
        
        console.log("Strikes:", data);
        
        if (data.strikes?.length) {
            strikesData = data.strikes;
            const hasLTP = data.has_ltp;
            
            let options = '<option value="">-- Select Strike --</option>';
            
            for (const item of strikesData) {
                const strike = item.strike;
                const isATM = item.is_atm;
                
                // Build label with LTP if available
                let label = strike.toString();
                let rightLabel = "";
                
                if (hasLTP && selectedType) {
                    const ltp = selectedType === "CE" ? item.ce_ltp : item.pe_ltp;
                    if (ltp) {
                        rightLabel = `₹${ltp.toFixed(1)}`;
                    }
                } else if (hasLTP) {
                    // Show both CE/PE prices if no type selected
                    const parts = [];
                    if (item.ce_ltp) parts.push(`CE:${item.ce_ltp.toFixed(0)}`);
                    if (item.pe_ltp) parts.push(`PE:${item.pe_ltp.toFixed(0)}`);
                    if (parts.length) rightLabel = parts.join(" | ");
                }
                
                if (isATM) label += " ★";
                if (rightLabel) label += ` — ${rightLabel}`;
                
                options += `<option value="${strike}" ${isATM ? 'class="atm-option"' : ''}>${label}</option>`;
            }
            
            select.innerHTML = options;
            
            // Auto-select ATM
            const atmItem = strikesData.find(s => s.is_atm);
            if (atmItem) {
                select.value = atmItem.strike;
                selectedStrike = atmItem.strike;
                updateEntryPrice();
            }
        } else {
            select.innerHTML = '<option value="">No strikes found</option>';
        }
    } catch (e) {
        console.error("Strikes error:", e);
        select.innerHTML = '<option value="">Error</option>';
    }
    
    validate();
}

function selectType(type) {
    selectedType = type;
    
    const ceBtn = document.getElementById("btn-ce");
    const peBtn = document.getElementById("btn-pe");
    
    ceBtn.classList.remove("selected", "ce");
    peBtn.classList.remove("selected", "pe");
    
    if (type === "CE") {
        ceBtn.classList.add("selected", "ce");
    } else {
        peBtn.classList.add("selected", "pe");
    }
    
    // Reload strikes to show correct LTP
    if (selectedExpiry) {
        loadStrikes();
    }
    
    // Update entry price if strike selected
    if (selectedStrike) {
        updateEntryPrice();
    }
    
    validate();
}

async function onStrikeChange() {
    const select = document.getElementById("strike-select");
    selectedStrike = parseInt(select.value) || null;
    
    if (selectedStrike) {
        updateEntryPrice();
    } else {
        document.getElementById("strike-ltp").classList.add("hidden");
    }
    
    validate();
}

function updateEntryPrice() {
    if (!selectedStrike || !selectedType) return;
    
    // Find strike data
    const strikeInfo = strikesData.find(s => s.strike === selectedStrike);
    if (!strikeInfo) return;
    
    const ltp = selectedType === "CE" ? strikeInfo.ce_ltp : strikeInfo.pe_ltp;
    
    const ltpBadge = document.getElementById("strike-ltp");
    
    if (ltp) {
        ltpBadge.textContent = `LTP: ₹${ltp.toFixed(2)}`;
        ltpBadge.classList.remove("hidden");
        document.getElementById("entry-price").value = ltp.toFixed(2);
        updateSL();
    } else {
        ltpBadge.textContent = "Enter price manually";
        ltpBadge.classList.remove("hidden");
    }
}

async function fetchLTP() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;
    
    const ltpBadge = document.getElementById("strike-ltp");
    ltpBadge.textContent = "Fetching...";
    ltpBadge.classList.remove("hidden");
    
    try {
        const url = `${API}/api/ltp?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}`;
        const res = await fetch(url);
        const data = await res.json();
        
        if (data.ltp) {
            ltpBadge.textContent = `LTP: ₹${data.ltp.toFixed(2)}`;
            document.getElementById("entry-price").value = data.ltp.toFixed(2);
            updateSL();
        } else {
            ltpBadge.textContent = "Enter manually";
        }
    } catch (e) {
        ltpBadge.textContent = "Error";
    }
    
    validate();
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

document.getElementById("entry-price")?.addEventListener("input", () => {
    updateSL();
    validate();
});

function updateSL() {
    const price = parseFloat(document.getElementById("entry-price").value);
    const slInfo = document.getElementById("sl-info");
    const slPoints = tradingConfig.sl_points || 5;
    
    if (price > 0) {
        document.getElementById("sl-price").textContent = `₹${(price - slPoints).toFixed(2)}`;
        slInfo.classList.remove("hidden");
    } else {
        slInfo.classList.add("hidden");
    }
}

// ============ VALIDATE ============

function validate() {
    const price = parseFloat(document.getElementById("entry-price").value);
    const valid = selectedIndex && selectedExpiry && selectedType && selectedStrike && price > 0;
    document.getElementById("submit-btn").disabled = !valid;
}

// ============ TRADE ============

async function placeTrade() {
    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "Placing...";
    
    const payload = {
        index: selectedIndex,
        option_type: selectedType,
        strike_price: selectedStrike,
        expiry: selectedExpiry,
        entry_price: parseFloat(document.getElementById("entry-price").value),
        lots: parseInt(document.getElementById("lots").value),
    };
    
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