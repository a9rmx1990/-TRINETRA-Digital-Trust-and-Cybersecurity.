/**
 * BankingPortal — customer-facing retail banking view (OLED dark)
 */
import { Building2, ShieldCheck } from 'lucide-react';
import TransferForm from './TransferForm';

export default function BankingPortal() {
  return (
    <div className="py-6 px-4">
      {/* Portal header card */}
      <div className="mx-auto mb-6 max-w-xl">
        <div
          className="flex items-center gap-3.5 rounded-2xl p-4"
          style={{
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.07)',
          }}
        >
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl"
            style={{
              background: 'rgba(99,102,241,0.12)',
              border: '1px solid rgba(99,102,241,0.2)',
            }}
          >
            <Building2 size={20} className="text-indigo-400" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-200">SecureBank Voice Payment Terminal</h2>
            <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
              In-line behavioral fraud interception powered by TRINETRA
            </p>
          </div>
          <div
            className="ml-auto flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
            style={{
              background: 'rgba(16,185,129,0.1)',
              border: '1px solid rgba(16,185,129,0.2)',
              color: '#34d399',
            }}
          >
            <ShieldCheck size={11} />
            <span>Active</span>
          </div>
        </div>
      </div>

      <TransferForm />
    </div>
  );
}
