import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createStudent, listStudents, updateStudent, type StudentData } from "../api/students";
import Button from "../components/ui/Button";
import EmptyState from "../components/layout/EmptyState";

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
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-bold text-[var(--color-text)]">学生管理</h1>
      </div>

      <div className="bg-white border border-[var(--color-border)] rounded-card p-4 mb-5">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <input value={studentId} onChange={(e) => setStudentId(e.target.value)}
            className="px-3 py-2 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary"
            placeholder="学号" />
          <input value={name} onChange={(e) => setName(e.target.value)}
            className="px-3 py-2 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary"
            placeholder="姓名" />
          <input value={grade} onChange={(e) => setGrade(e.target.value)}
            className="px-3 py-2 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary"
            placeholder="年级" />
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            disabled={!studentId.trim() || !name.trim() || createMut.isPending}
          >
            新增学生
          </Button>
        </div>
        {error && <div className="mt-3 text-xs text-danger">{error}</div>}
      </div>

      {isLoading ? (
        <div className="text-sm text-[var(--color-text-muted)]">加载中...</div>
      ) : students.length === 0 ? (
        <EmptyState icon="👥" title="暂无学生" description="先新增学生，再上传对应学生的答题卡" />
      ) : (
        <div className="space-y-3">
          {students.map((student) => {
            const isEditing = editingId === student.student_id;
            return (
              <div key={student.student_id} className="bg-white border border-[var(--color-border)] rounded-card p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 flex-1">
                  <div>
                    <div className="text-[10px] text-[var(--color-text-muted)]">学号</div>
                    <div className="text-sm font-medium text-[var(--color-text)]">{student.student_id}</div>
                  </div>
                  <div>
                    <div className="text-[10px] text-[var(--color-text-muted)]">姓名</div>
                    {isEditing ? (
                      <input value={editDraft.name} onChange={(e) => setEditDraft((draft) => ({ ...draft, name: e.target.value }))}
                        className="w-full px-2 py-1 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary" />
                    ) : <div className="text-sm text-[var(--color-text)]">{student.name}</div>}
                  </div>
                  <div>
                    <div className="text-[10px] text-[var(--color-text-muted)]">年级</div>
                    {isEditing ? (
                      <input value={editDraft.grade} onChange={(e) => setEditDraft((draft) => ({ ...draft, grade: e.target.value }))}
                        className="w-full px-2 py-1 border border-[var(--color-border)] rounded-btn text-sm outline-none focus:border-primary" />
                    ) : <div className="text-sm text-[var(--color-text)]">{student.grade || "-"}</div>}
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {isEditing ? (
                    <>
                      <Button variant="primary" size="sm" onClick={() => updateMut.mutate(student)} disabled={!editDraft.name.trim() || updateMut.isPending}>保存</Button>
                      <Button variant="ghost" size="sm" onClick={() => setEditingId(null)}>取消</Button>
                    </>
                  ) : (
                    <Button variant="secondary" size="sm" onClick={() => startEdit(student)}>编辑</Button>
                  )}
                  <Link to={`/students/${encodeURIComponent(student.student_id)}`}>
                    <Button variant="ghost" size="sm">历史分析报告</Button>
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
