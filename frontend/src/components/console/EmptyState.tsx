import { Inbox } from 'lucide-react';

interface Props {
  title: string;
  description?: string;
  icon?: React.ElementType;
}

export default function EmptyState({ title, description, icon: Icon = Inbox }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <Icon className="h-12 w-12 text-gray-600 mb-4" />
      <h3 className="text-lg font-medium text-gray-400 mb-1">{title}</h3>
      {description && <p className="text-sm text-gray-600 max-w-sm">{description}</p>}
    </div>
  );
}
