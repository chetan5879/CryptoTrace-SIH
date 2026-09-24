/* =========================================================
   CRYPTOTRACE — GLOBAL STATE
========================================================= */
let currentTraceData = null; // Holds the latest trace result for the PDF generator

/* =========================================================
   BLOCKCHAIN + AI BACKGROUND
========================================================= */
function createAIBackground() {
    if (document.querySelector(".ai-background")) return;

    const background = document.createElement("div");
    background.className = "ai-background";
    background.innerHTML = `
        <div class="ai-grid"></div>
        <div class="ai-glow one"></div>
        <div class="ai-glow two"></div>
    `;
    document.body.prepend(background);
}

/* =========================================================
   PAGE NAVIGATION
========================================================= */
function showPage(pageId, clickedButton) {
    const pages = document.querySelectorAll(".page");
    pages.forEach(page => page.classList.remove("active-page"));

    const selectedPage = document.getElementById(pageId);
    if (selectedPage) {
        selectedPage.classList.add("active-page");
    }

    const menuItems = document.querySelectorAll(".menu-item");
    menuItems.forEach(item => item.classList.remove("active"));

    if (clickedButton) {
        clickedButton.classList.add("active");
    }

    const sidebar = document.getElementById("sidebar");
    if (sidebar) {
        sidebar.classList.remove("open");
    }
}

/* =========================================================
   MOBILE SIDEBAR
========================================================= */
function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    if (sidebar) {
        sidebar.classList.toggle("open");
    }
}

/* =========================================================
   FORM ACTIONS & SHORTCUTS
========================================================= */

// 1. Dashboard "New Investigation" Button (Switches tab & focuses)
function openInvestigation() {
    const menuItems = document.querySelectorAll(".menu-item");
    showPage("investigations", menuItems[1]);

    setTimeout(() => {
        const walletInput = document.getElementById("walletInput");
        if (walletInput) {
            walletInput.focus();
            walletInput.scrollIntoView({ behavior: "smooth", block: "center" });
        }
    }, 100);
}

// 2. Trace Engine "Reset Form" Button
function resetInvestigationForm() {
    // 1. Force clear the target wallet address input
    const walletInput = document.getElementById("walletInput");
    if (walletInput) {
        walletInput.value = "";
        walletInput.removeAttribute("value");
        walletInput.focus();
    }

    // 2. Clear case parameters
    const caseIdInput = document.getElementById("caseId");
    if (caseIdInput) caseIdInput.value = "";

    const fraudTypeSelect = document.getElementById("fraudType");
    if (fraudTypeSelect) fraudTypeSelect.selectedIndex = 0;

    const blockchainSelect = document.getElementById("blockchain");
    if (blockchainSelect) blockchainSelect.value = "Ethereum";

    const hopDepthSelect = document.getElementById("hopDepth");
    if (hopDepthSelect) hopDepthSelect.value = "2";

    const fanThresholdInput = document.getElementById("fanThreshold");
    if (fanThresholdInput) fanThresholdInput.value = "5";

    // 3. Clear validation feedback and error banners
    hideValidationFeedback();

    // 4. Clear the standalone wallet input on other tabs
    const intelInput = document.getElementById("intelSearchInput");
    if (intelInput) intelInput.value = "";
}

// 3. Topbar Search Bar Handler
function handleGlobalSearch(event) {
    if (event.key === "Enter") {
        const query = event.target.value.trim();
        if (!query) return;

        // If it starts with NCRP, jump to reports or filter
        if (query.toUpperCase().startsWith("NCRP")) {
            showPage("reports", document.querySelectorAll(".menu-item")[6]);
            const reportsFilter = document.querySelector("#reports input");
            if (reportsFilter) reportsFilter.value = query;
        } else {
            // Treat as a wallet address and execute investigation
            showPage("investigations", document.querySelectorAll(".menu-item")[1]);
            const walletInput = document.getElementById("walletInput");
            if (walletInput) {
                walletInput.value = query;
                startTrace();
            }
        }
    }
}

// 4. Reports Tab Action Button
function openLatestReport() {
    if (currentTraceData) {
        generateReport();
    } else {
        alert("No active investigation in memory. Run a new trace or click 'Full Dossier' on any case in the ledger below.");
    }
}

/* =========================================================
   POPULATE DASHBOARD FROM DATABASE
========================================================= */
async function loadRecentCases() {
    try {
        const response = await fetch("http://127.0.0.1:8000/cases");
        const cases = await response.json();

        const tbody = document.querySelector("#dashboard tbody");
        if (!tbody) return;

        tbody.innerHTML = ""; 

        cases.forEach(c => {
            let badgeClass = "low";
            if (c.risk_score >= 80) badgeClass = "critical";
            else if (c.risk_score >= 50) badgeClass = "high";
            else if (c.risk_score >= 20) badgeClass = "medium";

            let statusClass = c.status === "Completed" ? "completed" : "tracing";
            const shortWallet = c.wallet_address.substring(0, 6) + "..." + c.wallet_address.substring(c.wallet_address.length - 4);

            tbody.innerHTML += `
                <tr>
                    <td><strong>${c.case_id}</strong></td>
                    <td style="font-family: monospace;">${shortWallet}</td>
                    <td>${c.blockchain}</td>
                    <td>${c.fraud_type}</td>
                    <td><span class="badge ${badgeClass}">${c.risk_score > 0 ? c.risk_score + '/100' : 'Pending'}</span></td>
                    <td><span class="status ${statusClass}">${c.status}</span></td>
                </tr>
            `;
        });

        populateAlerts(cases);
        populateReports(cases);

    } catch (err) {
        console.error("Failed to load cases from DB", err);
    }
}

/* =========================================================
   LOAD DASHBOARD & ANALYTICS STATISTICS
========================================================= */
async function loadDashboardStats() {
    try {
        const response = await fetch("http://127.0.0.1:8000/stats");
        if (!response.ok) return;
        const stats = await response.json();

        // 1. Top Dashboard Cards
        const casesEl = document.getElementById("dashTotalCases");
        const walletsEl = document.getElementById("dashWalletsTraced");
        const riskEl = document.getElementById("dashHighRisk");

        if (casesEl) casesEl.innerText = stats.active_cases;
        if (walletsEl) walletsEl.innerText = stats.wallets_traced.toLocaleString();
        if (riskEl) riskEl.innerText = stats.high_risk;

        // 2. Risk Distribution Widget
        const dist = stats.risk_distribution;
        if (dist) {
            const pLow = document.getElementById("pctLow");
            const pMed = document.getElementById("pctMedium");
            const pHigh = document.getElementById("pctHigh");
            const pCrit = document.getElementById("pctCritical");

            if (pLow) pLow.innerText = `${dist.low.pct}%`;
            if (pMed) pMed.innerText = `${dist.medium.pct}%`;
            if (pHigh) pHigh.innerText = `${dist.high.pct}%`;
            if (pCrit) pCrit.innerText = `${dist.critical.pct}%`;
        }

        // 3. Analytics Page Metrics
        const aTotal = document.getElementById("analyticsTotalCases");
        const aCrit = document.getElementById("analyticsCriticalCases");
        const aHops = document.getElementById("analyticsHopsTracked");

        if (aTotal) aTotal.innerText = stats.active_cases;
        if (aCrit) aCrit.innerText = dist ? dist.critical.count : 0;
        if (aHops) aHops.innerText = (stats.active_cases * 2).toLocaleString();

        // 4. Analytics Typology Progress Bars
        const typoContainer = document.getElementById("typologyContainer");
        if (typoContainer && stats.typologies) {
            typoContainer.innerHTML = "";
            if (stats.typologies.length === 0) {
                typoContainer.innerHTML = `<p style="color: #718b9b; padding: 1rem;">No fraud typologies recorded yet.</p>`;
            } else {
                stats.typologies.forEach(t => {
                    const pctVal = stats.active_cases > 0 
                        ? Math.round((t.count / stats.active_cases) * 100) 
                        : 0;

                    typoContainer.innerHTML += `
                        <div>
                            <span>${t.fraud_type}</span>
                            <div>
                                <b style="width: ${pctVal}%"></b>
                            </div>
                            <strong>${pctVal}% (${t.count})</strong>
                        </div>
                    `;
                });
            }
        }

    } catch (err) {
        console.error("Failed to load dashboard/analytics stats", err);
    }
}

/* =========================================================
   START BLOCKCHAIN TRACE
========================================================= */
async function startTrace() {
    const walletInput = document.getElementById("walletInput");
    if (!walletInput || !walletInput.value.trim()) {
        alert("Please enter a suspect wallet address.");
        return;
    }

    // PRE-FLIGHT VALIDATION: Block execution if network and address do not match
    const isValid = validateAddressAndChain();
    if (!isValid) {
        alert("Validation Error: The target wallet address and selected cryptocurrency network do not match! Please choose the correct blockchain or verify your address.");
        return;
    }

    const wallet = walletInput.value.trim();
    const maxHops = document.getElementById("hopDepth") ? document.getElementById("hopDepth").value : 2;
    const fanThreshold = document.getElementById("fanThreshold") ? document.getElementById("fanThreshold").value : 5;
    
    const caseIdInput = document.getElementById("caseId");
    const caseId = (caseIdInput && caseIdInput.value.trim()) ? caseIdInput.value.trim() : `NCRP-${Math.floor(Math.random()*10000)}`;
    
    const fraudTypeEl = document.getElementById("fraudType");
    const fraudType = fraudTypeEl ? fraudTypeEl.value : "Investment Scam";
    
    const blockchainEl = document.getElementById("blockchain");
    const blockchain = blockchainEl ? blockchainEl.value : "Ethereum";

    const button = document.querySelector(".trace-button");
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Traversal in Progress...';
    button.disabled = true;

    try {
        await fetch("http://127.0.0.1:8000/cases", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ 
                case_id: caseId, 
                wallet_address: wallet, 
                blockchain: blockchain, 
                fraud_type: fraudType,
                max_hops: parseInt(maxHops)
            })
        });

        const url = `http://127.0.0.1:8000/wallet/${wallet}/graph?max_hops=${maxHops}&fan_threshold=${fanThreshold}&blockchain=${encodeURIComponent(blockchain)}`;
        const response = await fetch(url);
        
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `Server returned error ${response.status}`);
        }
        
        const data = await response.json();
        currentTraceData = data; 

        const vaspNode = data.nodes.find(n => n.type === "exchange");
        const networkScores = data.nodes
            .filter(n => n.type !== "reported_wallet" && n.type !== "exchange")
            .map(n => n.risk_score);
        const finalScore = networkScores.length > 0 ? Math.max(...networkScores) : 0;
        
        document.querySelector(".trace-result").innerHTML = `
            <div><span>Threat Severity</span><strong class="danger-text">${finalScore}/100</strong></div>
            <div><span>Nodes Analyzed</span><strong>${data.node_count}</strong></div>
            <div><span>Direct Edges</span><strong>${data.edge_count}</strong></div>
            <div><span>VASP Off-Ramp</span><strong>${vaspNode ? vaspNode.entity_name : "None Found"}</strong></div>
        `;

        await fetch(`http://127.0.0.1:8000/cases/${caseId}?risk_score=${finalScore}`, { method: "PATCH" });

        renderGraph(data.nodes, data.edges);
        document.getElementById("traceModal").classList.add("show");
        
        loadRecentCases();
        updateSecondaryTabs(data);

    } catch (err) {
        console.error(err);
        alert(`Investigation Error: ${err.message}`);
    } finally {
        button.innerHTML = '<i class="fa-solid fa-bolt"></i> Execute Autonomous Trace';
        button.disabled = false;
    }
}
/* =========================================================
   RENDER INTERACTIVE GRAPH (vis-network)
========================================================= */
function renderGraph(rawNodes, rawEdges) {
    const container = document.getElementById("networkGraph");
    if (!container) return;

    const nodes = new vis.DataSet(rawNodes.map(n => {
        let nodeColor = "#0879c9";
        let nodeSize = 13;

        if (n.type === "reported_wallet") {
            nodeColor = "#8e44ad"; 
            nodeSize = 24;
        } else {
            if (n.risk_score >= 80) nodeColor = "#d9364f";
            else if (n.risk_score >= 50) nodeColor = "#e67e22";
            else if (n.risk_score >= 20) nodeColor = "#f1c40f";
            else nodeColor = "#0b9b72";

            if (n.type === "exchange") nodeSize = 20;
        }
        
        return {
            id: n.id,
            label: n.entity_name ? n.entity_name : `${n.id.slice(0, 6)}...`,
            color: { background: nodeColor, border: "#ffffff" },
            font: { color: "#08263d", size: 11, face: "Inter", bold: true },
            size: nodeSize,
            shadow: true,
            title: `Risk Score: ${n.risk_score}/100\n\nFlags:\n • ${n.risk_reasons ? n.risk_reasons.join('\n • ') : 'None'}`
        };
    }));

    const edges = new vis.DataSet(rawEdges.map(e => ({
        from: e.from,
        to: e.to,
        arrows: { to: { scaleFactor: 0.5 } },
        color: { color: e.rapid_movement ? "rgba(217, 54, 79, 0.5)" : "rgba(169, 216, 237, 0.6)", highlight: "#0879c9" },
        smooth: { type: "continuous", roundness: 0.5 }
    })));

    const options = {
        nodes: { shape: "dot", borderWidth: 2 },
        physics: {
            solver: "forceAtlas2Based",
            forceAtlas2Based: { gravitationalConstant: -150, centralGravity: 0.01, springConstant: 0.05, springLength: 150, avoidOverlap: 0.5 },
            stabilization: { iterations: 150 }
        },
        interaction: { hover: true, tooltipDelay: 200, zoomView: true }
    };

    const network = new vis.Network(container, { nodes, edges }, options);
    network.once("stabilizationIterationsDone", function() { network.fit(); });
}

/* =========================================================
   GENERATE PDF REPORT
========================================================= */
async function generateReport() {
    if (!currentTraceData) {
        alert("No active trace data available. Please run a trace first.");
        return;
    }
    const caseId = document.getElementById("caseId")?.value.trim() || "NCRP-PENDING";
    const blockchain = document.getElementById("blockchain")?.value || "Ethereum";
    const fraudType = document.getElementById("fraudType")?.value || "Investment Scam";

    await buildAndDownloadForensicPDF(caseId, currentTraceData.wallet_address, blockchain, fraudType, currentTraceData);
}

async function downloadFullReport(caseId, wallet, blockchain, fraudType, maxHops = 2) {
    let traceData = (currentTraceData && currentTraceData.wallet_address.toLowerCase() === wallet.toLowerCase()) 
        ? currentTraceData 
        : null;

    if (!traceData) {
        const targetBtn = event ? event.target.closest("button") : null;
        let originalText = "";
        if (targetBtn) {
            originalText = targetBtn.innerHTML;
            targetBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Compiling...`;
            targetBtn.disabled = true;
        }

        try {
            const fanThreshold = document.getElementById("fanThreshold")?.value || 5;
            const res = await fetch(`http://127.0.0.1:8000/wallet/${wallet}/graph?max_hops=${maxHops}&fan_threshold=${fanThreshold}&blockchain=${encodeURIComponent(blockchain)}`);
            if (!res.ok) throw new Error("Failed to fetch graph data");
            traceData = await res.json();
        } catch (err) {
            console.error(err);
            alert("Could not pull detailed blockchain graph for this wallet.");
            return;
        } finally {
            if (targetBtn) {
                targetBtn.innerHTML = originalText;
                targetBtn.disabled = false;
            }
        }
    }

    await buildAndDownloadForensicPDF(caseId, wallet, blockchain, fraudType, traceData);
}

async function buildAndDownloadForensicPDF(caseId, wallet, blockchain, fraudType, traceData) {
    if (!window.jspdf || !window.jspdf.jsPDF) {
        alert("jsPDF library not loaded.");
        return;
    }

    const { jsPDF } = window.jspdf;
    const doc = new jsPDF();
    const pageWidth = doc.internal.pageSize.getWidth();

    // HEADER
    doc.setFillColor(6, 43, 73);
    doc.rect(0, 0, pageWidth, 26, "F");

    doc.setTextColor(255, 255, 255);
    doc.setFontSize(14);
    doc.setFont("helvetica", "bold");
    doc.text("CRYPTOTRACE | BLOCKCHAIN FORENSICS INTELLIGENCE DOSSIER", 14, 12);

    doc.setFontSize(8);
    doc.setFont("helvetica", "normal");
    doc.text("LAW ENFORCEMENT SENSITIVE // OFFICIAL INVESTIGATION RECORD // NCRP COMPLIANT", 14, 19);

    // CASE INFO BLOCK
    doc.setDrawColor(207, 228, 240);
    doc.setFillColor(248, 251, 254);
    doc.roundedRect(14, 30, pageWidth - 28, 44, 2, 2, "FD");

    doc.setFontSize(9);
    doc.setTextColor(18, 59, 84);

    doc.setFont("helvetica", "bold");
    doc.text("Case Reference ID:", 18, 38);
    doc.setFont("helvetica", "normal");
    doc.text(caseId, 55, 38);

    doc.setFont("helvetica", "bold");
    doc.text("Target Wallet:", 18, 46);
    doc.setFont("helvetica", "normal");
    doc.text(wallet, 55, 46);

    doc.setFont("helvetica", "bold");
    doc.text("Network / Asset:", 18, 54);
    doc.setFont("helvetica", "normal");
    doc.text(`${blockchain} (Mainnet)`, 55, 54);

    doc.setFont("helvetica", "bold");
    doc.text("Reported Typology:", 18, 62);
    doc.setFont("helvetica", "normal");
    doc.text(fraudType, 55, 62);

    const reportDate = new Date().toLocaleString();
    doc.setFont("helvetica", "bold");
    doc.text("Generated On:", 125, 38);
    doc.setFont("helvetica", "normal");
    doc.text(reportDate, 155, 38);

    doc.setFont("helvetica", "bold");
    doc.text("Trace Depth:", 125, 46);
    doc.setFont("helvetica", "normal");
    doc.text(`${traceData.max_hops} Hops Explored`, 155, 46);

    doc.setFont("helvetica", "bold");
    doc.text("Wallets Traced:", 125, 54);
    doc.setFont("helvetica", "normal");
    doc.text(`${traceData.node_count} Nodes Analyzed`, 155, 54);

    doc.setFont("helvetica", "bold");
    doc.text("Transaction Links:", 125, 62);
    doc.setFont("helvetica", "normal");
    doc.text(`${traceData.edge_count} Direct Edges`, 155, 62);

    // THREAT ASSESSMENT
    const vaspNodes = traceData.nodes.filter(n => n.type === "exchange");
    const networkScores = traceData.nodes
        .filter(n => n.type !== "reported_wallet" && n.type !== "exchange")
        .map(n => n.risk_score);
    const score = networkScores.length > 0 ? Math.max(...networkScores) : 0;

    let riskLevel = "LOW RISK";
    let riskColor = [11, 155, 114];
    if (score >= 80) {
        riskLevel = "CRITICAL RISK";
        riskColor = [217, 54, 79];
    } else if (score >= 50) {
        riskLevel = "HIGH RISK";
        riskColor = [230, 126, 34];
    }

    doc.setFontSize(10.5);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(6, 43, 73);
    doc.text("1. Threat Assessment & Attribution Summary", 14, 82);

    doc.setFillColor(...riskColor);
    doc.roundedRect(14, 86, 48, 10, 1.5, 1.5, "F");
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(8);
    doc.text(`SCORE: ${score}/100 (${riskLevel})`, 16, 93);

    doc.setTextColor(18, 59, 84);
    doc.setFontSize(8.5);
    doc.setFont("helvetica", "bold");
    doc.text("Off-Ramp / VASP Leads for Immediate Freeze Notice:", 66, 90);
    doc.setFont("helvetica", "normal");
    
    if (vaspNodes.length > 0) {
        const vaspNames = vaspNodes.map(v => `${v.entity_name || "VASP"} (${v.id.substring(0, 10)}...)`).join(", ");
        doc.text(vaspNames, 66, 95);
    } else {
        doc.text("No centralized exchange identified in initial hops. Deep trace recommended.", 66, 95);
    }

    const allFlags = new Set();
    traceData.nodes.forEach(n => {
        if (n.risk_reasons && Array.isArray(n.risk_reasons)) {
            n.risk_reasons.forEach(r => {
                if (r !== "Involved in fund flow" && r !== "Safe: Known Exchange") {
                    allFlags.add(r);
                }
            });
        }
    });

    const flagSummary = allFlags.size > 0 
        ? Array.from(allFlags).join("  •  ") 
        : "Standard transaction flow; no secondary AML anomalies identified.";

    doc.setFont("helvetica", "bold");
    doc.text("Observed Network Red-Flag Typologies:", 14, 103);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(8);
    doc.setTextColor(50, 50, 50);
    doc.text(flagSummary, 14, 108, { maxWidth: pageWidth - 28 });

    // TABLE
    doc.setFontSize(10.5);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(6, 43, 73);
    doc.text("2. Forensic Fund Flow & Node Attribution Ledger", 14, 122);

    const tableRows = traceData.nodes.map(n => {
        let role = "Intermediary Wallet";
        let displayScore = `${n.risk_score}/100`;
        
        if (n.type === "reported_wallet") {
            role = "REPORTED SUSPECT";
            displayScore = "N/A (Origin)";
        } else if (n.type === "exchange") {
            role = `EXCHANGE (${n.entity_name || "VASP"})`;
        }

        const flags = n.risk_reasons && n.risk_reasons.length > 0 ? n.risk_reasons.join(", ") : "Normal Flow";

        return [`Hop ${n.hop}`, n.id, role, displayScore, flags];
    });

    doc.autoTable({
        startY: 126,
        head: [['Hop', 'Address', 'Classification / Entity', 'Risk', 'Detected AML / FATF Flags']],
        body: tableRows,
        theme: 'grid',
        styles: { fontSize: 7.5, cellPadding: 2.2, textColor: [18, 59, 84], overflow: 'linebreak' },
        headStyles: { fillColor: [8, 121, 201], textColor: [255, 255, 255], fontStyle: 'bold' },
        alternateRowStyles: { fillColor: [245, 249, 253] },
        columnStyles: {
            0: { cellWidth: 14, halign: 'center' },
            1: { cellWidth: 50, font: "courier" },
            2: { cellWidth: 38 },
            3: { cellWidth: 18, halign: 'center', fontStyle: 'bold' },
            4: { cellWidth: 'auto' }
        },
        didDrawPage: () => {
            const str = `Page ${doc.internal.getNumberOfPages()} | CryptoTrace Autonomous Blockchain Forensics | Stamped By: ${localStorage.getItem("ct_name") || "Investigator"}`;
            doc.setFontSize(7.5);
            doc.setTextColor(150, 150, 150);
            doc.text(str, 14, doc.internal.pageSize.getHeight() - 8);
        }
    });

    doc.save(`${caseId}_Full_Forensic_Dossier.pdf`);
}

/* =========================================================
   POPULATE SECONDARY TABS
========================================================= */
function updateSecondaryTabs(data) {
    const txTable = document.getElementById("txTable");
    if (txTable) {
        let txTbody = txTable.querySelector("tbody");
        if (!txTbody) {
            txTbody = document.createElement("tbody");
            txTable.appendChild(txTbody);
        }
        
        txTbody.innerHTML = ""; 
        
        data.edges.forEach(edge => {
            const shortHash = edge.tx_hash ? edge.tx_hash.substring(0, 10) + "..." : "Direct Route";
            const shortFrom = edge.from.substring(0, 8) + "...";
            const shortTo = edge.to.substring(0, 8) + "...";
            
            const flagHtml = edge.rapid_movement 
                ? `<span class="badge critical">Rapid Movement</span>` 
                : `<span class="badge low">Standard</span>`;

            txTbody.innerHTML += `
                <tr>
                    <td style="color: #0879c9; font-family: monospace;">${shortHash}</td>
                    <td style="font-family: monospace;">${shortFrom}</td>
                    <td style="font-family: monospace;">${shortTo}</td>
                    <td><strong>${edge.amount} ${edge.asset || ""}</strong></td>
                    <td>${edge.timestamp || "Recent"}</td>
                    <td>${flagHtml}</td>
                </tr>
            `;
        });
    }

    const reportedNode = data.nodes.find(n => n.type === "reported_wallet") || data.nodes[0];
    const vaspNode = data.nodes.find(n => n.type === "exchange");
    
    const networkScores = data.nodes
        .filter(n => n.type !== "reported_wallet" && n.type !== "exchange")
        .map(n => n.risk_score);
    const caseScore = networkScores.length > 0 ? Math.max(...networkScores) : 0;
    
    const riskEl = document.getElementById("intelRiskScore");
    const vaspEl = document.getElementById("intelVaspLead");
    const anomalyEl = document.getElementById("intelAnomalies");
    const txEl = document.getElementById("intelTxCount");

    if (riskEl) riskEl.innerText = caseScore + "/100";
    if (vaspEl) vaspEl.innerText = vaspNode ? vaspNode.entity_name : "None Found";
    if (anomalyEl) anomalyEl.innerText = reportedNode.risk_reasons ? reportedNode.risk_reasons.length : 0;
    if (txEl) txEl.innerText = data.edge_count;
}

/* =========================================================
   MODAL CONTROLS & INITIALIZERS
========================================================= */
function closeModal() {
    const modal = document.getElementById("traceModal");
    if (modal) modal.classList.remove("show");
}

document.addEventListener("keydown", function(event) {
    if (event.key === "Escape") closeModal();
});

document.addEventListener("DOMContentLoaded", function() {
    createAIBackground();
    loadRecentCases(); 
    loadDashboardStats(); 
    loadInvestigatorSettings();
});

/* =========================================================
   POPULATE ALERTS TAB
========================================================= */
function populateAlerts(cases) {
    const alertsContainer = document.getElementById("alertsContainer");
    if (!alertsContainer) return;

    alertsContainer.innerHTML = "";
    const highRiskCases = cases.filter(c => c.risk_score >= 50);

    if (highRiskCases.length === 0) {
        alertsContainer.innerHTML = `<p style="color: #718b9b; grid-column: 1 / -1; text-align: center; padding: 2rem;">No critical alerts. All tracked wallets are within safe thresholds.</p>`;
        return;
    }

    highRiskCases.forEach(c => {
        const isCritical = c.risk_score >= 80;
        const badgeClass = isCritical ? "critical" : "high";
        const badgeText = isCritical ? "CRITICAL" : "HIGH";
        const icon = isCritical ? "fa-triangle-exclamation" : "fa-bolt";
        const shortWallet = c.wallet_address.substring(0, 8) + "...";

        alertsContainer.innerHTML += `
            <div class="alert-card ${isCritical ? 'critical-alert' : ''}">
                <div class="alert-symbol">
                    <i class="fa-solid ${icon}"></i>
                </div>
                <div>
                    <span class="badge ${badgeClass}">${badgeText}</span>
                    <h3>High Risk: ${c.fraud_type}</h3>
                    <p>Suspect wallet <strong>${shortWallet}</strong> flagged on ${c.blockchain} with severity score ${c.risk_score}/100.</p>
                    <small>Case: ${c.case_id} • Status: ${c.status}</small>
                </div>
                <button onclick="reviewAlertWallet('${c.wallet_address}', '${c.case_id}', '${c.fraud_type}')">
                    <i class="fa-solid fa-magnifying-glass"></i> Re-Trace
                </button>
            </div>
        `;
    });

    const sidebarBadge = document.getElementById("sidebarAlertCount");
    const topbarBadge = document.getElementById("topbarAlertCount");
    if (sidebarBadge) sidebarBadge.innerText = highRiskCases.length;
    if (topbarBadge) topbarBadge.innerText = highRiskCases.length;
}

function reviewAlertWallet(wallet, caseId, fraudType) {
    showPage('investigations', document.querySelectorAll('.menu-item')[1]);
    document.getElementById("walletInput").value = wallet;
    if (document.getElementById("caseId")) document.getElementById("caseId").value = caseId;
    if (document.getElementById("fraudType")) document.getElementById("fraudType").value = fraudType;
    startTrace();
}

/* =========================================================
   POPULATE REPORTS TAB
========================================================= */
function populateReports(cases) {
    const reportsTbody = document.getElementById("reportsTableBody");
    if (!reportsTbody) return;

    reportsTbody.innerHTML = "";

    cases.forEach(c => {
        let badgeClass = "low";
        if (c.risk_score >= 80) badgeClass = "critical";
        else if (c.risk_score >= 50) badgeClass = "high";
        else if (c.risk_score >= 20) badgeClass = "medium";

        const shortWallet = c.wallet_address.substring(0, 10) + "...";
        const hops = c.max_hops || 2;

        reportsTbody.innerHTML += `
            <tr>
                <td><strong>${c.case_id}</strong></td>
                <td style="font-family: monospace;">${shortWallet}</td>
                <td>${c.blockchain}</td>
                <td><span class="badge ${badgeClass}">${c.risk_score}/100</span></td>
                <td>
                    <button class="small-button" onclick="downloadFullReport('${c.case_id}', '${c.wallet_address}', '${c.blockchain}', '${c.fraud_type}', ${hops})">
                        <i class="fa-solid fa-file-pdf"></i> Full Dossier
                    </button>
                </td>
            </tr>
        `;
    });
}

/* =========================================================
   STANDALONE WALLET ANALYZER
========================================================= */
async function analyzeStandaloneWallet() {
    const input = document.getElementById("intelSearchInput");
    if (!input || !input.value.trim()) {
        alert("Please enter a valid wallet address.");
        return;
    }
    const address = input.value.trim();

    const btn = event.target.closest("button");
    const origText = btn.innerHTML;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Querying...`;
    btn.disabled = true;

    try {
        const res = await fetch(`http://127.0.0.1:8000/wallet/${address}/graph?max_hops=1&fan_threshold=5`);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || "Lookup failed");
        }
        const data = await res.json();
        updateSecondaryTabs(data);
        alert(`Analysis Complete: ${data.node_count} direct counterparties identified.`);
    } catch (e) {
        alert(`Analysis Error: ${e.message}`);
    } finally {
        btn.innerHTML = origText;
        btn.disabled = false;
    }
}

/* =========================================================
   TRANSACTION EXPLORER LIVE FILTER
========================================================= */
function filterTransactionsTable() {
    const searchVal = (document.getElementById("txSearchFilter")?.value || "").toLowerCase();
    const riskVal = document.getElementById("txRiskFilterSelect")?.value || "all";
    const rows = document.querySelectorAll("#txTable tbody tr");

    rows.forEach(row => {
        const text = row.innerText.toLowerCase();
        const matchesSearch = text.includes(searchVal);
        const hasRapid = row.innerHTML.includes("Rapid Movement");

        let matchesRisk = true;
        if (riskVal === "rapid") matchesRisk = hasRapid;
        else if (riskVal === "standard") matchesRisk = !hasRapid;

        row.style.display = (matchesSearch && matchesRisk) ? "" : "none";
    });
}

/* =========================================================
   SETTINGS & SYSTEM DIAGNOSTICS
========================================================= */
function loadInvestigatorSettings() {
    const name = localStorage.getItem("ct_name") || "Investigator";
    const badge = localStorage.getItem("ct_badge") || "LEA-7704";
    const unit = localStorage.getItem("ct_unit") || "Cyber Crime Unit";

    if (document.getElementById("settingName")) document.getElementById("settingName").value = name;
    if (document.getElementById("settingBadge")) document.getElementById("settingBadge").value = badge;
    if (document.getElementById("settingUnit")) document.getElementById("settingUnit").value = unit;
}

function saveInvestigatorSettings() {
    const name = document.getElementById("settingName")?.value.trim() || "Investigator";
    const badge = document.getElementById("settingBadge")?.value.trim() || "LEA-7704";
    const unit = document.getElementById("settingUnit")?.value.trim() || "Cyber Crime Unit";

    localStorage.setItem("ct_name", name);
    localStorage.setItem("ct_badge", badge);
    localStorage.setItem("ct_unit", unit);

    alert("Investigator profile saved. This will stamp all generated dossiers.");
}

async function checkSystemDiagnostics() {
    const bEl = document.getElementById("diagBackend");
    const dEl = document.getElementById("diagDb");
    const aEl = document.getElementById("diagAlchemy");

    try {
        const res = await fetch("http://127.0.0.1:8000/health");
        if (res.ok) {
            bEl.innerText = "Online";
            bEl.className = "connected";
            dEl.innerText = "Connected";
            dEl.className = "connected";
            aEl.innerText = "Active";
            aEl.className = "connected";
            alert("All backend subsystems responding normally.");
        } else {
            throw new Error();
        }
    } catch {
        bEl.innerText = "Offline";
        bEl.className = "negative";
        alert("Backend health check failed. Ensure FastAPI is running on port 8000.");
    }
}

function detectBlockchain(address) {
    const trimmed = address.trim();
    if (!trimmed) return null;

    // EVM: 0x followed by 40 hexadecimal characters (42 total)
    if (/^0x[a-fA-F0-9]{40}$/.test(trimmed)) {
        return "EVM";
    }

    // Tron: Starts with T, Base58 characters, exactly 34 characters
    if (/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(trimmed)) {
        return "Tron";
    }

    // Bitcoin: Legacy (1...), P2SH (3...), or Native SegWit Bech32 (bc1...)
    if (/^(1[1-9A-HJ-NP-Za-km-z]{25,34}|3[1-9A-HJ-NP-Za-km-z]{25,34}|bc1[a-zA-HJ-NP-Z0-9]{39,59})$/.test(trimmed)) {
        return "Bitcoin";
    }

    return "Unknown";
}

// Triggered every time the user types or pastes into the wallet address box
function handleWalletAddressInput() {
    const input = document.getElementById("walletInput");
    if (!input) return;
    
    const addr = input.value.trim();
    const chainSelect = document.getElementById("blockchain");

    if (!addr) {
        hideValidationFeedback();
        return;
    }

    const detected = detectBlockchain(addr);

    if (detected === "Bitcoin") {
        if (chainSelect.value !== "Bitcoin") {
            chainSelect.value = "Bitcoin";
        }
        showValidationBadge("✓ Bitcoin Address Detected", "#0b9b72", "#d8f3e9");
        hideMismatch();
    } else if (detected === "Tron") {
        if (chainSelect.value !== "Tron") {
            chainSelect.value = "Tron";
        }
        showValidationBadge("✓ Tron Address Detected", "#0b9b72", "#d8f3e9");
        hideMismatch();
    } else if (detected === "EVM") {
        // Retain EVM selection if user already picked Polygon or BNB Chain
        if (!["Ethereum", "Polygon", "BNB Chain"].includes(chainSelect.value)) {
            chainSelect.value = "Ethereum";
        }
        showValidationBadge(`✓ ${chainSelect.value} (EVM) Detected`, "#0b9b72", "#d8f3e9");
        hideMismatch();
    } else {
        if (addr.length >= 10) {
            validateAddressAndChain();
        } else {
            hideValidationFeedback();
        }
    }
}

// Validates whether the currently selected dropdown matches the address format
function validateAddressAndChain() {
    const input = document.getElementById("walletInput");
    const chainSelect = document.getElementById("blockchain");
    if (!input || !chainSelect) return true;

    const addr = input.value.trim();
    if (!addr) {
        hideValidationFeedback();
        return true;
    }

    const selectedChain = chainSelect.value;
    const detected = detectBlockchain(addr);

    let isMismatch = false;

    if (detected === "Bitcoin" && selectedChain !== "Bitcoin") {
        isMismatch = true;
    } else if (detected === "Tron" && selectedChain !== "Tron") {
        isMismatch = true;
    } else if (detected === "EVM" && !["Ethereum", "Polygon", "BNB Chain"].includes(selectedChain)) {
        isMismatch = true;
    }

    if (isMismatch) {
        showMismatch(`Address format (${detected}) and selected network (${selectedChain}) do not match!`);
        showValidationBadge("Mismatch Alert", "#d9364f", "#ffe0e5");
        return false;
    } else {
        hideMismatch();
        if (detected !== "Unknown" && detected !== null) {
            showValidationBadge(`✓ ${selectedChain} Verified`, "#0b9b72", "#d8f3e9");
        }
        return true;
    }
}

function showValidationBadge(text, color, bgColor) {
    const badge = document.getElementById("walletValidationBadge");
    if (badge) {
        badge.innerText = text;
        badge.style.color = color;
        badge.style.background = bgColor;
        badge.style.display = "inline-block";
    }
}

function showMismatch(message) {
    const err = document.getElementById("walletMismatchError");
    const msgText = document.getElementById("mismatchMessageText");
    if (err && msgText) {
        msgText.innerText = message;
        err.style.display = "block";
    }
}

function hideMismatch() {
    const err = document.getElementById("walletMismatchError");
    if (err) err.style.display = "none";
}

function hideValidationFeedback() {
    const badge = document.getElementById("walletValidationBadge");
    if (badge) badge.style.display = "none";
    hideMismatch();
}