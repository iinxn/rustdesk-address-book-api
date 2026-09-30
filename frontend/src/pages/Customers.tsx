import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Confirm, Layout, LoadError, Loading, Toasts, btn, btnGhost, input } from '../components';
import { useTheme, useToasts } from '../hooks';
import type { Customer } from '../types';

export default function Customers() {
  const nav = useNavigate();
  const { dark, toggle } = useTheme();
  const { items, push } = useToasts();
  const [rows, setRows] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [editing, setEditing] = useState<Customer | null>(null);
  const [confirm, setConfirm] = useState<Customer | null>(null);

  const load = () => {
    setLoading(true); setFailed(false);
    api.customers().then(setRows).catch(() => setFailed(true)).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const create = async () => {
    if (!name.trim()) return;
    try {
      await api.createCustomer({ name: name.trim(), note });
      setName(''); setNote(''); push(true, 'Customer created'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const saveEdit = async () => {
    if (!editing) return;
    try {
      await api.updateCustomer(editing.id, { name: editing.name, note: editing.note });
      setEditing(null); push(true, 'Customer updated'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };
  const doDelete = async () => {
    if (!confirm) return;
    try {
      await api.deleteCustomer(confirm.id);
      setConfirm(null); push(true, 'Customer deleted'); load();
    } catch (e) { push(false, String((e as Error).message)); }
  };

  return (
    <Layout dark={dark} onTheme={toggle}>
      <h1 className="mb-3 text-xl font-bold">Customers</h1>
      <div className="mb-3 flex flex-wrap gap-2">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" className={`${input} w-48`} />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" className={`${input} w-64`} />
        <button onClick={create} className={btn}>+ Add</button>
      </div>
      {loading ? <Loading text="Loading customers" /> : failed ? <LoadError onRetry={load} /> : (
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-slate-200 text-left text-slate-500 dark:border-slate-800">
              <th className="px-3 py-2">Customer</th><th className="px-3 py-2">Devices</th><th className="px-3 py-2"></th>
            </tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
                  <td className="px-3 py-2">
                    <button
                      onClick={() => { sessionStorage.setItem('ab_customer', c.id); nav('/'); }}
                      className="font-medium text-blue-600 hover:underline" title="Show devices">
                      {c.name}
                    </button>
                    {c.note && <span className="block text-xs text-slate-500">{c.note}</span>}
                  </td>
                  <td className="px-3 py-2">{c.devices}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => setEditing({ ...c })} className={`${btnGhost} mr-1`}>Edit</button>
                    <button onClick={() => setConfirm(c)} className="rounded-md bg-red-600 px-2 py-1 text-white">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <p className="py-8 text-center text-sm text-slate-500">No customers yet</p>}
        </div>
      )}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setEditing(null)}>
          <div className="w-80 rounded-lg bg-white p-4 dark:bg-slate-900" onClick={(e) => e.stopPropagation()}>
            <h2 className="mb-3 font-bold">Edit customer</h2>
            <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} className={`${input} mb-2`} />
            <input value={editing.note} onChange={(e) => setEditing({ ...editing, note: e.target.value })} className={input} />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setEditing(null)} className={btnGhost}>Cancel</button>
              <button onClick={saveEdit} className={btn}>Save</button>
            </div>
          </div>
        </div>
      )}
      {confirm && <Confirm text={`Delete customer "${confirm.name}"?`} onYes={doDelete} onNo={() => setConfirm(null)} />}
      <Toasts items={items} />
    </Layout>
  );
}
