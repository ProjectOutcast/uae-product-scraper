let currentJobId = null;
let eventSource = null;
let elapsedTimer = null;
let startTime = null;
let selectedRetailers = [];
let retailerStates = {};   // name -> 'pending' | 'active' | 'done' | 'failed'
let totalProducts = 0;
let completedRetailers = 0;

document.addEventListener('DOMContentLoaded', () => {
    loadRetailers();
    document.getElementById('selectAll').addEventListener('click', () => toggleAll(true));
    document.getElementById('deselectAll').addEventListener('click', () => toggleAll(false));
});

async function loadRetailers() {
    try {
        const res = await fetch('/api/retailers');
        const data = await res.json();
        const grid = document.getElementById('retailerGrid');
        grid.innerHTML = '';

        data.retailers.forEach(name => {
            const item = document.createElement('div');
            item.className = 'retailer-item checked';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.checked = true;
            cb.id = `cb-${name.replace(/[^a-zA-Z0-9]/g, '')}`;
            cb.value = name;
            cb.addEventListener('change', () => {
                item.classList.toggle('checked', cb.checked);
            });

            const label = document.createElement('label');
            label.textContent = name;
            label.htmlFor = cb.id;

            item.addEventListener('click', (e) => {
                if (e.target !== cb) {
                    cb.checked = !cb.checked;
                    cb.dispatchEvent(new Event('change'));
                }
            });

            item.appendChild(cb);
            item.appendChild(label);
            grid.appendChild(item);
        });
    } catch (e) {
        console.error('Failed to load retailers:', e);
    }
}

function toggleAll(checked) {
    document.querySelectorAll('.retailer-item input[type="checkbox"]').forEach(cb => {
        cb.checked = checked;
        cb.closest('.retailer-item').classList.toggle('checked', checked);
    });
}

function getSelectedRetailers() {
    return Array.from(
        document.querySelectorAll('.retailer-item input[type="checkbox"]:checked')
    ).map(cb => cb.value);
}

async function startScraping() {
    const keyword = document.getElementById('keyword').value.trim();
    selectedRetailers = getSelectedRetailers();

    if (!keyword) { alert('Please enter a keyword.'); return; }
    if (selectedRetailers.length === 0) { alert('Please select at least one retailer.'); return; }

    const btn = document.getElementById('startBtn');
    btn.disabled = true;
    btn.textContent = 'Scraping...';

    // Reset state
    totalProducts = 0;
    completedRetailers = 0;
    retailerStates = {};
    selectedRetailers.forEach(name => { retailerStates[name] = 'pending'; });

    // Show progress section
    const progressSection = document.getElementById('progressSection');
    progressSection.classList.add('active');
    document.getElementById('logContainer').innerHTML = '';
    document.getElementById('logContainer').classList.remove('open');
    document.getElementById('logToggle').classList.remove('open');
    document.getElementById('progressBar').style.width = '0%';
    document.getElementById('progressPct').textContent = '0%';
    document.getElementById('downloadSection').classList.remove('active');

    // Init dashboard
    document.getElementById('statProducts').textContent = '0';
    document.getElementById('statRetailers').textContent = `0 / ${selectedRetailers.length}`;
    document.getElementById('statElapsed').textContent = '0:00';

    // Init current action
    const actionEl = document.getElementById('currentAction');
    actionEl.classList.remove('done');
    document.getElementById('actionText').textContent = 'Initializing...';

    // Build retailer tracker chips
    buildTrackerChips();

    // Start elapsed timer
    startTime = Date.now();
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = setInterval(updateElapsed, 1000);

    // Scroll to progress
    progressSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    try {
        const res = await fetch('/api/product-scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword, retailers: selectedRetailers }),
        });
        const data = await res.json();

        if (data.error) {
            addLog(data.error, 'fail');
            setActionText(data.error, true);
            resetBtn();
            return;
        }

        currentJobId = data.job_id;
        connectSSE(data.job_id);
    } catch (e) {
        addLog('Failed to start scraping: ' + e.message, 'fail');
        setActionText('Failed to connect', true);
        resetBtn();
    }
}

function buildTrackerChips() {
    const grid = document.getElementById('trackerGrid');
    grid.innerHTML = '';
    selectedRetailers.forEach(name => {
        const chip = document.createElement('span');
        chip.className = 'tracker-chip';
        chip.textContent = name;
        chip.id = `tracker-${name.replace(/[^a-zA-Z0-9]/g, '')}`;
        grid.appendChild(chip);
    });
}

function updateTrackerChip(name, state) {
    const chipId = `tracker-${name.replace(/[^a-zA-Z0-9]/g, '')}`;
    const chip = document.getElementById(chipId);
    if (!chip) return;
    chip.className = 'tracker-chip';
    if (state === 'active') chip.classList.add('active');
    else if (state === 'done') chip.classList.add('done');
    else if (state === 'failed') chip.classList.add('failed');
}

function updateElapsed() {
    if (!startTime) return;
    const secs = Math.floor((Date.now() - startTime) / 1000);
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    document.getElementById('statElapsed').textContent = `${m}:${s.toString().padStart(2, '0')}`;
}

function setActionText(text, isDone) {
    const actionEl = document.getElementById('currentAction');
    document.getElementById('actionText').textContent = text;
    if (isDone) {
        actionEl.classList.add('done');
    } else {
        actionEl.classList.remove('done');
    }
}

function resetBtn() {
    const btn = document.getElementById('startBtn');
    btn.disabled = false;
    btn.textContent = 'Start Scraping';
    if (elapsedTimer) clearInterval(elapsedTimer);
}

function connectSSE(jobId) {
    if (eventSource) eventSource.close();

    eventSource = new EventSource(`/api/progress/${jobId}`);

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
            case 'log':
                handleLogMessage(data.message);
                break;

            case 'progress':
                const pct = data.percent;
                document.getElementById('progressBar').style.width = pct + '%';
                document.getElementById('progressPct').textContent = pct + '%';
                break;

            case 'completed':
                eventSource.close();
                document.getElementById('progressBar').style.width = '100%';
                document.getElementById('progressPct').textContent = '100%';

                if (data.has_file || (data.summary && data.summary.total > 0)) {
                    const dl = document.getElementById('downloadSection');
                    dl.classList.add('active');
                    document.getElementById('downloadBtn').href = `/api/download/${jobId}?format=csv`;
                    document.getElementById('downloadSummary').textContent =
                        `${data.summary.total} products scraped`;
                    totalProducts = data.summary.total;
                    document.getElementById('statProducts').textContent = totalProducts;
                }

                setActionText('Scraping complete!', true);
                resetBtn();
                break;

            case 'error':
                eventSource.close();
                addLog('Error: ' + data.message, 'fail');
                setActionText('Error: ' + data.message, true);
                resetBtn();
                break;
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
    };
}

function handleLogMessage(message) {
    // Determine log class
    let cls = 'info';
    if (message.includes('[OK]')) cls = 'ok';
    else if (message.includes('[FAIL]') || message.includes('Error')) cls = 'fail';
    else if (message.startsWith('DONE')) cls = 'ok';
    else if (message.startsWith('  ')) cls = 'detail';

    addLog(message, cls);

    // Parse message to update dashboard

    // "Scraping: Le Bouquet (1/22)" → mark retailer active
    const scrapingMatch = message.match(/^Scraping: (.+?) \((\d+)\/(\d+)\)/);
    if (scrapingMatch) {
        const name = scrapingMatch[1];
        // Mark previous active as done (if any still active and not this one)
        for (const [n, s] of Object.entries(retailerStates)) {
            if (s === 'active' && n !== name) {
                // It was already handled by [OK]/[FAIL]
            }
        }
        retailerStates[name] = 'active';
        updateTrackerChip(name, 'active');
        setActionText(`Scraping ${name}...`, false);
        return;
    }

    // "[OK] Le Bouquet: 38 products scraped (total so far: 38)" → mark done
    const okMatch = message.match(/\[OK\] (.+?): (\d+) products scraped \(total so far: (\d+)\)/);
    if (okMatch) {
        const name = okMatch[1];
        totalProducts = parseInt(okMatch[3]);
        retailerStates[name] = 'done';
        completedRetailers++;
        updateTrackerChip(name, 'done');
        document.getElementById('statProducts').textContent = totalProducts;
        document.getElementById('statRetailers').textContent = `${completedRetailers} / ${selectedRetailers.length}`;
        setActionText(`${name} done — ${okMatch[2]} products found`, false);
        return;
    }

    // Also handle older format without "total so far"
    const okMatchSimple = message.match(/\[OK\] (.+?): (\d+) products scraped/);
    if (okMatchSimple && !okMatch) {
        const name = okMatchSimple[1];
        totalProducts += parseInt(okMatchSimple[2]);
        retailerStates[name] = 'done';
        completedRetailers++;
        updateTrackerChip(name, 'done');
        document.getElementById('statProducts').textContent = totalProducts;
        document.getElementById('statRetailers').textContent = `${completedRetailers} / ${selectedRetailers.length}`;
        setActionText(`${name} done — ${okMatchSimple[2]} products found`, false);
        return;
    }

    // "[FAIL] Mumzworld: timeout" → mark failed
    const failMatch = message.match(/\[FAIL\] (.+?):/);
    if (failMatch) {
        const name = failMatch[1];
        retailerStates[name] = 'failed';
        completedRetailers++;
        updateTrackerChip(name, 'failed');
        document.getElementById('statRetailers').textContent = `${completedRetailers} / ${selectedRetailers.length}`;
        setActionText(`${name} failed`, false);
        return;
    }

    // "  [Le Bouquet] Product 5/38 — 4 scraped" → update action text with per-product progress
    const productMatch = message.match(/\[(.+?)\] Product (\d+)\/(\d+)/);
    if (productMatch) {
        setActionText(`${productMatch[1]}: product ${productMatch[2]} of ${productMatch[3]}`, false);
        return;
    }

    // "  Found 38 product URLs on Le Bouquet" → update action
    const foundMatch = message.match(/Found (\d+) product URLs on (.+)/);
    if (foundMatch) {
        setActionText(`Found ${foundMatch[1]} products on ${foundMatch[2]} — scraping...`, false);
        return;
    }

    // "  Collecting product URLs from X..." → update action
    const collectMatch = message.match(/Collecting product URLs from (.+)/);
    if (collectMatch) {
        setActionText(`Searching ${collectMatch[1]} for products...`, false);
        return;
    }

    // "  Launching browser for X..." → update action
    const launchMatch = message.match(/Launching browser for (.+)/);
    if (launchMatch) {
        setActionText(`Launching browser for ${launchMatch[1]}...`, false);
        return;
    }

    // "DONE — 156 products from 20/22 retailers" → final
    if (message.startsWith('DONE')) {
        setActionText(message, true);
        return;
    }

    // Generic: update action text for non-detail messages
    if (!message.startsWith('  ') && message.length > 5) {
        setActionText(message, false);
    }
}

function toggleLog() {
    const toggle = document.getElementById('logToggle');
    const container = document.getElementById('logContainer');
    toggle.classList.toggle('open');
    container.classList.toggle('open');
}

function addLog(message, cls = '') {
    const container = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = 'log-entry' + (cls ? ' ' + cls : '');
    entry.textContent = message;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}
