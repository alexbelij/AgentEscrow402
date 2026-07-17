import { AlertTriangle, X } from 'lucide-react';

interface Props {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmModal({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  danger = true,
  onConfirm,
  onCancel,
}: Props) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
    >
      <div className="bg-[#12121a] border border-[#1e1e2e] rounded-xl p-6 max-w-md w-full mx-4 shadow-2xl">
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className={`h-6 w-6 mt-0.5 ${danger ? 'text-red-400' : 'text-amber-400'}`} />
          <div className="flex-1">
            <h3 id="confirm-modal-title" className="text-lg font-semibold text-gray-100">
              {title}
            </h3>
            <p className="text-sm text-gray-400 mt-1">{description}</p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="text-gray-500 hover:text-gray-300"
            aria-label="Cancel"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded-lg bg-gray-700 text-gray-300 hover:bg-gray-600 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`px-4 py-2 text-sm rounded-lg font-semibold text-white transition-colors ${
              danger ? 'bg-red-600 hover:bg-red-500' : 'bg-ae-accent hover:bg-ae-accent-bright'
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
