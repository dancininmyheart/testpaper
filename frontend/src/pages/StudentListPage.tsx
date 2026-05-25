import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createStudent, listStudents, updateStudent, type StudentData } from "../api/students";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";
import {
  UserPlus,
  Edit2,
  Eye,
  User,
  Save,
  X,
  ArrowRight,
  Loader2,
  GraduationCap,
  Hash,
  AlertCircle,
  Users
} from "lucide-react";

export default function StudentListPage() {
  const queryClient = useQueryClient();
  const { data: students = [], isLoading } = useQuery({ queryKey: ["students"], queryFn: listStudents });
  const [studentId, setStudentId] = useState("");
  const [name, setName] = useState("");
  const [grade, setGrade] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState({ name: "", grade: "" });
  const [error, setError] = useState<string | null>(null);

  const createMut = useMutation({
    mutationFn: () => createStudent({ student_id: studentId.trim(), name: name.trim(), grade: grade.trim() }),
    onSuccess: () => {
      setStudentId("");
      setName("");
      setGrade("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["students"] });
    },
    onError: (err: any) => setError(err?.message || "新增学生失败"),
  });

  const updateMut = useMutation({
    mutationFn: (student: StudentData) => updateStudent(student.student_id, editDraft),
    onSuccess: () => {
      setEditingId(null);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["students"] });
    },
    onError: (err: any) => setError(err?.message || "编辑学生失败"),
  });

  const startEdit = (student: StudentData) => {
    setEditingId(student.student_id);
    setEditDraft({ name: student.name, grade: student.grade });
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* 头部区域 */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center text-primary shadow-sm">
          <Users className="w-5 h-5" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-slate-800 tracking-tight">学生管理</h1>
          <p className="text-xs text-[var(--color-text-muted)] mt-0.5">创建与维护学生档案，以便录入答题卡和查看学习报告</p>
        </div>
      </div>

      {/* 新增学生一体化卡片 */}
      <div className="bg-white border border-slate-200/80 rounded-2xl p-5 shadow-[0_2px_12px_rgba(0,0,0,0.015)] space-y-4">
        <h3 className="text-xs font-bold text-slate-500 tracking-wider flex items-center gap-1.5 uppercase">
          <UserPlus className="w-4 h-4 text-primary" />
          <span>快速新增学生</span>
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
              <Hash className="w-4 h-4" />
            </div>
            <input
              value={studentId}
              onChange={(e) => setStudentId(e.target.value)}
              className="w-full pl-9 pr-3 py-2.5 border border-slate-200 rounded-xl text-xs outline-none focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all bg-slate-50/20"
              placeholder="学号 (如 2026001)"
            />
          </div>

          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
              <User className="w-4 h-4" />
            </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full pl-9 pr-3 py-2.5 border border-slate-200 rounded-xl text-xs outline-none focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all bg-slate-50/20"
              placeholder="姓名 (如 张三)"
            />
          </div>

          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
              <GraduationCap className="w-4 h-4" />
            </div>
            <input
              value={grade}
              onChange={(e) => setGrade(e.target.value)}
              className="w-full pl-9 pr-3 py-2.5 border border-slate-200 rounded-xl text-xs outline-none focus:border-primary focus:ring-4 focus:ring-primary/5 transition-all bg-slate-50/20"
              placeholder="年级 (如 高一3班)"
            />
          </div>

          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            disabled={!studentId.trim() || !name.trim() || createMut.isPending}
            className="w-full h-full py-2.5 rounded-xl shadow-premium flex items-center justify-center gap-1.5"
          >
            {createMut.isPending ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>处理中...</span>
              </>
            ) : (
              <>
                <UserPlus className="w-4 h-4" />
                <span>录入学生档案</span>
              </>
            )}
          </Button>
        </div>

        {error && (
          <div className="text-xs bg-rose-50 border border-rose-100 text-rose-700 px-3 py-2 rounded-lg flex items-center gap-1.5 animate-fadeIn">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* 学生列表区 */}
      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-20 space-y-3">
          <Loader2 className="w-8 h-8 animate-spin text-primary" />
          <div className="text-xs text-slate-500 font-medium">载入学生档案中...</div>
        </div>
      ) : students.length === 0 ? (
        <div className="bg-white rounded-2xl border border-slate-200/85 p-8">
          <EmptyState icon="👥" title="暂无学生" description="先新增学生，再上传对应学生的答题卡" />
        </div>
      ) : (
        <div className="grid gap-3">
          {students.map((student) => {
            const isEditing = editingId === student.student_id;
            const initialLetter = student.name ? student.name.charAt(0) : "S";

            return (
              <div
                key={student.student_id}
                className="bg-white border border-slate-200/80 rounded-2xl p-4 md:p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4 transition-all duration-300 hover:shadow-premium hover:-translate-y-0.5 group"
              >
                {/* 学生元数据卡片 */}
                <div className="flex items-center gap-3.5 flex-1 min-w-0">
                  <div className="w-10 h-10 rounded-full bg-gradient-to-br from-primary/10 to-indigo-50/60 border border-primary/20 text-primary flex items-center justify-center font-bold text-sm shadow-sm shrink-0">
                    {initialLetter}
                  </div>
                  
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-1 flex-1 min-w-0">
                    <div className="min-w-0">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">学号</div>
                      <div className="text-xs font-mono font-bold text-slate-700 mt-0.5 truncate">{student.student_id}</div>
                    </div>
                    
                    <div className="min-w-0">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">姓名</div>
                      {isEditing ? (
                        <input
                          value={editDraft.name}
                          onChange={(e) => setEditDraft((draft) => ({ ...draft, name: e.target.value }))}
                          className="mt-0.5 w-full px-2 py-1 border border-primary/30 rounded-lg text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/5"
                        />
                      ) : (
                        <div className="text-xs font-semibold text-slate-800 mt-0.5 truncate">{student.name}</div>
                      )}
                    </div>

                    <div className="min-w-0">
                      <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">年级</div>
                      {isEditing ? (
                        <input
                          value={editDraft.grade}
                          onChange={(e) => setEditDraft((draft) => ({ ...draft, grade: e.target.value }))}
                          className="mt-0.5 w-full px-2 py-1 border border-primary/30 rounded-lg text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/5"
                        />
                      ) : (
                        <div className="text-xs font-semibold text-slate-500 mt-0.5 truncate">{student.grade || "-"}</div>
                      )}
                    </div>
                  </div>
                </div>

                {/* 动作按钮区 */}
                <div className="flex items-center gap-2.5 shrink-0 self-end md:self-auto">
                  {isEditing ? (
                    <>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => updateMut.mutate(student)}
                        disabled={!editDraft.name.trim() || updateMut.isPending}
                        className="rounded-lg py-1.5 flex items-center gap-1"
                      >
                        {updateMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                        <span>保存</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditingId(null)}
                        className="rounded-lg py-1.5 flex items-center gap-1 text-slate-500 hover:text-slate-700"
                      >
                        <X className="w-3.5 h-3.5" />
                        <span>取消</span>
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => startEdit(student)}
                      className="rounded-lg py-1.5 flex items-center gap-1 border-slate-200 text-slate-600 hover:text-slate-900"
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                      <span>编辑</span>
                    </Button>
                  )}
                  
                  <Link to={`/students/${encodeURIComponent(student.student_id)}`}>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="rounded-lg py-1.5 text-primary hover:bg-primary-light flex items-center gap-1.5 group/btn"
                    >
                      <Eye className="w-3.5 h-3.5" />
                      <span>学情报告</span>
                      <ArrowRight className="w-3.5 h-3.5 transition-transform duration-200 group-hover/btn:translate-x-0.5" />
                    </Button>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
