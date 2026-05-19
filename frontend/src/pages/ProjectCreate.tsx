import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createProject } from "../api/projects";
import Button from "../components/ui/Button";

export default function ProjectCreate() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<1 | 2>(1);
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const [grade, setGrade] = useState("");
  const [mode, setMode] = useState<"standard" | "mineru">("standard");

  const createMut = useMutation({
    mutationFn: () => createProject(title.trim(), subject, grade),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${data.project_id}`);
    },
  });

  const handleCreate = () => {
    if (!title.trim()) return;
    createMut.mutate();
  };

  return (
    <div className="max-w-lg mx-auto">
      {/* Step indicator */}
      <div className="flex items-center justify-center gap-3 mb-8">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step >= 1 ? "bg-primary text-white" : "bg-gray-200 text-gray-400"}`}>1</div>
        <div className={`w-8 h-0.5 ${step >= 2 ? "bg-primary" : "bg-gray-200"}`} />
        <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${step >= 2 ? "bg-primary text-white" : "bg-gray-200 text-gray-400"}`}>2</div>
      </div>

      {step === 1 && (
        <div className="bg-white border border-[var(--color-border)] rounded-card p-8">
          <h2 className="text-base font-bold text-[var(--color-text)] mb-6">创建新项目</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">项目名称 *</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)}
                className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
                placeholder="例如：初三数学期中试卷" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">学科</label>
                <select value={subject} onChange={(e) => setSubject(e.target.value)}
                  className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary">
                  <option value="">选择学科</option>
                  {["语文","数学","英语","物理","化学","生物","历史","地理","政治"].map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--color-text-secondary)] mb-1.5">年级</label>
                <select value={grade} onChange={(e) => setGrade(e.target.value)}
                  className="w-full px-3 py-2.5 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary">
                  <option value="">选择年级</option>
                  {["初一","初二","初三","高一","高二","高三"].map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              </div>
            </div>
          </div>
          <div className="flex justify-end mt-8">
            <Button onClick={() => { if (title.trim()) setStep(2); }} variant="primary" disabled={!title.trim()}>下一步</Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="bg-white border border-[var(--color-border)] rounded-card p-8">
          <h2 className="text-base font-bold text-[var(--color-text)] mb-2">选择提取方式</h2>
          <p className="text-xs text-[var(--color-text-muted)] mb-6">不同的提取方式适用于不同的试卷类型</p>
          <div className="grid grid-cols-2 gap-4 mb-8">
            <button onClick={() => setMode("standard")}
              className={`text-left p-5 rounded-card border-2 transition-all ${
                mode === "standard" ? "border-primary bg-primary-light" : "border-[var(--color-border)] hover:border-gray-300"
              }`}>
              <div className="text-2xl mb-2">🤖</div>
              <div className="font-semibold text-sm mb-1">标准 AI 提取</div>
              <div className="text-xs text-[var(--color-text-muted)] leading-relaxed">AI 自动识别试卷图片中的试题和答案区域，提取后人工审查确认。</div>
              <div className="mt-3">
                <span className="text-[10px] bg-primary-light text-primary px-2 py-0.5 rounded-pill font-medium">推荐 · 适合大多数场景</span>
              </div>
            </button>
            <button onClick={() => setMode("mineru")}
              className={`text-left p-5 rounded-card border-2 transition-all ${
                mode === "mineru" ? "border-primary bg-primary-light" : "border-[var(--color-border)] hover:border-gray-300"
              }`}>
              <div className="text-2xl mb-2">🔬</div>
              <div className="font-semibold text-sm mb-1">MinerU 智能提取</div>
              <div className="text-xs text-[var(--color-text-muted)] leading-relaxed">使用 MinerU OCR 引擎精准解析，适合复杂排版、含图表的试卷。</div>
              <div className="mt-3">
                <span className="text-[10px] bg-gray-100 text-[var(--color-text-muted)] px-2 py-0.5 rounded-pill font-medium">需配置 MinerU 服务</span>
              </div>
            </button>
          </div>
          <div className="flex justify-between">
            <Button onClick={() => setStep(1)} variant="ghost">← 返回</Button>
            <Button onClick={handleCreate} variant="primary" disabled={createMut.isPending}>
              {createMut.isPending ? "创建中..." : "创建项目"}
            </Button>
          </div>
          {createMut.isError && <p className="text-xs text-danger mt-3">{(createMut.error as Error)?.message || "创建失败"}</p>}
        </div>
      )}
    </div>
  );
}
