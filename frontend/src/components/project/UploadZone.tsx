import { useState, useRef, type DragEvent } from "react";

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
    <div>
      <div className="text-xs font-medium text-[var(--color-text-secondary)] mb-2">
        {label}
        {files.length > 0 && (
          <span className="ml-1 text-primary font-semibold">({files.length} 个文件)</span>
        )}
      </div>

      {/* Entire area is clickable */}
      <div
        onClick={openFileDialog}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-card p-6 text-center transition-colors cursor-pointer ${
          dragging ? "border-primary bg-primary-light/50" : "border-[var(--color-border)] hover:border-primary/50 hover:bg-gray-50"
        }`}
      >
        <div className="text-2xl mb-2">📤</div>
        <p className="text-xs text-[var(--color-text-muted)] mb-1">
          {files.length > 0 ? `已选择 ${files.length} 个文件` : "点击或拖拽文件到此处"}
        </p>
        <p className="text-[10px] text-[var(--color-text-muted)]">{hint}</p>
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
        <div className="mt-2 flex flex-wrap gap-2">
          {files.map((f, i) => (
            <span key={`${f.name}-${i}`} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 rounded text-xs text-[var(--color-text-secondary)]">
              {f.name}
              <button
                className="text-gray-400 hover:text-danger"
                onClick={(e) => {
                  e.stopPropagation();
                  onFiles(files.filter((_, j) => j !== i));
                }}
              >×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
