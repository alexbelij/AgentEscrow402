import React from 'react';
import ErrorBoundary from './ErrorBoundary';
import BackendWakeOverlay from './BackendWakeOverlay';
import WalletStatus from './WalletStatus';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import {
  Monitor,
  DollarSign,
  Users,
  Shield,
  Activity,
  FileText,
  FlaskConical,
  Bot,
  ChevronRight,
} from 'lucide-react';

interface NavItem {
  name: string;
  path: string;
  icon: React.ElementType;
}

const navItems: NavItem[] = [
  { name: 'Overview', path: '/console/overview', icon: Monitor },
  { name: 'Escrows', path: '/console/escrows', icon: DollarSign },
  { name: 'Agents', path: '/console/agents', icon: Users },
  { name: 'Insurance', path: '/console/insurance', icon: Shield },
  { name: 'Risk', path: '/console/risk', icon: Activity },
  { name: 'Contracts', path: '/console/contracts', icon: FileText },
  { name: 'Agent Demo', path: '/console/agent-demo', icon: Bot },
  { name: 'Sandbox', path: '/console/sandbox', icon: FlaskConical },
];

const ConsoleLayout: React.FC = () => {
  const location = useLocation();
  const pathnames = location.pathname.split('/').filter((x) => x);

  const getBreadcrumbs = () => {
    let currentPath = '';
    return pathnames.map((name, index) => {
      currentPath += `/${name}`;
      const isLast = index === pathnames.length - 1;
      const displayName = name.charAt(0).toUpperCase() + name.slice(1).replace(/-/g, ' ');
      return (
        <React.Fragment key={name}>
          <NavLink
            to={currentPath}
            className={`text-gray-400 hover:text-ae-accent transition-colors ${
              isLast ? 'font-semibold text-ae-accent' : ''
            }`}
          >
            {displayName}
          </NavLink>
          {!isLast && <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />}
        </React.Fragment>
      );
    });
  };

  return (
    <div className="min-h-screen bg-ae-bg text-gray-100 flex flex-col">
      {/* Console section rail — one professional horizontal nav row on desktop and mobile. */}
      <div className="sticky top-14 z-40 bg-ae-card/95 backdrop-blur border-b border-ae-border">
        <div className="ae-section h-12 flex items-center overflow-x-auto no-scrollbar">
          <nav className="flex items-center gap-1 min-w-max">
            {navItems.map((item) => (
              <NavLink
                key={item.name}
                to={item.path}
                className={({ isActive }) =>
                  `flex items-center gap-1.5 px-3 py-2 rounded-full text-xs font-medium transition-colors whitespace-nowrap ${
                    isActive
                      ? 'bg-ae-accent/20 text-ae-accent border border-ae-accent/30'
                      : 'text-gray-400 hover:bg-ae-border/50 hover:text-gray-200 border border-transparent'
                  }`
                }
              >
                <item.icon className="h-3.5 w-3.5" />
                {item.name}
              </NavLink>
            ))}
          </nav>
        </div>
      </div>
      <WalletStatus />

      {/* Main Content Area */}
      <main className="flex-1 p-4 sm:p-6 lg:p-8">
        {/* Breadcrumbs */}
        <nav className="mb-6 hidden sm:flex items-center text-sm">
          <NavLink to="/" className="text-gray-400 hover:text-ae-accent transition-colors">
            Home
          </NavLink>
          <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />
          {getBreadcrumbs()}
        </nav>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <BackendWakeOverlay />
    </div>
  );
};

export default ConsoleLayout;
