import { useState, useRef, type DragEvent } from "react";
import { UploadCloud, X, FileImage } from "lucide-react";

interface Props {
  label: string;
  hint: string;
  files: File[];
  onFiles: (files: File[]) => void;
}

export default function UploadZone({ label, hint, files, onFiles }: Props) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const openFileDialog = () => inputRef.current?.click();

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = Array.from(e.dataTransfer.files);
    onFiles([...files, ...dropped]);
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    if (selected.length > 0) {
      onFiles([...files, ...selected]);
    }
    // Reset so same file can be re-selected
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="w-full">
      <div className="text-xs font-bold text-slate-600 mb-2 flex items-center justify-between">
        <span>{label}</span>
        {files.length > 0 && (
          <span className="text-primary font-bold text-[11px] bg-indigo-50 px-2 py-0.5 rounded-md">
            已选 {files.length} 个文件
          </span>
        )}
      </div>

      {/* Entire area is clickable */}
      <div
        onClick={openFileDialog}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`group border-2 border-dashed rounded-card p-8 text-center transition-all duration-300 cursor-pointer ${
          dragging
            ? "border-primary bg-indigo-50/30 shadow-inner"
            : "border-slate-200 hover:border-primary/40 hover:bg-slate-50/50"
        }`}
      >
        <div className={`p-3.5 rounded-full bg-slate-50 mb-3 mx-auto w-fit group-hover:scale-105 group-hover:bg-indigo-50/80 transition-all duration-300 ${dragging ? "scale-105 bg-indigo-50" : ""}`}>
          <UploadCloud className={`w-8 h-8 ${dragging ? "text-primary" : "text-slate-400 group-hover:text-primary"} transition-colors`} />
        </div>
        <p className="text-xs text-slate-500 font-semibold mb-1">
          {files.length > 0 ? "继续拖入或点击添加" : "点击或拖入图片文件到此处"}
        </p>
        <p className="text-[10px] text-slate-400 font-medium">{hint}</p>
      </div>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept="image/*"
        className="hidden"
        onChange={handleChange}
      />

      {/* File list with remove */}
      {files.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 max-h-40 overflow-y-auto p-1">
          {files.map((f, i) => (
            <span
              key={`${f.name}-${i}`}
              className="inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-1 bg-white border border-slate-100 rounded-btn text-xs text-slate-600 shadow-sm animate-fadeIn"
            >
              <FileImage className="w-3.5 h-3.5 text-indigo-400" />
              <span className="truncate max-w-[120px] font-medium">{f.name}</span>
              <button
                type="button"
                className="w-4.5 h-4.5 rounded-full flex items-center justify-center text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all p-0.5"
                onClick={(e) => {
                  e.stopPropagation();
                  onFiles(files.filter((_, j) => j !== i));
                }}
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
