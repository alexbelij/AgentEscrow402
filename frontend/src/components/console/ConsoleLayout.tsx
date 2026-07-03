import React, { useState } from 'react';
import ErrorBoundary from './ErrorBoundary';
import { Outlet, NavLink, useLocation } from 'react-router-dom';
import {
  Monitor,
  Wallet,
  Menu,
  X,
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
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);

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
            className={`text-gray-400 hover:text-purple-400 transition-colors ${
              isLast ? 'font-semibold text-purple-400' : ''
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
    <div className="min-h-screen bg-[#0a0a0f] text-gray-100 flex flex-col">
      {/* Top Navigation Bar */}
      <header className="bg-[#12121a] border-b border-[#1e1e2e] p-4 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center">
          <button
            className="lg:hidden text-gray-400 hover:text-purple-400 mr-4"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          >
            {isMobileMenuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
          <NavLink to="/console/overview" className="flex items-center text-2xl font-bold text-purple-400">
            <Bot className="h-8 w-8 mr-2" />
            AgentEscrow402
          </NavLink>
        </div>

        {/* Desktop Nav Links */}
        <nav className="hidden lg:flex space-x-6">
          {navItems.map((item) => (
            <NavLink
              key={item.name}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center px-3 py-2 rounded-md text-sm font-medium transition-colors duration-200 ${
                  isActive
                    ? 'bg-purple-500/20 text-purple-400'
                    : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                }`
              }
            >
              <item.icon className="h-5 w-5 mr-2" />
              {item.name}
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center">
          {/* Wallet Connect Button */}
          <button className="flex items-center bg-purple-600 hover:bg-purple-700 text-white font-semibold py-2 px-4 rounded-lg shadow-md transition-colors duration-200">
            <Wallet className="h-5 w-5 mr-2" />
            Connect Wallet
          </button>
        </div>
      </header>

      {/* Mobile Menu (Overlay) */}
      {isMobileMenuOpen && (
        <div className="fixed inset-0 bg-[#0a0a0f] z-40 flex flex-col p-4 lg:hidden">
          <div className="flex justify-end mb-4">
            <button
              className="text-gray-400 hover:text-purple-400"
              onClick={() => setIsMobileMenuOpen(false)}
            >
              <X size={24} />
            </button>
          </div>
          <nav className="flex flex-col space-y-2">
            {navItems.map((item) => (
              <NavLink
                key={item.name}
                to={item.path}
                onClick={() => setIsMobileMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center px-4 py-3 rounded-md text-lg font-medium transition-colors duration-200 ${
                    isActive
                      ? 'bg-purple-500/20 text-purple-400'
                      : 'text-gray-400 hover:bg-gray-800 hover:text-gray-200'
                  }`
                }
              >
                <item.icon className="h-6 w-6 mr-3" />
                {item.name}
              </NavLink>
            ))}
          </nav>
        </div>
      )}

      {/* Main Content Area */}
      <main className="flex-1 p-6 lg:p-8">
        {/* Breadcrumbs */}
        <nav className="mb-6 flex items-center text-sm">
          <NavLink to="/" className="text-gray-400 hover:text-purple-400 transition-colors">
            Home
          </NavLink>
          <ChevronRight className="h-4 w-4 text-gray-600 mx-1" />
          {getBreadcrumbs()}
        </nav>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </div>
  );
};

export default ConsoleLayout;
