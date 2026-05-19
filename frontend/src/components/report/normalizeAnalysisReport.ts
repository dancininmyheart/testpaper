export interface ReportMetric {
  label: string;
  value: string;
  helper?: string;
  tone?: "primary" | "success" | "warning" | "danger" | "muted";
}

export interface ReportQuestionItem {
  id: string;
  title: string;
  questionText: string;
  knowledgePoints: string[];
  studentAnswer: string;
  result: string;
  scoreText: string;
  issue: string;
  suggestion: string;
  evidence: string;
}

export interface ReportWeakness {
  skill: string;
  priority: string;
  symptom: string;
  cause: string;
  suggestion: string;
  practicePlan: string;
  improvementSteps: string[];
  evidence: string[];
}

export interface ReportMasteryItem {
  skill: string;
  value: number | null;
  label: string;
}

export interface ReportErrorItem {
  label: string;
  value: string;
}

export interface ReportLiteracyItem {
  id: string;
  name: string;
  definition: string;
  value: number | null;
  label: string;
  level: string;
  levelLabel: string;
  evidence: string[];
  reason: string;
  suggestion: string;
  confidence: number | null;
}

export interface NormalizedAnalysisReport {
  studentId: string;
  generatedAt: string;
  summary: string;
  metrics: ReportMetric[];
  questions: ReportQuestionItem[];
  weaknesses: ReportWeakness[];
  mastery: ReportMasteryItem[];
  literacy: ReportLiteracyItem[];
  errorProfile: ReportErrorItem[];
  warnings: string[];
  stageCount: number;
  raw: Record<string, unknown>;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asRecord(value: unknown): UnknownRecord {
  return isRecord(value) ? value : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value.trim() || fallback;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return fallback;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function stringList(value: unknown): string[] {
  return asArray(value).map((item) => text(item)).filter(Boolean);
}

function uniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const output: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    output.push(normalized);
  }
  return output;
}

function firstText(source: UnknownRecord, keys: string[], fallback = ""): string {
  for (const key of keys) {
    const value = text(source[key]);
    if (value) return value;
  }
  return fallback;
}

function formatPercent(value: number | null): string {
  if (value == null) return "暂无数据";
  const percent = value <= 1 ? value * 100 : value;
  return `${Math.round(percent)}%`;
}

function formatScore(score: number | null, maxScore: number | null): string {
  if (score == null && maxScore == null) return "暂无数据";
  if (score != null && maxScore != null) return `${score}/${maxScore}`;
  if (score != null) return `${score}`;
  return `满分 ${maxScore}`;
}

function readableStatus(item: UnknownRecord, score: number | null, maxScore: number | null): string {
  const raw = firstText(item, ["status", "judgement", "result", "correctness"]);
  if (raw) {
    const lower = raw.toLowerCase();
    if (lower.includes("correct") || raw.includes("正确")) return "正确";
    if (lower.includes("partial") || raw.includes("部分")) return "部分正确";
    if (lower.includes("wrong") || lower.includes("incorrect") || raw.includes("错误")) return "需订正";
    if (lower.includes("missing") || lower.includes("blank") || raw.includes("空")) return "未作答";
    return raw;
  }
  if (score != null && maxScore != null) {
    if (maxScore > 0 && score >= maxScore) return "正确";
    if (score > 0) return "部分正确";
    return "需订正";
  }
  return "暂无判断";
}

function pickAnswerItems(report: UnknownRecord): UnknownRecord[] {
  const display = asArray(report.answer_trace_display).filter(isRecord);
  if (display.length > 0) return display;
  return asArray(report.answer_trace).filter(isRecord);
}

function questionLookupKey(value: string): string {
  return value.replace(/（整题）|\(整题\)/g, "").trim();
}

function buildQuestionTextLookup(report: UnknownRecord): Map<string, string> {
  const lookup = new Map<string, string>();
  const sources = [
    ...asArray(report.structured_questions_full).filter(isRecord),
    ...asArray(report.question_analysis).filter(isRecord),
  ];

  for (const question of sources) {
    const qid = firstText(question, ["question_id", "display_question_id"]);
    if (!qid) continue;
    const fullText = firstText(question, ["problem_text_full", "problem_text", "question_anchor_text", "question_text"]);
    if (fullText) lookup.set(questionLookupKey(qid), fullText);

    for (const sub of asArray(question.sub_questions).filter(isRecord)) {
      const subId = firstText(sub, ["sub_question_id", "question_id"]);
      const subText = firstText(sub, ["sub_text", "problem_text_full", "problem_text", "question_text"]);
      if (subId && subText) lookup.set(questionLookupKey(subId), subText);
    }
  }

  return lookup;
}

function buildSkillAliasMap(report: UnknownRecord): Map<string, string> {
  const aliases = new Map<string, string>();
  const aliasMap = asRecord(report.skill_alias_map);

  for (const [key, value] of Object.entries(aliasMap)) {
    const name = text(value);
    if (key && name) aliases.set(key, name);
  }

  for (const point of asArray(report.new_knowledge_points).filter(isRecord)) {
    const id = firstText(point, ["id", "skill_id"]);
    const name = firstText(point, ["name", "short_name", "skill_name"]);
    if (id && name && !aliases.has(id)) aliases.set(id, name);
  }

  return aliases;
}

function resolveSkillName(value: unknown, skillAliasMap: Map<string, string>): string {
  const raw = text(value);
  if (!raw) return "";
  return skillAliasMap.get(raw) || raw;
}

function questionSkillValues(source: UnknownRecord): string[] {
  const values: string[] = [];
  for (const key of ["skill_tags", "knowledge_points", "knowledge_tags", "skills"]) {
    values.push(...stringList(source[key]));
  }
  for (const key of ["skill_name", "skill_id", "knowledge_point", "knowledge_point_name"]) {
    const value = text(source[key]);
    if (value) values.push(value);
  }
  return uniqueStrings(values);
}

function resolveQuestionSkills(source: UnknownRecord, skillAliasMap: Map<string, string>): string[] {
  return uniqueStrings(questionSkillValues(source).map((value) => resolveSkillName(value, skillAliasMap)).filter(Boolean));
}

function buildQuestionSkillLookup(report: UnknownRecord, skillAliasMap: Map<string, string>): Map<string, string[]> {
  const lookup = new Map<string, string[]>();
  const sources = [
    ...asArray(report.structured_questions_full).filter(isRecord),
    ...asArray(report.question_analysis).filter(isRecord),
  ];

  for (const question of sources) {
    const qid = firstText(question, ["question_id", "display_question_id"]);
    const skills = resolveQuestionSkills(question, skillAliasMap);
    if (qid && skills.length > 0) lookup.set(questionLookupKey(qid), skills);

    for (const sub of asArray(question.sub_questions).filter(isRecord)) {
      const subId = firstText(sub, ["sub_question_id", "question_id"]);
      const subSkills = resolveQuestionSkills(sub, skillAliasMap);
      if (subId && subSkills.length > 0) lookup.set(questionLookupKey(subId), subSkills);
    }
  }

  return lookup;
}

function firstSkillName(source: UnknownRecord, keys: string[], skillAliasMap: Map<string, string>, fallback: string): string {
  for (const key of keys) {
    const raw = text(source[key]);
    if (raw) return resolveSkillName(raw, skillAliasMap);
  }
  return fallback;
}

function normalizeQuestion(
  item: UnknownRecord,
  index: number,
  questionTextLookup: Map<string, string>,
  questionSkillLookup: Map<string, string[]>,
  skillAliasMap: Map<string, string>,
): ReportQuestionItem {
  const trace = asRecord(item.trace);
  const score = numberValue(item.score);
  const maxScore = numberValue(item.max_score);
  const id = firstText(item, ["display_question_id", "sub_question_id", "question_id"], `Q${index + 1}`);
  const parentId = firstText(item, ["parent_question_id", "question_id"]);
  const lookupText = questionTextLookup.get(questionLookupKey(id)) || questionTextLookup.get(questionLookupKey(parentId));
  const lookupSkills = questionSkillLookup.get(questionLookupKey(id)) || questionSkillLookup.get(questionLookupKey(parentId)) || [];
  const issue = firstText(
    trace,
    ["reason", "reason_code", "diagnosis", "comment", "feedback"],
    firstText(item, ["reason", "comment", "feedback"], "暂无数据"),
  );

  return {
    id,
    title: `第 ${id} 题`,
    questionText: firstText(
      item,
      ["sub_question_text", "problem_text_full", "problem_text", "question_anchor_text", "question_text"],
      lookupText || "暂无题干",
    ),
    knowledgePoints: uniqueStrings([...resolveQuestionSkills(item, skillAliasMap), ...lookupSkills]),
    studentAnswer: firstText(item, ["student_answer_text", "answer_text", "student_answer", "selected_answer"], "暂无数据"),
    result: readableStatus(item, score, maxScore),
    scoreText: formatScore(score, maxScore),
    issue,
    suggestion: firstText(trace, ["suggestion", "next_step"], firstText(item, ["suggestion"], "暂无数据")),
    evidence: firstText(trace, ["evidence"], firstText(item, ["evidence"], "")),
  };
}

function normalizeWeakness(item: UnknownRecord, skillAliasMap: Map<string, string>): ReportWeakness {
  return {
    skill: firstSkillName(item, ["skill_name", "name", "skill_id"], skillAliasMap, "未命名知识点"),
    priority: firstText(item, ["priority"], "普通"),
    symptom: firstText(item, ["symptom"], "暂无数据"),
    cause: firstText(item, ["cause"], "暂无数据"),
    suggestion: firstText(item, ["suggestion"], "暂无数据"),
    practicePlan: firstText(item, ["practice_plan"], "暂无数据"),
    improvementSteps: stringList(item.improvement_steps),
    evidence: stringList(item.evidence),
  };
}

function normalizeMastery(item: UnknownRecord, skillAliasMap: Map<string, string>): ReportMasteryItem {
  const value = numberValue(item.value ?? item.mastery ?? item.score);
  return {
    skill: firstSkillName(item, ["skill_name", "name", "skill_id"], skillAliasMap, "未命名知识点"),
    value,
    label: formatPercent(value),
  };
}

function legacyLiteracyName(id: string): string {
  const names: Record<string, string> = {
    logical_reasoning: "逻辑推理",
    abstraction: "抽象建模",
    computation: "运算规范",
    representation: "表征转化",
    reflection: "反思修正",
  };
  return names[id] || id;
}

function literacyLevelLabel(level: string, value: number | null): string {
  if (level === "high") return "优势";
  if (level === "medium") return "稳定";
  if (level === "low") return "待提升";
  if (value == null) return "暂无判断";
  if (value >= 0.75) return "优势";
  if (value >= 0.45) return "稳定";
  return "待提升";
}

function normalizeLiteracyValue(value: unknown): number | null {
  const parsed = numberValue(value);
  if (parsed == null) return null;
  const ratio = parsed > 1 ? parsed / 100 : parsed;
  return Math.min(1, Math.max(0, ratio));
}

function normalizeLiteracyEntry(item: UnknownRecord): ReportLiteracyItem | null {
  const id = firstText(item, ["literacy_id", "dimension_id", "id"]);
  if (!id) return null;
  const value = normalizeLiteracyValue(item.value ?? item.score ?? item.current_score);
  const level = firstText(item, ["level"]);
  const name = firstText(item, ["name", "dimension_name"], legacyLiteracyName(id));
  return {
    id,
    name,
    definition: firstText(item, ["definition"], ""),
    value,
    label: formatPercent(value),
    level,
    levelLabel: literacyLevelLabel(level, value),
    evidence: stringList(item.evidence),
    reason: firstText(item, ["reason"], ""),
    suggestion: firstText(item, ["suggestion"], ""),
    confidence: normalizeLiteracyValue(item.confidence),
  };
}

function normalizeLiteracyItems(report: UnknownRecord): ReportLiteracyItem[] {
  const profile = asRecord(report.student_profile);
  const temporal = asRecord(report.temporal_analysis);
  const group = asRecord(report.group_analysis);
  const radar = asRecord(group.literacy_radar);
  const candidates = [
    ...asArray(profile.literacy).filter(isRecord),
    ...asArray(temporal.literacy_history).filter(isRecord),
    ...asArray(radar.dimensions).filter(isRecord),
  ];
  const byId = new Map<string, ReportLiteracyItem>();
  for (const item of candidates) {
    const normalized = normalizeLiteracyEntry(item);
    if (!normalized) continue;
    const existing = byId.get(normalized.id);
    if (!existing) {
      byId.set(normalized.id, normalized);
      continue;
    }
    byId.set(normalized.id, {
      ...existing,
      ...normalized,
      definition: existing.definition || normalized.definition,
      evidence: existing.evidence.length > 0 ? existing.evidence : normalized.evidence,
      reason: existing.reason || normalized.reason,
      suggestion: existing.suggestion || normalized.suggestion,
    });
  }
  return Array.from(byId.values());
}

function normalizeErrorProfile(profile: UnknownRecord): ReportErrorItem[] {
  return Object.entries(profile).map(([key, value]) => ({
    label: key,
    value: text(value, "0"),
  }));
}

export function normalizeAnalysisReport(input: unknown): NormalizedAnalysisReport {
  const report = asRecord(input);
  const mapping = asRecord(report.mapping_report);
  const profile = asRecord(report.student_profile);
  const process = asRecord(report.analysis_process);
  const questionTextLookup = buildQuestionTextLookup(report);
  const skillAliasMap = buildSkillAliasMap(report);
  const questionSkillLookup = buildQuestionSkillLookup(report, skillAliasMap);
  const questions = pickAnswerItems(report).map((item, index) =>
    normalizeQuestion(item, index, questionTextLookup, questionSkillLookup, skillAliasMap)
  );
  const totalQuestions = numberValue(mapping.total_questions) ?? questions.length;
  const mappedQuestions = numberValue(mapping.mapped_questions) ?? questions.length;
  const scorePairs = questions
    .map((question) => question.scoreText)
    .filter((value) => value !== "暂无数据");
  const weaknesses = asArray(profile.weaknesses).filter(isRecord).map((item) => normalizeWeakness(item, skillAliasMap));
  const mastery = asArray(profile.mastery).filter(isRecord).map((item) => normalizeMastery(item, skillAliasMap));
  const literacy = normalizeLiteracyItems(report);
  const scoreSum = pickAnswerItems(report).reduce<{ score: number; max: number }>(
    (acc, item) => {
      acc.score += numberValue(item.score) ?? 0;
      acc.max += numberValue(item.max_score) ?? 0;
      return acc;
    },
    { score: 0, max: 0 },
  );

  return {
    studentId: firstText(report, ["student_id"], "暂无数据"),
    generatedAt: firstText(process, ["finished_at", "updated_at", "started_at"], firstText(report, ["finished_at", "updated_at"], "")),
    summary: firstText(profile, ["summary"], "暂无数据"),
    metrics: [
      { label: "题目总数", value: String(totalQuestions), helper: "本次报告覆盖的题目数量", tone: "primary" },
      { label: "已匹配题目", value: `${mappedQuestions}/${totalQuestions || "暂无数据"}`, helper: "题目与作答匹配情况", tone: mappedQuestions < totalQuestions ? "warning" : "success" },
      { label: "得分情况", value: scoreSum.max > 0 ? `${scoreSum.score}/${scoreSum.max}` : scorePairs[0] || "暂无数据", helper: "按逐题明细汇总", tone: "success" },
      { label: "主要薄弱点", value: String(weaknesses.length), helper: "系统识别出的重点提升方向", tone: weaknesses.length > 0 ? "warning" : "success" },
    ],
    questions,
    weaknesses,
    mastery,
    literacy,
    errorProfile: normalizeErrorProfile(asRecord(profile.error_profile)),
    warnings: stringList(report.warnings),
    stageCount: asArray(process.stages).length,
    raw: report,
  };
}
