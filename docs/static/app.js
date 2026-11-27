(() => {
  const state = {
    mode: "checking", // "live_eda" | "static_showcase"
    apiBase: localStorage.getItem("fpga_autopilot_api_url") || "",
    toolchain: null,
    runs: [],
    selectedRun: null,
    activeTab: "rtl",
    selectedRtlIdx: 0,
    staticGuiEvents: [],
  };

  const els = {
    engineBadge: document.getElementById("engineBadge"),
    engineBadgeText: document.getElementById("engineBadgeText"),
    runCountBadge: document.getElementById("runCountBadge"),
    runList: document.getElementById("runList"),
    toolchainList: document.getElementById("toolchainList"),
    benchPresetTag: document.getElementById("benchPresetTag"),
    benchDeviceTag: document.getElementById("benchDeviceTag"),
    benchGateBadge: document.getElementById("benchGateBadge"),
    benchTitle: document.getElementById("benchTitle"),
    benchDesc: document.getElementById("benchDesc"),
    dlPdfBtn: document.getElementById("dlPdfBtn"),
    dlZipBtn: document.getElementById("dlZipBtn"),
    dlVcdBtn: document.getElementById("dlVcdBtn"),
    kpiSim: document.getElementById("kpiSim"),
    kpiSimSub: document.getElementById("kpiSimSub"),
    kpiLatches: document.getElementById("kpiLatches"),
    kpiLintTools: document.getElementById("kpiLintTools"),
    kpiLEs: document.getElementById("kpiLEs"),
    kpiCombSub: document.getElementById("kpiCombSub"),
    kpiRegs: document.getElementById("kpiRegs"),
    kpiPinsSub: document.getElementById("kpiPinsSub"),
    kpiFmax: document.getElementById("kpiFmax"),
    kpiSlackSub: document.getElementById("kpiSlackSub"),
    capturesGallery: document.getElementById("capturesGallery"),
    rtlFileSelectorBar: document.getElementById("rtlFileSelectorBar"),
    codePaneWrap: document.getElementById("codePaneWrap"),
    codeViewer: document.querySelector("#codeViewer code"),
    specTableWrap: document.getElementById("specTableWrap"),
    btnCopyCode: document.getElementById("btnCopyCode"),
    runModal: document.getElementById("runModal"),
    liveServerUrlBox: document.getElementById("liveServerUrlBox"),
    customApiInput: document.getElementById("customApiInput"),
    btnSaveApiUrl: document.getElementById("btnSaveApiUrl"),
    inputModName: document.getElementById("inputModName"),
    selectBoardPreset: document.getElementById("selectBoardPreset"),
    inputLabPrompt: document.getElementById("inputLabPrompt"),
    chkQuartusGui: document.getElementById("chkQuartusGui"),
    jobConsoleWrap: document.getElementById("jobConsoleWrap"),
    jobConsoleLog: document.getElementById("jobConsoleLog"),
    btnSubmitRun: document.getElementById("btnSubmitRun"),
    lightboxModal: document.getElementById("lightboxModal"),
    lightboxTitle: document.getElementById("lightboxTitle"),
    lightboxBody: document.getElementById("lightboxBody"),
  };

  function escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function resolveUrl(url) {
    if (!url) return "#";
    if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("./")) {
      return url;
    }
    return `${state.apiBase}${url}`;
  }

  async function tryConnectLiveApi(baseUrl) {
    const cleanBase = baseUrl.replace(/\/+$/, "");
    const resp = await fetch(`${cleanBase}/api/status`, { cache: "no-store" });
    if (!resp.ok) throw new Error("Live API unreachable");
    const statusData = await resp.json();
    const runsResp = await fetch(`${cleanBase}/api/runs`, { cache: "no-store" });
    const runsData = await runsResp.json();
    state.mode = "live_eda";
    state.apiBase = cleanBase;
    state.toolchain = statusData.toolchain;
    state.runs = runsData.runs || [];
    els.engineBadge.className = "status-pill status-live";
    els.engineBadgeText.textContent = "Live Quartus II + GTKWave Engine Connected";
    els.liveServerUrlBox.classList.add("hidden");
  }

  async function initData() {
    // 1. Try same-origin live FastAPI backend first
    try {
      await tryConnectLiveApi("");
    } catch {
      // 2. Fallback to static GitHub Pages bundle (+ optional live Cloudflare tunnel!)
      const staticResp = await fetch("./data/static_bundle.json", { cache: "no-store" });
      const bundle = await staticResp.json();
      state.toolchain = bundle.toolchain;
      state.runs = bundle.runs || [];
      state.staticGuiEvents = bundle.gui_audit_events || [];

      const candidateTunnel = state.apiBase || bundle.live_tunnel_url || "";
      if (candidateTunnel) {
        try {
          await tryConnectLiveApi(candidateTunnel);
        } catch {
          state.mode = "static_showcase";
          els.engineBadge.className = "status-pill status-static";
          els.engineBadgeText.textContent = "Verified Static Archive (GitHub Pages)";
          els.customApiInput.value = candidateTunnel;
          els.liveServerUrlBox.classList.remove("hidden");
        }
      } else {
        state.mode = "static_showcase";
        els.engineBadge.className = "status-pill status-static";
        els.engineBadgeText.textContent = "Verified Static Archive (GitHub Pages)";
        els.liveServerUrlBox.classList.remove("hidden");
      }
    }

    renderToolchain();
    renderRunList();
    if (state.runs.length > 0) {
      selectRun(state.runs[0].name);
    }
  }

  function renderToolchain() {
    const tools = state.toolchain?.tools || {};
    const keyTools = [
      ["quartus_map", "Quartus Synthesis"],
      ["quartus_fit", "Quartus Fitter"],
      ["quartus_sta", "TimeQuest STA"],
      ["quartus", "Quartus RTL GUI"],
      ["verilator", "Verilator Lint"],
      ["iverilog", "Icarus SV-2012"],
      ["vsim", "ModelSim ASE"],
      ["gtkwave", "GTKWave 3.3"],
      ["xelatex", "XeLaTeX PDF"],
    ];
    els.toolchainList.innerHTML = keyTools
      .map(([key, label]) => {
        const avail = Boolean(tools[key]?.available);
        return `<div class="tool-row">
          <span>${escapeHtml(label)}</span>
          <span class="${avail ? "tool-ok" : "tool-miss"}">${avail ? "READY" : "FALLBACK"}</span>
        </div>`;
      })
      .join("");
  }

  function renderRunList() {
    els.runCountBadge.textContent = String(state.runs.length);
    els.runList.innerHTML = state.runs
      .map((r) => {
        const sum = r.summary;
        const res = sum.synthesis_report.resources;
        const activeCls = state.selectedRun?.name === r.name ? "active" : "";
        return `<button class="run-item ${activeCls}" data-name="${escapeHtml(r.name)}" type="button">
          <div class="run-item-top">
            <span>${escapeHtml(r.name)}</span>
            <span class="pass-dot">${sum.overall_passed ? "&#10003; PASS" : "WARN"}</span>
          </div>
          <div class="run-item-sub">
            <span>${escapeHtml(sum.board_preset)}</span>
            <span>${res.logic_elements_or_alms} LE/ALM &middot; ${sum.sim_result.passed_vectors}/${sum.sim_result.total_vectors}</span>
          </div>
        </button>`;
      })
      .join("");

    els.runList.querySelectorAll(".run-item").forEach((btn) => {
      btn.addEventListener("click", () => selectRun(btn.dataset.name));
    });
  }

  function selectRun(name) {
    const found = state.runs.find((r) => r.name === name);
    if (!found) return;
    state.selectedRun = found;
    state.selectedRtlIdx = 0;
    renderRunList();
    renderSelectedBenchmark();
  }

  function renderSelectedBenchmark() {
    const r = state.selectedRun;
    if (!r) return;
    const sum = r.summary;
    const synth = sum.synthesis_report;
    const res = synth.resources;
    const tim = synth.timing;

    els.benchPresetTag.textContent = sum.board_preset;
    els.benchDeviceTag.textContent = `${synth.family} · ${synth.device}`;
    els.benchGateBadge.textContent = sum.overall_passed ? "100% VERIFIED PASS" : "CHECK LOGS";
    els.benchTitle.textContent = r.title;
    els.benchDesc.textContent = r.description;

    els.dlPdfBtn.href = resolveUrl(r.downloads.pdf_url);
    els.dlZipBtn.href = resolveUrl(r.downloads.quartus_zip_url);
    els.dlVcdBtn.href = resolveUrl(r.downloads.vcd_url);

    els.kpiSim.textContent = `${sum.sim_result.passed_vectors} / ${sum.sim_result.total_vectors}`;
    els.kpiSimSub.textContent = `${sum.sim_result.simulator} · ${sum.sim_result.runtime_sec.toFixed(2)}s`;

    els.kpiLatches.textContent = `${res.inferred_latches} Latches`;
    els.kpiLintTools.textContent = `${sum.lint_report.warning_count} warns (${sum.lint_report.tools_used.join(", ")})`;

    els.kpiLEs.textContent = `${res.logic_elements_or_alms}`;
    els.kpiCombSub.textContent = `${res.combinational_functions} Comb LUTs/ALUTs`;

    els.kpiRegs.textContent = `${res.dedicated_logic_registers}`;
    els.kpiPinsSub.textContent = `${res.total_pins} I/O Pins · ${res.memory_bits} Mem Bits`;

    els.kpiFmax.textContent = tim.fmax_mhz ? `${tim.fmax_mhz.toFixed(2)} MHz` : "Comb Path";
    els.kpiSlackSub.textContent =
      tim.worst_setup_slack_ns !== null
        ? `Setup +${tim.worst_setup_slack_ns.toFixed(3)}ns · Hold +${(tim.worst_hold_slack_ns ?? 0).toFixed(3)}ns`
        : "TimeQuest STA Verified";

    const labelMap = {
      gtkwave_waveform: "GTKWave Digital Waveform",
      quartus_rtl_viewer: "Quartus II RTL Viewer Schematic",
      quartus_fsm_viewer: "Quartus II State Machine Viewer",
    };

    els.capturesGallery.innerHTML = (r.captures || [])
      .map((cap) => {
        const imgUrl = resolveUrl(cap.url);
        const title = labelMap[cap.capture_type] || cap.capture_type;
        return `<div class="capture-card" data-url="${escapeHtml(imgUrl)}" data-title="${escapeHtml(title)}">
          <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(title)}" loading="lazy" />
          <div class="capture-meta">
            <strong>${escapeHtml(title)}</strong>
            <span class="pass-dot">OpenCV Audit &#10003; (${cap.width_px}&times;${cap.height_px})</span>
          </div>
        </div>`;
      })
      .join("");

    els.capturesGallery.querySelectorAll(".capture-card").forEach((card) => {
      card.addEventListener("click", () => {
        els.lightboxTitle.textContent = card.dataset.title;
        els.lightboxBody.innerHTML = `<img src="${escapeHtml(card.dataset.url)}" alt="${escapeHtml(card.dataset.title)}" />`;
        els.lightboxModal.classList.remove("hidden");
      });
    });

    renderActiveTab();
  }

  function renderActiveTab() {
    const r = state.selectedRun;
    if (!r) return;
    const tab = state.activeTab;

    if (tab === "ports") {
      els.rtlFileSelectorBar.classList.add("hidden");
      els.codePaneWrap.classList.add("hidden");
      els.specTableWrap.classList.remove("hidden");

      const portRows = (r.ports || [])
        .map(
          (p) => `<tr>
            <td><code>${escapeHtml(p.name)}</code></td>
            <td>${escapeHtml(p.direction)}</td>
            <td>${p.width}</td>
            <td>${p.signed ? "signed" : p.active_low ? "active-low" : "logic"}</td>
            <td>${escapeHtml(p.description)}</td>
          </tr>`
        )
        .join("");

      let fsmHtml = "";
      if (r.fsm_states && r.fsm_states.length > 0) {
        const sRows = r.fsm_states
          .map(
            (st) => `<tr>
              <td><code>${escapeHtml(st.name)}</code></td>
              <td><code>${escapeHtml(st.encoding || "-")}</code></td>
              <td>${escapeHtml(JSON.stringify(st.outputs))}</td>
            </tr>`
          )
          .join("");
        fsmHtml = `<h4 style="margin:18px 0 8px;font-size:13px;">FSM State Encoding</h4>
          <table class="data-table">
            <thead><tr><th>State</th><th>Encoding</th><th>Moore Outputs</th></tr></thead>
            <tbody>${sRows}</tbody>
          </table>`;
      }

      els.specTableWrap.innerHTML = `<table class="data-table">
          <thead><tr><th>Port</th><th>Direction</th><th>Width</th><th>Type</th><th>Description</th></tr></thead>
          <tbody>${portRows}</tbody>
        </table>${fsmHtml}`;
      return;
    }

    els.specTableWrap.classList.add("hidden");
    els.codePaneWrap.classList.remove("hidden");

    if (tab === "rtl") {
      const rtlFiles = r.sources.rtl || [];
      if (rtlFiles.length > 1) {
        els.rtlFileSelectorBar.classList.remove("hidden");
        els.rtlFileSelectorBar.innerHTML = rtlFiles
          .map(
            (f, idx) =>
              `<button class="subfile-chip ${idx === state.selectedRtlIdx ? "active" : ""}" data-idx="${idx}" type="button">${escapeHtml(f.filename)}</button>`
          )
          .join("");
        els.rtlFileSelectorBar.querySelectorAll(".subfile-chip").forEach((chip) => {
          chip.addEventListener("click", () => {
            state.selectedRtlIdx = Number(chip.dataset.idx);
            renderActiveTab();
          });
        });
      } else {
        els.rtlFileSelectorBar.classList.add("hidden");
      }
      els.codeViewer.textContent = rtlFiles[state.selectedRtlIdx]?.code || "";
    } else {
      els.rtlFileSelectorBar.classList.add("hidden");
      els.codeViewer.textContent = r.sources[tab] || "";
    }
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.activeTab = btn.dataset.tab;
      renderActiveTab();
    });
  });

  els.btnCopyCode.addEventListener("click", async () => {
    await navigator.clipboard.writeText(els.codeViewer.textContent || "");
    els.btnCopyCode.textContent = "Copied!";
    setTimeout(() => {
      els.btnCopyCode.textContent = "Copy";
    }, 1200);
  });

  // Modal controls
  document.getElementById("btnOpenNewRun").addEventListener("click", () => {
    els.runModal.classList.remove("hidden");
  });
  document.getElementById("btnCloseRunModal").addEventListener("click", () => {
    els.runModal.classList.add("hidden");
  });
  document.getElementById("btnCancelRun").addEventListener("click", () => {
    els.runModal.classList.add("hidden");
  });
  document.getElementById("btnCloseLightbox").addEventListener("click", () => {
    els.lightboxModal.classList.add("hidden");
  });

  els.btnSaveApiUrl.addEventListener("click", async () => {
    const url = els.customApiInput.value.trim();
    if (!url) return;
    localStorage.setItem("fpga_autopilot_api_url", url);
    try {
      await tryConnectLiveApi(url);
      renderToolchain();
      renderRunList();
    } catch (err) {
      alert(`Could not reach live EDA engine at ${url}: ${err.message}`);
    }
  });

  els.btnSubmitRun.addEventListener("click", async () => {
    if (state.mode !== "live_eda") {
      alert("Connect a Live EDA Tunnel URL above to synthesize new designs on Quartus II hardware.");
      return;
    }
    els.btnSubmitRun.disabled = true;
    els.jobConsoleWrap.classList.remove("hidden");
    els.jobConsoleLog.textContent = "Submitting job to FPGA Autopilot engine...\n";

    try {
      const resp = await fetch(`${state.apiBase}/api/run/prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: els.inputLabPrompt.value,
          name: els.inputModName.value,
          board_preset: els.selectBoardPreset.value,
          enable_gui: true,
          enable_quartus_gui: els.chkQuartusGui.checked,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to start run");

      const jobId = data.job_id;
      while (true) {
        await new Promise((res) => setTimeout(res, 1500));
        const jResp = await fetch(`${state.apiBase}/api/jobs/${jobId}`, { cache: "no-store" });
        const jData = await jResp.json();
        els.jobConsoleLog.textContent = (jData.logs || []).join("\n");
        if (jData.status === "completed") {
          const runsResp = await fetch(`${state.apiBase}/api/runs`, { cache: "no-store" });
          const runsData = await runsResp.json();
          state.runs = runsData.runs || [];
          renderRunList();
          selectRun(jData.spec_name);
          setTimeout(() => els.runModal.classList.add("hidden"), 900);
          break;
        }
        if (jData.status === "failed") {
          throw new Error(jData.error || "Synthesis job failed");
        }
      }
    } catch (err) {
      els.jobConsoleLog.textContent += `\n[ERROR] ${err.message}`;
    } finally {
      els.btnSubmitRun.disabled = false;
    }
  });

  document.getElementById("btnViewAuditLog").addEventListener("click", async () => {
    let events = state.staticGuiEvents;
    if (state.mode === "live_eda") {
      try {
        const resp = await fetch(`${state.apiBase}/api/gui-audit-log`, { cache: "no-store" });
        const data = await resp.json();
        events = data.events || [];
      } catch {
        // fallback to static
      }
    }
    els.lightboxTitle.textContent = "GUI Window Confinement & OpenCV Audit Trail (gui_audit_log.jsonl)";
    els.lightboxBody.innerHTML = `<pre class="code-viewer">${escapeHtml(
      events.map((e) => JSON.stringify(e)).join("\n")
    )}</pre>`;
    els.lightboxModal.classList.remove("hidden");
  });

  initData();
})();
