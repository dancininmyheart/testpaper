from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from random import Random
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from demo import http_app as _http_app
from demo import service as _service

# Keep direct references for monkeypatch-friendly tests.
_post_with_retry = _service._post_with_retry


def _call_llm_json(*args, **kwargs):
    # Allow tests patching demo_server._post_with_retry to affect service call path.
    old_post = _service._post_with_retry
    try:
        _service._post_with_retry = globals().get("_post_with_retry", old_post)
        return _service._call_llm_json(*args, **kwargs)
    finally:
        _service._post_with_retry = old_post


_ANALYSIS_UI_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>个人时序分析与班级群体分析</title>
  <style>
    :root {
      --bg: #f5f7fb;
      --card: #ffffff;
      --line: #dce4f0;
      --text: #0f2340;
      --muted: #4f617d;
      --accent: #1d5dff;
      --accent-2: #1847bf;
      --warn: #d9480f;
      --good: #2b8a3e;
      --violet: #7c4dff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 5% 0%, #dbeafe 0%, transparent 35%),
        radial-gradient(circle at 90% 15%, #e0f2fe 0%, transparent 30%),
        var(--bg);
    }
    .wrap {
      max-width: 1280px;
      margin: 20px auto 40px;
      padding: 0 16px;
      display: grid;
      gap: 14px;
    }
    .card {
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
      box-shadow: 0 12px 24px rgba(15, 35, 64, 0.07);
    }
    h1, h2, h3 { margin: 0 0 8px; }
    h2 { font-size: 20px; }
    h3 { font-size: 16px; }
    .muted { color: var(--muted); font-size: 13px; line-height: 1.45; }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
      align-items: center;
    }
    .field {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
      background: #f3f7ff;
      border: 1px solid #d4e0f4;
      border-radius: 9px;
      padding: 6px 8px;
    }
    .field input {
      width: 92px;
      border: 1px solid #c5d3ea;
      border-radius: 6px;
      padding: 4px 6px;
      font-size: 13px;
      color: var(--text);
      background: #fff;
    }
    .field select {
      min-width: 120px;
      border: 1px solid #c5d3ea;
      border-radius: 6px;
      padding: 4px 6px;
      font-size: 13px;
      color: var(--text);
      background: #fff;
    }
    .field input.text {
      width: 120px;
    }
    button {
      border: 0;
      border-radius: 10px;
      padding: 9px 13px;
      font-weight: 700;
      cursor: pointer;
      color: #fff;
      background: linear-gradient(120deg, var(--accent), var(--accent-2));
    }
    button.ghost {
      color: #1a4ac7;
      background: #e8f0ff;
    }
    button:disabled { opacity: 0.65; cursor: not-allowed; }
    .status { font-size: 13px; color: var(--muted); }
    .status.error { color: #c92a2a; font-weight: 700; }
    .grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
    }
    .metric {
      border: 1px solid #d7e2f7;
      border-radius: 11px;
      background: #f7faff;
      padding: 8px 10px;
    }
    .metric .k { font-size: 12px; color: var(--muted); margin-bottom: 3px; }
    .metric .v { font-size: 19px; font-weight: 800; line-height: 1.2; word-break: break-word; }
    .row2 {
      display: grid;
      gap: 12px;
      grid-template-columns: 1.2fr 1fr;
      align-items: start;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12.5px;
    }
    th, td {
      border: 1px solid #dde6f5;
      padding: 7px 8px;
      text-align: left;
      vertical-align: top;
    }
    th { background: #f2f7ff; }
    .good { color: var(--good); font-weight: 700; }
    .warn { color: var(--warn); font-weight: 700; }
    .violet { color: var(--violet); font-weight: 700; }
    .empty { color: var(--muted); font-size: 13px; }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      background: #1d5dff;
    }
    @media (max-width: 1024px) {
      .grid { grid-template-columns: repeat(2, minmax(150px, 1fr)); }
      .row2 { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="card">
      <h1>个人时序分析 + 班级群体分析</h1>
      <div class="muted">时序分析聚焦单个学生历史知识点掌握和素养变化；群体分析聚焦班级知识点掌握汇总与整体素养雷达图。</div>
      <div class="toolbar">
        <label class="field">随机种子 <input id="seedInput" type="number" value="20260418" /></label>
        <label class="field">时间点数 <input id="periodInput" type="number" min="6" max="24" value="10" /></label>
        <label class="field">知识点数 <input id="knowledgeInput" type="number" min="4" max="10" value="6" /></label>
        <label class="field">班级人数 <input id="studentInput" type="number" min="30" max="300" value="120" /></label>
        <label class="field">学生ID <input id="studentIdInput" class="text" type="text" value="S001" /></label>
        <label class="field">班级名 <input id="classInput" class="text" type="text" value="八年级(1)班" /></label>
        <label class="field">数据源
          <select id="sourceInput">
            <option value="analysis_mock">分析页仿真</option>
            <option value="profile_export_mock">导出格式仿真</option>
          </select>
        </label>
        <button id="genBtn">生成模拟数据</button>
        <button id="sampleBtn" class="ghost">恢复默认参数</button>
        <div id="status" class="status">等待生成</div>
      </div>
    </section>

    <section class="card">
      <h2>时序分析（个人）</h2>
      <div id="temporalSummary" class="empty">暂无数据</div>
      <div class="row2" style="margin-top: 10px;">
        <div>
          <h3>个人总体变化趋势（掌握度 / 素养）</h3>
          <svg id="personalTrendChart" viewBox="0 0 760 260" width="100%" height="260" role="img" aria-label="personal trend chart"></svg>
        </div>
        <div>
          <h3>最近学习事件</h3>
          <div id="recentEventTable" class="empty">暂无数据</div>
        </div>
      </div>
      <div class="row2" style="margin-top: 12px;">
        <div>
          <h3>历史知识点掌握变化</h3>
          <div id="knowledgeHistoryTable" class="empty">暂无数据</div>
        </div>
        <div>
          <h3>历史素养维度变化</h3>
          <div id="literacyHistoryTable" class="empty">暂无数据</div>
        </div>
      </div>
    </section>

    <section class="card">
      <h2>个人画像（导出格式）</h2>
      <div id="profileSummary" class="empty">暂无数据</div>
      <div class="row2" style="margin-top: 10px;">
        <div>
          <h3>掌握度画像</h3>
          <div id="profileMasteryTable" class="empty">暂无数据</div>
        </div>
        <div>
          <h3>错误类型分布</h3>
          <div id="profileErrorTable" class="empty">暂无数据</div>
        </div>
      </div>
      <div style="margin-top: 12px;">
        <h3>薄弱点与改进计划</h3>
        <div id="profileWeaknessTable" class="empty">暂无数据</div>
      </div>
    </section>

    <section class="card">
      <h2>群体分析（班级）</h2>
      <div id="groupSummary" class="empty">暂无数据</div>
      <div class="row2" style="margin-top: 10px;">
        <div>
          <h3>班级知识点掌握汇总</h3>
          <div id="classKnowledgeTable" class="empty">暂无数据</div>
        </div>
        <div>
          <h3>整体素养画像雷达图</h3>
          <svg id="literacyRadarChart" viewBox="0 0 360 360" width="100%" height="340" role="img" aria-label="literacy radar chart"></svg>
          <div id="radarLegend" class="legend"></div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const $ = (id) => document.getElementById(id);
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[ch]);
    const pct = (v) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      return `${(n * 100).toFixed(1)}%`;
    };
    const fmt = (v, d = 3) => {
      const n = Number(v);
      if (!Number.isFinite(n)) return "-";
      return n.toFixed(d);
    };
    function clamp01(v) {
      const n = Number(v);
      if (!Number.isFinite(n)) return 0;
      return Math.max(0, Math.min(1, n));
    }
    function levelByScore(score) {
      const s = Number(score);
      if (!Number.isFinite(s)) return "-";
      if (s >= 0.8) return "熟练";
      if (s >= 0.65) return "稳定";
      if (s >= 0.5) return "发展中";
      return "薄弱";
    }
    function buildRecentPeriods(count) {
      const total = Math.max(2, Number(count) || 8);
      const out = [];
      const now = new Date();
      for (let i = total - 1; i >= 0; i -= 1) {
        const d = new Date(now.getTime() - i * 7 * 24 * 60 * 60 * 1000);
        const mm = String(d.getMonth() + 1).padStart(2, "0");
        const dd = String(d.getDate()).padStart(2, "0");
        out.push(`${mm}-${dd}`);
      }
      return out;
    }
    function buildLinearSeries(start, end, count) {
      const n = Math.max(2, Number(count) || 8);
      const s = clamp01(start);
      const e = clamp01(end);
      return Array.from({ length: n }, (_, idx) => {
        const t = idx / (n - 1);
        return Number((s + (e - s) * t).toFixed(4));
      });
    }
    function avgSeries(rows) {
      if (!Array.isArray(rows) || rows.length === 0) return [];
      const len = rows[0].length;
      return Array.from({ length: len }, (_, idx) => {
        const total = rows.reduce((sum, row) => sum + Number(row[idx] || 0), 0);
        return Number((total / rows.length).toFixed(4));
      });
    }
    function scoreClass(v) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "";
      if (n >= 0.7) return "good";
      if (n < 0.5) return "warn";
      return "";
    }
    function deltaClass(v) {
      const n = Number(v);
      if (!Number.isFinite(n)) return "";
      return n >= 0 ? "good" : "warn";
    }
    function setStatus(text, isError = false) {
      const el = $("status");
      el.textContent = text;
      el.className = isError ? "status error" : "status";
    }
    function readParams() {
      return {
        seed: Number($("seedInput").value || 0),
        periods: Number($("periodInput").value || 10),
        knowledge_points: Number($("knowledgeInput").value || 6),
        students: Number($("studentInput").value || 120),
        student_id: $("studentIdInput").value || "S001",
        class_name: $("classInput").value || "八年级(1)班",
        data_source: $("sourceInput").value || "analysis_mock",
      };
    }
    function resetDefaults() {
      $("seedInput").value = "20260418";
      $("periodInput").value = "10";
      $("knowledgeInput").value = "6";
      $("studentInput").value = "120";
      $("studentIdInput").value = "S001";
      $("classInput").value = "八年级(1)班";
      $("sourceInput").value = "analysis_mock";
    }
    function convertProfileExportToAnalysis(exportData, params) {
      const analysisResult = (exportData && exportData.analysis_result) || {};
      const profile = analysisResult.student_profile || {};
      const masteryRows = Array.isArray(profile.mastery) ? profile.mastery : [];
      const weaknesses = Array.isArray(profile.weaknesses) ? profile.weaknesses : [];
      const errorProfile = (profile && typeof profile.error_profile === "object" && profile.error_profile) || {};
      const periods = buildRecentPeriods(Math.max(6, Math.min(12, Number(params.periods) || 8)));
      const takeCount = Math.max(1, Number(params.knowledge_points) || 6);
      const selectedMastery = masteryRows.slice(0, takeCount);

      const knowledgeHistory = selectedMastery.map((row, idx) => {
        const current = clamp01(Number(row.value));
        const start = clamp01(current - (0.06 + (idx % 3) * 0.02));
        const series = buildLinearSeries(start, current, periods.length);
        return {
          knowledge_id: row.skill_id || `skill_${idx + 1}`,
          knowledge_name: row.skill_id || `skill_${idx + 1}`,
          periods,
          series,
          start_mastery: series[0],
          current_mastery: series[series.length - 1],
          delta_mastery: Number((series[series.length - 1] - series[0]).toFixed(4)),
          level: levelByScore(series[series.length - 1]),
        };
      });

      const totalErr =
        Number(errorProfile.concept || 0) +
        Number(errorProfile.calculation || 0) +
        Number(errorProfile.reading || 0) +
        Number(errorProfile.strategy || 0) +
        Number(errorProfile.unknown || 0) || 1;

      const logical = clamp01(0.82 - (Number(errorProfile.strategy || 0) / totalErr) * 0.45);
      const abstraction = clamp01(0.8 - (Number(errorProfile.concept || 0) / totalErr) * 0.45);
      const computation = clamp01(0.8 - (Number(errorProfile.calculation || 0) / totalErr) * 0.50);
      const representation = clamp01(0.78 - (Number(errorProfile.reading || 0) / totalErr) * 0.40);
      const reflection = clamp01(0.68 + (Number(errorProfile.unknown || 0) / totalErr) * 0.10);

      const literacyDef = [
        ["logical_reasoning", "逻辑推理", logical],
        ["abstraction", "抽象建模", abstraction],
        ["computation", "运算规范", computation],
        ["representation", "表征转化", representation],
        ["reflection", "反思修正", reflection],
      ];
      const literacyHistory = literacyDef.map((item, idx) => {
        const current = Number(item[2]);
        const start = clamp01(current - (0.04 + idx * 0.006));
        const series = buildLinearSeries(start, current, periods.length);
        return {
          dimension_id: item[0],
          dimension_name: item[1],
          periods,
          series,
          start_score: series[0],
          current_score: series[series.length - 1],
          delta_score: Number((series[series.length - 1] - series[0]).toFixed(4)),
        };
      });

      const overallMastery = avgSeries(knowledgeHistory.map((item) => item.series));
      const overallLiteracy = avgSeries(literacyHistory.map((item) => item.series));
      const weakest = knowledgeHistory
        .slice()
        .sort((a, b) => Number(a.current_mastery) - Number(b.current_mastery))[0];

      const recentEvents = weaknesses.slice(0, 6).map((item, idx) => {
        const sid = item.skill_id || `skill_${idx + 1}`;
        const kh = knowledgeHistory.find((x) => x.knowledge_id === sid) || knowledgeHistory[idx % Math.max(knowledgeHistory.length, 1)];
        const current = kh ? Number(kh.current_mastery || 0.6) : 0.6;
        const before = clamp01(current - 0.04);
        const impact =
          item.priority === "high"
            ? -0.04
            : item.priority === "medium"
              ? -0.02
              : -0.01;
        return {
          date: periods[Math.max(0, periods.length - 1 - idx)],
          knowledge_id: sid,
          knowledge_name: sid,
          mastery_before: Number(before.toFixed(4)),
          mastery_after: Number(current.toFixed(4)),
          literacy_impact: Number(impact.toFixed(4)),
          note: item.symptom || item.suggestion || "错因归纳与复盘",
        };
      });

      const classKnowledge = knowledgeHistory.map((item) => {
        const avg = clamp01(Number(item.current_mastery) + 0.03);
        const passRate = clamp01(avg * 0.92 + 0.04);
        const lowCount = Math.round((1 - avg) * Number(params.students || 120) * 0.55);
        return {
          knowledge_id: item.knowledge_id,
          knowledge_name: item.knowledge_name,
          avg_mastery: Number(avg.toFixed(4)),
          pass_rate: Number(passRate.toFixed(4)),
          low_mastery_count: lowCount,
          priority: avg < 0.5 ? "高" : avg < 0.65 ? "中" : "低",
        };
      }).sort((a, b) => Number(a.avg_mastery) - Number(b.avg_mastery));

      const radarDims = literacyHistory.map((item) => ({
        dimension_id: item.dimension_id,
        dimension_name: item.dimension_name,
        score: Number(item.current_score),
      }));
      const classAvgMastery = classKnowledge.length
        ? Number((classKnowledge.reduce((s, x) => s + Number(x.avg_mastery || 0), 0) / classKnowledge.length).toFixed(4))
        : 0.6;
      const classAvgLiteracy = radarDims.length
        ? Number((radarDims.reduce((s, x) => s + Number(x.score || 0), 0) / radarDims.length).toFixed(4))
        : 0.62;
      const riskRate = Number(clamp01(0.08 + (0.65 - classAvgMastery) * 0.5).toFixed(4));

      return {
        temporal_analysis: {
          student: {
            student_id: profile.student_id || params.student_id,
            name: "模拟学生",
            class_name: params.class_name,
          },
          summary: {
            window_start: periods[0],
            window_end: periods[periods.length - 1],
            mastery_gain: Number((overallMastery[overallMastery.length - 1] - overallMastery[0]).toFixed(4)),
            literacy_gain: Number((overallLiteracy[overallLiteracy.length - 1] - overallLiteracy[0]).toFixed(4)),
            knowledge_points_count: knowledgeHistory.length,
            current_literacy: overallLiteracy[overallLiteracy.length - 1] || 0,
            weakest_knowledge: weakest ? weakest.knowledge_name : "-",
            warning_events: weaknesses.filter((w) => w.priority === "high").length,
          },
          series: {
            periods,
            overall_mastery: overallMastery,
            overall_literacy: overallLiteracy,
          },
          knowledge_history: knowledgeHistory,
          literacy_history: literacyHistory,
          recent_events: recentEvents,
        },
        group_analysis: {
          class_profile: {
            class_id: "CLS-01",
            class_name: params.class_name,
            student_count: Number(params.students || 120),
            avg_mastery: classAvgMastery,
            avg_literacy: classAvgLiteracy,
            risk_rate: riskRate,
            focus_weak_knowledge: classKnowledge.slice(0, 3).map((x) => x.knowledge_name),
          },
          knowledge_mastery_overview: classKnowledge,
          literacy_radar: {
            dimensions: radarDims,
          },
        },
      };
    }
    function renderProfileExport(profile) {
      if (!profile || typeof profile !== "object") {
        $("profileSummary").innerHTML = '<div class="empty">当前数据源未提供 student_profile</div>';
        $("profileMasteryTable").innerHTML = '<div class="empty">暂无数据</div>';
        $("profileErrorTable").innerHTML = '<div class="empty">暂无数据</div>';
        $("profileWeaknessTable").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }

      const mastery = Array.isArray(profile.mastery) ? profile.mastery : [];
      const weaknesses = Array.isArray(profile.weaknesses) ? profile.weaknesses : [];
      const errorProfile = (profile.error_profile && typeof profile.error_profile === "object") ? profile.error_profile : {};

      $("profileSummary").innerHTML = `
        <div class="grid">
          <div class="metric"><div class="k">student_id</div><div class="v">${esc(profile.student_id || "-")}</div></div>
          <div class="metric"><div class="k">掌握技能数</div><div class="v">${esc(mastery.length)}</div></div>
          <div class="metric"><div class="k">薄弱点数</div><div class="v warn">${esc(weaknesses.length)}</div></div>
          <div class="metric"><div class="k">画像总结</div><div class="v" style="font-size:14px;font-weight:600;line-height:1.45;">${esc(profile.summary || "-")}</div></div>
        </div>
      `;

      const masteryRows = mastery.map((item) => `
        <tr>
          <td>${esc(item.skill_id)}</td>
          <td class="${scoreClass(item.value)}">${pct(item.value)}</td>
          <td>${esc(item.reason || "-")}</td>
        </tr>
      `).join("");
      $("profileMasteryTable").innerHTML = `
        <table>
          <thead><tr><th>skill_id</th><th>value</th><th>reason</th></tr></thead>
          <tbody>${masteryRows || '<tr><td colspan="3">暂无</td></tr>'}</tbody>
        </table>
      `;

      const errorRows = ["concept", "calculation", "reading", "strategy", "unknown"].map((k) => `
        <tr>
          <td>${k}</td>
          <td>${esc(Number(errorProfile[k] || 0))}</td>
        </tr>
      `).join("");
      $("profileErrorTable").innerHTML = `
        <table>
          <thead><tr><th>error_type</th><th>count</th></tr></thead>
          <tbody>${errorRows}</tbody>
        </table>
      `;

      const weaknessRows = weaknesses.map((item) => `
        <tr>
          <td>${esc(item.skill_id)}</td>
          <td class="${item.priority === "high" ? "warn" : ""}">${esc(item.priority || "-")}</td>
          <td>${esc(item.symptom || "-")}</td>
          <td>${esc(item.cause || "-")}</td>
          <td>${esc(Array.isArray(item.improvement_steps) ? item.improvement_steps.join("；") : "-")}</td>
          <td>${esc(item.practice_plan || "-")}</td>
          <td>${esc(item.success_criteria || "-")}</td>
        </tr>
      `).join("");
      $("profileWeaknessTable").innerHTML = `
        <table>
          <thead><tr><th>skill_id</th><th>priority</th><th>symptom</th><th>cause</th><th>improvement_steps</th><th>practice_plan</th><th>success_criteria</th></tr></thead>
          <tbody>${weaknessRows || '<tr><td colspan="7">暂无</td></tr>'}</tbody>
        </table>
      `;
    }
    function renderTemporalSummary(summary, student) {
      if (!summary || typeof summary !== "object") {
        $("temporalSummary").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      $("temporalSummary").innerHTML = `
        <div class="grid">
          <div class="metric"><div class="k">学生</div><div class="v">${esc((student && student.name) || "-")} (${esc((student && student.student_id) || "-")})</div></div>
          <div class="metric"><div class="k">时间窗口</div><div class="v">${esc(summary.window_start)} - ${esc(summary.window_end)}</div></div>
          <div class="metric"><div class="k">掌握度增量</div><div class="v ${deltaClass(summary.mastery_gain)}">${pct(summary.mastery_gain)}</div></div>
          <div class="metric"><div class="k">素养增量</div><div class="v ${deltaClass(summary.literacy_gain)}">${pct(summary.literacy_gain)}</div></div>
          <div class="metric"><div class="k">当前知识点数</div><div class="v">${esc(summary.knowledge_points_count)}</div></div>
          <div class="metric"><div class="k">当前素养均分</div><div class="v ${scoreClass(summary.current_literacy)}">${pct(summary.current_literacy)}</div></div>
          <div class="metric"><div class="k">薄弱知识点</div><div class="v warn">${esc(summary.weakest_knowledge || "-")}</div></div>
          <div class="metric"><div class="k">预警事件数</div><div class="v warn">${esc(summary.warning_events || 0)}</div></div>
        </div>
      `;
    }
    function renderDualLineChart(svgId, periods, seriesA, seriesB, labelA, labelB, colorA, colorB) {
      const svg = $(svgId);
      if (!svg || !Array.isArray(periods) || periods.length === 0) {
        if (svg) svg.innerHTML = "";
        return;
      }
      const width = 760;
      const height = 260;
      const left = 44;
      const right = 18;
      const top = 16;
      const bottom = 42;
      const cw = width - left - right;
      const ch = height - top - bottom;
      const xStep = periods.length > 1 ? cw / (periods.length - 1) : 0;
      const y = (v) => top + (1 - Number(v || 0)) * ch;
      const points = (arr) => arr.map((v, i) => `${left + i * xStep},${y(v)}`).join(" ");

      const grid = [0, 0.25, 0.5, 0.75, 1].map((t) => {
        const yy = y(t);
        return `<line x1="${left}" y1="${yy}" x2="${width - right}" y2="${yy}" stroke="#e6edf9" />
                <text x="8" y="${yy + 4}" font-size="11" fill="#6b7f9e">${(t * 100).toFixed(0)}%</text>`;
      }).join("");

      const labels = periods.map((label, idx) => (
        `<text x="${left + idx * xStep}" y="${height - 16}" text-anchor="middle" font-size="11" fill="#6b7f9e">${esc(label)}</text>`
      )).join("");

      svg.innerHTML = `
        <rect x="0" y="0" width="${width}" height="${height}" fill="#fff" />
        ${grid}
        <polyline fill="none" stroke="${colorA}" stroke-width="3" points="${points(seriesA || [])}" />
        <polyline fill="none" stroke="${colorB}" stroke-width="3" stroke-dasharray="5 4" points="${points(seriesB || [])}" />
        <text x="${left}" y="${top}" font-size="12" fill="${colorA}">${esc(labelA)}</text>
        <text x="${left + 92}" y="${top}" font-size="12" fill="${colorB}">${esc(labelB)}</text>
        ${labels}
      `;
    }
    function renderRecentEvents(items) {
      if (!Array.isArray(items) || items.length === 0) {
        $("recentEventTable").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      const rows = items.map((x) => `
        <tr>
          <td>${esc(x.date)}</td>
          <td>${esc(x.knowledge_name)}</td>
          <td>${fmt(x.mastery_before, 3)} -> ${fmt(x.mastery_after, 3)}</td>
          <td class="${deltaClass(x.literacy_impact)}">${pct(x.literacy_impact)}</td>
          <td>${esc(x.note)}</td>
        </tr>
      `).join("");
      $("recentEventTable").innerHTML = `
        <table>
          <thead><tr><th>日期</th><th>知识点</th><th>掌握度变化</th><th>素养影响</th><th>说明</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }
    function renderKnowledgeHistory(items) {
      if (!Array.isArray(items) || items.length === 0) {
        $("knowledgeHistoryTable").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      const rows = items.map((x) => `
        <tr>
          <td>${esc(x.knowledge_name)}</td>
          <td>${fmt(x.start_mastery, 3)}</td>
          <td class="${scoreClass(x.current_mastery)}">${fmt(x.current_mastery, 3)}</td>
          <td class="${deltaClass(x.delta_mastery)}">${pct(x.delta_mastery)}</td>
          <td>${esc(x.level)}</td>
        </tr>
      `).join("");
      $("knowledgeHistoryTable").innerHTML = `
        <table>
          <thead><tr><th>知识点</th><th>起始</th><th>当前</th><th>变化</th><th>水平</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }
    function renderLiteracyHistory(items) {
      if (!Array.isArray(items) || items.length === 0) {
        $("literacyHistoryTable").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      const rows = items.map((x) => `
        <tr>
          <td>${esc(x.dimension_name)}</td>
          <td>${fmt(x.start_score, 3)}</td>
          <td class="${scoreClass(x.current_score)}">${fmt(x.current_score, 3)}</td>
          <td class="${deltaClass(x.delta_score)}">${pct(x.delta_score)}</td>
        </tr>
      `).join("");
      $("literacyHistoryTable").innerHTML = `
        <table>
          <thead><tr><th>素养维度</th><th>起始</th><th>当前</th><th>变化</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }
    function renderGroupSummary(profile) {
      if (!profile || typeof profile !== "object") {
        $("groupSummary").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      $("groupSummary").innerHTML = `
        <div class="grid">
          <div class="metric"><div class="k">班级</div><div class="v">${esc(profile.class_name)} (${esc(profile.class_id)})</div></div>
          <div class="metric"><div class="k">人数</div><div class="v">${esc(profile.student_count)}</div></div>
          <div class="metric"><div class="k">班级平均掌握度</div><div class="v ${scoreClass(profile.avg_mastery)}">${pct(profile.avg_mastery)}</div></div>
          <div class="metric"><div class="k">班级平均素养</div><div class="v ${scoreClass(profile.avg_literacy)}">${pct(profile.avg_literacy)}</div></div>
          <div class="metric"><div class="k">风险学生占比</div><div class="v warn">${pct(profile.risk_rate)}</div></div>
          <div class="metric"><div class="k">重点薄弱知识点</div><div class="v warn">${esc((profile.focus_weak_knowledge || []).join(", "))}</div></div>
        </div>
      `;
    }
    function renderClassKnowledge(items) {
      if (!Array.isArray(items) || items.length === 0) {
        $("classKnowledgeTable").innerHTML = '<div class="empty">暂无数据</div>';
        return;
      }
      const rows = items.map((x) => `
        <tr>
          <td>${esc(x.knowledge_name)}</td>
          <td class="${scoreClass(x.avg_mastery)}">${pct(x.avg_mastery)}</td>
          <td>${pct(x.pass_rate)}</td>
          <td class="warn">${esc(x.low_mastery_count)}</td>
          <td>${esc(x.priority)}</td>
        </tr>
      `).join("");
      $("classKnowledgeTable").innerHTML = `
        <table>
          <thead><tr><th>知识点</th><th>平均掌握度</th><th>达标率</th><th>低掌握人数</th><th>优先级</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }
    function renderLiteracyRadar(radar) {
      const svg = $("literacyRadarChart");
      const legend = $("radarLegend");
      if (!radar || !Array.isArray(radar.dimensions) || radar.dimensions.length < 3) {
        svg.innerHTML = "";
        legend.innerHTML = "";
        return;
      }
      const dims = radar.dimensions;
      const n = dims.length;
      const cx = 180;
      const cy = 180;
      const r = 120;
      const levels = [0.25, 0.5, 0.75, 1.0];
      const angle = (idx) => (Math.PI * 2 * idx) / n - Math.PI / 2;
      const point = (idx, scale) => ({
        x: cx + Math.cos(angle(idx)) * r * scale,
        y: cy + Math.sin(angle(idx)) * r * scale,
      });

      const rings = levels.map((lv) => {
        const pts = dims.map((_, i) => {
          const p = point(i, lv);
          return `${p.x},${p.y}`;
        }).join(" ");
        return `<polygon points="${pts}" fill="none" stroke="#dce6f7" stroke-width="1" />`;
      }).join("");

      const axes = dims.map((d, i) => {
        const p = point(i, 1);
        const label = point(i, 1.1);
        return `
          <line x1="${cx}" y1="${cy}" x2="${p.x}" y2="${p.y}" stroke="#c9d8f2" stroke-width="1" />
          <text x="${label.x}" y="${label.y}" font-size="11" fill="#4f617d" text-anchor="middle">${esc(d.dimension_name)}</text>
        `;
      }).join("");

      const polyPts = dims.map((d, i) => {
        const p = point(i, Number(d.score || 0));
        return `${p.x},${p.y}`;
      }).join(" ");

      const points = dims.map((d, i) => {
        const p = point(i, Number(d.score || 0));
        return `<circle cx="${p.x}" cy="${p.y}" r="3" fill="#1d5dff" />`;
      }).join("");

      svg.innerHTML = `
        <rect x="0" y="0" width="360" height="360" fill="#fff" />
        ${rings}
        ${axes}
        <polygon points="${polyPts}" fill="rgba(29,93,255,0.24)" stroke="#1d5dff" stroke-width="2" />
        ${points}
      `;

      legend.innerHTML = dims.map((d, idx) => `
        <span class="legend-item">
          <span class="dot" style="background:${idx % 2 === 0 ? "#1d5dff" : "#7c4dff"}"></span>
          ${esc(d.dimension_name)}: <strong>${pct(d.score)}</strong>
        </span>
      `).join("");
    }
    function renderResult(result) {
      const temporal = (result && result.temporal_analysis) || {};
      const group = (result && result.group_analysis) || {};
      renderTemporalSummary(temporal.summary || {}, temporal.student || {});
      renderDualLineChart(
        "personalTrendChart",
        (temporal.series && temporal.series.periods) || [],
        (temporal.series && temporal.series.overall_mastery) || [],
        (temporal.series && temporal.series.overall_literacy) || [],
        "总体知识掌握",
        "总体素养",
        "#1d5dff",
        "#7c4dff"
      );
      renderRecentEvents(temporal.recent_events || []);
      renderKnowledgeHistory(temporal.knowledge_history || []);
      renderLiteracyHistory(temporal.literacy_history || []);
      renderGroupSummary(group.class_profile || {});
      renderClassKnowledge(group.knowledge_mastery_overview || []);
      renderLiteracyRadar(group.literacy_radar || {});
    }
    async function generateData() {
      const btn = $("genBtn");
      btn.disabled = true;
      setStatus("生成中...");
      try {
        const params = readParams();
        if (params.data_source === "profile_export_mock") {
          const resp = await fetch("/api/demo/profile/mock-export", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              seed: params.seed,
              student_id: params.student_id,
              input_mode: "paper_answer_sheet",
              question_count: 27,
              paper_image_count: 4,
            }),
          });
          const exportData = await resp.json();
          if (!resp.ok || !exportData.analysis_result) {
            throw new Error((exportData && (exportData.error || exportData.detail)) || `HTTP ${resp.status}`);
          }
          const converted = convertProfileExportToAnalysis(exportData, params);
          renderResult(converted);
          renderProfileExport(exportData.analysis_result.student_profile || null);
          setStatus(`已生成（导出格式），时间 ${new Date().toLocaleTimeString()}`);
        } else {
          const resp = await fetch("/api/demo/analysis/mock", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
          });
          const data = await resp.json();
          if (!resp.ok || !data.ok) {
            throw new Error((data && (data.error || data.detail)) || `HTTP ${resp.status}`);
          }
          renderResult(data.result || {});
          renderProfileExport(null);
          setStatus(`已生成（分析页仿真），时间 ${new Date().toLocaleTimeString()}`);
        }
      } catch (err) {
        renderResult({});
        renderProfileExport(null);
        setStatus(err.message || String(err), true);
      } finally {
        btn.disabled = false;
      }
    }
    $("genBtn").addEventListener("click", generateData);
    $("sampleBtn").addEventListener("click", () => {
      resetDefaults();
      setStatus("已恢复默认参数");
    });
    $("sourceInput").addEventListener("change", () => {
      setStatus(`已切换数据源：${$("sourceInput").value}`);
    });
    generateData();
  </script>
</body>
</html>
"""


def _read_json_body(handler: Any) -> Dict[str, Any]:
    content_len = int(handler.headers.get("Content-Length", "0"))
    if content_len <= 0:
        return {}
    raw = handler.rfile.read(content_len)
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request must be json object")
    return payload


def _to_int(raw: Any, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _to_str(raw: Any, default: str) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _clamp_float(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _level_by_score(score: float) -> str:
    if score >= 0.8:
        return "熟练"
    if score >= 0.65:
        return "稳定"
    if score >= 0.5:
        return "发展中"
    return "薄弱"


def _series_average(values: List[List[float]]) -> List[float]:
    if not values:
        return []
    length = len(values[0])
    result: List[float] = []
    for idx in range(length):
        result.append(round(sum(row[idx] for row in values) / len(values), 4))
    return result


def _build_mock_analysis_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now()
    seed = _to_int(payload.get("seed"), 20260418)
    periods = _clamp(_to_int(payload.get("periods"), 10), 6, 24)
    knowledge_points = _clamp(_to_int(payload.get("knowledge_points"), 6), 4, 10)
    students = _clamp(_to_int(payload.get("students"), 120), 30, 300)
    student_id = _to_str(payload.get("student_id"), "S001")
    class_name = _to_str(payload.get("class_name"), "八年级(1)班")
    rng = Random(seed)

    period_labels: List[str] = []
    for idx in range(periods):
        point_date = now - timedelta(days=(periods - 1 - idx) * 7)
        period_labels.append(point_date.strftime("%m-%d"))

    candidate_knowledges = [
        ("eq.linear_transform", "一次方程移项"),
        ("eq.fraction_solve", "分式方程求解"),
        ("func.domain_range", "函数定义域值域"),
        ("geo.triangle_similarity", "三角形相似"),
        ("geo.parallel_proof", "平行线性质证明"),
        ("stats.mean_variance", "均值方差"),
        ("algebra.factorization", "因式分解"),
        ("algebra.root_equation", "一元二次方程"),
        ("model.word_problem", "应用题建模"),
        ("logic.reasoning_chain", "推理链构造"),
    ]
    selected = candidate_knowledges[:knowledge_points]

    knowledge_history = []
    knowledge_series_rows: List[List[float]] = []
    for kid, name in selected:
        start = rng.uniform(0.35, 0.68)
        series = []
        current = start
        for _ in range(periods):
            current = _clamp_float(current + rng.uniform(-0.012, 0.035), 0.18, 0.98)
            series.append(round(current, 4))
        knowledge_series_rows.append(series)
        delta = round(series[-1] - series[0], 4)
        knowledge_history.append(
            {
                "knowledge_id": kid,
                "knowledge_name": name,
                "periods": period_labels,
                "series": series,
                "start_mastery": series[0],
                "current_mastery": series[-1],
                "delta_mastery": delta,
                "level": _level_by_score(series[-1]),
            }
        )

    literacy_dims = [
        ("logical_reasoning", "逻辑推理"),
        ("abstraction", "抽象建模"),
        ("computation", "运算规范"),
        ("representation", "表征转化"),
        ("reflection", "反思修正"),
    ]
    literacy_history = []
    literacy_series_rows: List[List[float]] = []
    for dim_id, dim_name in literacy_dims:
        start = rng.uniform(0.42, 0.72)
        series = []
        current = start
        for _ in range(periods):
            current = _clamp_float(current + rng.uniform(-0.01, 0.026), 0.20, 0.96)
            series.append(round(current, 4))
        literacy_series_rows.append(series)
        delta = round(series[-1] - series[0], 4)
        literacy_history.append(
            {
                "dimension_id": dim_id,
                "dimension_name": dim_name,
                "periods": period_labels,
                "series": series,
                "start_score": series[0],
                "current_score": series[-1],
                "delta_score": delta,
            }
        )

    overall_mastery = _series_average(knowledge_series_rows)
    overall_literacy = _series_average(literacy_series_rows)

    weakest = min(knowledge_history, key=lambda item: float(item["current_mastery"])) if knowledge_history else None
    warning_events = sum(1 for item in knowledge_history if float(item["delta_mastery"]) < 0.0)

    event_notes = [
        "阶段测验错因集中在计算步骤",
        "课堂提问表现提升明显",
        "迁移题型出现思路中断",
        "作业订正后同类题稳定",
        "表达步骤不完整导致失分",
        "复习后概念辨析改善",
    ]
    recent_events = []
    event_count = min(8, periods)
    for idx in range(event_count):
        k = knowledge_history[idx % len(knowledge_history)]
        sample_pos = max(1, periods - event_count + idx)
        before = float(k["series"][sample_pos - 1])
        after = float(k["series"][sample_pos])
        recent_events.append(
            {
                "date": period_labels[sample_pos],
                "knowledge_id": k["knowledge_id"],
                "knowledge_name": k["knowledge_name"],
                "mastery_before": round(before, 4),
                "mastery_after": round(after, 4),
                "literacy_impact": round(rng.uniform(-0.03, 0.05), 4),
                "note": event_notes[idx % len(event_notes)],
            }
        )

    student_names = ["王子涵", "李思睿", "张雨桐", "赵锦程", "孙若彤", "周泽宇"]
    student_name = student_names[seed % len(student_names)]

    temporal_analysis = {
        "student": {
            "student_id": student_id,
            "name": student_name,
            "class_name": class_name,
        },
        "summary": {
            "window_start": period_labels[0],
            "window_end": period_labels[-1],
            "mastery_gain": round(overall_mastery[-1] - overall_mastery[0], 4),
            "literacy_gain": round(overall_literacy[-1] - overall_literacy[0], 4),
            "knowledge_points_count": len(knowledge_history),
            "current_literacy": overall_literacy[-1],
            "weakest_knowledge": weakest["knowledge_name"] if weakest else "",
            "warning_events": warning_events,
        },
        "series": {
            "periods": period_labels,
            "overall_mastery": overall_mastery,
            "overall_literacy": overall_literacy,
        },
        "knowledge_history": knowledge_history,
        "literacy_history": literacy_history,
        "recent_events": recent_events,
    }

    class_knowledge = []
    for item in knowledge_history:
        class_avg = _clamp_float(float(item["current_mastery"]) + rng.uniform(-0.08, 0.06), 0.2, 0.95)
        pass_rate = _clamp_float(class_avg * rng.uniform(0.85, 1.02), 0.1, 0.98)
        low_mastery = int(round((1 - class_avg) * students * rng.uniform(0.3, 0.7)))
        if class_avg < 0.5:
            priority = "高"
        elif class_avg < 0.65:
            priority = "中"
        else:
            priority = "低"
        class_knowledge.append(
            {
                "knowledge_id": item["knowledge_id"],
                "knowledge_name": item["knowledge_name"],
                "avg_mastery": round(class_avg, 4),
                "pass_rate": round(pass_rate, 4),
                "low_mastery_count": low_mastery,
                "priority": priority,
            }
        )
    class_knowledge.sort(key=lambda x: float(x["avg_mastery"]))

    radar_dims = []
    for dim in literacy_history:
        score = _clamp_float(float(dim["current_score"]) + rng.uniform(-0.06, 0.08), 0.2, 0.96)
        radar_dims.append(
            {
                "dimension_id": dim["dimension_id"],
                "dimension_name": dim["dimension_name"],
                "score": round(score, 4),
            }
        )

    class_avg_mastery = round(sum(float(x["avg_mastery"]) for x in class_knowledge) / max(len(class_knowledge), 1), 4)
    class_avg_literacy = round(sum(float(x["score"]) for x in radar_dims) / max(len(radar_dims), 1), 4)
    risk_rate = round(_clamp_float(0.08 + (0.65 - class_avg_mastery) * 0.5 + rng.uniform(-0.04, 0.05), 0.05, 0.55), 4)
    focus_weak = [item["knowledge_name"] for item in class_knowledge[:3]]

    group_analysis = {
        "class_profile": {
            "class_id": "CLS-01",
            "class_name": class_name,
            "student_count": students,
            "avg_mastery": class_avg_mastery,
            "avg_literacy": class_avg_literacy,
            "risk_rate": risk_rate,
            "focus_weak_knowledge": focus_weak,
        },
        "knowledge_mastery_overview": class_knowledge,
        "literacy_radar": {
            "dimensions": radar_dims,
        },
    }

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "parameters": {
            "seed": seed,
            "periods": periods,
            "knowledge_points": knowledge_points,
            "students": students,
            "student_id": student_id,
            "class_name": class_name,
        },
        "temporal_analysis": temporal_analysis,
        "group_analysis": group_analysis,
    }


def _build_mock_profile_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    seed = _to_int(payload.get("seed"), 20260418)
    student_id = _to_str(payload.get("student_id"), "41201200")
    input_mode = _to_str(payload.get("input_mode"), "paper_answer_sheet")
    question_count = _clamp(_to_int(payload.get("question_count"), 27), 18, 36)
    paper_image_count = _clamp(_to_int(payload.get("paper_image_count"), 4), 1, 8)
    rng = Random(seed)

    started_at = now - timedelta(seconds=rng.randint(420, 980))
    finished_at = now

    skill_pool = [
        ("eq.method.linear_transpose", "一次方程移项解法", "方程建模与求解步骤规范，检验意识较好"),
        ("root.formula.mul", "二次根式乘除", "根式化简过程完整，符号处理稳定"),
        ("geom.theorem.congruence", "全等三角形判定", "证明链清晰，条件使用准确"),
        ("stats.mean_variance", "均值与方差", "数据读取准确，计算较稳定"),
        ("root.method.add_sub", "同类二次根式加减", "同类项判定偶有混淆"),
        ("eq.theorem.quadratic_discriminant", "判别式与根的性质", "综合判断易遗漏限制条件"),
        ("geom.theorem.pythagorean", "勾股定理综合", "图形关系识别不够稳，复杂情境波动明显"),
        ("geom.properties.angle_bisector", "角平分线性质", "分类讨论意识不足，易出现漏解"),
        ("geom.method.construction", "几何作图与构造", "新定义题作答结构不完整"),
        ("model.word_problem", "应用题建模", "数量关系抽象速度偏慢"),
    ]
    skill_alias_map = {skill_id: alias for skill_id, alias, _ in skill_pool}

    base_mastery = {
        "eq.method.linear_transpose": 0.93,
        "root.formula.mul": 0.9,
        "geom.theorem.congruence": 0.87,
        "stats.mean_variance": 0.81,
        "root.method.add_sub": 0.68,
        "eq.theorem.quadratic_discriminant": 0.61,
        "geom.theorem.pythagorean": 0.56,
        "geom.properties.angle_bisector": 0.52,
        "geom.method.construction": 0.46,
        "model.word_problem": 0.58,
    }
    mastery_rows = []
    for skill_id, _, reason in skill_pool:
        val = _clamp_float(base_mastery[skill_id] + rng.uniform(-0.04, 0.04), 0.3, 0.97)
        mastery_rows.append(
            {
                "skill_id": skill_id,
                "value": round(val, 2),
                "reason": reason,
            }
        )
    mastery_rows.sort(key=lambda item: float(item["value"]), reverse=True)

    question_templates = [
        ("choice", "下列各式中属于最简二次根式的是", "root.method.add_sub"),
        ("choice", "已知一元二次方程，判别式满足的结论是", "eq.theorem.quadratic_discriminant"),
        ("fill", "化简并求值：二次根式运算", "root.formula.mul"),
        ("fill", "解方程并写出检验过程", "eq.method.linear_transpose"),
        ("solve", "在直角三角形中求未知边长", "geom.theorem.pythagorean"),
        ("solve", "证明两三角形全等并求角", "geom.theorem.congruence"),
        ("solve", "角平分线相关性质证明", "geom.properties.angle_bisector"),
        ("solve", "新定义几何背景下的构造与证明", "geom.method.construction"),
        ("solve", "阅读材料并完成建模求解", "model.word_problem"),
        ("choice", "某组数据的均值和方差判断", "stats.mean_variance"),
    ]

    mastery_lookup = {item["skill_id"]: float(item["value"]) for item in mastery_rows}
    question_analysis: List[Dict[str, Any]] = []
    structured_questions_full: List[Dict[str, Any]] = []
    answer_trace: List[Dict[str, Any]] = []
    answer_trace_display: List[Dict[str, Any]] = []
    error_counts = {"concept": 0, "calculation": 0, "reading": 0, "strategy": 0, "unknown": 0}

    for idx in range(question_count):
        qid = f"Q{idx + 1}"
        qtype, anchor, skill_id = question_templates[idx % len(question_templates)]
        max_score = 20 if qtype == "choice" else (24 if qtype == "fill" else 28)
        mastery_score = mastery_lookup.get(skill_id, 0.62)
        correctness_prob = _clamp_float(0.25 + mastery_score * 0.7, 0.35, 0.95)
        correct = rng.random() < correctness_prob

        if correct:
            if rng.random() < 0.2:
                score = max_score - rng.randint(1, 2)
                error_type = "strategy"
                reason = "核心思路正确，但关键步骤表述不完整导致过程分损失"
                suggestion = "保持当前思路，补齐推导步骤与结论论证"
            else:
                score = max_score
                error_type = "unknown"
                reason = "作答正确，无明显错误"
                suggestion = "保持当前优势，继续巩固同类型题"
        else:
            drop = max(2, int(round(max_score * rng.uniform(0.2, 0.55))))
            score = max(0, max_score - drop)
            roll = rng.random()
            if roll < 0.42:
                error_type = "concept"
                reason = "概念边界识别不清，关键定义应用出现偏差"
                suggestion = "先回顾定义，再做2-3道同类基础题强化判别"
            elif roll < 0.67:
                error_type = "strategy"
                reason = "解题路径选择不稳定，未先建立清晰的中间关系"
                suggestion = "练习先列条件-目标-关系，再展开计算"
            elif roll < 0.86:
                error_type = "calculation"
                reason = "计算过程有符号/代数化简失误，导致结果偏差"
                suggestion = "分步书写并在关键转换处复核符号"
            else:
                error_type = "reading"
                reason = "审题未覆盖全部约束，遗漏条件导致答案不完整"
                suggestion = "圈画题干约束词，列检查清单后再作答"
        error_counts[error_type] += 1

        trace_item = {
            "question_id": qid,
            "question_type": qtype,
            "skill_tags": [skill_id],
            "status": "answered",
            "score": score,
            "max_score": max_score,
            "is_correct": None,
            "selected_option": None,
            "filled_value": None,
            "student_answer_text": None,
            "answer_text": None,
            "steps": [],
            "skill_observations": [],
            "trace": {
                "scratchwork": None,
                "corrections": None,
                "readability": None,
                "confidence": None,
                "notes": None,
            },
            "raw_question_id": qid,
            "sub_question_id": None,
            "raw_sub_question_id": None,
            "error_analysis": {
                "error_type": error_type,
                "reason": reason,
                "evidence": f"本题得分{score}分，满分{max_score}分",
                "suggestion": suggestion,
            },
        }

        q_item = {
            "question_id": qid,
            "raw_question_id": qid,
            "question_type": qtype,
            "problem_text": anchor,
            "problem_text_full": f"{idx + 1}. {anchor}",
            "skill_tags": [skill_id],
            "confidence": round(rng.uniform(0.74, 0.98), 2),
            "max_score": None,
            "sub_questions": [],
            "paper_page_index": idx // 7,
            "question_order_index": idx,
            "question_anchor_text": anchor,
            "neighbor_question_ids": [f"Q{idx}"] if idx > 0 else ([f"Q{idx + 2}"] if question_count > 1 else []),
            "answer_page_hint": idx // 14,
            "answer_page_hint_confidence": round(rng.uniform(0.75, 0.95), 2),
            "answer_page_hint_evidence": "题号定位与答题区域一致",
            "answer_trace": trace_item,
            "sub_traces": [],
        }
        question_analysis.append(q_item)
        structured_questions_full.append(dict(q_item))
        answer_trace.append(dict(trace_item))

        display_item = dict(trace_item)
        display_item.update(
            {
                "display_question_id": qid,
                "parent_question_id": qid,
                "question_anchor_text": anchor,
                "problem_text": anchor,
                "sub_question_text": None,
                "is_question_summary": False,
            }
        )
        answer_trace_display.append(display_item)

    weakness_templates = {
        "root.method.add_sub": {
            "priority": "medium",
            "symptom": "同类二次根式判定不稳定，选择与填空题失分波动较大",
            "cause": "未先化简到最简形式就进行同类项判断，规则触发顺序混乱",
            "improvement_steps": [
                "整理同类二次根式判定流程：化简 -> 比较被开方数 -> 合并",
                "完成4道判定+2道合并专项题，并口述每一步依据",
            ],
            "practice_plan": "连续3天每天15分钟：2道判定题+1道合并题",
            "success_criteria": "同类题连续两次正确率达到90%以上",
            "suggestion": "把“先化简再判断”固定为首步骤，避免凭直觉处理",
        },
        "eq.theorem.quadratic_discriminant": {
            "priority": "high",
            "symptom": "根的个数与性质类综合判断题易漏条件",
            "cause": "判别式与参数取值联动推理不够完整，缺少边界检查",
            "improvement_steps": [
                "复盘判别式三种取值对应结论，并标注参数边界",
                "完成5道结论判断题，逐选项给出证伪或证明过程",
            ],
            "practice_plan": "连续4天每天20分钟：3道基础+2道综合判断",
            "success_criteria": "同类综合题正确率稳定在85%以上",
            "suggestion": "每次先列Delta与参数范围，再推导结论",
        },
        "geom.theorem.pythagorean": {
            "priority": "high",
            "symptom": "复杂图形中边角关系提取慢，建模方程不完整",
            "cause": "图形分解与辅助线意识不足，关系转换链断裂",
            "improvement_steps": [
                "训练三类经典构型的边角关系抽取模板",
                "每题先写“已知-目标-关键关系”再代入计算",
            ],
            "practice_plan": "连续3天每天15分钟：1道基础+1道综合图形题",
            "success_criteria": "复杂图形题能完整列出关键等量关系",
            "suggestion": "先结构化标注图形，再进入公式计算",
        },
        "geom.properties.angle_bisector": {
            "priority": "medium",
            "symptom": "分类讨论场景有漏解，证明链不闭合",
            "cause": "审题阶段未显式列出可能情形，讨论分支管理不足",
            "improvement_steps": [
                "归纳需分类讨论的关键词并建立检查清单",
                "专项训练3道分类题，确保分支全覆盖后再求解",
            ],
            "practice_plan": "连续2天每天12分钟：1道分类题+复盘1道错题",
            "success_criteria": "分类题连续3题无漏解",
            "suggestion": "写出分支树后再解题，避免中途遗漏情形",
        },
        "geom.method.construction": {
            "priority": "high",
            "symptom": "新定义几何题只给结论，过程与论证不足",
            "cause": "作答框架未先规划，步骤分层与表达意识偏弱",
            "improvement_steps": [
                "按“定义解释-构造-证明-计算-结论”模板训练",
                "完成2道新定义题并对照评分点自查",
            ],
            "practice_plan": "连续3天每天20分钟：1道新定义几何完整作答",
            "success_criteria": "作答环节完整，过程分丢失显著下降",
            "suggestion": "先列作答提纲，再逐段输出过程",
        },
        "model.word_problem": {
            "priority": "medium",
            "symptom": "文字条件转方程耗时长，易遗漏隐含约束",
            "cause": "变量定义和单位检查不系统，建模步骤跳跃",
            "improvement_steps": [
                "固定变量定义模板并记录单位",
                "完成4道应用题并逐步校验约束完整性",
            ],
            "practice_plan": "连续3天每天15分钟：2道中等难度应用题",
            "success_criteria": "建模题约束覆盖完整，错因集中下降",
            "suggestion": "把题干信息先表格化，再写方程",
        },
    }

    sorted_mastery = sorted(mastery_rows, key=lambda item: float(item["value"]))
    weaknesses: List[Dict[str, Any]] = []
    for row in sorted_mastery[:5]:
        sid = str(row["skill_id"])
        tpl = weakness_templates.get(sid)
        if not tpl:
            continue
        weaknesses.append(
            {
                "skill_id": sid,
                "evidence": [f"Q{rng.randint(1, question_count)}", f"Q{rng.randint(1, question_count)}"],
                "priority": tpl["priority"],
                "symptom": tpl["symptom"],
                "cause": tpl["cause"],
                "improvement_steps": tpl["improvement_steps"],
                "practice_plan": tpl["practice_plan"],
                "success_criteria": tpl["success_criteria"],
                "suggestion": tpl["suggestion"],
            }
        )
    weaknesses = weaknesses[:4]

    unknown_count = max(0, question_count - sum(error_counts.values()))
    error_counts["unknown"] += unknown_count

    profile_summary = (
        "学生在基础方程求解、根式运算和常规几何证明方面表现稳定，说明基本功较扎实；"
        "在判别式综合判断、复杂图形建模、分类讨论与新定义题规范作答方面仍有波动。"
        "建议按“概念澄清-模板化训练-错因复盘”三步推进，以提升综合题稳定性与表达完整度。"
    )
    student_profile = {
        "student_id": student_id,
        "mastery": mastery_rows,
        "error_profile": error_counts,
        "weaknesses": weaknesses,
        "summary": profile_summary,
    }

    mapping_report = {
        "total_questions": question_count,
        "mapped_questions": question_count,
        "missing_from_step1": [],
        "unmatched_traces": [],
        "sub_question_mapped_count": max(2, question_count // 6),
        "question_pass_chunks": max(4, question_count // 5),
        "answer_pass_chunks": max(8, question_count // 2),
        "route_pass_chunks": max(6, question_count // 3),
        "repair_rounds_used": 1,
        "repaired_questions_count": max(6, question_count // 2),
        "route_hinted_count": question_count,
        "score_conflict_count": 0,
        "score_conflict_question_ids": [],
        "knowledge_tagging_count": question_count - rng.randint(0, 2),
        "objective_pass_chunks": max(1, question_count // 20),
        "subjective_pass_chunks": max(4, question_count // 3),
        "matching_repair_rounds": 1,
        "error_analysis_count": question_count,
        "paper_parallel_tasks": paper_image_count,
        "answer_parallel_tasks": max(4, question_count // 2),
        "answer_segment_saved_crop_count": max(6, question_count // 2),
        "answer_segment_saved_crop_dir": f"D:\\project\\testpaper\\outputs\\answer_sheet_crops\\{student_id}\\{now.strftime('%Y%m%d_%H%M%S')}",
    }

    stages = [
        {
            "stage": "validate_input",
            "status": "ok",
            "input_mode": input_mode,
            "paper_image_count": paper_image_count,
            "answer_image_count": 2,
            "elapsed_ms": round(rng.uniform(0, 40), 1),
        },
        {
            "stage": "question_analysis",
            "status": "ok",
            "index_batches_total": paper_image_count,
            "index_batches_success": paper_image_count,
            "index_batches_failed": 0,
            "question_pass_chunks": mapping_report["question_pass_chunks"],
            "question_repair_rounds": 0,
            "repaired_questions_count": 0,
            "paper_parallel_tasks": mapping_report["paper_parallel_tasks"],
            "question_count": question_count,
            "missing_question_count": 0,
            "elapsed_ms": round(rng.uniform(82000, 150000), 1),
        },
        {
            "stage": "knowledge_tagging",
            "status": "ok",
            "question_count": question_count,
            "tagged_question_count": mapping_report["knowledge_tagging_count"],
            "elapsed_ms": round(rng.uniform(18000, 36000), 1),
        },
        {
            "stage": "new_knowledge_points",
            "status": "ok",
            "added_count": 0,
            "elapsed_ms": round(rng.uniform(0.1, 1.5), 1),
        },
        {
            "stage": "answer_route",
            "status": "ok",
            "batches_total": 2,
            "batches_success": 2,
            "batches_failed": 0,
            "route_pass_chunks": mapping_report["route_pass_chunks"],
            "route_hinted_count": mapping_report["route_hinted_count"],
            "answer_parallel_tasks": mapping_report["answer_parallel_tasks"],
            "elapsed_ms": round(rng.uniform(90000, 180000), 1),
        },
        {
            "stage": "error_analysis",
            "status": "ok",
            "error_analysis_count": mapping_report["error_analysis_count"],
            "elapsed_ms": round(rng.uniform(30000, 85000), 1),
        },
        {
            "stage": "answer_trace",
            "status": "ok",
            "batches_total": mapping_report["answer_parallel_tasks"],
            "batches_success": mapping_report["answer_parallel_tasks"],
            "batches_failed": 0,
            "answer_count": question_count,
            "mapped_question_count": question_count,
            "unmatched_trace_count": 0,
            "answer_pass_chunks": mapping_report["answer_pass_chunks"],
            "objective_pass_chunks": mapping_report["objective_pass_chunks"],
            "subjective_pass_chunks": mapping_report["subjective_pass_chunks"],
            "answer_repair_rounds": mapping_report["repair_rounds_used"],
            "repaired_questions_count": mapping_report["repaired_questions_count"],
            "score_conflict_count": 0,
            "answer_parallel_tasks": mapping_report["answer_parallel_tasks"],
            "saved_crop_count": mapping_report["answer_segment_saved_crop_count"],
            "saved_crop_dir": mapping_report["answer_segment_saved_crop_dir"],
            "elapsed_ms": round(rng.uniform(260000, 520000), 1),
        },
        {
            "stage": "student_profile",
            "status": "ok",
            "used_fallback": False,
            "elapsed_ms": round(rng.uniform(38000, 90000), 1),
        },
    ]

    request_payload = {
        "student_id": student_id,
        "input_mode": input_mode,
        "paper_image_count": paper_image_count,
        "paper_image_names": [f"paper_page_{idx + 1}.png" for idx in range(paper_image_count)],
        "answer_front_name": "answer_front.png",
        "answer_back_name": "answer_back.png",
    }
    process_payload = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "mock_mode": True,
        "stages": stages,
    }
    analysis_result = {
        "student_id": student_id,
        "input_mode": input_mode,
        "question_analysis": question_analysis,
        "structured_questions_full": structured_questions_full,
        "answer_trace": answer_trace,
        "answer_trace_display": answer_trace_display,
        "mapping_report": mapping_report,
        "student_profile": student_profile,
        "new_knowledge_points": [],
        "skill_alias_map": skill_alias_map,
        "warnings": [],
        "analysis_process": process_payload,
    }
    return {
        "meta": {
            "exported_at": finished_at.isoformat(timespec="seconds"),
            "schema_version": "analysis-export-v1",
        },
        "request": request_payload,
        "analysis_process": process_payload,
        "analysis_result": analysis_result,
    }


def make_handler(service: Any):  # type: ignore[override]
    base_handler = _http_app.make_handler(service)

    class Handler(base_handler):  # type: ignore[misc, valid-type]
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path in {"/analysis", "/analysis.html"}:
                _service._text_response(self, 200, _ANALYSIS_UI_HTML)
                return
            if path == "/api/demo/analysis/mock":
                query = parse_qs(parsed.query)
                payload = {key: values[-1] for key, values in query.items() if values}
                result = _build_mock_analysis_result(payload)
                _service._json_response(self, 200, {"ok": True, "result": result})
                return
            if path == "/api/demo/profile/mock-export":
                query = parse_qs(parsed.query)
                payload = {key: values[-1] for key, values in query.items() if values}
                result = _build_mock_profile_export(payload)
                _service._json_response(self, 200, result)
                return
            super().do_GET()

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/api/demo/analysis/mock":
                try:
                    payload = _read_json_body(self)
                    result = _build_mock_analysis_result(payload)
                    _service._json_response(self, 200, {"ok": True, "result": result})
                except Exception as exc:  # pragma: no cover - network path
                    _service._json_response(self, 400, {"ok": False, "error": str(exc)})
                return
            if path == "/api/demo/profile/mock-export":
                try:
                    payload = _read_json_body(self)
                    result = _build_mock_profile_export(payload)
                    _service._json_response(self, 200, result)
                except Exception as exc:  # pragma: no cover - network path
                    _service._json_response(self, 400, {"ok": False, "error": str(exc)})
                return
            super().do_POST()

    return Handler


def main() -> None:  # type: ignore[override]
    from dotenv import load_dotenv

    load_dotenv()

    parser = argparse.ArgumentParser(description="Demo server for paper+answer VLM analysis.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--config", default="llm_config.json")
    parser.add_argument("--profile", default=None)
    parser.add_argument("--key-word", default="key_word.json")
    parser.add_argument("--mock", action="store_true", help="Run demo with mock results, no LLM call.")
    args = parser.parse_args()

    service = DemoService(
        Path(args.config),
        args.profile,
        Path(args.key_word),
        mock_mode=args.mock,
    )
    handler = make_handler(service)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Demo server running: http://{args.host}:{args.port}")
    print(f"Personal temporal + class analysis demo: http://{args.host}:{args.port}/analysis")
    print(f"Profile export mock api: http://{args.host}:{args.port}/api/demo/profile/mock-export")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


# Re-export service module symbols so existing scripts/tests can import
# helpers from `demo_server` directly.  Uses module-level __getattr__ to
# avoid the old globals()[...] = ... anti-pattern.
DemoService = _service.DemoService

_EXPLICIT_OVERRIDES = {"_call_llm_json": _call_llm_json}


def __getattr__(name: str):
    if name in _EXPLICIT_OVERRIDES:
        return _EXPLICIT_OVERRIDES[name]
    try:
        return getattr(_service, name)
    except AttributeError:
        raise AttributeError(f"module 'demo_server' has no attribute {name!r}") from None


__all__ = [name for name in dir(_service) if not name.startswith("__")] + ["DemoService", "main"]

if __name__ == "__main__":
    main()
