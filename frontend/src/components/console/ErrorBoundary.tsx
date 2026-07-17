import React from 'react';
import { AlertTriangle, RefreshCcw, ArrowLeft } from 'lucide-react';

interface Props { children: React.ReactNode; }
interface State { hasError: boolean; error: string; prevPath: string; }

class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: '', prevPath: window.location.pathname };
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    if (import.meta.env.DEV) console.error('Console error:', error, info);
  }

  componentDidUpdate() {
    // Reset error state when user navigates to a different route
    if (this.state.hasError && window.location.pathname !== this.state.prevPath) {
      this.setState({ hasError: false, error: '', prevPath: window.location.pathname });
    } else if (!this.state.hasError && window.location.pathname !== this.state.prevPath) {
      this.setState({ prevPath: window.location.pathname });
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center min-h-[400px] text-center p-8">
          <AlertTriangle className="h-12 w-12 text-amber-500 mb-4" />
          <h2 className="text-xl font-semibold text-gray-200 mb-2">Something went wrong</h2>
          <p className="text-gray-400 mb-6 max-w-md font-mono text-sm">{this.state.error}</p>
          <div className="flex gap-3">
            <button
              onClick={() => { this.setState({ hasError: false, error: '' }); }}
              className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-white rounded-lg transition-colors"
            >
              <ArrowLeft className="h-4 w-4" /> Dismiss
            </button>
            <button
              onClick={() => { this.setState({ hasError: false, error: '' }); window.location.reload(); }}
              className="flex items-center gap-2 px-4 py-2 bg-ae-accent hover:bg-ae-accent-bright text-white rounded-lg transition-colors"
            >
              <RefreshCcw className="h-4 w-4" /> Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
