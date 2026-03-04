const API = "http://127.0.0.1:8000";

let broker = "FYERS";
let selectedIndex = null;
let selectedExpiry = null;
let selectedType = null;
let selectedStrike = null;
let strikesData = [];
let tradingConfig = {};
let suggestedSL = null;

let LOT_SIZE = { NIFTY: 75, BANKNIFTY: 30, SENSEX: 20 };

document.addEventListener("DOMContentLoaded", init);

document.getElementById("entry-price")?.addEventListener("input", () => {
    updateSL();
    validate();
});

document.getElementById("manual-sl")?.addEventListener("input", () => {
    updateSL();
    validate();
});

async function init() {
    await loadConfig();

    try {
        const status = await fetch(`${API}/api/broker-status`).then(r => r.json());
        if (status.authenticated) {
            hideModal();
            showApp();
            loadProfile();
            loadIndexPrices();
            setInterval(loadIndexPrices, 5000);
        } else {
            showModal();
        }
    } catch (e) {
        showModal();
    }
}

async function loadConfig() {
    try {
        const data = await fetch(`${API}/api/config`).then(r => r.json());
        if (data.lot_sizes) {
            LOT_SIZE = data.lot_sizes;
            tradingConfig = data;
        }
    } catch (e) {}
}

function showModal() {
    document.getElementById("broker-modal").classList.add("active");
    document.getElementById("broker-modal").style.display = "flex";
    document.getElementById("app").classList.add("hidden");
}

function hideModal() {
    document.getElementById("broker-modal").classList.remove("active");
    document.getElementById("broker-modal").style.display = "none";
}

async function loginFyers() {
    const login = await fetch(`${API}/auth/login`).then(r => r.json());
    if (login.login_url) window.location.href = login.login_url;
}

function showApp() {
    document.getElementById("app").classList.remove("hidden");
    document.getElementById("app").style.display = "block";
    document.getElementById("broker-tag").textContent = broker;
    document.getElementById("index-cards").classList.remove("hidden");
}

async function loadProfile() {
    try {
        const data = await fetch(`${API}/auth/status`).then(r => r.json());
        if (data.authenticated) {
            document.getElementById("user-name").textContent = data.user_name || data.user_id || "Trader";
        }
    } catch (e) {}
}

async function logout() {
    await fetch(`${API}/auth/logout`, { method: "POST" });
    location.reload();
}

async function loadIndexPrices() {
    for (const index of ["NIFTY", "BANKNIFTY", "SENSEX"]) {
        try {
            const data = await fetch(`${API}/api/index-quote/${index}`).then(r => r.json());
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

async function selectIndex(index) {
    selectedIndex = index;
    selectedExpiry = null;
    selectedType = null;
    selectedStrike = null;
    strikesData = [];
    suggestedSL = null;

    document.querySelectorAll('.index-card').forEach(el => {
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
    document.getElementById("manual-sl").value = "";
    document.getElementById("sl-info").classList.add("hidden");
    document.getElementById("candle-info").classList.add("hidden");
    document.getElementById("strike-ltp").classList.add("hidden");
    validate();
}

async function loadExpiries(index) {
    const container = document.getElementById("expiry-btns");
    container.innerHTML = '<span style="color:var(--muted)">Loading...</span>';

    try {
        const data = await fetch(`${API}/api/expiries/${index}`).then(r => r.json());
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
    await loadStrikes();
}

async function loadStrikes() {
    if (!selectedIndex || !selectedExpiry) return;

    const select = document.getElementById("strike-select");
    select.innerHTML = '<option value="">Loading...</option>';

    try {
        const data = await fetch(`${API}/api/strikes/${selectedIndex}?expiry=${selectedExpiry}`).then(r => r.json());

        if (data.strikes?.length) {
            strikesData = data.strikes;
            let options = '<option value="">-- Select Strike --</option>';

            for (const item of strikesData) {
                let label = item.strike.toString();
                const parts = [];
                if (item.ce_ltp) parts.push(`CE:${item.ce_ltp.toFixed(1)}`);
                if (item.pe_ltp) parts.push(`PE:${item.pe_ltp.toFixed(1)}`);
                if (item.is_atm) label += " ★";
                if (parts.length) label += ` — ${parts.join(" | ")}`;
                options += `<option value="${item.strike}" ${item.is_atm ? 'class="atm-option"' : ''}>${label}</option>`;
            }

            select.innerHTML = options;

            const atmItem = strikesData.find(s => s.is_atm);
            if (atmItem) {
                select.value = atmItem.strike;
                selectedStrike = atmItem.strike;
                updateEntryPrice();
                await fetchSLReference();
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

    document.getElementById("btn-ce").classList.remove("selected", "ce");
    document.getElementById("btn-pe").classList.remove("selected", "pe");

    if (type === "CE") {
        document.getElementById("btn-ce").classList.add("selected", "ce");
    } else {
        document.getElementById("btn-pe").classList.add("selected", "pe");
    }

    if (selectedStrike) {
        updateEntryPrice();
        fetchSLReference();
    }

    validate();
}

async function onStrikeChange() {
    selectedStrike = parseInt(document.getElementById("strike-select").value) || null;

    if (selectedStrike) {
        updateEntryPrice();
        await fetchSLReference();
    } else {
        document.getElementById("strike-ltp").classList.add("hidden");
    }

    validate();
}

function updateEntryPrice() {
    if (!selectedStrike || !selectedType) return;

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
        fetchLTP();
    }
}

async function fetchLTP() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;

    const ltpBadge = document.getElementById("strike-ltp");
    ltpBadge.textContent = "Fetching...";
    ltpBadge.classList.remove("hidden");

    try {
        const data = await fetch(`${API}/api/ltp?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}`).then(r => r.json());
        if (data.ltp) {
            ltpBadge.textContent = `LTP: ₹${data.ltp.toFixed(2)}`;
            document.getElementById("entry-price").value = data.ltp.toFixed(2);
            updateSL();
        } else {
            ltpBadge.textContent = "LTP unavailable";
        }
    } catch (e) {
        ltpBadge.textContent = "Error";
    }

    validate();
}

async function fetchSLReference() {
    if (!selectedIndex || !selectedStrike || !selectedType || !selectedExpiry) return;

    try {
        const data = await fetch(`${API}/api/sl-reference?index=${selectedIndex}&strike=${selectedStrike}&option_type=${selectedType}&expiry=${selectedExpiry}`).then(r => r.json());
        const candleInfo = document.getElementById("candle-info");

        if (data.last_3_low || data.last_close) {
            suggestedSL = data.suggested_sl;
            document.getElementById("last-3-low").textContent = data.last_3_low ? `₹${data.last_3_low.toFixed(2)}` : "--";
            document.getElementById("last-close").textContent = data.last_close ? `₹${data.last_close.toFixed(2)}` : "--";
            document.getElementById("suggested-sl").textContent = data.suggested_sl ? `₹${data.suggested_sl.toFixed(2)}` : "--";
            candleInfo.classList.remove("hidden");
            updateSL();
        } else {
            suggestedSL = null;
            candleInfo.classList.add("hidden");
        }
    } catch (e) {
        suggestedSL = null;
    }
}

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

function updateSL() {
    const entry = parseFloat(document.getElementById("entry-price").value);
    const manualSL = parseFloat(document.getElementById("manual-sl").value);
    const slInfo = document.getElementById("sl-info");
    const slPoints = tradingConfig.sl_points || 5;

    let activeSL = null;
    let sourceText = "";

    if (manualSL > 0) {
        activeSL = manualSL;
        sourceText = "Manual SL";
    } else if (suggestedSL > 0) {
        activeSL = suggestedSL;
        sourceText = "3-candle SL";
    } else if (entry > 0) {
        activeSL = entry - slPoints;
        sourceText = `Entry - ${slPoints}`;
    }

    if (activeSL > 0) {
        document.getElementById("sl-price").textContent = `₹${activeSL.toFixed(2)}`;
        document.getElementById("sl-source").textContent = sourceText;
        slInfo.classList.remove("hidden");
    } else {
        slInfo.classList.add("hidden");
    }
}

function validate() {
    const price = parseFloat(document.getElementById("entry-price").value);
    const valid = selectedIndex && selectedExpiry && selectedType && selectedStrike && price > 0;
    document.getElementById("submit-btn").disabled = !valid;
}

async function placeTrade() {
    const btn = document.getElementById("submit-btn");
    btn.disabled = true;
    btn.textContent = "Placing...";

    const manualSL = parseFloat(document.getElementById("manual-sl").value);

    const payload = {
        index: selectedIndex,
        option_type: selectedType,
        strike_price: selectedStrike,
        expiry: selectedExpiry,
        entry_price: parseFloat(document.getElementById("entry-price").value),
        lots: parseInt(document.getElementById("lots").value),
        manual_sl: manualSL > 0 ? manualSL : null,
    };

    try {
        const data = await fetch(`${API}/api/trade`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        }).then(r => r.json());

        if (data.success) {
            showStatus(`✅ ${data.message} | Entry: ₹${data.entry_price.toFixed(2)} | SL: ₹${data.sl_price.toFixed(2)}`, "success");
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
